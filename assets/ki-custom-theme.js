/* ══════════════════════════════════════════════════════════════════════════
   ki-custom-theme.js — "Eigenes Theme": Besucher definieren eigene Farben.
   Tokens: BG · Surface · Accent · Neon · Text  →  als CSS-Variablen.
   Speicher: localStorage 'ki_custom' (JSON) + 'ki_genesis_theme'==='custom'.
   Wird auf JEDER Seite NACH dem Inline-Theme-Script eingebunden.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  var PROPS = ['--bg', '--surface', '--card', '--field', '--hairline', '--sidebar-bg', '--nav-bg',
               '--nav-border', '--border', '--accent', '--accent-hover', '--neon-rgb', '--text', '--muted'];

  function hexToRgb(h) {
    h = String(h || '').trim().replace('#', '');
    if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(h, 16);
    if (isNaN(n)) return '0,212,255';
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(',');
  }

  function applyVars(c) {
    if (!c) return;
    var s = document.documentElement.style;
    var neon = c.neon ? hexToRgb(c.neon) : null;
    var textRgb = c.text ? hexToRgb(c.text) : null;
    if (c.bg)      { s.setProperty('--bg', c.bg); s.setProperty('--nav-bg', c.bg); }
    if (c.surface) { s.setProperty('--surface', c.surface); s.setProperty('--card', c.surface); s.setProperty('--field', c.surface); s.setProperty('--sidebar-bg', c.surface); }
    if (c.accent)  { s.setProperty('--accent', c.accent); s.setProperty('--accent-hover', c.accent); }
    if (neon)      { s.setProperty('--neon-rgb', neon); s.setProperty('--border', 'rgba(' + neon + ',0.18)'); s.setProperty('--nav-border', 'rgba(' + neon + ',0.12)'); s.setProperty('--hairline', 'rgba(' + neon + ',0.22)'); }
    if (c.text)    { s.setProperty('--text', c.text); if (textRgb) s.setProperty('--muted', 'rgba(' + textRgb + ',0.5)'); }
  }

  function clearVars() {
    var s = document.documentElement.style;
    PROPS.forEach(function (p) { s.removeProperty(p); });
  }

  function getCustom() {
    try { return JSON.parse(localStorage.getItem('ki_custom') || 'null'); } catch (e) { return null; }
  }

  // Beim Laden: wenn "custom" aktiv ist, anwenden
  function applyIfActive() {
    try {
      if ((localStorage.getItem('ki_genesis_theme') || '') === 'custom') {
        var c = getCustom();
        if (c) {
          document.documentElement.setAttribute('data-theme', 'custom');
          document.documentElement.classList.remove('light', 'dark');
          clearVars(); applyVars(c);
          return true;
        }
      }
    } catch (e) {}
    return false;
  }

  // Öffentliche API
  window.kiHexToRgb = hexToRgb;
  window.kiGetCustom = getCustom;
  window.kiApplyCustomVars = applyVars;
  window.kiClearCustomVars = clearVars;

  window.kiSetCustom = function (c) {
    try {
      localStorage.setItem('ki_custom', JSON.stringify(c));
      localStorage.setItem('ki_genesis_theme', 'custom');
    } catch (e) {}
    document.documentElement.setAttribute('data-theme', 'custom');
    document.documentElement.classList.remove('light', 'dark');
    clearVars(); applyVars(c);
    document.querySelectorAll('.gdot').forEach(function (d) {
      d.classList.toggle('active', d.getAttribute('data-t') === 'custom');
    });
  };

  // setGenesisTheme umschließen: beim Wechsel auf ein Preset Inline-Variablen
  // entfernen; bei "custom" eigene Anwendung statt Preset-Logik.
  if (typeof window.setGenesisTheme === 'function') {
    var orig = window.setGenesisTheme;
    window.setGenesisTheme = function (name) {
      if (name === 'custom') {
        var c = getCustom();
        if (c) { window.kiSetCustom(c); return; }
        name = 'genesis'; // kein gespeichertes Custom-Theme → Fallback
      }
      clearVars();
      orig(name);
    };
  }

  // Custom-Dot + Stil in die Nav injizieren (falls noch nicht vorhanden),
  // damit das eigene Theme von jeder Seite aus wählbar ist.
  function ensureUI() {
    if (!document.getElementById('ki-custom-dot-style')) {
      var st = document.createElement('style');
      st.id = 'ki-custom-dot-style';
      st.textContent = '.gdot[data-t="custom"]{background:conic-gradient(from 0deg,#00d4ff,#34d399,#fb923c,#a78bfa,#00d4ff);}'
        + '[data-theme="custom"] #sidebar{background:var(--sidebar-bg)!important;}'
        + '[data-theme="custom"] #main-content{background:var(--bg)!important;}'
        + '[data-theme="custom"] nav.fixed,[data-theme="custom"] nav.ki-nav{background:var(--nav-bg)!important;}'
        + '[data-theme="custom"] .card-hover{background:var(--card)!important;}'
        + '[data-theme="custom"] .card-hover h4{color:var(--text)!important;}'
        + '[data-theme="custom"] .card-hover p{color:var(--muted)!important;}'
        + '[data-theme="custom"] .ki-card{background:var(--card)!important;}'
        + '[data-theme="custom"] #searchWrap,[data-theme="custom"] #stand-box{background:var(--surface)!important;}'
        + '[data-theme="custom"] .bg-\\[\\#0d1117\\],[data-theme="custom"] .bg-\\[\\#16181c\\],[data-theme="custom"] .bg-\\[\\#1d1f23\\]{background:var(--surface)!important;}'
        + '[data-theme="custom"] h1.text-white,[data-theme="custom"] h2.text-white,[data-theme="custom"] h3.text-white{color:var(--text)!important;}';
      document.head.appendChild(st);
    }
    var dots = document.getElementById('genesis-dots');
    if (dots && !dots.querySelector('[data-t="custom"]')) {
      var b = document.createElement('button');
      b.className = 'gdot';
      b.setAttribute('data-t', 'custom');
      b.title = 'Eigenes Theme';
      b.onclick = function () { window.setGenesisTheme('custom'); };
      dots.appendChild(b);
    }
    if ((function(){try{return localStorage.getItem('ki_genesis_theme')==='custom';}catch(e){return false;}})()) {
      document.querySelectorAll('.gdot').forEach(function (d) {
        d.classList.toggle('active', d.getAttribute('data-t') === 'custom');
      });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureUI);
  else ensureUI();

  applyIfActive();
})();
