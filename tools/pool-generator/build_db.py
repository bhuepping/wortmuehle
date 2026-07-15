#!/usr/bin/env python3
"""Wortmühle — lexicon ETL into a SQLite "source of truth" (dev machine only).

Pipeline (staged ELT; each stage idempotent and separately runnable):

    extract  raw sources            -> stg_*           (slow: streams the wiktionary bz2)
    conform  surfaces + provenance  -> word, word_source
    decide   SQL rules              -> word_decision   (materialized from v_word_decision)

The grain of `word` is the SURFACE FORM (case-sensitive): "malte" (verb form) and
"Malte" (given name) are two rows, exactly like Wiktionary page titles. Lowercasing is
only a projection at play time, so excluding the name never removes the verb form.

Sources:
  * wngerman            morphologically dense wordlist (inflections + compounds)
  * de.wiktionary dump  part-of-speech / name / abbreviation / inflection + base forms
  * de_50k.txt          OpenSubtitles frequency (seeds + difficulty; mart stage)
  * extra_words.txt     manual include list   (staged into stg_manual)
  * blacklist.txt       manual exclude list   (staged into stg_manual)

Once the staging tables are populated, iterating on acceptance rules is pure SQL in
milliseconds — no 253 MB re-parse. The shipped puzzle pool (JSON) is produced by a
separate mart stage; this script only owns the lexicon.

Usage:
    python3 build_db.py all            # extract (if empty) + conform + decide
    python3 build_db.py extract        # (re)load raw sources into stg_*   [--force]
    python3 build_db.py conform        # rebuild word / word_source
    python3 build_db.py decide         # rebuild word_decision (cheap, re-run freely)
    python3 build_db.py why <word>     # explain a word's lineage + verdict
    python3 build_db.py report         # counts per source / reason
"""
import os, re, sys, bz2, sqlite3, subprocess, glob, json, time, hashlib
from collections import Counter

BASE  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache")
DB    = os.path.join(CACHE, "wortmuehle.db")
OUT   = os.path.normpath(os.path.join(BASE, "..", "piGallery", "data", "wortmuehle_pool.json"))

MIN_LEN = 3
TILES   = 9                       # max surface length we care about for the game
ALPHABET = "abcdefghijklmnopqrstuvwxyzäöüß"
ALLOWED  = set(ALPHABET)
BIT      = {c: 1 << i for i, c in enumerate(ALPHABET)}

# Standard German-language Scrabble letter values (official tile distribution).
# ß has no tile of its own in German Scrabble (words use "ss" on the board), so it's
# priced as ss (1+1) here — the game's alphabet includes it, Scrabble's doesn't.
LETTER_VALUE = {
    'e': 1, 'n': 1, 's': 1, 'i': 1, 'r': 1, 't': 1, 'u': 1, 'a': 1, 'd': 1,
    'h': 2, 'g': 2, 'l': 2, 'o': 2,
    'm': 3, 'b': 3, 'w': 3, 'z': 3,
    'c': 4, 'f': 4, 'k': 4, 'p': 4,
    'ä': 6, 'j': 6, 'ü': 6, 'v': 6,
    'ö': 8, 'x': 8,
    'q': 10, 'y': 10,
    'ß': 2,
}
BINGO_BONUS = 50                  # Scrabble's flat bonus for using the whole rack; here,
                                  # "the whole rack" = all 9 tiles = a pangram.


def word_score(w):
    return sum(LETTER_VALUE.get(c, 0) for c in w.lower()) + (BINGO_BONUS if len(w) == TILES else 0)


# mart (puzzle) parameters
TOPN        = 50000               # frequency cutoff for seed (pangram) core
BAND        = (25, 65)            # allowed solution count per puzzle (via center choice)
TARGET      = 45                  # desired solution count
POOL_SCHEMA = 5                   # 5: one puzzle/day (no difficulty tiers), Scrabble letter
                                  #    scoring. Full pool shipped to the Pi; the Flask server
                                  #    slices the rolling day-window per request.


def mask(word):
    m = 0
    for c in word:
        m |= BIT[c]
    return m


def submultiset(wc, rc):
    for k, v in wc.items():
        if rc.get(k, 0) < v:
            return False
    return True

