# Wortmühle — Offline-APK

Capacitor-Wrapper um das Vanilla-JS-Webspiel aus `piGallery`. **Der komplette
Rätselpool (2500 Rätsel, der Tages-Fahrplan) ist eingebacken** → läuft vollständig offline, kein Pi nötig.
Auch die Worterklärungen sind eingebacken (`www/defs.js`, aus dem
de.wiktionary-Dump). Die App macht **keine Netzzugriffe** und hat **keine
Berechtigungen** im Manifest. `www/defs.js` steht unter CC BY-SA 4.0 und trägt
seinen Lizenzkopf selbst — deshalb liegt es als eigenes Asset neben dem
GPLv3-Code und nicht darin.

## Aufbau
- `www/` — die Web-App (Quelle für den APK)
  - `index.html` — Standalone-Version des Templates (ohne Flask, ohne `/spielwiese`-Back-Link)
  - `wortmuehle.css` / `wortmuehle.js` — Kopien aus `piGallery/static/`, JS minimal gepatcht:
    - `puzzleFor()` hat eine **Modulo-Fallback-Rotation** (`list[day % len]`), die exakt
      dieselbe Tagesrätsel-Wahl liefert wie der Pi-Server — verifiziert gegen `app.py`.
    - `dayLoaded()` meldet jeden Tag als spielbar (voller Pool im Speicher).
  - `pool.json` — voller Pool, sortiert nach `id` (= Server-Rotationsordnung, Schema 5)
- `android/` — von `npx cap add android` generiertes Gradle-Projekt
- `capacitor.config.json` — appId `de.huepping.wortmuehle`, webDir `www`

## Web-Assets aktualisieren (nach Spiel-Änderungen in piGallery)
```sh
./sync-www.sh          # kopiert css/js aus piGallery, backt pool.json neu,
                       # spiegelt den Pool-Generator nach tools/pool-generator/,
                       # re-applied die Offline-Patches (s.u.) idempotent, cap sync
```
**Wichtig:** Nie `cp piGallery/static/wortmuehle.js www/` von Hand — das überschreibt die
beiden Offline-Patches (`puzzleFor`-Modulo-Fallback, `dayLoaded`). `sync-www.sh` trägt sie
nach jedem Kopieren wieder ein und bricht ab, falls der piGallery-JS-Anker sich geändert hat.

## APK bauen
Toolchain liegt fertig unter `~/claude/.tools/` (JDK 17, Android SDK 34, node) —
**bewusst nicht in `$HOME`**: die bwrap-Sandbox mountet `/home` als tmpfs, dort
installierte Tools sind nach der Session weg (so gingen JDK/SDK/node schon einmal
verloren). `android/local.properties` zeigt auf denselben Pfad.
```sh
source ~/claude/.tools/android-env.sh   # JAVA_HOME, ANDROID_HOME, GRADLE_USER_HOME, PATH
cd android
./gradlew assembleDebug      # → app/build/outputs/apk/debug/app-debug.apk  (sideloadbar)
```
Wächst das APK unerwartet (hier einmal um 900 KB), ist es tote Luft: Gradle packt
inkrementell und lässt ersetzte Assets als Leichen im Archiv liegen. `./gradlew clean
assembleDebug` räumt auf — die Nutzdaten sind vorher wie nachher gleich groß, prüfbar
mit `unzip -v app-debug.apk | tail -3`.

Neu aufsetzen (falls `.tools` mal fehlt): Temurin JDK 17 (`api.adoptium.net`) nach
`.tools/jdk17`, `commandlinetools-linux-*.zip` nach `.tools/android-sdk/cmdline-tools/latest`,
dann `sdkmanager --licenses` und `sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"`.
Zusammen ~800 MB.

## Release bauen (signiert)
`keystore.properties` + `release.keystore` liegen im Repo-Root und sind **nicht
eingecheckt** (.gitignore) — **beide sichern**, der Keystore ist die dauerhafte
Identität der App für Play Store und Sideload-Updates. **F-Droid signiert mit
eigenem Key** (Reproducible Builds bewusst nicht aktiviert) — F-Droid-Installationen
lassen sich daher nicht mit unseren APKs cross-updaten und umgekehrt.
Fehlt die Datei (frischer Checkout, F-Droid-Buildserver), baut Gradle ein
unsigniertes Release.
```sh
source ~/claude/.tools/android-env.sh
cd android
./gradlew assembleRelease   # → app/build/outputs/apk/release/app-release.apk
```

Alternativ: `android/` einfach in **Android Studio** öffnen und auf ▶ klicken.
