# Wortmühle

Ein tägliches deutsches Wort-Puzzle für Android — vollständig offline.

Aus neun Buchstaben auf der 3×3-Mühle gilt es, möglichst viele deutsche Wörter
zu legen. Jedes Wort muss den Mittelbuchstaben enthalten; jedes Rätsel hat
mindestens ein Pangramm (ein Wort, das alle neun Buchstaben nutzt). Pro Tag
gibt es ein Rätsel; die letzten sieben Tage lassen sich nachspielen. Punkte
folgen den Buchstabenwerten des deutschen Scrabble.

Der komplette Rätselpool (~2700 Rätsel) **und** die Worterklärungen sind in die
App eingebaut — sie braucht keine Internetverbindung und fordert **keine einzige
Berechtigung** an. Tippt man ein Wort der Lösungsliste an, steht die Erklärung
sofort da, aus de.wiktionary.org, gekürzt und mitgeliefert.

## Technik

Capacitor-Wrapper (WebView) um ein Vanilla-JS-Webspiel. Kein Tracking, keine
Werbung, keine Google-Dienste — und **keine Berechtigungen**: Das Manifest
fordert nichts an, die App greift zu keinem Zeitpunkt auf das Netz zu. Der
Link „↗ Wiktionary" unter einer Erklärung öffnet den Systembrowser; das
erledigt Android, nicht die App.
Details zum Bauen: [BUILD.md](BUILD.md).

## Lizenz

GPL-3.0-only — siehe [LICENSE](LICENSE). Code und Rätseldaten dieses
Repositories stehen unter der GNU General Public License v3.

Eine Ausnahme: **`www/defs.js`** (die Worterklärungen) stammt aus
de.wiktionary.org und steht unter
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.de) — die
Datei trägt ihren Lizenzkopf selbst. Sie ist bewusst ein eigenes Asset und
nicht Teil des Codes, damit die Share-Alike-Bedingung nicht über die
Erklärungstexte hinausreicht.

## Danksagung / Datenquellen

Der Rätselpool (`www/pool.json`) ist ein aus freien Quellen abgeleitetes Werk:

- **[igerman98 / wngerman](https://www.j3e.de/ispell/igerman98/)** von Björn
  Jacke — deutsche Wortliste (neue Rechtschreibung), Lizenz GPL-2 oder GPL-3.
  Hauptquelle der gültigen Lösungswörter.
- **[de.wiktionary.org](https://de.wiktionary.org/)** — Wortartenprüfung,
  Beugungsformen und Filterung; außerdem die **Worterklärungen**, die als
  `www/defs.js` mitgeliefert werden (gekürzt auf die ersten zwei Bedeutungen,
  Wiki-Markup entfernt). Inhalte unter
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.de); die
  Autoren stehen in der Versionsgeschichte der Seite, die jede Erklärung verlinkt.
- **[FrequencyWords](https://github.com/hermitdave/FrequencyWords)** von
  Hermit Dave (Häufigkeitsliste aus dem OpenSubtitles-2018-Korpus) —
  Auswahl und Schwierigkeitseinstufung der Rätsel. Inhalte unter
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

CC BY-SA 4.0 ist einseitig GPL-3-kompatibel; der abgeleitete Pool wird daher
insgesamt unter GPL-3.0 weitergegeben.

`pool.json` wird von einem ETL-Skript erzeugt (SQLite-Lexikon aus den drei
oben genannten, öffentlich herunterladbaren Quellen; Filterung über
Wiktionary-Wortarten und einen Vornamen-Gazetteer, der ausschließlich zum
*Ausschluss* von Namen dient — sein Inhalt landet nicht in der App). Das
Skript liegt samt Erläuterung unter
[`tools/pool-generator/`](tools/pool-generator/).
