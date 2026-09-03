/* ============================================================
   ki-layout.js — Single Source of Truth für das Site-Chrome
   Rendert auf JEDER Seite identisch: Topbar, Sidebar, Theme-
   Toggle, Genesis-Theme-System, Mobile-Drawer.
   Einbindung (eine Zeile, direkt nach <body>):
     <script src="assets/ki-layout.js"></script>        (Root)
     <script src="../assets/ki-layout.js"></script>     (artikel/)
   Aktive Seite wird automatisch aus der URL erkannt.
   Seiten-spezifischer Sidebar-Inhalt: vorher window.KI_SIDEBAR_EXTRA setzen.
   Referenz-Design: index.html (Stand 10.06.2026)
   ============================================================ */
(function () {
  'use strict';

  /* ── Pfad-Präfix + aktive Seite automatisch erkennen ───────── */
  var path = location.pathname.replace(/\\/g, '/');
  var inSub = /\/artikel\//.test(path);
  var ROOT = inSub ? '../' : '';
  var file = (path.split('/').pop() || 'index.html').toLowerCase();
  var ACTIVE = 'aktuell';
  if (inSub || file === 'artikel.html') ACTIVE = 'artikel';
  else if (file === 'archiv.html') ACTIVE = 'archiv';
  else if (file === 'stats.html') ACTIVE = 'statistik';
  else if (file === 'profil.html') ACTIVE = 'profil';
  else if (file === '' || file === 'index.html') ACTIVE = 'aktuell';
  else ACTIVE = 'none';

  /* ── Navigation: EINE Definition für Topbar + Sidebar ──────── */
  var NAV = [
    { key: 'aktuell',   label: 'Aktuell',         href: 'index.html',  icon: 'bolt' },
    { key: 'archiv',    label: 'Archiv',           href: 'Archiv.html', icon: 'archive' },
    { key: 'artikel',   label: 'Artikel',          href: 'artikel.html', icon: 'menu_book' },
    { key: 'podcast',   label: 'Podcast',          href: 'https://soundcloud.com/dscampy/sets/podcast-wissen', ext: true, icon: 'mic' },
    { key: 'youtube',   label: 'YouTube',          href: 'https://youtube.com/@ScampyKI', ext: true, icon: 'play_circle', sidebarOnly: true },
    { key: 'statistik', label: 'Statistik',        href: 'stats.html',  icon: 'bar_chart' },
    { key: 'profil',    label: 'Profil & Design',  href: 'profil.html', icon: 'person', topLabel: 'Profil' }
  ];

  var SOCIAL_X_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.835L1.254 2.25H8.08l4.253 5.622 5.911-5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>';
  var SPY_SVG = '<svg class="spy-eye" viewBox="0 0 24 24" fill="none" style="width:16px;height:16px;"><g class="eye-shape"><path d="M1.5 12 C6 6.5 18 6.5 22.5 12 C18 17.5 6 17.5 1.5 12 Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle class="eye-pupil" cx="12" cy="12" r="3.2" fill="currentColor"/></g></svg>';

  /* ── Theme-System (kanonisch, aus index.html übernommen) ───── */
  var GEN = ['genesis', 'karst', 'aurora', 'meridian', 'blanc'];
  var memGen = null, memContrast = null;
  function prefersLight() { return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches); }
  function getContrast() { var v = null; try { v = localStorage.getItem('ki_theme'); } catch (e) {} return v || memContrast || 'auto'; }
  function rawGenesis() { var v = null; try { v = localStorage.getItem('ki_genesis_theme'); } catch (e) {} return v || memGen || 'genesis'; }
  function getGenesis() { var g = rawGenesis(); return GEN.indexOf(g) === -1 ? 'genesis' : g; }
  function resolveLight() {
    if (getGenesis() === 'blanc') return true;
    var c = getContrast();
    return c === 'light' ? true : (c === 'dark' ? false : prefersLight());
  }
  function applyAll() {
    var root = document.documentElement, raw = rawGenesis();
    if (raw === 'custom') {
      root.setAttribute('data-theme', 'custom');
      root.classList.remove('light', 'dark');
    } else {
      var g = getGenesis(), light = resolveLight();
      root.setAttribute('data-theme', g);
      root.classList.toggle('light', light);
      root.classList.toggle('dark', !light);
    }
    var active = (raw === 'custom') ? 'custom' : getGenesis();
    var dots = document.querySelectorAll('.gdot');
    for (var i = 0; i < dots.length; i++) dots[i].classList.toggle('active', dots[i].getAttribute('data-t') === active);
    if (typeof window.__kiThemeHook === 'function') { try { window.__kiThemeHook(root.classList.contains('light'), active); } catch (e) {} }
  }
  window.setGenesisTheme = function (name) {
    if (GEN.indexOf(name) === -1) name = 'genesis';
    memGen = name;
    try { localStorage.setItem('ki_genesis_theme', name); } catch (e) {}
    applyAll();
  };
  window.cycleTheme = function () {
    var light = document.documentElement.classList.contains('light');
    var next = light ? 'dark' : 'light';
    if (next === 'dark' && getGenesis() === 'blanc' && rawGenesis() !== 'custom') { memGen = 'genesis'; try { localStorage.setItem('ki_genesis_theme', 'genesis'); } catch (e) {} }
    memContrast = next;
    try { localStorage.setItem('ki_theme', next); } catch (e) {}
    applyAll();
  };
  window.setTheme = function (t) { try { localStorage.setItem('ki_theme', t); } catch (e) {} applyAll(); };
  window.__kiApplyTheme = applyAll;
  applyAll(); /* sofort — verhindert Theme-Flackern */
  if (window.matchMedia) { try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { if (getContrast() === 'auto') applyAll(); }); } catch (e) {} }

  /* ── Chrome-CSS (Tailwind-unabhängig — funktioniert überall) ── */
  var CSS = [
    '/* 5-Theme-System */',
    '[data-theme="genesis"]{--neon-rgb:0,212,255;--accent:#00d4ff;--accent-hover:#1a8cd8;--bg:#000000;--surface:rgba(0,212,255,0.06);--text:#e8f8ff;--muted:rgba(180,220,240,0.55);--sidebar-bg:#0c1220;--nav-bg:rgba(0,0,0,0.72);--card:#0d1117;--field:#1d1f23;--hairline:#2f3336;}',
    '[data-theme="karst"]{--neon-rgb:52,211,153;--accent:#34d399;--accent-hover:#2bb583;--bg:#060e08;--surface:rgba(52,211,153,0.06);--text:#e0f5ec;--muted:rgba(160,220,190,0.55);--sidebar-bg:#06100a;--nav-bg:rgba(4,12,6,0.80);--card:#08140d;--field:#0f2016;--hairline:#1d3328;}',
    '[data-theme="aurora"]{--neon-rgb:167,139,250;--accent:#a78bfa;--accent-hover:#9171e8;--bg:#04020f;--surface:rgba(167,139,250,0.06);--text:#ede9fe;--muted:rgba(180,160,240,0.55);--sidebar-bg:#0a0818;--nav-bg:rgba(4,2,15,0.80);--card:#0a0816;--field:#16122a;--hairline:#2a2442;}',
    '[data-theme="meridian"]{--neon-rgb:251,146,60;--accent:#fb923c;--accent-hover:#e07f2a;--bg:#090300;--surface:rgba(251,146,60,0.06);--text:#fff0e6;--muted:rgba(240,190,140,0.55);--sidebar-bg:#100600;--nav-bg:rgba(9,3,0,0.80);--card:#100600;--field:#1e1206;--hairline:#33220e;}',
    '[data-theme="blanc"]{--neon-rgb:14,165,233;--accent:#0ea5e9;--accent-hover:#0c8fcb;--bg:#f0f6ff;--surface:rgba(14,165,233,0.06);--text:#0f172a;--muted:rgba(30,80,140,0.55);--sidebar-bg:#e8edf4;--nav-bg:rgba(255,255,255,0.88);--card:#ffffff;--field:#eef3fa;--hairline:#e2e8f0;}',
    'html.light{--bg:#f0f4f8;--surface:rgba(var(--neon-rgb),0.06);--sidebar-bg:#e8edf4;--nav-bg:rgba(255,255,255,0.88);--card:#ffffff;--field:#eef3fa;--hairline:#e2e8f0;--text:#0f172a;--muted:rgba(30,80,140,0.55);}',
    '*,*::before,*::after{box-sizing:border-box;}',
    '#kl-nav{position:fixed;top:0;left:0;width:100%;z-index:50;display:flex;justify-content:space-between;align-items:center;padding:0 16px;height:56px;background:var(--nav-bg,rgba(0,0,0,0.72));backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--hairline,#2f3336);}',
    'html.light #kl-nav{border-color:#e2e8f0;}',
    '#kl-nav .kl-left{display:flex;align-items:center;gap:32px;min-width:0;}',
    '#kl-brand{display:flex;align-items:center;gap:10px;text-decoration:none;}',
    '#kl-brand img{width:30px;height:30px;border-radius:6px;flex-shrink:0;filter:drop-shadow(0 0 8px rgba(var(--neon-rgb),0.45));}',
    '#kl-brand .kl-brand-col{display:flex;flex-direction:column;justify-content:center;line-height:1.02;}',
    '#kl-brand .kl-brand-title{font-family:\'Space Grotesk\',sans-serif;font-size:20px;font-weight:900;letter-spacing:-0.05em;text-transform:uppercase;color:var(--accent);}',
    '#brand-menu-hint{display:none;font-size:8px;font-family:monospace;letter-spacing:0.14em;text-transform:uppercase;color:var(--muted,rgba(148,163,184,0.75));margin-top:2px;}',
    '@media(max-width:767px){#brand-menu-hint{display:inline-flex;align-items:center;gap:4px;}#kl-brand{cursor:pointer;}}',
    '.kl-de-badge{font-size:10px;font-family:monospace;letter-spacing:0.1em;text-transform:uppercase;color:var(--muted,#8b98a5);border:1px solid var(--hairline,#2f3336);padding:2px 6px;display:none;}',
    '@media(min-width:640px){.kl-de-badge{display:inline;}}',
    '#kl-toplinks{display:none;align-items:center;gap:24px;}',
    '@media(min-width:768px){#kl-toplinks{display:flex;}}',
    '#kl-toplinks a{font-family:\'Space Grotesk\',sans-serif;font-size:14px;font-weight:500;color:var(--muted,#8b98a5);text-decoration:none;transition:color .15s;}',
    '#kl-toplinks a:hover{color:var(--text,#fff);}',
    '#kl-toplinks a.kl-active{color:var(--accent);border-bottom:2px solid var(--accent);padding-bottom:4px;font-weight:600;}',
    '#kl-nav .kl-right{display:flex;align-items:center;gap:16px;flex-shrink:0;}',
    '#kl-contrast{background:none;border:none;cursor:pointer;color:rgba(255,255,255,0.45);display:flex;align-items:center;padding:0;}',
    'html.light #kl-contrast{color:rgba(15,23,42,0.5);}',
    '#kl-contrast:hover{color:var(--accent);}',
    '#genesis-dots{display:flex;align-items:center;gap:5px;}',
    '.gdot{width:13px;height:13px;border-radius:50%;cursor:pointer;border:2px solid transparent;transition:transform .15s,border-color .15s;flex-shrink:0;padding:0;}',
    '.gdot:hover{transform:scale(1.25);}',
    '.gdot.active{border-color:rgba(255,255,255,0.85);transform:scale(1.15);}',
    'html.light .gdot.active{border-color:rgba(0,0,0,0.6);}',
    '.gdot[data-t="genesis"]{background:#00d4ff;}',
    '.gdot[data-t="karst"]{background:#34d399;}',
    '.gdot[data-t="aurora"]{background:#a78bfa;}',
    '.gdot[data-t="meridian"]{background:#fb923c;}',
    '.gdot[data-t="blanc"]{background:#e2e8f0;border-color:rgba(0,0,0,0.2);}',
    '#sidebar{position:fixed;left:0;top:56px;height:calc(100vh - 56px);z-index:40;display:none;flex-direction:column;overflow:hidden;background:var(--sidebar-bg,#0c1220);border-right:1px solid rgba(var(--neon-rgb),0.18);transition:width .25s ease,opacity .2s ease;width:240px;}',
    '@media(min-width:1024px){#sidebar{display:flex;}}',
    '#sidebar.collapsed{width:0;opacity:0;overflow:hidden;pointer-events:none;}',
    'html.light #sidebar{background:#e8edf4;border-color:#d1d9e6;}',
    '.kl-side-head{padding:16px 20px 12px;display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(var(--neon-rgb),0.12);flex-shrink:0;}',
    '.kl-side-head img{width:36px;height:36px;object-fit:contain;filter:drop-shadow(0 0 6px rgba(var(--neon-rgb),0.5));}',
    '.kl-side-name{font-family:\'Space Grotesk\',sans-serif;font-size:13px;font-weight:800;color:var(--accent);letter-spacing:-0.02em;}',
    '.kl-side-sub{font-size:9px;font-family:monospace;color:rgba(255,255,255,0.35);letter-spacing:0.08em;}',
    'html.light .kl-side-sub{color:rgba(15,23,42,0.4);}',
    '.kl-side-nav{display:flex;flex-direction:column;gap:2px;padding:12px 8px 0;flex-shrink:0;}',
    '.sidebar-nav-link{display:flex;align-items:center;gap:12px;padding:10px 16px;font-size:11px;font-family:\'Space Grotesk\',sans-serif;font-weight:700;letter-spacing:.12em;text-transform:uppercase;transition:all .15s;border-left:2px solid transparent;color:rgba(180,220,240,0.55);text-decoration:none;}',
    '.sidebar-nav-link:hover{background:rgba(29,37,53,0.85);color:#fff;border-left-color:var(--accent);}',
    'html.light .sidebar-nav-link{color:rgba(30,80,140,0.7);}',
    'html.light .sidebar-nav-link:hover{background:#deeaf7;color:#0f172a;border-left-color:var(--accent,#0ea5e9);}',
    '.sidebar-nav-link.kl-active{color:var(--accent);border-left-color:var(--accent);background:rgba(var(--neon-rgb),0.08);}',
    'html.light .sidebar-nav-link.kl-active{background:#eff6ff;}',
    '.sidebar-nav-link .material-symbols-outlined{font-size:14px;}',
    '.kl-side-extra{padding:0 16px;display:flex;flex-direction:column;gap:8px;overflow-y:auto;flex:1;margin-top:8px;min-height:0;}',
    '.kl-side-spacer{flex:1 1 auto;}',
    '.kl-search{display:flex;align-items:center;gap:8px;margin:10px 16px 0;padding:8px 12px;background:var(--field,#111827);border:1px solid rgba(var(--neon-rgb),0.18);border-radius:8px;flex-shrink:0;}',
    '.kl-search .material-symbols-outlined{font-size:16px;color:rgba(255,255,255,0.4);flex-shrink:0;}',
    'html.light .kl-search .material-symbols-outlined{color:rgba(15,23,42,0.4);}',
    '.kl-search input{background:transparent;border:none;outline:none;font-family:monospace;font-size:11px;color:rgba(255,255,255,0.85);width:100%;}',
    '.kl-search input::placeholder{color:rgba(255,255,255,0.3);}',
    'html.light .kl-search input{color:#0f172a;}',
    'html.light .kl-search input::placeholder{color:rgba(15,23,42,0.35);}',
    '.kl-search button{background:none;border:none;padding:0;cursor:pointer;color:rgba(255,255,255,0.35);display:flex;flex-shrink:0;}',
    'html.light .kl-search button{color:rgba(15,23,42,0.35);}',
    '.kl-search button:hover{color:var(--accent);}',
    '.kl-stand{margin:10px 16px 0;padding:10px 12px;border:1px solid rgba(var(--neon-rgb),0.12);border-radius:6px;background:var(--card,#0d1520);flex-shrink:0;}',
    '.kl-stand-label{font-size:9px;font-family:monospace;color:rgba(var(--neon-rgb),0.4);letter-spacing:.08em;margin:0 0 2px;}',
    '.kl-stand-value{font-size:11px;font-family:monospace;color:rgba(255,255,255,0.55);margin:0;}',
    'html.light .kl-stand-value{color:#475569;}',
    '.kl-ov-analyse{margin:14px 0;padding:12px 14px;border-left:2px solid var(--accent);background:var(--field,#111827);border-radius:0 6px 6px 0;}',
    '.kl-ov-analyse-label{font-size:10px;font-family:monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin:0 0 6px;}',
    '.kl-ov-analyse p{font-size:13px;line-height:1.6;color:rgba(255,255,255,0.75);margin:0 0 8px;}',
    '.kl-ov-analyse ol{margin:0;padding-left:18px;font-size:13px;line-height:1.6;color:rgba(255,255,255,0.75);}',
    '.kl-ov-analyse ol li{margin-bottom:4px;}',
    'html.light .kl-ov-analyse{background:#f1f5f9;}',
    'html.light .kl-ov-analyse p,html.light .kl-ov-analyse ol{color:#334155;}',
    '.kl-side-divider{margin:8px 16px 0;height:1px;background:rgba(var(--neon-rgb),0.10);flex-shrink:0;}',
    '.kl-side-label{padding:8px 16px 4px;font-size:9px;font-family:monospace;color:rgba(var(--neon-rgb),0.5);letter-spacing:0.12em;text-transform:uppercase;flex-shrink:0;}',
    '.kl-side-foot{padding:12px 20px;border-top:1px solid rgba(var(--neon-rgb),0.10);flex-shrink:0;}',
    '.kl-side-foot p{font-size:9px;font-family:monospace;color:rgba(255,255,255,0.22);line-height:1.5;margin:0;}',
    'html.light .kl-side-foot p{color:rgba(15,23,42,0.35);}',
    '#sidebar-toggle{position:fixed;left:0;top:50%;transform:translateY(-50%);z-index:45;background:var(--accent);border:none;cursor:pointer;width:20px;height:60px;display:none;align-items:center;justify-content:center;color:#000;transition:left .25s ease,box-shadow .2s;border-radius:0 6px 6px 0;box-shadow:0 0 12px rgba(var(--neon-rgb),0.5);}',
    '#sidebar-toggle:hover{box-shadow:0 0 20px rgba(var(--neon-rgb),0.8);filter:brightness(1.18);}',
    '@media(min-width:1024px){#sidebar-toggle{display:flex;}}',
    '#sidebar-toggle .material-symbols-outlined{font-size:14px;font-weight:700;}',
    '#sidebar-backdrop{position:fixed;inset:0;z-index:48;background:rgba(0,0,0,0.6);backdrop-filter:blur(2px);opacity:0;visibility:hidden;transition:opacity .28s ease,visibility .28s ease;}',
    '#sidebar-backdrop.open{opacity:1;visibility:visible;}',
    '@media(min-width:1024px){#sidebar-backdrop{display:none !important;}}',
    '@media(max-width:1023px){',
    '  #sidebar{display:flex !important;width:284px !important;max-width:84vw;transform:translateX(-100%);transition:transform .28s ease;opacity:1 !important;z-index:60;pointer-events:none;box-shadow:8px 0 40px rgba(0,0,0,0.55);}',
    '  #sidebar.collapsed{width:284px !important;max-width:84vw;opacity:1 !important;transform:translateX(-100%);pointer-events:none;}',
    '  #sidebar.drawer-open{transform:translateX(0);pointer-events:auto;}',
    '}',
    '#main-content{transition:margin-left .25s ease;}',
    '@media(max-width:1023px){#main-content{margin-left:0 !important;}}',
    '.spy-eye{display:block;overflow:visible;}',
    '.spy-eye .eye-shape{transform-box:fill-box;transform-origin:center;animation:spyBlink 9s ease-in-out infinite;}',
    '.spy-eye .eye-pupil{transform-box:fill-box;transform-origin:center;animation:spyGlance 11s ease-in-out infinite;}',
    '@keyframes spyBlink{0%,89%,100%{transform:scaleY(1);}93%{transform:scaleY(0.08);}96%{transform:scaleY(1);}}',
    '@keyframes spyGlance{0%,16%{transform:translate(0,0);}24%,38%{transform:translate(2.4px,0.4px);}48%,62%{transform:translate(-2.4px,0.4px);}72%,100%{transform:translate(0,0);}}',
    '@keyframes spyWink{0%,100%{transform:scaleY(1);}45%{transform:scaleY(0.08);}}',
    '@media (prefers-reduced-motion: reduce){.spy-eye .eye-shape,.spy-eye .eye-pupil{animation:none;}}',
    '.spy-row .spy-eye{color:var(--accent);filter:drop-shadow(0 0 5px rgba(var(--neon-rgb),0.65));flex-shrink:0;}',
    '.spy-row:hover .spy-eye .eye-shape{animation:spyWink .55s ease;}',
    '.spy-row:hover .spy-eye{filter:drop-shadow(0 0 10px rgba(var(--neon-rgb),0.95));}',
    /* ── Artikel-Overlay (30.08.) ─────────────────────────────── */
    '#kl-ov{position:fixed;inset:0;z-index:80;display:none;align-items:center;justify-content:center;padding:24px 16px;overflow-y:auto;background:rgba(0,0,0,0.65);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);}',
    '.kl-ov-card{position:relative;width:100%;max-width:660px;max-height:88vh;overflow-y:auto;background:var(--card,#0d1117);border:1px solid var(--hairline,#2f3336);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,0.5);}',
    'html.light .kl-ov-card{box-shadow:0 20px 60px rgba(15,23,42,0.25);}',
    '.kl-ov-close{position:absolute;top:12px;right:12px;z-index:2;background:rgba(0,0,0,0.45);border:none;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;color:#fff;cursor:pointer;padding:0;}',
    '.kl-ov-close:hover{background:var(--accent);color:#000;}',
    'html.light .kl-ov-close{background:rgba(255,255,255,0.8);color:#0f172a;}',
    '.kl-ov-img-wrap{position:relative;padding-top:42%;overflow:hidden;border-radius:14px 14px 0 0;background:var(--field,#111827);}',
    '.kl-ov-img-wrap img,.kl-ov-img-wrap video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}',
    '.kl-ov-body{padding:22px 24px 24px;}',
    '.kl-ov-meta{font-size:11px;font-family:monospace;letter-spacing:0.05em;text-transform:uppercase;color:var(--muted,#8b98a5);margin-bottom:8px;}',
    '.kl-ov-title{font-family:\'Space Grotesk\',sans-serif;font-size:22px;font-weight:800;line-height:1.28;color:var(--text,#e8f8ff);margin:0 0 12px;}',
    '.kl-ov-summary{font-family:\'Work Sans\',sans-serif;font-size:14.5px;line-height:1.6;color:var(--text,#e8f8ff);opacity:0.88;margin:0 0 16px;white-space:pre-line;}',
    '.kl-ov-related{margin:0 0 18px;padding:12px 14px;background:var(--surface,rgba(255,255,255,0.04));border:1px solid var(--hairline,#2f3336);border-radius:10px;}',
    '.kl-ov-related-label{font-size:9px;font-family:monospace;letter-spacing:0.12em;text-transform:uppercase;color:rgba(var(--neon-rgb),0.75);margin-bottom:8px;}',
    '.kl-ov-related-chips{display:flex;flex-wrap:wrap;gap:6px;}',
    '.kl-chip{font-size:11px;font-family:monospace;padding:3px 9px;border-radius:20px;border:1px solid var(--hairline,#2f3336);color:var(--muted,#8b98a5);white-space:nowrap;}',
    '.kl-chip-hit{color:var(--accent);border-color:var(--accent);}',
    '.kl-ov-link{display:inline-flex;align-items:center;gap:6px;font-family:\'Space Grotesk\',sans-serif;font-size:14px;font-weight:700;color:#000;background:var(--accent);padding:10px 18px;border-radius:8px;text-decoration:none;}',
    '.kl-ov-link:hover{filter:brightness(1.1);}',
    '.kl-ov-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '.kl-ov-share{display:inline-flex;align-items:center;gap:6px;font-family:\'Space Grotesk\',sans-serif;font-size:14px;font-weight:700;color:var(--text,#e8f8ff);background:transparent;border:1px solid var(--hairline,#2f3336);padding:9px 16px;border-radius:8px;cursor:pointer;transition:border-color .15s,color .15s;}',
    '.kl-ov-share:hover{border-color:var(--accent);color:var(--accent);}',
    '.kl-ov-share.done{border-color:var(--accent);color:var(--accent);}'
  ].join('\n');

  /* ── Chrome-HTML ────────────────────────────────────────────── */
  function navLinksHtml() {
    return NAV.filter(function (n) { return !n.sidebarOnly; }).map(function (n) {
      var href = n.ext ? n.href : ROOT + n.href;
      var cls = n.key === ACTIVE ? ' class="kl-active"' : '';
      var tgt = n.ext ? ' target="_blank" rel="noopener"' : '';
      return '<a' + cls + ' href="' + href + '"' + tgt + '>' + (n.topLabel || n.label) + '</a>';
    }).join('');
  }
  function sideLinksHtml() {
    return NAV.map(function (n) {
      var href = n.ext ? n.href : ROOT + n.href;
      var cls = 'sidebar-nav-link' + (n.key === ACTIVE ? ' kl-active' : '');
      var tgt = n.ext ? ' target="_blank" rel="noopener"' : '';
      return '<a class="' + cls + '" href="' + href + '"' + tgt + '><span class="material-symbols-outlined">' + n.icon + '</span>' + n.label + '</a>';
    }).join('');
  }

  function chromeHtml() {
    return '<nav id="kl-nav" class="ki-nav">' +
      '<div class="kl-left">' +
        '<a href="' + (ROOT || './') + '" id="brand-link" onclick="return brandClick(event);">' +
          '<span id="kl-brand"><img src="' + ROOT + 's-logo.png" alt=""/>' +
          '<span class="kl-brand-col"><span class="kl-brand-title">KI NEWS</span>' +
          '<span id="brand-menu-hint">&#9776; Men&uuml;</span></span>' +
          '<span class="kl-de-badge">DE</span></span>' +
        '</a>' +
        '<div id="kl-toplinks">' + navLinksHtml() + '</div>' +
      '</div>' +
      '<div class="kl-right">' +
        '<button id="kl-contrast" onclick="cycleTheme()" title="Dark/Light Toggle"><span class="material-symbols-outlined" style="font-size:18px;">contrast</span></button>' +
        '<div id="genesis-dots" title="Design-Theme">' +
          GEN.map(function (t) { return '<button class="gdot" data-t="' + t + '" onclick="setGenesisTheme(\'' + t + '\')" title="' + t.charAt(0).toUpperCase() + t.slice(1) + '"></button>'; }).join('') +
        '</div>' +
      '</div>' +
    '</nav>' +
    '<button id="sidebar-toggle" onclick="toggleSidebar()" title="Sidebar ein-/ausklappen"><span class="material-symbols-outlined" id="toggle-icon">chevron_right</span></button>' +
    '<div id="sidebar-backdrop" onclick="closeDrawer()"></div>' +
    '<aside id="sidebar" class="collapsed">' +
      '<div class="kl-side-head"><img src="' + ROOT + 's-logo.png" alt="ScampyKI"/>' +
        '<div><div class="kl-side-name">ScampyKI</div><div class="kl-side-sub">KI-NEWS.LIVE</div></div></div>' +
      '<div class="kl-side-nav">' + sideLinksHtml() + '</div>' +
      '<div class="kl-search" id="kl-search-wrap">' +
        '<span class="material-symbols-outlined">search</span>' +
        '<input id="searchInput" type="text" placeholder="Suchen&hellip;" aria-label="Artikel durchsuchen" ' +
          'oninput="klSearchInput(this.value)" onkeydown="if(event.key===\'Enter\'){klSearchSubmit();}"/>' +
        '<button type="button" title="Suche leeren" onclick="klSearchClear()"><span class="material-symbols-outlined" style="font-size:15px;">close</span></button>' +
      '</div>' +
      '<div class="kl-stand" id="stand-box">' +
        '<p class="kl-stand-label">LETZTES UPDATE</p>' +
        '<p class="kl-stand-value" id="standLabel">&mdash;</p>' +
      '</div>' +
      (window.KI_SIDEBAR_EXTRA ? '<div class="kl-side-extra">' + window.KI_SIDEBAR_EXTRA + '</div>' : '<div class="kl-side-spacer"></div>') +
      '<div class="kl-side-divider"></div>' +
      '<div class="kl-side-label">Kontakt &amp; Social</div>' +
      '<a class="sidebar-nav-link" href="https://x.com/ScampyKI" target="_blank" rel="noopener" style="flex-shrink:0">' + SOCIAL_X_SVG + '@ScampyKI</a>' +
      '<a class="sidebar-nav-link" href="https://instagram.com/KIScampy" target="_blank" rel="noopener" style="flex-shrink:0"><span class="material-symbols-outlined">photo_camera</span>KIScampy</a>' +
      '<a class="sidebar-nav-link" href="https://linkedin.com/in/dscampy" target="_blank" rel="noopener" style="flex-shrink:0"><span class="material-symbols-outlined">work</span>dscampy</a>' +
      '<a class="sidebar-nav-link spy-row" href="' + ROOT + 'was-dein-browser-verraet.html" style="flex-shrink:0" title="Was wei&szlig; das Netz &uuml;ber dich?">' + SPY_SVG + 'Wer sieht mich?</a>' +
      '<div class="kl-side-foot"><p>KI-News t&auml;glich auf Deutsch.<br>Kuratiert &middot; Eingeordnet &middot; Erkl&auml;rt.</p></div>' +
    '</aside>';
  }

  /* ── Artikel-Overlay-HTML (einmalig injiziert) ─────────────── */
  function overlayHtml() {
    return '<div id="kl-ov" role="dialog" aria-modal="true" aria-labelledby="kl-ov-title" ' +
        'onclick="if(event.target===this)window.klCloseArticle();">' +
      '<div class="kl-ov-card">' +
        '<button type="button" class="kl-ov-close" onclick="window.klCloseArticle()" aria-label="Schlie&szlig;en">' +
          '<span class="material-symbols-outlined">close</span></button>' +
        '<div id="kl-ov-img-wrap" class="kl-ov-img-wrap" hidden><img id="kl-ov-img" alt="">' +
          /* Fallback-Video (01.09.), Daniels Wunsch: Artikel ohne eigenes og:image
             zeigen im Overlay statt eines leeren Slots einen Marken-Clip. Nur hier
             (Overlay), nicht im Karten-Grid -- sonst wuerden bei vielen bildlosen
             Karten gleichzeitig etliche Videos autoplayen. Quelle (src) wird NICHT
             hier fest verdrahtet, sondern erst in klPlayFallbackVideo() gesetzt --
             Daniel hat mehrere Clips zur Auswahl (siehe FALLBACK_VIDEOS unten),
             es soll bei jedem Oeffnen zufaellig genau einer laufen. */
          '<video id="kl-ov-video" muted loop playsinline preload="none" hidden></video></div>' +
        '<div class="kl-ov-body">' +
          '<div id="kl-ov-meta" class="kl-ov-meta"></div>' +
          '<h2 id="kl-ov-title" class="kl-ov-title"></h2>' +
          '<p id="kl-ov-summary" class="kl-ov-summary"></p>' +
          '<div id="kl-ov-related" class="kl-ov-related" hidden></div>' +
          '<div id="kl-ov-analyse" class="kl-ov-analyse" hidden></div>' +
          '<div class="kl-ov-actions">' +
            '<a id="kl-ov-link" class="kl-ov-link" href="#" target="_blank" rel="noopener noreferrer">Zum Original &#8599;</a>' +
            '<button type="button" id="kl-ov-share" class="kl-ov-share" onclick="window.klShareArticle()">' +
              '<span class="material-symbols-outlined" style="font-size:17px">ios_share</span>' +
              '<span id="kl-ov-share-label">Teilen</span>' +
            '</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  /* ── Sidebar-Suche (auf jeder Seite sichtbar) ──────────────────
     Auf Archiv.html selbst spiegelt Archiv.html's eigenes handleSearch()
     die Eingabe live in die Modell-Registry -> Artikel-Suche (siehe dort).
     Auf jeder anderen Seite existiert kein handleSearch() -- dort passiert
     beim Tippen nichts, erst Enter/Such-Klick navigiert zu Archiv.html
     mit ?such=<Begriff>, wo derselbe Mechanismus die Suche uebernimmt. */
  window.klSearchInput = function (v) {
    if (typeof window.handleSearch === 'function') window.handleSearch(v);
  };
  window.klSearchSubmit = function () {
    var input = document.getElementById('searchInput');
    var q = (input && input.value || '').trim();
    if (!q || typeof window.handleSearch === 'function') return; // auf Archiv.html schon live
    location.href = ROOT + 'Archiv.html?such=' + encodeURIComponent(q);
  };
  window.klSearchClear = function () {
    var input = document.getElementById('searchInput');
    if (input) input.value = '';
    if (typeof window.clearSearch === 'function') window.clearSearch();
  };

  /* ── Sidebar-Verhalten (Desktop-Collapse + Mobile-Drawer) ──── */
  var sidebarOpen = (function () { try { return localStorage.getItem('ki_sidebar_open') === '1'; } catch (e) { return false; } })();
  window.toggleSidebar = function () {
    sidebarOpen = !sidebarOpen;
    var sidebar = document.getElementById('sidebar');
    var main = document.getElementById('main-content');
    var toggle = document.getElementById('sidebar-toggle');
    var icon = document.getElementById('toggle-icon');
    if (sidebarOpen) {
      if (sidebar) sidebar.classList.remove('collapsed');
      if (main) main.style.marginLeft = '240px';
      if (toggle) toggle.style.left = '240px';
      if (icon) icon.textContent = 'chevron_left';
    } else {
      if (sidebar) sidebar.classList.add('collapsed');
      if (main) main.style.marginLeft = '0';
      if (toggle) toggle.style.left = '0';
      if (icon) icon.textContent = 'chevron_right';
    }
    try { localStorage.setItem('ki_sidebar_open', sidebarOpen ? '1' : '0'); } catch (e) {}
  };
  window.openDrawer = function () {
    var s = document.getElementById('sidebar'), b = document.getElementById('sidebar-backdrop');
    if (s) s.classList.add('drawer-open');
    if (b) b.classList.add('open');
    document.body.style.overflow = 'hidden';
  };
  window.closeDrawer = function () {
    var s = document.getElementById('sidebar'), b = document.getElementById('sidebar-backdrop');
    if (s) s.classList.remove('drawer-open');
    if (b) b.classList.remove('open');
    document.body.style.overflow = '';
  };
  window.toggleDrawer = function () {
    var s = document.getElementById('sidebar');
    if (s && s.classList.contains('drawer-open')) { window.closeDrawer(); } else { window.openDrawer(); }
  };
  window.brandClick = function (e) {
    if (window.innerWidth < 768) { e.preventDefault(); window.toggleDrawer(); return false; }
    return true;
  };

  /* ── Artikel-Overlay (30.08.) ───────────────────────────────────
     window.klOpenArticle(data) oeffnet ein Overlay ueber der aktuellen
     Seite statt wegzunavigieren. data-Felder (alle optional, defensiv
     behandelt): title, summary, image, source, link, region, label,
     score, first_seen/date. "Verwandte Themen" laedt entities.json +
     graph.json EINMAL (modul-intern gecacht) und matcht Alias-Regexe
     gegen title+summary; bei Fehlern bleibt der Bereich einfach leer. */
  function klEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  window.klPlainClick = function (e) {
    return !!e && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  };
  function klFmtDate(v) {
    if (!v) return '';
    var d = new Date(v);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  var klEntitiesP = null, klGraphP = null;
  function klLoadEntities() {
    if (!klEntitiesP) {
      klEntitiesP = fetch(ROOT + 'entities.json').then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      }).catch(function () { return null; });
    }
    return klEntitiesP;
  }
  function klLoadGraph() {
    if (!klGraphP) {
      klGraphP = fetch(ROOT + 'graph.json').then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      }).catch(function () { return null; });
    }
    return klGraphP;
  }
  /* Baut die "Verwandte Themen"-Zeile: erkannte Entitaeten + je Top-2-
     Graph-Partner (nach Kantengewicht), max. ~6 Chips insgesamt. Liefert
     '' wenn nichts erkannt wird oder entities.json/graph.json fehlen. */
  function klRelatedHtml(text) {
    return Promise.all([klLoadEntities(), klLoadGraph()]).then(function (res) {
      var ent = res[0], graph = res[1];
      if (!ent || !ent.entities || !graph || !graph.edges) return '';
      var hay = text || '', found = [];
      for (var i = 0; i < ent.entities.length; i++) {
        var e = ent.entities[i], aliasse = e.aliasse || [], hit = false;
        for (var j = 0; j < aliasse.length; j++) {
          try { if (new RegExp(aliasse[j], 'i').test(hay)) { hit = true; break; } } catch (err) {}
        }
        if (hit && found.indexOf(e.id) === -1) found.push(e.id);
      }
      if (!found.length) return '';
      var chips = [], seen = {};
      found.forEach(function (id) {
        chips.push('<span class="kl-chip kl-chip-hit">' + klEsc(id) + '</span>');
        seen['hit:' + id] = true;
      });
      found.forEach(function (id) {
        var edges = graph.edges.filter(function (ed) { return ed.source === id || ed.target === id; })
          .sort(function (a, b) { return (b.count || 0) - (a.count || 0); });
        edges.slice(0, 2).forEach(function (ed) {
          var partner = ed.source === id ? ed.target : ed.source;
          var key = [id, partner].sort().join('|');
          if (seen[key] || seen['hit:' + partner]) return;
          seen[key] = true;
          chips.push('<span class="kl-chip">' + klEsc(id) + ' &harr; ' + klEsc(partner) + ' &middot; ' + (ed.count || 0) + '&times;</span>');
        });
      });
      chips = chips.slice(0, 6);
      if (!chips.length) return '';
      return '<div class="kl-ov-related-label">Verwandte Themen</div>' +
        '<div class="kl-ov-related-chips">' + chips.join('') + '</div>';
    }).catch(function () { return ''; });
  }
  var klOvOpen = false, klOvReqId = 0;
  // Fallback-Clips fuer Artikel ohne eigenes og:image (01.09., erweitert um
  // 3 weitere Daniel-Clips). Bei jedem Oeffnen wird EINER zufaellig gewaehlt --
  // nie mehrere gleichzeitig, absichtlich nur Varianz statt Dauerschleife
  // desselben Videos.
  var FALLBACK_VIDEOS = [
    'fallback-artikel.mp4', 'fallback-schrifthell.mp4', 'fallback-space.mp4', 'fallback-drache.mp4',
    'fallback-eule.mp4', 'fallback-weltraum.mp4', 'fallback-wasserwellen.mp4', 'fallback-buchaufschlagen.mp4'
  ];
  function klPlayFallbackVideo(videoEl) {
    if (!videoEl) return;
    var pick = FALLBACK_VIDEOS[Math.floor(Math.random() * FALLBACK_VIDEOS.length)];
    videoEl.src = ROOT + 'assets/' + pick;
    videoEl.hidden = false;
    videoEl.currentTime = 0;
    videoEl.play().catch(function () {}); // Autoplay-Block ignorieren, ist eh muted
  }
  /* -- Teilen (03.09.26) -------------------------------------------------
     Bis hierhin gab es keinen Weg, EINE gelesene Meldung weiterzuschicken --
     nur die ganze Seite als Link. klHashId() macht aus dem Artikel-Link eine
     kurze, stabile ID (djb2, base36); index.html oeffnet beim Laden das
     Overlay, wenn die Adresse auf #a=<id> endet. Der Teilen-Knopf nutzt die
     native Share-Sheet (Handy) und faellt sonst auf "Link kopiert" zurueck. */
  window.klHashId = function (str) {
    var key = String(str == null ? '' : str), h = 5381;
    for (var i = 0; i < key.length; i++) h = ((h * 33) ^ key.charCodeAt(i)) >>> 0;
    return h.toString(36);
  };
  var klCurrent = null;
  function klShareUrl() {
    var base = location.origin + location.pathname;
    if (!klCurrent || !klCurrent.link) return base;
    return base + '#a=' + window.klHashId(klCurrent.link);
  }
  function klShareFeedback(text) {
    var lab = document.getElementById('kl-ov-share-label'),
        btn = document.getElementById('kl-ov-share');
    if (!lab) return;
    lab.textContent = text;
    if (btn) btn.classList.add('done');
    setTimeout(function () {
      lab.textContent = 'Teilen';
      if (btn) btn.classList.remove('done');
    }, 1900);
  }
  window.klShareArticle = function () {
    var url = klShareUrl(), title = (klCurrent && klCurrent.title) || 'KI News';
    if (navigator.share) {
      navigator.share({ title: title, text: title, url: url }).catch(function () {});
      return;
    }
    var done = function () { klShareFeedback('Link kopiert'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, function () { klCopyFallback(url, done); });
    } else {
      klCopyFallback(url, done);
    }
  };
  function klCopyFallback(url, done) {
    // execCommand ist veraltet, aber der einzige Weg ohne Clipboard-API
    // (aeltere Browser, http-Kontext). Schlaegt auch das fehl: URL anzeigen.
    try {
      var ta = document.createElement('textarea');
      ta.value = url; ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:absolute;left:-9999px;top:0';
      document.body.appendChild(ta); ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) { done(); return; }
    } catch (e) {}
    window.prompt('Link zum Kopieren:', url);
  }
  window.klOpenArticle = function (data) {
    data = data || {};
    klCurrent = data;
    var ov = document.getElementById('kl-ov');
    if (!ov) return; // Overlay-HTML fehlt (Injektion nicht gelaufen) -- niemals crashen
    var titleEl = document.getElementById('kl-ov-title');
    var summEl = document.getElementById('kl-ov-summary');
    var metaEl = document.getElementById('kl-ov-meta');
    var linkEl = document.getElementById('kl-ov-link');
    var imgWrap = document.getElementById('kl-ov-img-wrap');
    var imgEl = document.getElementById('kl-ov-img');
    var videoEl = document.getElementById('kl-ov-video');
    var relatedEl = document.getElementById('kl-ov-related');
    var title = data.title || '', summary = data.summary || '';
    titleEl.textContent = title;
    summEl.textContent = summary;
    var dateStr = klFmtDate(data.first_seen || data.date || '');
    var metaParts = [];
    if (data.source) metaParts.push(klEsc(data.source));
    if (dateStr) metaParts.push(dateStr);
    if (data.region) metaParts.push(klEsc(data.region));
    metaEl.innerHTML = metaParts.join(' &middot; ');
    if (data.image) {
      if (videoEl) { videoEl.pause(); videoEl.hidden = true; }
      imgEl.hidden = false;
      imgEl.onerror = function () {
        // Eigenes Bild kaputt (404 o.ä.) -> auf einen Fallback-Clip ausweichen
        // statt den ganzen Slot zu verstecken.
        imgEl.hidden = true;
        if (videoEl) klPlayFallbackVideo(videoEl);
        else imgWrap.hidden = true;
      };
      imgEl.src = data.image;
      imgWrap.hidden = false;
    } else if (videoEl) {
      imgEl.hidden = true;
      klPlayFallbackVideo(videoEl);
      imgWrap.hidden = false;
    } else {
      imgWrap.hidden = true;
    }
    if (data.link) {
      linkEl.href = data.link;
      linkEl.style.display = '';
    } else {
      linkEl.style.display = 'none';
    }
    // Scampy-6-Analyse (30.08., Daniels Wunsch) -- nur Top-5-Storys haben
    // `post.erklaerung`/`post.thread`, alle anderen Artikel zeigen nichts.
    var analyseEl = document.getElementById('kl-ov-analyse');
    var post = data.post;
    var thread = (post && post.thread) || [];
    if (post && (post.erklaerung || thread.length)) {
      var lead = post.erklaerung ? '<p>' + klEsc(post.erklaerung) + '</p>' : '';
      var list = thread.length
        ? '<ol>' + thread.map(function (t) { return '<li>' + klEsc(t) + '</li>'; }).join('') + '</ol>'
        : '';
      analyseEl.innerHTML = '<div class="kl-ov-analyse-label">Analyse</div>' + lead + list;
      analyseEl.hidden = false;
    } else {
      analyseEl.innerHTML = '';
      analyseEl.hidden = true;
    }
    relatedEl.hidden = true;
    relatedEl.innerHTML = '';
    ov.style.display = 'flex';
    document.documentElement.style.overflow = 'hidden';
    klOvOpen = true;
    // replaceState statt location.hash: kein Sprung, kein History-Eintrag pro
    // geoeffnetem Artikel -- die Adresszeile ist trotzdem sofort teilbar.
    if (data.link && window.history && history.replaceState) {
      try { history.replaceState(null, '', '#a=' + window.klHashId(data.link)); } catch (e) {}
    }
    var reqId = ++klOvReqId;
    try {
      klRelatedHtml(title + ' ' + summary).then(function (html) {
        if (!klOvOpen || reqId !== klOvReqId) return; // Overlay inzwischen zu/gewechselt
        if (html) { relatedEl.innerHTML = html; relatedEl.hidden = false; }
      });
    } catch (e) {}
  };
  window.klCloseArticle = function () {
    var ov = document.getElementById('kl-ov');
    if (ov) ov.style.display = 'none';
    klCurrent = null;
    if (location.hash.indexOf('#a=') === 0 && window.history && history.replaceState) {
      try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
    }
    var v = document.getElementById('kl-ov-video');
    if (v) v.pause(); // laeuft sonst im Hintergrund weiter (muted, aber unnoetig)
    document.documentElement.style.overflow = '';
    klOvOpen = false;
  };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && klOvOpen) window.klCloseArticle(); });

  /* ── "Letztes Update" (30.08.) ─────────────────────────────────
     Auf jeder Seite an derselben Stelle in der Sidebar, statt nur auf
     Archiv.html -- Daniel wollte dieselbe Reihenfolge/Position ueberall,
     damit man schneller durchscrollen kann. Eigener Fetch (einmal pro
     Seitenaufruf, gecacht), damit auch Seiten ohne eigenen news.json-Abruf
     (stats.html, profil.html, artikel/*.html) den Stand zeigen koennen. */
  var klStandP = null;
  function klLoadStand() {
    if (!klStandP) {
      klStandP = fetch(ROOT + 'news.json?t=' + Date.now()).then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      }).then(function (d) { return (d && d.stand) || null; }).catch(function () { return null; });
    }
    return klStandP;
  }

  /* ── Injection ──────────────────────────────────────────────── */
  function inject() {
    var old = document.getElementById('kl-nav');
    if (old) old.remove();
    var style = document.createElement('style');
    style.id = 'kl-css';
    style.textContent = CSS;
    document.head.appendChild(style);
    document.body.insertAdjacentHTML('afterbegin', chromeHtml());
    if (!document.getElementById('kl-ov')) document.body.insertAdjacentHTML('beforeend', overlayHtml());
    if (sidebarOpen && window.innerWidth >= 1024) {
      var s = document.getElementById('sidebar'), m = document.getElementById('main-content'),
          t = document.getElementById('sidebar-toggle'), i = document.getElementById('toggle-icon');
      if (s) s.classList.remove('collapsed');
      if (m) m.style.marginLeft = '240px';
      if (t) t.style.left = '240px';
      if (i) i.textContent = 'chevron_left';
    }
    applyAll();
    klLoadStand().then(function (stand) {
      var el = document.getElementById('standLabel');
      if (el && stand) el.textContent = stand;
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') window.closeDrawer(); });
    var sb = document.getElementById('sidebar');
    if (sb) sb.addEventListener('click', function (e) { if (e.target.closest('a')) window.closeDrawer(); });
    window.addEventListener('resize', function () { if (window.innerWidth >= 1024) window.closeDrawer(); });
  }

  /* Sofort injizieren wenn <body> bereits existiert (Script steht direkt
     nach <body>) - kein Chrome-Flackern, keine Races mit Seiten-Scripts. */
  if (document.body) { inject(); }
  else if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', inject); }
  else { inject(); }
})();
