/* ki-fetchcache.js (30.09.26): ein Abruf je JSON-Datei und Seitenaufruf.
   Messung Startseite 30.09.: news.json wurde 5x geladen (je 82 KB), cards.json 3x -
   jedes Skript holt sich die Datei selbst. Dieses Skript haelt pro Datei EINEN
   laufenden Abruf und gibt jedem Aufrufer eine Kopie (Response.clone). Gilt 60 s,
   danach wird wieder frisch geladen (spaetere Aktualisierungen der Seite).
   Bricht ein Aufrufer per AbortController ab, trifft das nur ihn, nicht den
   gemeinsamen Abruf. Muss VOR ki-bilder.js geladen werden (das umhuellt fetch auch). */
(function () {
  'use strict';
  if (!window.fetch || window.__kiFetchCache) return;
  window.__kiFetchCache = true;
  var ZIEL = /(^|\/)(news|cards|hersteller)\.json(\?|$)/;
  var TTL = 60000;
  var orig = window.fetch.bind(window);
  var cache = {};

  function abbruch() {
    try { return new DOMException('Aborted', 'AbortError'); } catch (e) { var f = new Error('Aborted'); f.name = 'AbortError'; return f; }
  }

  window.fetch = function (eingabe, optionen) {
    var url = typeof eingabe === 'string' ? eingabe : (eingabe && eingabe.url) || '';
    var methode = String((optionen && optionen.method) || (eingabe && eingabe.method) || 'GET').toUpperCase();
    if (methode !== 'GET' || !ZIEL.test(url)) return orig(eingabe, optionen);
    var schluessel;
    try { var u = new URL(url, location.href); schluessel = u.origin + u.pathname; } catch (e) { return orig(eingabe, optionen); }

    var jetzt = Date.now();
    var eintrag = cache[schluessel];
    if (!eintrag || jetzt - eintrag.t > TTL) {
      var opt = {};
      if (optionen) for (var k in optionen) if (k !== 'signal') opt[k] = optionen[k];
      eintrag = { t: jetzt };
      eintrag.p = orig(url, opt).then(function (r) {
        if (!r.ok && cache[schluessel] === eintrag) delete cache[schluessel];
        return r;
      });
      eintrag.p.catch(function () { if (cache[schluessel] === eintrag) delete cache[schluessel]; });
      cache[schluessel] = eintrag;
    }

    var kopie = eintrag.p.then(function (r) { return r.clone(); });
    var signal = optionen && optionen.signal;
    if (!signal) return kopie;
    if (signal.aborted) return Promise.reject(abbruch());
    return new Promise(function (ok, fehler) {
      signal.addEventListener('abort', function () { fehler(abbruch()); }, { once: true });
      kopie.then(ok, fehler);
    });
  };
})();
