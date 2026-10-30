#!/usr/bin/env bash
# Web-Assets aus piGallery in den Offline-APK übernehmen.
#
# Die App teilt sich CSS/JS mit der piGallery-Webversion, braucht aber zwei
# Offline-Anpassungen am JS (voller Pool statt Pi-Fenster). Damit ein simples
# `cp` aus piGallery diese nicht still überschreibt, kopiert dieses Skript die
# Assets UND re-applied die Offline-Patches idempotent. Danach `cap sync`.
set -euo pipefail
PIG=/home/bjoern/claude/piGallery
APP=/home/bjoern/claude/wortmuehle-app
GEN=/home/bjoern/claude/wortmuehle-pool

cp "$PIG/static/wortmuehle.css" "$APP/www/wortmuehle.css"
cp "$PIG/static/wortmuehle.js"  "$APP/www/wortmuehle.js"

# Pool-Generator verbatim mitspiegeln (Transparenz/Provenienz; kanonisch bleibt $GEN)
cp "$GEN/build_db.py" "$GEN/blacklist.txt" "$GEN/extra_words.txt" "$GEN/SOURCES.md" "$APP/tools/pool-generator/"
{ echo "# NUR EIN SPIEGEL — bearbeite piGallery/data/wortmuehle_tabu.txt, nicht diese Datei."
  cat "$PIG/data/wortmuehle_tabu.txt"; } > "$APP/tools/pool-generator/wortmuehle_tabu.txt"

# Nur die Rätsel mit festem Fahrplan-Platz, nach seq sortiert — je Modus (9er: CYCLE,
# 8er: CYCLE8). Dann trifft das Offline-Modulo (`liste[Tag mod Länge]`) exakt die Wahl
# des Servers. Die Reserve bleibt draußen — sie hat keinen Tag und würde die Rechnung verschieben.
bake_pool() {
python3 - "$1" "$2" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src, encoding='utf-8'))
cycle = d['meta']['cycle']
geplant = sorted((p for p in d['puzzles'] if p.get('seq') is not None),
                 key=lambda p: p['seq'])
if [p['seq'] for p in geplant] != list(range(cycle)):
    sys.exit('FEHLER: Fahrplan ist lückenhaft — build_db.py neu laufen lassen.')
d['puzzles'] = geplant
d['meta'] = dict(d['meta'], offline=True, count=cycle)
json.dump(d, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('pool baked:', dst.rsplit('/', 1)[-1], len(geplant), 'puzzles (Zyklus', cycle, '- Reserve bleibt draußen)')
PY
}
bake_pool "$PIG/data/wortmuehle_pool.json"  "$APP/www/pool.json"
bake_pool "$PIG/data/wortmuehle_pool8.json" "$APP/www/pool8.json"

# index.html wird aus dem piGallery-Template abgeleitet: ohne raspi5-Kopf (kein
# site-header, kein ←; zurück = Android-Geste), Offline-Pfade, keine Pi-Skripte.
python3 - "$PIG/templates/wortmuehle.html" "$APP/www/index.html" <<'PY'
import re, sys
s = open(sys.argv[1], encoding='utf-8').read()
def ersetze(muster, neu, was):
    global s
    s, n = re.subn(muster, lambda m: neu, s, count=1, flags=re.S)
    if n != 1:
        sys.exit('FEHLER: Anker für %s nicht gefunden – Template geändert? Skript prüfen.' % was)
ersetze(r'\{\{ versioned_url\(\'wortmuehle\.css\'\) \}\}', 'wortmuehle.css', 'CSS')
ersetze(r'  <link rel="stylesheet" href="\{\{ versioned_url\(\'site-header\.css\'\) \}\}">\n', '', 'site-header.css')
ersetze(r'  \{% set back_href[^\n]*\n  \{% include "_site_header\.html" %\}\n', '', 'site-header')
ersetze(r'<script>window\.POOL_URL.*?</script>\n  <script src="\{\{ url_for\(\'wortmuehle_defs\'\) \}\}" defer></script>\n'
        r'  <script src="\{\{ versioned_url\(\'wortmuehle\.js\'\) \}\}"></script>\n  <script src="\{\{ versioned_url\(\'app\.js\'\) \}\}"></script>',
        "<script>window.POOL_URL = './pool.json';   /* voller Pool, im APK eingebacken */\n"
        "          window.POOL8_URL = './pool8.json';\n"
        "          window.PUZZLE_URL = './p/';        /* offline ungenutzt: jede ID löst lokal auf */</script>\n"
        '  <script src="defs.js"></script>\n  <script src="wortmuehle.js"></script>', 'Skripte')
ersetze(r'user-scalable=no"', 'user-scalable=no, viewport-fit=cover"', 'viewport')
if '{{' in s or '{%' in s or 'site-header' in s:
    sys.exit('FEHLER: Template-Reste in index.html – Skript prüfen.')
