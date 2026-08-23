/* ============================================================================
   Modell-Registry — Panel-Logik für Archiv.html
   ============================================================================
   Vollständig gekapselt in einer IIFE. Exportiert genau eine globale Funktion:
   toggleRegistryPanel(), analog zu togglePodcastPanel()/toggleVideoPanel().
   Rührt weder allNews noch render(), createCard(), setFilter() oder setLayout()
   an. Alle Element-IDs tragen das Präfix "rg-", alle CSS-Klassen ebenfalls.

   Daten: registry/registry.json, geladen per fetch wie news.json und
   archive.json auch — kein globales window.REGISTRY, kein <script src>.

   Struktur der Ansicht, dreistufig:
       Anbieter  ->  Familie (zugeklappt)  ->  Modell  ->  Artikel
   Gezeigt wird, was im letzten Jahr ein Release hatte. Älteres bleibt
   erreichbar, nur hinter einem Schalter.
   Stand 20.08.2026.
   ========================================================================= */
(function () {
  "use strict";

  var R = null, geladen = false, laedt = false;
  var offenAnb = null, offenMod = null, offeneFam = null;
  var zeigeAlteAnbieter = false, zeigeAlteFamilien = false;
  // Das Panel steht offen, sobald die Seite geladen ist -- die Registry ist
  // jetzt der Schwerpunkt der Archivseite, nicht mehr ein Anhang.
  var offen = true;

  // Ein Jahr. Alles Ältere ist nicht falsch, nur nicht mehr die Nachricht.
  var GRENZE = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);

  var modVonAnb = {}, anbVon = {}, artZahlAnb = {}, maxMod = 1;
  var F = {};        // Facetten je Link
  var artMap = {};   // Link -> Artikel aus allNews

  /*
   * Die Artikel kommen aus allNews, derselben Quelle wie das Artikelraster.
   * Frueher lagen Kopien in registry.json -- das hiess: 367 Artikel fehlten
   * durch die Deckelung, Bild und Zusammenfassung fehlten ganz, und die Kopie
   * veraltete ab dem Tag ihrer Erzeugung. Jetzt wird nur noch zugeordnet.
   */
  function baueArtMap() {
    var q = window.allNews;
    if (!q || !q.length) return false;
    if (artMap.__n === q.length) return true;   // unveraendert
    artMap = { __n: q.length };
    q.forEach(function (a) { if (a && a.link) artMap[a.link] = a; });
    return true;
  }

  function artikel(link) { return artMap[link]; }

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Artikellinks kommen aus fremden RSS-Feeds. esc() schützt nur vor
  // Attribut-Ausbruch — ein href="javascript:…" käme unbeschadet durch und
  // würde beim Klick im Seitenkontext ausgeführt. Deshalb Schema-Whitelist.
  function sicherLink(u) {
    u = String(u == null ? "" : u).trim();
    return /^https?:\/\//i.test(u) ? u : "";
  }

  function neuestes(lst) {
    return lst.reduce(function (b, m) { return (m.r || "") > b ? (m.r || "") : b; }, "");
  }

  function entprellt(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  /* ── Laden ─────────────────────────────────────────────────────────── */
  function laden() {
    if (geladen || laedt) return;
    laedt = true;
    // allNews wird per fetch gefuellt und ist beim ersten Zeichnen oft noch
    // leer. Deshalb spaeter nochmal nachziehen.
    var versuche = 0;
    var warten = setInterval(function () {
      if (baueArtMap()) {
        clearInterval(warten);
        if (geladen) { zeichneAnbieter(); zeichneListe(); }
        return;
      }
      if (++versuche > 40) {          // zehn Sekunden
        clearInterval(warten);
        // Ohne allNews gibt es keine Artikel zum Anzeigen. Das lieber sagen,
        // als eine leere Liste ohne Erklaerung zu zeigen.
        if ($("rg-liste") && !$("rg-liste").innerHTML) {
          $("rg-liste").innerHTML = '<p class="rg-leer">Artikel konnten nicht ' +
            'geladen werden (news.json / archive.json). Die Modellansicht ' +
            'funktioniert trotzdem.</p>';
        }
      }
    }, 250);
    // Wenn die Seite per file:// geoeffnet wird, verbietet der Browser jeden
    // fetch -- auch auf Nachbardateien. Dann greift registry/registry-data.js,
    // das die Daten als window.KI_REGISTRY_DATA mitbringt. Auf dem Server
    // gewinnt immer der fetch, damit nur eine Datei gepflegt werden muss.
    if (location.protocol === "file:") {
      if (window.KI_REGISTRY_DATA) {
        F = (window.KI_FACETTEN_DATA || {}).artikel || {};
        uebernehmen(window.KI_REGISTRY_DATA); return;
      }
      // Nur hier nachladen, nicht per festem script-Tag: auf dem Server waeren
      // das 430 KB, die jeder Besucher mitschleppt, ohne das Panel zu oeffnen.
      $("rg-status").textContent = "Registry wird geladen (lokale Datei) …";
      var sk = document.createElement("script");
      sk.src = "registry/registry-data.js";
      sk.onload = function () {
        if (window.KI_REGISTRY_DATA) {
          F = (window.KI_FACETTEN_DATA || {}).artikel || {};
          uebernehmen(window.KI_REGISTRY_DATA);
        }
        else $("rg-status").textContent = "registry/registry-data.js ohne Daten.";
      };
      sk.onerror = function () {
        laedt = false;
        $("rg-status").textContent = "registry/registry-data.js nicht gefunden.";
      };
      document.head.appendChild(sk);
      return;
    }
    $("rg-status").textContent = "Registry wird geladen …";
    Promise.all([
      fetch("registry/registry.json?t=" + Date.now()).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }),
      // Facetten sind optional: fehlen sie, laeuft die Registry ohne Filter
      // weiter statt gar nicht.
      fetch("registry/facetten.json?t=" + Date.now())
        .then(function (r) { return r.ok ? r.json() : { artikel: {} }; })
        .catch(function () { return { artikel: {} }; })
    ]).then(function (beide) {
      F = beide[1].artikel || {};
      uebernehmen(beide[0]);
    })
      .catch(function (e) {
        laedt = false;
        if (window.KI_REGISTRY_DATA) {
          F = (window.KI_FACETTEN_DATA || {}).artikel || {};
          uebernehmen(window.KI_REGISTRY_DATA); return;
        }
        $("rg-status").textContent =
          "Registry nicht ladbar (" + e.message + "). Beim Öffnen per Doppelklick " +
          "blockiert der Browser jeden Dateizugriff — dafür einen lokalen Server " +
          "starten oder registry/registry-data.js einbinden.";
      });
  }

  function uebernehmen(d) {
    R = d;
    R.anbieter.forEach(function (a) { anbVon[a.a] = a; modVonAnb[a.a] = []; });
    R.modelle.forEach(function (m) { (modVonAnb[m.a] = modVonAnb[m.a] || []).push(m); });
    Object.keys(R.artAnbieter).forEach(function (k) {
      artZahlAnb[k] = R.artAnbieter[k].length;
    });
    maxMod = Math.max.apply(null, R.anbieter.map(function (a) { return a.m; })) || 1;
    geladen = true; laedt = false;
    $("rg-status").textContent = "";
    fuelleFilter();
    zeichneAnbieter();
    zeichneListe();
  }

  /* ── Anbieterebene ─────────────────────────────────────────────────── */
  function zeichneAnbieter() {
    if (!R) return;
    var q = ($("rg-q").value || "").toLowerCase().trim();
    var kat = $("rg-kat").value;
    var sort = $("rg-sort").value;

    var liste = R.anbieter.filter(function (a) {
      if (kat && !(a.k || {})[kat]) return false;
      if (!q) return true;
      if ((a.n + " " + a.a).toLowerCase().indexOf(q) > -1) return true;
      return (modVonAnb[a.a] || []).some(function (m) {
        return m.n.toLowerCase().indexOf(q) > -1;
      });
    });
    liste.sort(function (x, y) {
      if (sort === "name") return x.n.localeCompare(y.n);
      if (sort === "release") return (y.r || "").localeCompare(x.r || "");
      if (sort === "artikel") return (artZahlAnb[y.a] || 0) - (artZahlAnb[x.a] || 0);
      return y.m - x.m;
    });

    // Ruhend: seit über einem Jahr kein neues Modell.
    var ruhend = liste.filter(function (a) { return (a.r || "") < GRENZE; });
    var frisch = liste.filter(function (a) { return (a.r || "") >= GRENZE; });
    var zeigen = zeigeAlteAnbieter ? frisch.concat(ruhend) : frisch;

    $("rg-cnt").textContent = zeigen.length + " Anbieter · " +
      (kat ? zeigen.reduce(function (n, a) { return n + a.k[kat]; }, 0) + " " + kat
           : R.modelle.length + " Modelle");

    // Das Badge in der Panel-Kopfzeile stand bis 23.08.2026 statisch im HTML
    // ("391 Modelle · 57 Anbieter") und veraltete bei jedem Registry-Lauf.
    // Es zeigt bewusst die GESAMTZAHL (inkl. ruhender Anbieter) -- rg-cnt daneben
    // zeigt die gefilterte Auswahl, deshalb stehen dort zwei verschiedene Zahlen.
    var badge = $("registry-count");
    if (badge) badge.textContent = R.modelle.length + " Modelle · " + liste.length + " Anbieter";

    $("rg-grid").innerHTML = zeigen.map(function (a) {
      var na = artZahlAnb[a.a] || 0;
      var farbe = na > 20 ? "var(--rg-ak)" : na > 0 ? "var(--rg-ak2)" : "var(--rg-line)";
      var ruht = (a.r || "") < GRENZE;
      return '<div class="rg-pv' + (offenAnb === a.a ? " on" : "") + (ruht ? " ruht" : "") +
        '" data-a="' + esc(a.a) + '" role="button" tabindex="0" aria-expanded="' +
        (offenAnb === a.a) + '">' +
        '<div class="rg-pv-n"><span class="rg-dot" style="background:' + farbe + '"></span>' +
        esc(a.n) + '</div><div class="rg-pv-m"><span>' +
        (kat ? a.k[kat] + " " + kat : a.m + " Modelle") + '</span><span>' + a.f + ' Familien</span>' +
        Object.keys(a.k || {}).filter(function (x) { return x !== "text"; })
          .map(function (x) { return '<span class="rg-kt ' + x + '">' + x + '</span>'; }).join("") +
        (na ? '<span style="color:var(--rg-ak2)">' + na + ' News</span>' : '') +
        '</div><div class="rg-pv-b"><i style="width:' + (a.m / maxMod * 100) + '%"></i></div></div>';
    }).join("");

    $("rg-mehr-anb").hidden = ruhend.length === 0;
    $("rg-mehr-anb").textContent = zeigeAlteAnbieter
      ? "▲  " + ruhend.length + " ruhende Anbieter ausblenden"
      : "▼  " + ruhend.length + " ruhende Anbieter anzeigen (seit über einem Jahr kein neues Modell)";

    zeichneDetail();
  }

  /* ── Familien- und Modellebene ─────────────────────────────────────── */
  function zeichneDetail() {
    var host = $("rg-detail");
    if (!offenAnb || !R) { host.innerHTML = ""; return; }
    var a = anbVon[offenAnb];
    var kat = $("rg-kat").value;
    var mods = (modVonAnb[offenAnb] || []).filter(function (m) { return !kat || m.k === kat; });

    var fam = {};
    mods.forEach(function (m) { (fam[m.f] = fam[m.f] || []).push(m); });
    var alleFam = Object.keys(fam).sort(function (x, y) {
      return neuestes(fam[y]).localeCompare(neuestes(fam[x]));
    });
    var alteFam = alleFam.filter(function (f) { return neuestes(fam[f]) < GRENZE; });
    var famNamen = zeigeAlteFamilien
      ? alleFam
      : alleFam.filter(function (f) { return neuestes(fam[f]) >= GRENZE; });

    // Genau die neueste Familie steht offen. 30 gleichzeitig aufgeklappt wäre
    // derselbe Fehler wie 60 flache Modellkacheln, nur eine Ebene höher.
    if (offeneFam === null) offeneFam = famNamen[0] || null;

    var heute = new Date().toISOString().slice(0, 10);

    var html = famNamen.map(function (f) {
      var lst = fam[f].slice().sort(function (x, y) {
        return (y.r || "").localeCompare(x.r || "");
      });
      var auf = offeneFam === f;
      var ruht = neuestes(lst) < GRENZE;
      var news = lst.reduce(function (n, m) { return n + (R.artModell[m.s] || []).length; }, 0);
      var kats = {};
      lst.forEach(function (m) { kats[m.k] = 1; });

      return '<div class="rg-fam' + (ruht ? " ruht" : "") + '">' +
        '<button class="rg-fam-b' + (auf ? " auf" : "") + '" data-f="' + esc(f) +
        '" aria-expanded="' + auf + '"><span class="pf">▶</span>' +
        '<span class="nm">' + esc(f) + '</span><span class="mt">' +
        Object.keys(kats).filter(function (k) { return k !== "text"; })
          .map(function (k) { return '<span class="rg-kt ' + k + '">' + k + '</span>'; }).join("") +
        (!ruht && neuestes(lst) > GRENZE ? '' : '') +
        (news ? '<span style="color:var(--rg-ak2)">' + news + ' News</span>' : '') +
        '<span>' + esc(neuestes(lst) || "?") + '</span><span>' + lst.length +
        (lst.length === 1 ? ' Modell' : ' Modelle') + '</span></span></button>' +
        '<div class="rg-fam-i' + (auf ? " auf" : "") + '"><div class="rg-mods">' +
        lst.map(function (m) {
          var na = (R.artModell[m.s] || []).length;
          var jung = m.r && m.r > GRENZE;
          // 2098-12-31 ist der Platzhalter für "kein Ablaufdatum", kein Termin.
          var tot = m.ex && m.ex < heute && m.ex.slice(0, 4) < "2090";
          return '<div class="rg-md' + (offenMod === m.s ? " on" : "") + '" data-m="' +
            esc(m.s) + '" role="button" tabindex="0"><div class="rg-md-n">' + esc(m.n) +
            '</div><div class="rg-md-m">' +
            (m.k !== "text" ? '<span class="rg-kt ' + m.k + '">' + m.k + '</span>' : '') +
            (m.v ? '<span class="rg-tg vr">' + esc(m.v) + '</span>' : '') +
            (m.st ? '<span class="rg-tg st">' + esc(m.st) + '</span>' : '') +
            (jung ? '<span class="rg-tg n">neu</span>' : '') +
            (tot ? '<span class="rg-tg warn">abgekündigt</span>' : '') +
            '<span title="' + (m.rq === "slug" ? "exaktes Release-Datum aus dem Slug"
              : "Listungsdatum bei OpenRouter, kein echtes Release") + '">' +
            esc(m.r || "?") + (m.rq === "created" ? " ~" : "") + '</span>' +
            (m.c ? '<span>' + Math.round(m.c / 1000) + 'k</span>' : '') +
            (na ? '<span style="color:var(--rg-ak2)">' + na + ' News</span>' : '') +
            '</div></div>';
        }).join("") + '</div></div></div>';
    }).join("");

    var links = offenMod ? (R.artModell[offenMod] || []) : (R.artAnbieter[offenAnb] || []);
    var titel = offenMod
      ? (R.modelle.filter(function (m) { return m.s === offenMod; })[0] || {}).n
      : a.n;
    var sub = offenMod
      ? "Artikel, die dieses Modell ausdrücklich nennen"
      : "Alle Artikel zu diesem Anbieter";

    host.innerHTML = '<div class="rg-detail"><div style="display:flex;align-items:center;' +
      'gap:10px;flex-wrap:wrap;margin-bottom:11px">' +
      '<strong style="font-size:15px">' + esc(a.n) + '</strong>' +
      '<span style="color:var(--rg-tx3);font-size:11.5px">' + famNamen.length + ' von ' +
      alleFam.length + ' Familien · ' + mods.length + ' Modelle · neuestes ' +
      esc(a.r || "?") + '</span><button class="rg-x" id="rg-zu">schließen</button></div>' +
      (famNamen.length ? html : '<p class="rg-leer">Keine aktuellen Modelle dieser Art.</p>') +
      (alteFam.length ? '<button class="rg-mehr" id="rg-mehr-fam">' + (zeigeAlteFamilien
        ? "▲  " + alteFam.length + " ältere Familien ausblenden"
        : "▼  " + alteFam.length + " ältere Familien anzeigen (Release über ein Jahr her)") +
        '</button>' : "") +
      '<div style="margin-top:12px;border-top:1px solid var(--rg-line);padding-top:11px">' +
      '<p class="rg-h">' + esc(titel) + ' — ' + esc(sub) + '</p>' +
      (links.length ? links.map(artZeile).join("")
        : '<p class="rg-leer">Keine Nachrichten in den letzten Tagen.</p>') +
      '</div></div>';

    $("rg-zu").onclick = function () {
      offenAnb = null; offenMod = null; offeneFam = null; zeigeAlteFamilien = false;
      zeichneAnbieter();
    };
    var mf = $("rg-mehr-fam");
    if (mf) mf.onclick = function () { zeigeAlteFamilien = !zeigeAlteFamilien; zeichneDetail(); };
  }

  function artZeile(link) {
    var x = artikel(link);
    if (!x) return "";
    var f = F[link] || {};
    var url = sicherLink(x.link || link);
    var titel = url
      ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(x.title) + '</a>'
      : esc(x.title) + ' <span class="rg-tg warn">ohne Link</span>';
    return '<div class="rg-art"><div style="flex:1;min-width:0">' +
      '<p class="rg-art-t">' + titel + '</p>' +
      (x.summary ? '<p class="rg-art-z">' + esc(String(x.summary).slice(0, 150)) +
        (String(x.summary).length > 150 ? '…' : '') + '</p>' : '') +
      '<div class="rg-art-m">' +
      '<span>' + esc(x.source || "") + '</span>' +
      '<span>' + esc((x.first_seen || x.date || "").slice(0, 10)) + '</span>' +
      (x.label && x.label.indexOf("normal") === -1
        ? '<span class="rg-fc lb">' + esc(x.label) + '</span>' : '') +
      (f.re ? '<span class="rg-fc re">' + esc(f.re) + '</span>' : '') +
      (f.ev ? '<span class="rg-fc ev">' + esc(f.ev) + '</span>' : '') +
      (f.rg ? '<span class="rg-fc rg">' + esc(f.rg) + '</span>' : '') +
      (f.tf || []).map(function (t) {
        return '<span class="rg-fc tf">' + esc(t) + '</span>';
      }).join("") +
      '</div></div><div class="rg-art-s">' + esc(x.score == null ? "" : x.score) +
      '</div></div>';
  }

  /* ── Artikelansicht nach Facetten ──────────────────────────────────── */
  function fuelleFilter() {
    var z = { re: {}, tf: {}, rg: {}, ev: {} };
    Object.keys(F).forEach(function (k) {
      var x = F[k];
      if (x.re) z.re[x.re] = (z.re[x.re] || 0) + 1;
      if (x.rg) z.rg[x.rg] = (z.rg[x.rg] || 0) + 1;
      if (x.ev) z.ev[x.ev] = (z.ev[x.ev] || 0) + 1;
      (x.tf || []).forEach(function (t) { z.tf[t] = (z.tf[t] || 0) + 1; });
    });
    [["rg-f-re", z.re, "Ressort"], ["rg-f-tf", z.tf, "Thema"],
     ["rg-f-rg", z.rg, "Region"], ["rg-f-ev", z.ev, "Ereignis"]]
      .forEach(function (t) {
        var el = $(t[0]);
        if (!el) return;
        var keys = Object.keys(t[1]).sort(function (a, b) { return t[1][b] - t[1][a]; });
        el.innerHTML = '<option value="">' + t[2] + ': alle</option>' +
          keys.map(function (k) {
            return '<option value="' + esc(k) + '">' + esc(k) + ' (' + t[1][k] + ')</option>';
          }).join("");
      });
  }

  function zeichneListe() {
    if (!$("rg-liste")) return;
    baueArtMap();
    var alle = window.allNews || [];
    var q = ($("rg-aq").value || "").toLowerCase().trim();
    var re = $("rg-f-re").value, tf = $("rg-f-tf").value;
    var rg = $("rg-f-rg").value, ev = $("rg-f-ev").value;

    var treffer = alle.filter(function (x) {
      if (!x || !x.link) return false;
      var f = F[x.link] || {};
      if (re && f.re !== re) return false;
      if (rg && f.rg !== rg) return false;
      if (ev && f.ev !== ev) return false;
      if (tf && (f.tf || []).indexOf(tf) === -1) return false;
      if (q && ((x.title || "") + " " + (x.summary || "")).toLowerCase().indexOf(q) === -1)
        return false;
      return true;
    }).sort(function (a, b) {
      return ((b.first_seen || b.date || "")).localeCompare(a.first_seen || a.date || "");
    });

    var mitF = alle.filter(function (x) { return x && x.link && F[x.link]; }).length;
    $("rg-acnt").textContent = treffer.length + " von " + alle.length +
      " · " + mitF + " mit Facetten";
    // Nicht alles auf einmal: 1200 Zeilen am Stueck kosten auf dem Handy
    // spuerbar Zeit, und niemand liest so weit.
    $("rg-liste").innerHTML = treffer.length
      ? treffer.slice(0, 200).map(function (x) { return artZeile(x.link); }).join("") +
        (treffer.length > 200 ? '<p class="rg-leer">… und ' + (treffer.length - 200) +
          ' weitere. Filter enger setzen.</p>' : "")
      : '<p class="rg-leer">Nichts gefunden.</p>';
  }

  function zeigeAnsicht(modelle) {
    $("rg-view-mod").hidden = !modelle;
    $("rg-view-art").hidden = modelle;
    $("rg-tab-mod").classList.toggle("on", modelle);
    $("rg-tab-art").classList.toggle("on", !modelle);
    $("rg-tab-mod").setAttribute("aria-selected", modelle);
    $("rg-tab-art").setAttribute("aria-selected", !modelle);
  }

  /* ── Panel-Umschaltung, analog togglePodcastPanel() ────────────────── */
  window.toggleRegistryPanel = function () {
    offen = !offen;
    var body = $("registry-panel-body");
    var icon = $("registry-panel-icon");
    if (body) body.style.display = offen ? "" : "none";
    if (icon) icon.textContent = offen ? "expand_less" : "expand_more";
    // Erst laden, wenn jemand hinschaut: die Datei ist einige hundert KB groß
    // und die meisten Besucher öffnen das Panel nie.
    if (offen) laden();
  };

  /* ── Ereignisse ────────────────────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", function () {
    var grid = $("rg-grid");
    if (!grid) return;   // Panel nicht auf dieser Seite

    grid.addEventListener("click", function (e) {
      var k = e.target.closest("[data-a]");
      if (!k) return;
      var a = k.getAttribute("data-a");
      offenMod = null; offeneFam = null; zeigeAlteFamilien = false;
      offenAnb = offenAnb === a ? null : a;
      zeichneAnbieter();
    });
    grid.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var k = e.target.closest("[data-a]");
      if (!k) return;
      e.preventDefault(); k.click();
    });

    var det = $("rg-detail");
    det.addEventListener("click", function (e) {
      var f = e.target.closest("[data-f]");
      if (f) {
        var nf = f.getAttribute("data-f");
        offeneFam = offeneFam === nf ? "" : nf;
        zeichneDetail();
        return;
      }
      var k = e.target.closest("[data-m]");
      if (!k) return;
      var m = k.getAttribute("data-m");
      offenMod = offenMod === m ? null : m;
      zeichneDetail();
    });
    // Ohne das sind die Modellkacheln fokussierbar, aber per Tastatur nicht
    // auslösbar — der Kern der Ansicht wäre dann unbedienbar.
    det.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var k = e.target.closest("[data-m], [data-f]");
      if (!k) return;
      e.preventDefault(); k.click();
    });

    $("rg-q").addEventListener("input", entprellt(zeichneAnbieter, 160));
    $("rg-sort").addEventListener("input", zeichneAnbieter);
    $("rg-kat").addEventListener("input", function () {
      offeneFam = null; zeigeAlteFamilien = false; zeichneAnbieter();
    });
    laden();

    $("rg-mehr-anb").addEventListener("click", function () {
      zeigeAlteAnbieter = !zeigeAlteAnbieter;
      zeichneAnbieter();
    });

    $("rg-tab-mod").addEventListener("click", function () { zeigeAnsicht(true); });
    $("rg-tab-art").addEventListener("click", function () { zeigeAnsicht(false); });
    $("rg-aq").addEventListener("input", entprellt(zeichneListe, 160));
    ["rg-f-re", "rg-f-tf", "rg-f-rg", "rg-f-ev"].forEach(function (id) {
      $(id).addEventListener("input", zeichneListe);
    });
  });
})();
