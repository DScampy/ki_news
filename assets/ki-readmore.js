/* ============================================================
   ki-readmore.js — "Weiterlesen"-Block auf Artikel-Seiten
   Liest artikel/artikel-index.json (vom Generator gepflegt) und
   fügt vor dem Colophon bis zu 3 weitere Artikel ein.
   Einbindung in Artikel-Seiten: <script src="../assets/ki-readmore.js" defer></script>
   ============================================================ */
(function () {
  'use strict';
  var path = location.pathname.replace(/\\/g, '/');
  if (!/\/artikel\//.test(path)) return;
  var current = (path.split('/').pop() || '').replace(/\.html$/i, '');

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]; }); }

  function render(list) {
    var others = list.filter(function (a) { return a.slug !== current; }).slice(0, 3);
    if (!others.length) return;

    var style = document.createElement('style');
    style.textContent =
      '#ki-readmore{margin:56px 0 8px;}' +
      '#ki-readmore .rm-label{font-family:"Space Grotesk",sans-serif;font-size:10px;font-weight:800;letter-spacing:0.16em;text-transform:uppercase;color:var(--accent);margin-bottom:16px;display:flex;align-items:center;gap:10px;}' +
      '#ki-readmore .rm-label::after{content:"";flex:1;height:1px;background:rgba(var(--neon-rgb),0.18);}' +
      '#ki-readmore .rm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;}' +
      '.rm-card{display:flex;flex-direction:column;gap:8px;padding:18px 20px;border-radius:12px;border:1px solid rgba(var(--neon-rgb),0.30);background:rgba(10,14,22,0.6);text-decoration:none;transition:border-color .2s,box-shadow .2s;backdrop-filter:blur(8px);}' +
      '.rm-card:hover{border-color:rgba(var(--neon-rgb),0.65);box-shadow:0 0 18px rgba(var(--neon-rgb),0.25);}' +
      'html.light .rm-card{background:rgba(255,255,255,0.9);}' +
      '.rm-tag{font-family:"Space Grotesk",sans-serif;font-size:9px;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;color:var(--accent);}' +
      '.rm-title{font-family:"Space Grotesk",sans-serif;font-size:15px;font-weight:700;color:#dfe3ea;line-height:1.35;}' +
      'html.light .rm-title{color:#0f172a;}' +
      '.rm-meta{font-family:monospace;font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.04em;margin-top:auto;}' +
      'html.light .rm-meta{color:#64748b;}';
    document.head.appendChild(style);

    var sec = document.createElement('section');
    sec.id = 'ki-readmore';
    sec.innerHTML = '<div class="rm-label">Weiterlesen</div><div class="rm-grid">' +
      others.map(function (a) {
        var d = '';
        try { var dt = new Date(a.datum + 'T00:00:00'); d = dt.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }); } catch (e) {}
        return '<a class="rm-card" href="' + esc(a.slug) + '.html">' +
          '<span class="rm-tag">' + esc((a.tags && a.tags[0]) || 'Analyse') + '</span>' +
          '<span class="rm-title">' + esc(a.titel) + '</span>' +
          '<span class="rm-meta">' + d + (a.lesezeit ? ' · ≈ ' + a.lesezeit + ' Min.' : '') + '</span>' +
        '</a>';
      }).join('') + '</div>';

    var anchor = document.querySelector('.art-colophon') || document.querySelector('.back-btn');
    if (anchor) anchor.parentNode.insertBefore(sec, anchor);
    else { var ab = document.getElementById('article-body'); if (ab) ab.appendChild(sec); }
  }

  fetch('artikel-index.json?t=' + Date.now())
    .then(function (r) { return r.json(); })
    .then(function (list) {
      list.sort(function (a, b) { return String(b.datum).localeCompare(String(a.datum)); });
      render(list);
    })
    .catch(function () {});
})();