open(sys.argv[2], 'w', encoding='utf-8').write(s)
print('index.html abgeleitet (ohne Kopf)')
PY

# Worterklärungen einbacken: eigenes Asset mit eigenem Lizenzkopf (CC BY-SA 4.0),
# damit die Share-Alike-Bedingung nicht in den GPLv3-Code hineinreicht.
python3 - "$PIG/data/wortmuehle_defs.json" "$APP/www/defs.js" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
lic = d['_lizenz']
head = ('/*! Worterklaerungen: %s\n'
        ' *  Lizenz: %s  <%s>\n'
        ' *  Bearbeitung: %s\n'
        ' *  %s\n'
        ' *  Erzeugt von wortmuehle-pool/build_db.py defs — nicht von Hand aendern. */\n'
        % (lic['quelle'], lic['lizenz'], lic['lizenz_url'], lic['bearbeitung'], lic['hinweis']))
body = json.dumps({'pages': d['pages'], 'words': d['words']},
                  ensure_ascii=False, separators=(',', ':'), sort_keys=True)
open(sys.argv[2], 'w', encoding='utf-8').write(head + 'window.WM_DEFS=' + body + ';\n')
print('defs baked:', len(d['pages']), 'Seiten,', len(d['words']), 'Verweise')
PY

# Offline-Patches am JS (idempotent; bricht ab, wenn der Anker fehlt = upstream geändert)
python3 - "$APP/www/wortmuehle.js" <<'PY'
import sys
f = sys.argv[1]
s = open(f, encoding='utf-8').read()

# 1) puzzleFor(): voller Pool ohne day-Stempel → gleiche Modulo-Rotation wie der Server, je Modus
src1 = ("  function puzzleFor(day) {                              // Rätsel, das für `day` ansteht\n"
        "    return byDay[mode][day] || null;                           // nicht geladen (offline / außerhalb des Fensters)\n"
        "  }\n")
dst1 = ("  function puzzleFor(day) {                              // Rätsel, das für `day` ansteht\n"
        "    if (byDay[mode][day]) return byDay[mode][day];\n"
        "    // Offline-Build: voller Fahrplan ohne day-Stempel → gleiche Rotation wie der Server\n"
        "    // (seq-Reihenfolge, day % len) liefert dasselbe Tagesrätsel, jeden Tag, ohne Netz.\n"
        "    var all = allLoaded[mode];\n"
        "    if (!all.length) return null;\n"
        "    return Object.assign({}, all[((day % all.length) + all.length) % all.length], { day: day });  // Datumsleiste/Permalink folgen dem Tag\n"
        "  }\n")

# 2) dayLoaded(): voller Pool → jeder Tag spielbar
src2 = ("  function dayLoaded(day) {                              // ist das Rätsel dieses Tages im Speicher?\n"
        "    return day in byDay[mode];\n"
        "  }\n")
dst2 = ("  function dayLoaded(day) {                              // Offline-Build: voller Pool → jeder Tag spielbar\n"
        "    return (day in byDay[mode]) || allLoaded[mode].length > 0;\n"
        "  }\n")

# 3) 8er-Pool kommt aus ./pool8.json statt ?n=8
src3 = "fetch(window.POOL_URL + (n === 8 ? '?n=8' : ''), { cache: 'no-store' })"
dst3 = "fetch(n === 8 ? window.POOL8_URL : window.POOL_URL, { cache: 'no-store' })   // Offline-Build: lokale Dateien"

# 4) kein localStorage-Pool: ein alter Cache (v1.2) würde das neue Paket überdecken
src4 = ("  function loadCachedWindow() {                          // sofort aus localStorage (kann offline sein)\n"
        "    try {\n")
dst4 = ("  function loadCachedWindow() {                          // sofort aus localStorage (kann offline sein)\n"
        "    return false;                                        // Offline-Build: Pool liegt im APK, alter Cache soll ihn nie überdecken\n"
        "    try {\n")

for label, src, dst in (('puzzleFor', src1, dst1), ('dayLoaded', src2, dst2),
                        ('pool8-URL', src3, dst3), ('loadCachedWindow', src4, dst4)):
    if dst in s:
        print('already patched:', label)
        continue
    if src not in s:
        sys.exit('FEHLER: Anker für %s nicht gefunden – piGallery-JS geändert? Patch manuell prüfen.' % label)
    s = s.replace(src, dst, 1)
    print('patched:', label)

open(f, 'w', encoding='utf-8').write(s)
PY

cd "$APP"
npx --no-install cap sync android
echo "Fertig. APK bauen: source ~/claude/.tools/android-env.sh && cd android && ./gradlew assembleDebug"
