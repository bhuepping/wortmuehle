# Datenquellen und ihre Lizenzen

Die Wortmühle-Wortliste entsteht aus vier fremden Quellen. Diese Datei hält fest,
unter welcher Lizenz jede steht und ob sie **ausgeliefert** wird (im APK / auf dem
Pi landet) oder nur **beim Bauen** auf der Dev-Maschine benutzt wird. Der Unterschied
ist der entscheidende: nur Ausgeliefertes muss im Produkt genannt werden.

| Quelle | Lizenz | Rolle | ausgeliefert? |
|---|---|---|---|
| de.wiktionary-Dump | CC BY-SA 4.0 | Wortart, Namensmarkierung, Grundformen, **Worterklärungen** | **ja** (Erklärungen) |
| wngerman (igerman98) | GPL-2+ | Rechtschreib-Wortliste = Kandidatenmenge | ja (mittelbar, als Wortliste) |
| FrequencyWords `de_50k.txt` | Daten CC BY-SA 4.0, Code MIT | Häufigkeit → Auswahl geläufiger Seeds | nein |
| firstnames.csv | GFDL 1.2+ | Vornamen erkennen und ausschließen | nein |

## de.wiktionary
- Dump: `https://dumps.wikimedia.org/dewiktionary/latest/dewiktionary-latest-pages-articles.xml.bz2`
- Lizenz: **CC BY-SA 4.0**, Altbestand zusätzlich GFDL (siehe `Wiktionary:Lizenzbestimmungen`).
- **Namensnennung:** Die Wikimedia-Nutzungsbedingungen (Abschnitt 7) lassen für die
  Autorennennung ausdrücklich einen "hyperlink (where possible) or URL to the page or
  pages that you are reusing" genügen — die Autorenliste steht in der Versionsgeschichte
  der verlinkten Seite. Deshalb trägt **jede** Erklärung im Spiel einen Link auf ihre
  Wiktionary-Seite.
- **Bearbeitung:** Wir kürzen auf die ersten Bedeutungen und entfernen Wiki-Markup.
  Das ist kenntlich zu machen; im Spiel steht dafür "gekürzt" an der Erklärung.
- **Share-Alike:** Die Erklärungen bleiben CC BY-SA 4.0. Sie liegen deshalb als
  **eigenes Datenpaket** (`defs.json`) neben dem Code, nicht im Code — so zieht die
  Bedingung die GPLv3 der App nicht mit. Das Paket trägt seinen Lizenzkopf selbst.
- Wir benutzen den **Dump**, nicht die API: Wikimedia stellt Dumps genau für solche
  Massenauswertungen bereit, statt dass Wiederverwender ihre Server mit zehntausenden
  Einzelabrufen belasten.

## wngerman / igerman98
- Bezug: `apt-get download wngerman` (Ubuntu/Debian), Upstream `https://www.j3e.de/ispell/igerman98/`
- Lizenz laut Debian-`copyright`: **GPL-2+**, © 1999–2016 Björn Jacke.
- Verwendung: liefert die Menge gültiger deutscher Wörter, aus der das Spiel schöpft.
  Die Wortmühle-App steht unter **GPLv3** — GPL-2+ erlaubt die Weitergabe unter v3,
  das passt zusammen.

## FrequencyWords (de_50k.txt)
- Bezug: `https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/de/de_50k.txt`
- Lizenz: Inhalte **CC BY-SA 4.0**, Code MIT. Abgeleitet aus OpenSubtitles (OPUS 2018).
- Verwendung: nur als Häufigkeitssignal bei der Rätselauswahl. Die Liste selbst wird
  nicht ausgeliefert.

## firstnames.csv
- Quelle: Vornamen-Datenbank von Jörg Michael (c't 17/2007), gepflegt von Matthias
  Winkelmann, `https://github.com/MatthiasWinkelmann/firstname-database`
- Lizenz: **GFDL 1.2 oder später**.
- Verwendung: nur zum *Ausschließen* von Vornamen. Wird nicht ausgeliefert.

---
Stand: 2026-08-20. Bei neuen Quellen bitte hier ergänzen, **bevor** sie in die
Pipeline kommen.