NAME_TAGS = {"Vorname", "Nachname", "Familienname", "Eigenname",
             "Toponym", "Straßenname", "Ortsname", "Gewässername"}
ABBREV_TAGS = {"Abkürzung", "Kurzwort", "Symbol", "Akronym", "Initialwort"}
INFLECT_TAGS = {"Deklinierte Form", "Konjugierte Form", "Komparativ", "Superlativ",
                "Partizip", "Erweiterte Infinitive"}

FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/de/de_50k.txt"
WIKT_URL = "https://dumps.wikimedia.org/dewiktionary/latest/dewiktionary-latest-pages-articles.xml.bz2"


# ── data acquisition (cache) ────────────────────────────────────────────────
def ensure_wngerman():
    out = os.path.join(CACHE, "ngerman")
    if os.path.exists(out):
        return out
    os.makedirs(CACHE, exist_ok=True)
    print("· downloading wngerman (apt-get download)…")
    subprocess.run(["apt-get", "download", "wngerman"], cwd=CACHE, check=True)
    deb = glob.glob(os.path.join(CACHE, "wngerman_*.deb"))[0]
    subprocess.run(["dpkg-deb", "-x", deb, os.path.join(CACHE, "deb")], check=True)
    os.replace(os.path.join(CACHE, "deb", "usr", "share", "dict", "ngerman"), out)
    return out


def ensure_freq():
    out = os.path.join(CACHE, "de_50k.txt")
    if not os.path.exists(out):
        os.makedirs(CACHE, exist_ok=True)
        print("· downloading frequency list (curl)…")
        subprocess.run(["curl", "-sSL", "-o", out, FREQ_URL], check=True)
    return out


def ensure_wiktionary():
    out = os.path.join(CACHE, "dewiktionary.xml.bz2")
    if not os.path.exists(out):
        os.makedirs(CACHE, exist_ok=True)
        print("· downloading de.wiktionary dump (~265 MB, curl)…")
        subprocess.run(["curl", "-sSL", "-o", out, WIKT_URL], check=True)
    return out


def is_candidate(surface):
    """A single token that could ever appear in the game (length + charset)."""
    low = surface.lower()
    return (":" not in surface and MIN_LEN <= len(low) <= TILES
            and set(low) <= ALLOWED)


def _allcaps(s):
    return len(s) >= 2 and s == s.upper() and s != s.lower()


def is_acronym(surface):
    # all-caps (ADAC, ABS) or an all-caps stem with a plural -s (BHs, DJs, TVs, KZs)
    return _allcaps(surface) or (surface.endswith("s") and _allcaps(surface[:-1]))


