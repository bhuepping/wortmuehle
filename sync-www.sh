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

# Nur die Rätsel mit festem Fahrplan-Platz, nach seq sortiert. Dann trifft das
# Offline-Modulo (`liste[Tag mod Länge]`) exakt die Wahl des Servers. Die Reserve
# bleibt draußen — sie hat keinen Tag und würde die Rechnung verschieben.
python3 - "$PIG/data/wortmuehle_pool.json" "$APP/www/pool.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src, encoding='utf-8'))
cycle = d['meta']['cycle']
geplant = sorted((p for p in d['puzzles'] if p.get('seq') is not None),
                 key=lambda p: p['seq'])
if [p['seq'] for p in geplant] != list(range(cycle)):
    sys.exit('FEHLER: Fahrplan ist lückenhaft — build_db.py mart neu laufen lassen.')
d['puzzles'] = geplant
d['meta'] = dict(d['meta'], offline=True, count=cycle)
json.dump(d, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('pool baked:', len(geplant), 'puzzles (Zyklus', cycle, '- Reserve bleibt draußen)')
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

# 1) puzzleFor(): voller Pool ohne day-Stempel → gleiche Modulo-Rotation wie der Server
src1 = ("  function puzzleFor(day) {                              // Rätsel, das für `day` ansteht\n"
        "    return byDay[day] || null;                           // nicht geladen (offline / außerhalb des Fensters)\n"
        "  }\n")
dst1 = ("  function puzzleFor(day) {                              // Rätsel, das für `day` ansteht\n"
        "    if (byDay[day]) return byDay[day];\n"
        "    // Offline-Build: voller Pool ohne day-Stempel → gleiche Rotation wie der Server\n"
        "    // (sortiert nach id, dann day % len) liefert dasselbe Tagesrätsel, jeden Tag, ohne Netz.\n"
        "    if (!allLoaded.length) return null;\n"
        "    var p = allLoaded[((day % allLoaded.length) + allLoaded.length) % allLoaded.length];\n"
        "    return Object.assign({}, p, { day: day });           // Datumsleiste/Permalink folgen dem Tag\n"
        "  }\n")

# 2) dayLoaded(): voller Pool → jeder Tag spielbar
src2 = ("  function dayLoaded(day) {                              // ist das Rätsel dieses Tages im Speicher?\n"
        "    return day in byDay;\n"
        "  }\n")
dst2 = ("  function dayLoaded(day) {                              // Offline-Build: voller Pool → jeder Tag spielbar\n"
        "    return (day in byDay) || allLoaded.length > 0;\n"
        "  }\n")

for label, src, dst in (('puzzleFor', src1, dst1), ('dayLoaded', src2, dst2)):
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
