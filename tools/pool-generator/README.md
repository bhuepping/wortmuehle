# Pool-Generator

`build_db.py` erzeugt den Rätselpool der App — hier veröffentlicht, damit die
Herkunft von `www/pool.json` vollständig nachvollziehbar ist. Für den Bau der
App wird das Skript **nicht** gebraucht (der fertige Pool ist eingecheckt).

## Pipeline

Gestuftes ELT in ein SQLite-Lexikon (jede Stufe idempotent):

```
extract   Rohquellen laden          → stg_*        (streamt den Wiktionary-Dump)
conform   Oberflächenformen         → word, word_source
decide    SQL-Regeln                → word_decision
mart      Rätsel bauen              → wortmuehle_pool.json
```

```sh
python3 build_db.py all     # extract (falls leer) + conform + decide
python3 build_db.py mart    # Pool-JSON erzeugen
python3 build_db.py why <wort>   # Herkunft + Verdikt eines Wortes erklären
```

Das Skript lädt seine Quellen selbst herunter (nach `.cache/`, ~300 MB —
nicht einchecken): die wngerman-Wortliste per `apt-get download`, die
Häufigkeitsliste und den de.wiktionary-Dump per `curl`. Quellen und Lizenzen:
siehe Danksagung im [Haupt-README](../../README.md).

`firstnames.csv` (Vornamen-Gazetteer, dient nur dem *Ausschluss* von Namen)
liegt nicht bei; ohne die Datei wird die Stufe übersprungen.

## Von der Mart-Ausgabe zu `www/pool.json`

Das Skript schreibt nach `../piGallery/data/` (Pfad des Dev-Setups, in dem
auch die Web-Version des Spiels lebt). `sync-www.sh` im Repo-Root übernimmt
den Pool von dort in die App: nach `id` sortiert (= Rotationsordnung der
Tagesrätsel) und mit `meta.offline = true`.
