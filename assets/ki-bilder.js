/* ki-bilder.js (28.09.26): Quellbilder aus dem eigenen Spiegel bevorzugen.
   Die Pipeline legt Meldungsbilder als WebP im Medien-Repo ab (image_local, PR #12).
   Viele Verlage sperren Hotlinks, der Spiegel nicht. Dieses Skript setzt beim Laden
   von news.json, archive.json und archiv-monate/*.json in jedem Eintrag mit
   image_local das Feld image auf den Spiegel (Original bleibt in image_orig).
   Muss VOR den Seitenskripten geladen werden (im <head>, ohne defer). */
(function () {
  'use strict';
  if (!window.fetch || window.__kiBilder) return;
  window.__kiBilder = true;
  var ZIEL = /(^|\/)(news|archive)\.json(\?|$)|archiv-monate\/[^/?]+\.json(\?|$)/;
  var orig = window.fetch.bind(window);

  function umbiegen(wert, tiefe) {
    if (!wert || typeof wert !== 'object' || tiefe > 6) return;
    if (Array.isArray(wert)) {
      for (var i = 0; i < wert.length; i++) umbiegen(wert[i], tiefe + 1);
      return;
    }
    if (typeof wert.image_local === 'string' && /^https:\/\//.test(wert.image_local)) {
      if (wert.image && wert.image !== wert.image_local) wert.image_orig = wert.image;
      wert.image = wert.image_local;
    }
    for (var k in wert) {
      if (Object.prototype.hasOwnProperty.call(wert, k) && wert[k] && typeof wert[k] === 'object') umbiegen(wert[k], tiefe + 1);
    }
  }

  window.fetch = function (eingabe, optionen) {
    var url = typeof eingabe === 'string' ? eingabe : (eingabe && eingabe.url) || '';
    var p = orig(eingabe, optionen);
    if (!ZIEL.test(url)) return p;
    return p.then(function (antwort) {
      if (!antwort || !antwort.ok) return antwort;
      return antwort.clone().json().then(function (daten) {
        umbiegen(daten, 0);
        return new Response(JSON.stringify(daten), {
          status: antwort.status, statusText: antwort.statusText,
          headers: { 'Content-Type': 'application/json; charset=utf-8' }
        });
      }, function () { return antwort; });
    });
  };
})();
