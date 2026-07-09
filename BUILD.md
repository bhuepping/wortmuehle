# Wortmühle — Offline-APK

Capacitor-Wrapper um das Vanilla-JS-Webspiel aus `piGallery`. **Der komplette
Rätselpool (2827 Rätsel) ist eingebacken** → läuft vollständig offline, kein Pi nötig.
Einzige Online-Funktion: die Worterklärungen von de.wiktionary (fehlen ohne Netz still).

## Aufbau
- `www/` — die Web-App (Quelle für den APK)
  - `index.html` — Standalone-Version des Templates (ohne Flask, ohne `/spielwiese`-Back-Link)
  - `wortmuehle.css` / `wortmuehle.js` — Kopien aus `piGallery/static/`, JS minimal gepatcht:
    - `puzzleFor()` hat eine **Modulo-Fallback-Rotation** (`list[day % len]`), die exakt
      dieselbe Tagesrätsel-Wahl liefert wie der Pi-Server — verifiziert gegen `app.py`.
    - `dayLoaded()` meldet jeden Tag als spielbar (voller Pool im Speicher).
  - `pool.json` — voller Pool, sortiert nach `(diff,id)` (= Server-Rotationsordnung)
- `android/` — von `npx cap add android` generiertes Gradle-Projekt
- `capacitor.config.json` — appId `de.huepping.wortmuehle`, webDir `www`

## Web-Assets aktualisieren (nach Spiel-Änderungen in piGallery)
```sh
./sync-www.sh          # kopiert css/js aus piGallery, backt pool.json neu,
                       # re-applied die Offline-Patches (s.u.) idempotent, cap sync
```
**Wichtig:** Nie `cp piGallery/static/wortmuehle.js www/` von Hand — das überschreibt die
beiden Offline-Patches (`puzzleFor`-Modulo-Fallback, `dayLoaded`). `sync-www.sh` trägt sie
nach jedem Kopieren wieder ein und bricht ab, falls der piGallery-JS-Anker sich geändert hat.

## APK bauen
Benötigt **JDK 17** und das **Android SDK** (compileSdk 34, build-tools, platform-tools,
Lizenzen akzeptiert). Beides userspace installierbar (kein sudo):
```sh
export JAVA_HOME=/pfad/zu/jdk-17
export ANDROID_HOME=/pfad/zu/android-sdk     # cmdline-tools/sdkmanager
cd android
./gradlew assembleDebug      # → app/build/outputs/apk/debug/app-debug.apk  (sideloadbar)
```
## Release bauen (signiert)
`keystore.properties` + `release.keystore` liegen im Repo-Root und sind **nicht
eingecheckt** (.gitignore) — **beide sichern**, der Keystore ist die dauerhafte
Identität der App (gleicher Key für F-Droid-Repo, Play Store, Sideload-Updates).
Fehlt die Datei (frischer Checkout, F-Droid-Buildserver), baut Gradle ein
unsigniertes Release.
```sh
cd android
./gradlew assembleRelease   # → app/build/outputs/apk/release/app-release.apk
```

Alternativ: `android/` einfach in **Android Studio** öffnen und auf ▶ klicken.
