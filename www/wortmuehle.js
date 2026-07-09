/* Wortmühle — "Target"/Neun-Buchstaben-Wortspiel. Vanilla JS, keine Abhängigkeiten.
 *
 * 9 Steine (3×3-Mühle) = Buchstaben-Multimenge eines 9-Buchstaben-Wortes; jeder Stein
 * pro Wort höchstens einmal; der hervorgehobene Mittelstein muss vorkommen; Wortlänge 3..9.
 * Punkte: Scrabble-Buchstabenwerte (deutsches Scrabble); Pangramm (Länge 9, alle Steine)
 * bekommt zusätzlich Scrabbles "Bingo"-Bonus (+50, wie für ein volles Regal).
 *
 * Tagesrätsel: pro Tag genau ein festes Rätsel, deterministisch aus dem Datum gewählt
 * (stabil über Wort-Updates). Eingabe per Antippen der Steine (benutzte Steine werden
 * gesperrt, bis man sie per Löschen freigibt); "Mischen" lässt die Mühle drehen.
 * Fortschritt in localStorage. Worterklärungen live von de.wiktionary. */
(function () {
  'use strict';

  var STORE = 'wortmuehle.v1';
  var WIN_KEY = 'wortmuehle.window';                      // gecachtes Deploy-Fenster (offline spielbar)
  var KEEP_DAYS = 7;                                      // == Länge des wählbaren Datumsfensters (s. u.)
  var MINLEN = 3;
  // Deutsches Scrabble: offizielle Buchstabenwerte. ß hat keinen eigenen Stein im
  // echten Spiel (wird als "ss" gelegt) — hier als ss-Ersatz (1+1) bepreist.
  var LETTER_VALUE = {
    e: 1, n: 1, s: 1, i: 1, r: 1, t: 1, u: 1, a: 1, d: 1,
    h: 2, g: 2, l: 2, o: 2,
    m: 3, b: 3, w: 3, z: 3,
    c: 4, f: 4, k: 4, p: 4,
    ä: 6, j: 6, ü: 6, v: 6,
    ö: 8, x: 8,
    q: 10, y: 10,
    ß: 2
  };
  var BINGO_BONUS = 50;   // Scrabbles Bonus fürs volle Regal; hier: alle 9 Steine (Pangramm)
  function scoreWord(w) {
    w = w.toLowerCase();
    var pts = 0;
    for (var i = 0; i < w.length; i++) pts += LETTER_VALUE[w[i]] || 0;
    return pts + (w.length === 9 ? BINGO_BONUS : 0);
  }
  var byId = {}, byDay = {}, allLoaded = [];
  var selectedDay = 0;                                    // aktuell gewählter Tag (dayNum); 0 = noch nicht gesetzt
  var puzzle = null, canon = {}, found = new Set(), ended = false;
  var layout = [], cellEls = [], inputIdx = [];          // layout[0] = hervorgehobene Mitte
  var prog = {}, today = '';
  var HOVER = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  var $ = function (id) { return document.getElementById(id); };
  var hive = $('hive'), current = $('current'), statsEl = $('stats'),
      foundEl = $('found'), toastEl = $('toast'), defpop = $('defpop');

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
  }
  function dayNum() {                                    // Tage seit 1970 (lokaler Kalender)
    var d = new Date();
    return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000);
  }
  function puzzleFor(day) {                              // Rätsel, das für `day` ansteht
    if (byDay[day]) return byDay[day];
    // Offline-Build: voller Pool ohne day-Stempel → gleiche Rotation wie der Server
    // (sortiert nach id, dann day % len) liefert dasselbe Tagesrätsel, jeden Tag, ohne Netz.
    if (!allLoaded.length) return null;
    var p = allLoaded[((day % allLoaded.length) + allLoaded.length) % allLoaded.length];
    return Object.assign({}, p, { day: day });           // Datumsleiste/Permalink folgen dem Tag
  }
  function dayLoaded(day) {                              // Offline-Build: voller Pool → jeder Tag spielbar
    return (day in byDay) || allLoaded.length > 0;
  }
  function dateLabel(day) {
    var t = dayNum();
    if (day === t) return 'Heute';
    if (day === t - 1) return 'Gestern';
    var dt = new Date(day * 86400000);                  // dayNum ist UTC-Mitternacht
    return ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'][dt.getUTCDay()] +
           ' ' + dt.getUTCDate() + '.' + (dt.getUTCMonth() + 1) + '.';
  }

  // ── Deploy-Fenster laden (Cache zuerst → offline spielbar, dann frisch vom Pi) ──
  function applyPool(pool) {
    byId = {}; byDay = {}; allLoaded = [];
    pool.puzzles.forEach(function (p) {
      byId[p.id] = p; allLoaded.push(p);
      if (typeof p.day === 'number') byDay[p.day] = p;
    });
  }
  function loadWindow() {                                // frisch vom Pi holen + cachen
    return fetch(window.POOL_URL, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (pool) {
        applyPool(pool);
        try { localStorage.setItem(WIN_KEY, JSON.stringify(pool)); } catch (e) {}
        return pool;
      });
  }
  function loadCachedWindow() {                          // sofort aus localStorage (kann offline sein)
    try {
      var s = localStorage.getItem(WIN_KEY);
      if (!s) return false;
      applyPool(JSON.parse(s));
      return true;
    } catch (e) { return false; }
  }

  var hadCache = loadCachedWindow();
  if (hadCache) { $('loading').hidden = true; resume(); }   // sofort spielbar aus Cache
  loadWindow().then(function () {
    $('loading').hidden = true;
    if (hadCache) buildDateBar();                        // frische Daten → Datumsleiste auffrischen
    else resume();
  }).catch(function () {
    if (!hadCache) $('loading').textContent = 'Konnte Rätsel nicht laden.';
  });

  // ── Fortschritt (pro Rätsel, verfällt nach KEEP_DAYS) ────────────────────────
  function save() {
    if (puzzle) prog[puzzle.id] = {
      f: Array.from(found), e: ended, t: dayNum(),
      day: (typeof puzzle.day === 'number') ? puzzle.day : dayNum()   // für die Aufräum-Logik
    };
    try { localStorage.setItem(STORE, JSON.stringify({ prog: prog })); }
    catch (e) {}
  }
  function resume() {
    today = todayStr();
    selectedDay = dayNum();
    var s = null;
    try { s = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch (e) {}
    prog = (s && s.prog) || {};
    var now = dayNum();                                   // Aufräumen: Rätsel, die nicht mehr wählbar
    Object.keys(prog).forEach(function (id) {             // sind (älter als das wählbare Fenster), fliegen raus
      var d = (prog[id].day != null) ? prog[id].day : (prog[id].t || 0);
      if (now - d > KEEP_DAYS) delete prog[id];
    });
    buildDateBar();
    var pid = null;                                       // Permalink ?p=<id>
    try { pid = new URLSearchParams(location.search).get('p'); } catch (e) {}
    if (pid && byId[pid]) startPuzzle(byId[pid]);
    else if (pid) {                                       // außerhalb des Fensters: Rätsel einzeln holen
      fetch(window.PUZZLE_URL + encodeURIComponent(pid) + '.json')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (p) { if (p) { byId[p.id] = p; startPuzzle(p); } else start(); })
        .catch(function () { start(); });
    } else start();
  }

  // ── Spiel starten ───────────────────────────────────────────────────────────
  function start() {                                      // Rätsel für den gewählten Tag
    var p = puzzleFor(selectedDay);
    if (p) { startPuzzle(p); return; }
    // nicht geladen → einmal frisch vom Pi holen, dann erneut versuchen
    toast('lädt vom Pi …');
    loadWindow().then(function () {
      buildDateBar();
      var q = puzzleFor(selectedDay);
      if (q) { startPuzzle(q); return; }
      // Notnagel für heute: irgendeins (Pool veraltet)
      if (selectedDay === dayNum() && allLoaded.length) startPuzzle(allLoaded[dayNum() % allLoaded.length]);
      else toast('Dieses Datum gibt es nur mit Verbindung zum Pi.');
    }).catch(function () { toast('Keine Verbindung zum Pi.'); });
  }
  function startPuzzle(p) {                               // konkretes Rätsel (Tag oder Permalink)
    puzzle = p;
    if (typeof p.day === 'number') selectedDay = p.day;   // Datumsleiste folgt dem Rätsel
    buildDateBar();
    try { history.replaceState(null, '', '?p=' + p.id); } catch (e) {}  // URL = Lesezeichen
    var rec = prog[p.id] || { f: [], e: false };
    found = new Set(rec.f); ended = !!rec.e; inputIdx = [];
    canon = {};
    p.words.forEach(function (w) { canon[w.toLowerCase()] = w; });

    var outer = p.tiles.slice();
    outer.splice(outer.indexOf(p.center), 1);             // eine Instanz der Mitte raus
    shuffleArr(outer);
    layout = [{ letter: p.center, used: false }];
    outer.forEach(function (ch) { layout.push({ letter: ch, used: false }); });

    buildHive(); renderCurrent(); renderFound(); renderStats();
    setControlsDisabled(ended); hideDef(true);
  }

  // Großschreibung für die Anzeige: ß → ẞ (Versal-Eszett), NICHT "SS" wie es
  // String.toUpperCase()/CSS text-transform per Unicode-Default machen würden.
  function up(ch) { return String(ch).replace(/ß/g, 'ẞ').toUpperCase(); }

  // ── Wabe als Blüte: Mitte + 8 Blütenblätter rotationssymmetrisch im Kreis ──
  function buildHive() {                                  // 3×3-Mühle, Mitte = layout[0]
    hive.innerHTML = ''; cellEls = [];
    var order = [1, 2, 3, 4, 0, 5, 6, 7, 8];             // Zeilen-Reihenfolge; layout[0] landet im Zentrum
    order.forEach(function (li) {
      var cell = layout[li];
      var b = document.createElement('button');
      b.className = 'cell' + (li === 0 ? ' center' : '') + (cell.used ? ' used' : '');
      b.innerHTML = '<span>' + up(cell.letter) + '</span>';
      b.addEventListener('click', function () { type(li); });
      hive.appendChild(b);
      cellEls[li] = b;                                    // cellEls bleibt nach layout-Index indiziert
    });
  }
  function word() { return inputIdx.map(function (i) { return layout[i].letter; }).join(''); }
  function renderCurrent() {
    current.innerHTML = '';
    inputIdx.forEach(function (i) {
      var s = document.createElement('span');
      s.textContent = up(layout[i].letter);
      if (layout[i].letter === puzzle.center) s.className = 'miss';
      current.appendChild(s);
    });
    var caret = document.createElement('span'); caret.className = 'caret';
    current.appendChild(caret);
  }
  function renderFound() {
    // im Spiel nur gefundene (grün); nach Aufgeben alle eingereiht (fehlende gedämpft rot)
    var words = (ended ? puzzle.words.slice() : Array.from(found))
                  .sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
    foundEl.innerHTML = '';
    words.forEach(function (w) {
      var s = document.createElement('span');
      // Nur die Anzeige ist klein — w bleibt original-cased (Wiktionary-Lookup/Link
      // brauchen die echte Groß-/Kleinschreibung, s. showDef/renderDef unten).
      s.textContent = w.toLowerCase();
      s.className = (found.has(w) ? 'got' : 'miss') + (w.length === 9 ? ' pan' : '');
      s.addEventListener('click', function (e) { e.stopPropagation(); toggleDef(w, s); });
      if (HOVER) {
        s.addEventListener('mouseenter', function () { if (!defpop.dataset.pin) showDef(w, s, false); });
        s.addEventListener('mouseleave', function () { if (!defpop.dataset.pin) hideDef(); });
      }
      foundEl.appendChild(s);
    });
  }
  function renderStats() {
    var pts = 0;
    found.forEach(function (w) { pts += scoreWord(w); });
    var total = puzzle.words.length, max = puzzle.maxScore;
    statsEl.innerHTML =
      '<div><b>' + pts + '</b>/' + max + ' Pkt · ' + (max ? Math.round(pts / max * 100) : 0) + ' %</div>' +
      '<div><b>' + found.size + '</b>/' + total + ' Wörter · ' + (total ? Math.round(found.size / total * 100) : 0) + ' %</div>';
  }

  // ── Eingabe (tile-genau; benutzte Waben gesperrt) ─────────────────────────
  function type(idx) {
    if (ended || layout[idx].used) return;
    layout[idx].used = true; inputIdx.push(idx);
    cellEls[idx].classList.add('used'); renderCurrent();
  }
  function del() {
    if (!inputIdx.length) return;
    var idx = inputIdx.pop(); layout[idx].used = false;
    cellEls[idx].classList.remove('used'); renderCurrent();
  }
  function clearInput() {
    inputIdx.forEach(function (i) { layout[i].used = false; cellEls[i].classList.remove('used'); });
    inputIdx = []; renderCurrent();
  }
  function submit() {
    if (ended) return;
    var lw = word();                                      // getippte Buchstaben (klein)
    if (!lw) return;
    if (lw.length < MINLEN) return toast('Zu kurz');
    if (lw.indexOf(puzzle.center) < 0) return toast('Mitte fehlt');
    var cw = canon[lw];                                   // kanonische Schreibweise
    if (!cw) { clearInput(); return toast('Kein Wort'); }
    if (found.has(cw)) { clearInput(); return toast('Schon da'); }
    found.add(cw); clearInput();
    toast(lw.length === 9 ? 'Pangramm! +' + scoreWord(lw) : '+' + scoreWord(lw), true);
    renderFound(); renderStats(); save();
  }

  function giveUp() {
    if (ended) return;
    askConfirm('Wirklich aufgeben? Alle Lösungen werden dann angezeigt.', function () {
      ended = true; clearInput(); setControlsDisabled(true); renderFound(); save();
    });
  }

  // ── In-App-Bestätigung (statt window.confirm) ──────────────────────────────
  function askConfirm(msg, onYes) {
    var modal = $('confirm'), yes = $('confirm-yes'), no = $('confirm-no');
    $('confirm-msg').textContent = msg;
    modal.hidden = false;
    function close() {
      modal.hidden = true;
      yes.removeEventListener('click', onYesClick);
      no.removeEventListener('click', close);
      modal.removeEventListener('click', onBackdrop);
    }
    function onYesClick() { close(); onYes(); }
    function onBackdrop(e) { if (e.target === modal) close(); }
    yes.addEventListener('click', onYesClick);
    no.addEventListener('click', close);
    modal.addEventListener('click', onBackdrop);
  }

  // ── Worterklärung (de.wiktionary, live) ────────────────────────────────────
  var defCache = {}, wtCache = {};
  var WIKT_API = 'https://de.wiktionary.org/w/api.php?action=parse&prop=wikitext' +
                 '&format=json&origin=*&redirects=1&page=';

  function toggleDef(w, el) {
    if (defpop.dataset.pin === w && !defpop.hidden) { hideDef(true); return; }
    showDef(w, el, true);
  }
  function showDef(w, el, pin) {
    if (pin) defpop.dataset.pin = w; else delete defpop.dataset.pin;
    var r = el.getBoundingClientRect();
    defpop.innerHTML = '<div class="w">' + esc(w.toLowerCase()) + '</div><div class="muted">…</div>';
    defpop.hidden = false;
    defpop.style.left = Math.max(8, Math.min(r.left + window.scrollX,
      window.scrollX + document.documentElement.clientWidth - defpop.offsetWidth - 8)) + 'px';
    defpop.style.top = (r.bottom + window.scrollY + 6) + 'px';
    fetchDef(w).then(function (res) {
      if (defpop.dataset.pin !== w && pin) return;
      defpop.innerHTML = renderDef(w, res);
    });
  }
  function hideDef(force) {
    if (defpop.dataset.pin && !force) return;
    defpop.hidden = true; delete defpop.dataset.pin;
  }

  // ── Wikitext holen + Bedeutungen/Grundform parsen ──────────────────────────
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function wikitext(title) {
    if (wtCache[title] !== undefined) return Promise.resolve(wtCache[title]);
    return fetch(WIKT_API + encodeURIComponent(title))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var wt = (d && d.parse && d.parse.wikitext && d.parse.wikitext['*']) || '';
        wtCache[title] = wt; return wt;
      }).catch(function () { wtCache[title] = ''; return ''; });
  }
  function germanSection(wt) {                            // deutscher Sprachabschnitt
    var m = wt && wt.match(/==[^\n]*\(\{\{Sprache\|Deutsch\}\}\)[^\n]*==([\s\S]*?)(?=\n==[^=]|$)/);
    return m ? m[1] : '';
  }
  function cleanWiki(s) {                                 // Wiki-Markup → Klartext
    return s
      .replace(/<ref[^>]*\/>/gi, '').replace(/<ref[\s\S]*?<\/ref>/gi, '')
      .replace(/<!--[\s\S]*?-->/g, '')
      .replace(/\{\{K\|([^}]*)\}\}/g, function (_, p) {   // Kontext-Tag → "Bereich: "
        var ps = p.split('|').filter(function (x) { return x && x.indexOf('=') < 0; });
        return ps.length ? ps.join(', ') + ': ' : '';
      })
      .replace(/\{\{[^{}]*\}\}/g, '')                     // übrige Vorlagen raus
      .replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, '$1')        // [[ziel|text]] → text
      .replace(/\[\[([^\]]*)\]\]/g, '$1')                 // [[wort]] → wort
      .replace(/'''?/g, '')
      .replace(/\s+/g, ' ').trim();
  }
  function meanings(sec) {                                // nummerierte Bedeutungen
    var m = sec.match(/\{\{Bedeutungen\}\}\s*\n([\s\S]*?)(?=\n\{\{|\n\n|$)/);
    if (!m) return [];
    var out = [];
    m[1].split('\n').forEach(function (line) {
      line = line.replace(/^:/, '').trim();
      var mm = line.match(/^\[([\d ,.–\-]+)\]\s*(.*)$/);
      if (mm) {
        var txt = cleanWiki(mm[2]);
        if (txt) out.push('[' + mm[1].replace(/\s/g, '') + '] ' + txt);
      } else if (out.length && line && line[0] !== '{') {
        out[out.length - 1] += ' ' + cleanWiki(line);    // Fortsetzungszeile
      }
    });
    return out;
  }
  function baseForm(sec) {                                // Beugung → Grundform + Label
    var lemma = '';
    var g = sec.match(/\{\{Grundformverweis[^}]*\}\}/);
    if (g) {
      g[0].slice(2, -2).split('|').slice(1).some(function (p) {
        if (p && p.indexOf('=') < 0) { lemma = p.trim(); return true; }
      });
    }
    if (!lemma) {
      var d = sec.match(/des (?:Substantivs|Verbs|Adjektivs|Adverbs|Pronomens|Numerals)\s+'*\[\[([^\]|]+)/);
      if (d) lemma = d[1].trim();
    }
    if (!lemma) {
      var v = sec.match(/\bvon\s+'*\[\[([^\]|]+)\]\]/);
      if (v) lemma = v[1].trim();
    }
    if (!lemma) return null;
    var rel = /\bKomparativ\b/.test(sec) ? 'Komparativ'
            : /\bSuperlativ\b/.test(sec) ? 'Superlativ'
            : /\bPlural\b/.test(sec) ? 'Plural'
            : /\bSingular\b/.test(sec) ? 'Singular' : 'Form';
    return { lemma: lemma, label: rel + ' von ' + lemma };
  }
  function fetchDef(w) {
    if (defCache[w]) return Promise.resolve(defCache[w]);
    return wikitext(w).then(function (wt) {
      var sec = germanSection(wt);
      if (!sec) return { meanings: [] };
      var ms = meanings(sec);
      if (ms.length) return { meanings: ms };
      var base = baseForm(sec);                           // Beugung → Grundform nachladen
      if (base) {
        return wikitext(base.lemma).then(function (bwt) {
          return { deriv: base.label, meanings: meanings(germanSection(bwt)) };
        });
      }
      return { meanings: [] };
    }).then(function (res) {
      defCache[w] = res; return res;
    }).catch(function () { return { meanings: [] }; });
  }
  function renderDef(w, res) {
    var html = '<div class="w">' + esc(w.toLowerCase()) + '</div>';
    if (res.deriv) html += '<div class="deriv">' + esc(res.deriv) + '</div>';
    var ms = res.meanings || [], show = ms.slice(0, 5);
    if (show.length) {
      show.forEach(function (m) { html += '<div class="bd">' + esc(m) + '</div>'; });
      if (ms.length > show.length)
        html += '<div class="muted">(+' + (ms.length - show.length) + ' weitere)</div>';
    } else {
      html += '<div class="muted">Keine Bedeutung gefunden.</div>';
    }
    return html + '<a href="https://de.wiktionary.org/wiki/' + encodeURIComponent(w) +
           '" target="_blank" rel="noopener">↗ Wiktionary</a>';
  }

  // ── Helfer ────────────────────────────────────────────────────────────────
  function setControlsDisabled(v) {
    ['del', 'shuffle', 'enter'].forEach(function (id) { $(id).disabled = v; });
    $('giveup').disabled = v;
    cellEls.forEach(function (c) { c.disabled = v; });
  }
  var toastT;
  function toast(msg, good) {
    toastEl.textContent = msg; toastEl.className = 'toast' + (good ? ' good' : '');
    toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 1100);
  }
  function shuffleArr(a) {
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1)), t = a[i]; a[i] = a[j]; a[j] = t;
    }
  }

  $('del').addEventListener('click', del);
  $('enter').addEventListener('click', submit);
  $('shuffle').addEventListener('click', function () {
    if (ended) return;
    clearInput();
    var outer = layout.slice(1).map(function (c) { return c.letter; });
    shuffleArr(outer);
    layout = [layout[0]].concat(outer.map(function (ch) { return { letter: ch, used: false }; }));
    buildHive();
    hive.classList.remove('turning'); void hive.offsetWidth; hive.classList.add('turning'); // Mühle dreht
  });
  hive.addEventListener('animationend', function () { hive.classList.remove('turning'); });
  $('giveup').addEventListener('click', giveUp);

  // ── Datums-Auswahl (letzte 7 Tage; fett = im Browser, grau = nur mit Pi-Verbindung) ──
  function buildDateBar() {
    var pop = $('date-pop'), btn = $('date-btn');
    if (!pop || !btn) return;
    var t = dayNum(), html = '';
    for (var k = 0; k < KEEP_DAYS; k++) {                 // heute … heute-6
      var d = t - k, loaded = dayLoaded(d);
      html += '<button class="dateopt' + (loaded ? '' : ' off') + (d === selectedDay ? ' sel' : '') +
              '" role="menuitem" data-day="' + d + '">' + dateLabel(d) + '</button>';
    }
    pop.innerHTML = html;
    btn.hidden = false;
    btn.textContent = dateLabel(selectedDay) + ' ▾';
  }
  function closeDatePop() {
    $('date-pop').hidden = true;
    $('date-btn').setAttribute('aria-expanded', 'false');
  }
  $('date-btn').addEventListener('click', function (e) {
    e.stopPropagation();
    var pop = $('date-pop'), open = pop.hidden;
    pop.hidden = !open;
    $('date-btn').setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  $('date-pop').addEventListener('click', function (e) {
    var b = e.target.closest('.dateopt');
    if (!b) return;
    closeDatePop();
    var day = +b.dataset.day;
    if (day === selectedDay && puzzle) return;            // schon offen
    selectedDay = day;
    save();                                               // laufenden Fortschritt sichern, dann wechseln
    start();
  });
  document.addEventListener('click', function () { closeDatePop(); });
  document.addEventListener('click', function (e) {
    if (!defpop.contains(e.target)) hideDef(true);
  });
})();