# ── schema ──────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS stg_wngerman    (surface TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS stg_freq        (surface TEXT PRIMARY KEY, rank INT, count INT);
CREATE TABLE IF NOT EXISTS stg_wikt_section(title TEXT, ord INT, pos_tags TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS stg_wikt_meaning(title TEXT, ord INT, sense_idx TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS stg_wikt_baseform(title TEXT, lemma TEXT, relation TEXT);
CREATE TABLE IF NOT EXISTS stg_manual      (surface TEXT, lower_form TEXT, action TEXT);
CREATE TABLE IF NOT EXISTS stg_namelist    (surface TEXT, lower_form TEXT, kind TEXT);

CREATE TABLE IF NOT EXISTS word (
    surface    TEXT PRIMARY KEY,
    lower_form TEXT NOT NULL,
    length     INT  NOT NULL,
    canonical  TEXT,
    is_acronym INT  NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS word_source (
    surface TEXT,
    source  TEXT,
    attr    TEXT,
    PRIMARY KEY (surface, source)
);
CREATE TABLE IF NOT EXISTS reason (
    code TEXT PRIMARY KEY, kind TEXT, priority INT, description TEXT
);
CREATE TABLE IF NOT EXISTS word_decision (
    surface TEXT PRIMARY KEY, reason_code TEXT, priority INT, accepted INT
);
CREATE TABLE IF NOT EXISTS puzzle (
    id TEXT PRIMARY KEY, signature TEXT, tiles TEXT, center TEXT,
    difficulty INT, max_score INT, word_count INT
);
CREATE TABLE IF NOT EXISTS puzzle_word (puzzle_id TEXT, lower_form TEXT);

CREATE INDEX IF NOT EXISTS ix_word_lower    ON word(lower_form);
CREATE INDEX IF NOT EXISTS ix_wsection_title ON stg_wikt_section(title);
CREATE INDEX IF NOT EXISTS ix_wsource_surface ON word_source(surface);
CREATE INDEX IF NOT EXISTS ix_manual_lower   ON stg_manual(lower_form);
CREATE INDEX IF NOT EXISTS ix_namelist_lower ON stg_namelist(lower_form);
"""


def connect():
    os.makedirs(CACHE, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    con.executescript(SCHEMA)
    return con


# ── EXTRACT ─────────────────────────────────────────────────────────────────
def extract_wngerman(con):
    rows = [(w.strip(),) for w in open(ensure_wngerman(), encoding="utf-8")
            if is_candidate(w.strip())]
    con.execute("DELETE FROM stg_wngerman")
    con.executemany("INSERT OR IGNORE INTO stg_wngerman(surface) VALUES (?)", rows)
    con.commit()
    print(f"· stg_wngerman: {len(rows)} candidate surfaces")


def extract_freq(con):
    con.execute("DROP TABLE IF EXISTS stg_freq")
    con.execute("CREATE TABLE stg_freq (surface TEXT PRIMARY KEY, rank INT, count INT)")
    rows = []
    for rank, line in enumerate(open(ensure_freq(), encoding="utf-8")):
        word, _, cnt = line.strip().partition(" ")
        if word:
            rows.append((word, rank, int(cnt) if cnt.isdigit() else 0))
    con.executemany("INSERT OR IGNORE INTO stg_freq(surface, rank, count) VALUES (?, ?, ?)", rows)
    con.commit()
    print(f"· stg_freq: {len(rows)} ranked words")


def extract_manual(con):
    con.execute("DELETE FROM stg_manual")
    for fname, action in [("extra_words.txt", "include"), ("blacklist.txt", "exclude")]:
        p = os.path.join(BASE, fname)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            x = line.strip()
            if x and not x.startswith("#"):
                con.execute("INSERT INTO stg_manual(surface, lower_form, action) VALUES (?, ?, ?)",
                            (x, x.lower(), action))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM stg_manual").fetchone()[0]
    print(f"· stg_manual: {n} manual rules")


def extract_namelist(con):
    """German-speaking given names (Matthias Winkelmann firstname-database)."""
    path = os.path.join(CACHE, "firstnames.csv")
    con.execute("DELETE FROM stg_namelist")
    if not os.path.exists(path):
        print("· stg_namelist: firstnames.csv missing — skip"); return
    with open(path, encoding="utf-8", errors="replace") as f:
        header = f.readline().rstrip("\n").split(";")
        cols = [header.index(c) for c in ("East Frisia", "Germany", "Austria", "Swiss")
                if c in header]
        seen, rows = set(), []
        for line in f:
            parts = line.rstrip("\n").split(";")
            name = parts[0].strip() if parts else ""
            if not name or name in seen:
                continue
            if any(len(parts) > i and parts[i].strip() for i in cols) and is_candidate(name):
                seen.add(name)
                rows.append((name, name.lower(), "given"))
    con.executemany("INSERT INTO stg_namelist(surface, lower_form, kind) VALUES (?,?,?)", rows)
    con.commit()
    print(f"· stg_namelist: {len(rows)} German-speaking given names")


# wiktionary parsing helpers
_re_title = re.compile(r"<title>(.*?)</title>")
_re_text  = re.compile(r"<text[^>]*>(.*?)</text>", re.S)
_re_de    = re.compile(r"== .*?\(\{\{Sprache\|Deutsch\}\}\) ==(.*?)(?=\n== [^=]|\Z)", re.S)
_re_head  = re.compile(r"===+ (.*?) ===+")
_re_wa    = re.compile(r"\{\{Wortart\|([^|}]+)\|")
_re_gf    = re.compile(r"\{\{Grundformverweis\s*([^|}]*)\|([^|}\n]+)")
_re_bed   = re.compile(r"\{\{Bedeutungen\}\}\s*\n(.*?)(?=\n\{\{|\n\n|\Z)", re.S)
_re_sense = re.compile(r"^:*\s*\[([\d ,.–\-]+)\]\s*(.*)$")


def classify(tags):
    if tags and all(t in INFLECT_TAGS for t in tags):
        return "inflection"
    if any(t in NAME_TAGS for t in tags):
        return "name"
    if any(t in ABBREV_TAGS for t in tags):
        return "abbrev"
    return "common"


def clean_wiki(s):
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[\s\S]*?</ref>", "", s)
    s = re.sub(r"<!--[\s\S]*?-->", "", s)
    s = re.sub(r"\{\{K\|([^}]*)\}\}",
               lambda m: (", ".join(p for p in m.group(1).split("|") if p and "=" not in p) + ": ")
               if any(p and "=" not in p for p in m.group(1).split("|")) else "", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_page(title, sec):
    """Return (sections, meanings, baseform) for a German section `sec`."""
    sections = []
    for i, head in enumerate(_re_head.findall(sec)):
        tags = _re_wa.findall(head)
        if tags:
            sections.append((i, ", ".join(tags), classify(tags)))
    meanings = []
    mb = _re_bed.search(sec)
    if mb:
        i = 0
        for line in mb.group(1).split("\n"):
            m = _re_sense.match(line.strip())
            if m:
                txt = clean_wiki(m.group(2))
                if txt:
                    meanings.append((i, m.group(1).replace(" ", ""), txt))
                    i += 1
    base = None
    g = _re_gf.search(sec)
    if g:
        rel = g.group(1).strip() or "?"
        base = (g.group(2).strip(), rel)
    return sections, meanings, base


def extract_wikt(con, force=False):
    have = con.execute("SELECT COUNT(*) FROM stg_wikt_section").fetchone()[0]
    if have and not force:
        print(f"· stg_wikt_section already populated ({have} rows) — skip (use --force)")
        return
    for t in ("stg_wikt_section", "stg_wikt_meaning", "stg_wikt_baseform"):
        con.execute(f"DELETE FROM {t}")
    path = ensure_wiktionary()
    print("· streaming wiktionary dump…")
    sec_rows, mean_rows, base_rows = [], [], []
    title, keep, buf, pages, kept = None, False, [], 0, 0

    def flush():
        con.executemany("INSERT INTO stg_wikt_section VALUES (?,?,?,?)", sec_rows)
        con.executemany("INSERT INTO stg_wikt_meaning VALUES (?,?,?,?)", mean_rows)
        con.executemany("INSERT INTO stg_wikt_baseform VALUES (?,?,?)", base_rows)
        con.commit()
        sec_rows.clear(); mean_rows.clear(); base_rows.clear()

    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if "<title>" in line:
                m = _re_title.search(line)
                title = m.group(1) if m else None
                keep = bool(title) and is_candidate(title)
                buf = []
            elif keep:
                buf.append(line)
                if "</text>" in line:
                    pages += 1
                    if pages % 100000 == 0:
                        print(f"    … {pages} candidate pages, {kept} German")
                    m = _re_text.search("".join(buf))
                    if m:
                        de = _re_de.search(m.group(1))
                        if de:
                            kept += 1
                            secs, means, base = parse_page(title, de.group(1))
                            for ordn, tags, cat in secs:
                                sec_rows.append((title, ordn, tags, cat))
                            for ordn, idx, txt in means:
                                mean_rows.append((title, ordn, idx, txt))
                            if base:
                                base_rows.append((title, base[0], base[1]))
                            if len(sec_rows) > 50000:
                                flush()
                    keep = False
    flush()
    n = con.execute("SELECT COUNT(DISTINCT title) FROM stg_wikt_section").fetchone()[0]
    print(f"· stg_wikt: {kept} German pages, {n} with classified sections")


def extract(con, force=False):
    extract_wngerman(con)
    extract_freq(con)
    extract_manual(con)
    extract_namelist(con)
    extract_wikt(con, force=force)


# ── CONFORM ─────────────────────────────────────────────────────────────────
def conform(con):
    con.execute("DELETE FROM word")
    con.execute("DELETE FROM word_source")

    # gather every surface that appears in any source
    wn = {r[0] for r in con.execute("SELECT surface FROM stg_wngerman")}
    wk = {r[0] for r in con.execute("SELECT DISTINCT title FROM stg_wikt_section")}
    man = {r[0] for r in con.execute("SELECT surface FROM stg_manual WHERE action='include'")
           if is_candidate(r[0])}

    # generated short imperatives: "kralle" -> "krall" (verb-checked via -st / -en)
    wn_low = {w.lower() for w in wn}
    imper = set()
    for w in wn_low:
        if w.endswith("e") and len(w) - 1 >= MIN_LEN:
            base = w[:-1]
            if (base + "st") in wn_low and (base + "en") in wn_low:
                imper.add(base)
    imper = {b for b in imper if is_candidate(b)}

    surfaces = wn | wk | man | imper
    con.executemany(
        "INSERT OR IGNORE INTO word(surface, lower_form, length, is_acronym) VALUES (?,?,?,?)",
        [(s, s.lower(), len(s), 1 if is_acronym(s) else 0) for s in surfaces])

    # provenance bridge
    con.executemany("INSERT OR IGNORE INTO word_source(surface, source, attr) VALUES (?, 'wngerman', NULL)",
                    [(s,) for s in wn])
    # wiktionary: attr = distinct categories on the page
    wk_cat = {}
    for title, cat in con.execute("SELECT title, category FROM stg_wikt_section"):
        wk_cat.setdefault(title, set()).add(cat)
    con.executemany("INSERT OR IGNORE INTO word_source(surface, source, attr) VALUES (?, 'wikt', ?)",
                    [(t, ",".join(sorted(c))) for t, c in wk_cat.items()])
    con.executemany("INSERT OR IGNORE INTO word_source(surface, source, attr) VALUES (?, 'gen_imperative', NULL)",
                    [(s,) for s in imper])
    con.executemany("INSERT OR IGNORE INTO word_source(surface, source, attr) VALUES (?, 'manual', ?)",
                    [(r[0], r[1]) for r in con.execute("SELECT surface, action FROM stg_manual").fetchall()
                     if is_candidate(r[0])])
    # frequency rank, joined by surface where present
    con.execute("""INSERT OR IGNORE INTO word_source(surface, source, attr)
                   SELECT w.surface, 'freq', f.rank FROM word w
                   JOIN stg_freq f ON f.surface = w.surface""")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM word").fetchone()[0]
    print(f"· word: {n} surfaces (wngerman={len(wn)} wikt={len(wk)} imper={len(imper)} manual_inc={len(man)})")


# ── DECIDE (the source of truth: pure SQL rules) ────────────────────────────
REASONS = [
    ("inc_manual",      "include", 100, "on the manual include list"),
    ("ex_manual",       "exclude",  90, "on the manual exclude list"),
    ("ex_acronym",      "exclude",  80, "all-caps acronym (ADAC, ABS …)"),
    ("ex_name",         "exclude",  70, "Wiktionary name-only surface (no common/inflection sense)"),
    ("ex_abbrev",       "exclude",  60, "Wiktionary abbreviation-only surface"),
    ("inc_wikt_common", "include",  50, "Wiktionary common or inflection sense"),
    ("ex_namelist",     "exclude",  45, "in given-names gazetteer (and no Wiktionary sense)"),
    ("ex_name_genitive","exclude",  42, "genitive/plural -s of a known name (no own sense)"),
    ("inc_wngerman",    "include",  40, "present in wngerman"),
    ("inc_generated",   "include",  30, "generated imperative form"),
    ("ex_no_source",    "exclude",   0, "no accepting source"),
]

DECISION_VIEW = """
DROP VIEW IF EXISTS v_word_decision;
CREATE VIEW v_word_decision AS
WITH cat AS (
    SELECT w.surface,
        MAX(s.category IN ('common','inflection')) AS has_common,
        MAX(s.category = 'name')   AS has_name,
        MAX(s.category = 'abbrev') AS has_abbrev
    FROM word w LEFT JOIN stg_wikt_section s ON s.title = w.surface
    GROUP BY w.surface
),
names AS (                                    -- lower-forms that are proper names
    SELECT DISTINCT w.lower_form
    FROM word w JOIN cat c ON c.surface = w.surface
    WHERE c.has_name = 1 AND COALESCE(c.has_common,0) = 0
    UNION
    SELECT DISTINCT lower_form FROM stg_namelist
),
flags AS (
    SELECT w.surface, w.lower_form, w.is_acronym,
        EXISTS(SELECT 1 FROM stg_manual m WHERE m.lower_form = w.lower_form AND m.action='include') AS man_inc,
        EXISTS(SELECT 1 FROM stg_manual m WHERE m.lower_form = w.lower_form AND m.action='exclude') AS man_exc,
        EXISTS(SELECT 1 FROM stg_wngerman g WHERE g.surface = w.surface) AS in_wn,
        EXISTS(SELECT 1 FROM word_source ws WHERE ws.surface = w.surface AND ws.source='gen_imperative') AS gen_imp,
        EXISTS(SELECT 1 FROM stg_namelist nl WHERE nl.lower_form = w.lower_form) AS in_gazetteer,
        (w.lower_form LIKE '%s' AND EXISTS(           -- "Steves" = "Steve" + genitive/plural -s
            SELECT 1 FROM names n
            WHERE n.lower_form = substr(w.lower_form, 1, length(w.lower_form) - 1)
        )) AS is_name_gen,
        COALESCE(c.has_common,0) AS has_common,
        COALESCE(c.has_name,0)   AS has_name,
        COALESCE(c.has_abbrev,0) AS has_abbrev
    FROM word w LEFT JOIN cat c ON c.surface = w.surface
),
matched AS (
    SELECT surface, 'inc_manual'       AS code FROM flags WHERE man_inc
    UNION ALL SELECT surface, 'ex_manual'        FROM flags WHERE man_exc
    UNION ALL SELECT surface, 'ex_acronym'       FROM flags WHERE is_acronym
    UNION ALL SELECT surface, 'ex_name'          FROM flags WHERE has_name AND NOT has_common
    UNION ALL SELECT surface, 'ex_abbrev'        FROM flags WHERE has_abbrev AND NOT has_common
    UNION ALL SELECT surface, 'inc_wikt_common'  FROM flags WHERE has_common
    UNION ALL SELECT surface, 'ex_namelist'      FROM flags WHERE in_gazetteer
    UNION ALL SELECT surface, 'ex_name_genitive' FROM flags WHERE is_name_gen AND NOT has_common
    UNION ALL SELECT surface, 'inc_wngerman'     FROM flags WHERE in_wn
    UNION ALL SELECT surface, 'inc_generated'    FROM flags WHERE gen_imp
    UNION ALL SELECT surface, 'ex_no_source'     FROM word
),
ranked AS (
    SELECT m.surface, m.code, r.priority, r.kind,
           ROW_NUMBER() OVER (PARTITION BY m.surface ORDER BY r.priority DESC) AS rn
    FROM matched m JOIN reason r ON r.code = m.code
)
SELECT surface, code AS reason_code, priority,
       CASE WHEN kind='include' THEN 1 ELSE 0 END AS accepted
FROM ranked WHERE rn = 1;
"""


def decide(con):
    con.execute("DELETE FROM reason")
    con.executemany("INSERT INTO reason VALUES (?,?,?,?)", REASONS)
    con.executescript(DECISION_VIEW)
    con.execute("DELETE FROM word_decision")
    con.execute("""INSERT INTO word_decision(surface, reason_code, priority, accepted)
                   SELECT surface, reason_code, priority, accepted FROM v_word_decision""")
    # canonical spelling per lower_form group (from accepted surfaces only):
    #   prefer a Wiktionary title casing, else wngerman, else the surface; prefer capitalized
    con.execute("UPDATE word SET canonical = NULL")
    groups = {}
    for surface, lower, in con.execute("""SELECT w.surface, w.lower_form FROM word w
                                          JOIN word_decision d ON d.surface=w.surface
                                          WHERE d.accepted=1"""):
        groups.setdefault(lower, []).append(surface)
    wk = {r[0] for r in con.execute("SELECT DISTINCT title FROM stg_wikt_section")}
    pick = {}
    for lower, surfs in groups.items():
        def rank(s):
            return (s in wk, s[:1].isupper(), s)   # wiktionary title > capitalized > stable
        pick[lower] = max(surfs, key=rank)
    con.executemany("UPDATE word SET canonical = ? WHERE lower_form = ?",
                    [(c, l) for l, c in pick.items()])
    con.commit()
    acc = con.execute("SELECT COUNT(*) FROM word_decision WHERE accepted=1").fetchone()[0]
    play = con.execute("""SELECT COUNT(DISTINCT lower_form) FROM word w
                          JOIN word_decision d ON d.surface=w.surface WHERE d.accepted=1""").fetchone()[0]
    print(f"· word_decision: {acc} accepted surfaces → {play} playable lower-forms")


# ── MART (puzzles + JSON export, reads the accepted dictionary) ──────────────
def mart(con):
    # accepted play dictionary: one entry per lower_form with its display spelling
    sols = []
    for lf, canon in con.execute("""SELECT DISTINCT w.lower_form, w.canonical
            FROM word w JOIN word_decision d ON d.surface = w.surface WHERE d.accepted = 1"""):
        if MIN_LEN <= len(lf) <= TILES:
            sols.append((lf, mask(lf), Counter(lf), canon or lf))

    # seeds = frequency-core 9-letter wngerman words, deduped by letter signature
    wn_lower = {r[0].lower() for r in con.execute("SELECT surface FROM stg_wngerman")}
    seeds = {}
    for (surface,) in con.execute("SELECT surface FROM stg_freq WHERE rank < ?", (TOPN,)):
        if len(surface) == TILES and set(surface) <= ALLOWED and surface in wn_lower:
            seeds.setdefault("".join(sorted(surface)), surface)
    # whitelisted 9-letter words seed a puzzle too — "Gewinnt immer" (extra_words.txt)
    # also means: no frequency rank or wngerman entry required to carry a rack
    for (lf,) in con.execute("SELECT lower_form FROM stg_manual WHERE action='include'"):
        if len(lf) == TILES and set(lf) <= ALLOWED:
            seeds.setdefault("".join(sorted(lf)), lf)
    print(f"· mart: dict={len(sols)} seeds={len(seeds)}")

    puzzles = []
    for i, (sig, seed) in enumerate(seeds.items()):
        if i % 500 == 0:
            print(f"    … {i}/{len(seeds)}")
        rmask, rcount = mask(seed), Counter(seed)
        cands = [(lf, canon) for (lf, m, cnt, canon) in sols
                 if (m & ~rmask) == 0 and submultiset(cnt, rcount)]
        if not cands:
            continue
        best = None                                   # center: solution count in BAND, nearest TARGET
        for ch in sorted(set(seed)):
            ws = [x for x in cands if ch in x[0]]
            n = len(ws)
            if BAND[0] <= n <= BAND[1] and (best is None or abs(n - TARGET) < best[0]):
                best = (abs(n - TARGET), ch, ws)
        if best is None:
            continue
        _, center, wlist = best
        words = sorted({canon for (_lf, canon) in wlist}, key=str.lower)
        pangrams = [w for w in words if len(w) == TILES]
        if not pangrams:      # Namensfilter/Blacklist kann das Seed-Wort entfernt haben
            continue          # → Rätsel ohne findbares Pangramm nie ausliefern
        puzzles.append({
            "sig": sig, "tiles": sorted(seed), "center": center, "words": words,
            "pangrams": pangrams,
            "maxScore": sum(word_score(w) for w in words),
        })

    for p in puzzles:
        p["id"] = hashlib.sha1((p["sig"] + p["center"]).encode()).hexdigest()[:8]
    n = len(puzzles)

    # write back to the mart tables (auditable), then export JSON from the in-memory set
    con.execute("DELETE FROM puzzle")
    con.execute("DELETE FROM puzzle_word")
    con.executemany("""INSERT INTO puzzle(id, signature, tiles, center, difficulty, max_score, word_count)
                       VALUES (?,?,?,?,0,?,?)""",
                    [(p["id"], p["sig"], "".join(p["tiles"]), p["center"],
                      p["maxScore"], len(p["words"])) for p in puzzles])
    con.executemany("INSERT INTO puzzle_word(puzzle_id, lower_form) VALUES (?, ?)",
                    [(p["id"], w.lower()) for p in puzzles for w in p["words"]])
    con.commit()

    puzzles.sort(key=lambda p: p["id"])     # stable rotation order (= server/client modulo)

    # Ship the FULL pool to the Pi as data. The Flask server keeps these in memory and slices
    # the rolling day-window per request (today-7 … today+21) via `day % len(rotation)`,
    # stamping each served puzzle with its absolute `day`. The browser only ever fetches that
    # small window (plus single puzzles by id for old permalinks), never this whole file — so
    # the pool can never go "stale" and no redeploy is needed as days pass. One puzzle per day
    # (no difficulty tiers — they didn't feel meaningfully different in practice; the BAND/
    # TARGET solution-count window above already keeps every puzzle in a similar difficulty
    # range regardless).
    pool = {
        "meta": {"schema": POOL_SCHEMA, "generated": time.strftime("%Y-%m-%d"),
                 "topN": TOPN, "minLen": MIN_LEN, "count": n, "poolSize": n},
        "puzzles": [{"tiles": p["tiles"], "center": p["center"], "words": p["words"],
                     "pangrams": p["pangrams"], "maxScore": p["maxScore"],
                     "id": p["id"]} for p in puzzles],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT)
    med = sorted(len(p["words"]) for p in puzzles)[n // 2] if n else 0
    uml = sum(1 for p in puzzles if any(c in "äöüß" for c in p["tiles"]))
    print(f"· wrote {OUT}")
    print(f"  pool={n}  median_words={med}  umlaut_racks={uml}  size={size/1024:.0f} KiB  "
          f"(full pool; server windows per request)")


# ── audit ───────────────────────────────────────────────────────────────────
def why(con, word):
    rows = con.execute("""SELECT w.surface, w.lower_form, d.reason_code, d.accepted, w.canonical
                          FROM word w JOIN word_decision d ON d.surface=w.surface
                          WHERE w.lower_form = ? ORDER BY w.surface""", (word.lower(),)).fetchall()
    if not rows:
        print(f"'{word}' is not a tracked surface (no source).")
        return
    for surface, lower, code, accepted, canon in rows:
        verdict = "ACCEPTED" if accepted else "rejected"
        print(f"\n{surface}  ({lower})  →  {verdict}  [{code}]   canonical={canon}")
        for source, attr in con.execute("SELECT source, attr FROM word_source WHERE surface=? ORDER BY source", (surface,)):
            print(f"    source: {source:<14} {attr or ''}")
        for ordn, tags, cat in con.execute("SELECT ord, pos_tags, category FROM stg_wikt_section WHERE title=? ORDER BY ord", (surface,)):
            print(f"    wikt §{ordn}: {cat:<11} ({tags})")
        for idx, txt in con.execute("SELECT sense_idx, text FROM stg_wikt_meaning WHERE title=? ORDER BY ord LIMIT 3", (surface,)):
            print(f"    sense {idx}: {txt}")
        for lemma, rel in con.execute("SELECT lemma, relation FROM stg_wikt_baseform WHERE title=?", (surface,)):
            print(f"    base form: {rel} of {lemma}")


def report(con):
    print("\n— sources (surfaces) —")
    for source, n in con.execute("SELECT source, COUNT(*) FROM word_source GROUP BY source ORDER BY 2 DESC"):
        print(f"    {source:<14} {n}")
    print("\n— decisions (surfaces) —")
    for code, kind, n in con.execute("""SELECT d.reason_code, r.kind, COUNT(*) FROM word_decision d
                                        JOIN reason r ON r.code=d.reason_code
                                        GROUP BY d.reason_code ORDER BY r.priority DESC"""):
        print(f"    {code:<16} {kind:<8} {n}")
    acc = con.execute("SELECT COUNT(*) FROM word_decision WHERE accepted=1").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM word_decision").fetchone()[0]
    play = con.execute("""SELECT COUNT(DISTINCT lower_form) FROM word w
                          JOIN word_decision d ON d.surface=w.surface WHERE d.accepted=1""").fetchone()[0]
    print(f"\n    accepted {acc}/{tot} surfaces → {play} playable lower-forms")


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "all"
    force = "--force" in args
    con = connect()
    if cmd == "all":
        extract(con, force=force)
        conform(con)
        decide(con)
        report(con)
    elif cmd == "extract":
        extract(con, force=force)
    elif cmd == "conform":
        conform(con)
    elif cmd == "decide":
        decide(con)
    elif cmd == "mart":
        mart(con)
    elif cmd == "why":
        why(con, args[1])
    elif cmd == "report":
        report(con)
    else:
        print(__doc__)
        sys.exit(1)
    con.close()


if __name__ == "__main__":
    main()
