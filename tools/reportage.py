#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reportage.py — baut aus einem normalen ki-news-Artikel die Reportage-Fassung (25.09.2026)
=========================================================================================

Weg C der neuer-artikel-anleitung.md. Aus dem Prototyp bau_reportage.py
(KIVault/02 Projekte/KI-News/articles/reportage-prototyp/) verallgemeinert, den Daniel
am 25.09. abgenommen hat: stehende Vollbild-Hintergruende je Kapitel, Textspalte
darueber, Kapitelleiste oben. Immer dunkel (Fotos sind die Buehne).

Inhalt, Kopf (Meta-Tags, JSON-LD, Komponenten-CSS) und Seitenende (Drawer-Skript usw.)
kommen 1:1 aus der Quelle. Neu ist nur die Buehne. Kapitel = jedes <h2> im
<article class="art-body">, alles davor ist die Einleitung.

Hintergrund je Kapitel (reportage-config.json, Liste "bilder", ein Eintrag je Kapitel):
  null          -> erstes <figure> des Kapitels wird Hintergrund (Bildunterschrift bleibt),
                   ohne Figure: naechstes Bild aus "ersatz", sonst typografische Buehne
  "datei.jpg"   -> dieses Bild (relativ zu artikel/)
  "typo"        -> typografische Buehne (Kapitelnummer, Leuchtverlauf, Raster)
"start": wie oben, dazu "video:datei.mp4"; null = art-hero der Quelle, sonst typo.

Aufruf (im Repo-Ordner):
  python tools/reportage.py <slug> <quelle.html>        -> schreibt artikel/<slug>.html
  python tools/reportage.py alle <quellordner>           -> alle Slugs aus der Config
Die Quelle ist die NORMALE Fassung (Schreibtisch im Vault:
KIVault/02 Projekte/KI-News/articles/reportage-quellen/<slug>.html). Eine Reportage als
Quelle wird abgelehnt, damit nie Buehne auf Buehne gebaut wird.
"""
import html as html_mod
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "tools" / "reportage-config.json"
FIG_RE = re.compile(r'<figure[^>]*>.*?</figure>', re.S)


def _hintergrund(spec, nr, farbe):
    """HTML fuer einen Kapitel-Hintergrund."""
    if spec and spec.startswith("video:"):
        return ('<div class="rep-bg"><video src="%s" autoplay muted loop playsinline '
                'preload="metadata" aria-hidden="true"></video></div>' % spec[6:])
    if spec and spec != "typo":
        return '<div class="rep-bg"><img src="%s" alt="" loading="lazy"></div>' % spec
    return ('<div class="rep-bg rep-typo" style="--rep-h:%d" aria-hidden="true">'
            '<span class="rep-riesen">%s</span></div>' % (farbe, "%02d" % nr if nr else "&#9679;"))


def baue(slug, quelle, cfg):
    s = pathlib.Path(quelle).read_text(encoding="utf-8")
    if 'class="rep"' in s or "rep-kap" in s:
        raise SystemExit("%s: Quelle ist schon eine Reportage - normale Fassung nehmen" % quelle)

    kopf = s[:s.index("</head>")]
    body_tag = re.search(r'<body[^>]*>', s).group(0)
    body_start = s.index(body_tag) + len(body_tag)
    main_start = s.index('<main id="main-content"')
    praeambel = s[body_start:main_start]                       # Layout-Skripte, Theme
    art_start = re.search(r'<article class="art-body"[^>]*>', s)
    art_ende = s.index("</article>", art_start.end())
    colophon = s[s.index('<div class="art-colophon"'):s.index("</main>")]
    colophon = colophon[:colophon.rindex("</div>")]            # schliessendes art-container
    trailer = s[s.index("</main>") + len("</main>"):]
    # Partikel-Hintergrund (three.js) wird nie sichtbar - Quelle raus, der Lader bricht dann ab
    trailer = re.sub(r'<script type="text/plain" id="ki-genesis-src">.*?</script>\s*', '', trailer, flags=re.S)

    kopfbereich = s[main_start:art_start.start()]
    titel = re.search(r'<h1 class="art-headline">(.*?)</h1>', kopfbereich, re.S).group(1)
    subline = re.search(r'<p class="art-subline">(.*?)</p>', kopfbereich, re.S).group(1)
    eyebrow = re.search(r'<div class="art-eyebrow">(.*?)</div>', kopfbereich, re.S).group(1)
    meta = re.search(r'<div class="art-meta-row">(.*?)</div>\s*(?=<figure|<article|$)', kopfbereich, re.S)
    meta = meta.group(1) if meta else re.search(r'<div class="art-meta-row">(.*?)</div>', kopfbereich, re.S).group(1)
    hero = re.search(r'<figure class="art-hero">.*?</figure>', kopfbereich, re.S)

    inhalt = s[art_start.end():art_ende]
    inhalt = re.sub(r'<div class="art-continued">.*?</div>\s*', '', inhalt, flags=re.S)
    teile = re.split(r'(?=<h2[^>]*>)', inhalt)
    einleitung, kapitel = teile[0], teile[1:]
    kurz = cfg["kurz"]
    bilder = cfg.get("bilder") or [None] * len(kapitel)
    if len(kapitel) != len(kurz) or len(bilder) != len(kapitel):
        raise SystemExit("%s: %d Kapitel, aber %d Kurznamen / %d Bilder in der Config"
                         % (slug, len(kapitel), len(kurz), len(bilder)))
    farbe = int(cfg.get("farbton", 195))
    ersatz = iter(cfg.get("ersatz", []))        # fuer null-Kapitel ohne eigene Figure

    # Start-Hintergrund
    start = cfg.get("start")
    start_cap = ""
    if start is None and hero:
        src = re.search(r'src="([^"]+)"', hero.group(0))
        start = src.group(1).split("/")[-1] if src else "typo"
        cap = re.search(r'class="art-hero-cap"[^>]*>(.*?)</div>', hero.group(0), re.S)
        start_cap = re.sub(r"<[^>]+>", "", cap.group(1)).strip() if cap else ""
    start_bg = _hintergrund(start or "typo", 0, farbe)

    sektionen = []
    for k, (roh, name, spec) in enumerate(zip(kapitel, kurz, bilder), 1):
        m = re.match(r'<h2[^>]*>(.*?)</h2>', roh, re.S)
        h2, rest = m.group(1), roh[m.end():]
        cap = ""
        if spec is None:
            fig = FIG_RE.search(rest)
            if fig:
                # nur echte Fotos - eingebettete Grafiken (iframe/svg) bleiben im Text
                src = re.search(r'<img[^>]*src="([^"]+\.(?:jpe?g|png|webp|avif))"', fig.group(0), re.I)
                if src:
                    spec = src.group(1).split("/")[-1]
                    c = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', fig.group(0), re.S)
                    cap = re.sub(r"<[^>]+>", "", c.group(1)).strip() if c else ""
                    rest = rest[:fig.start()] + rest[fig.end():]
            if spec is None:
                spec = next(ersatz, None)
        bg = _hintergrund(spec or "typo", k, (farbe + 28 * (k - 1)) % 360)
        if cap:
            bg = bg.replace("</div>", '<span class="rep-cap">%s</span></div>' % cap, 1)
        sektionen.append(
            '\n<section class="rep-kap" id="k%d">\n  %s\n  <div class="rep-flow">\n'
            '    <h2 class="rep-h2"><span class="rep-nr">Kapitel %d</span>%s</h2>\n'
            '    <div class="rep-spalte art-body">%s</div>\n  </div>\n</section>'
            % (k, bg, k, h2, rest))

    nav = "".join('<a href="#k%d" data-k="k%d">%s</a>' % (k, k, html_mod.escape(n))
                  for k, n in enumerate(kurz, 1))
    if start_cap:
        start_bg = start_bg.replace("</div>", '<span class="rep-cap">%s</span></div>' % start_cap, 1)

    seite = (kopf + CSS + "</head>\n" + body_tag + "\n" + DUNKEL_JS + praeambel +
             '<main id="main-content" class="rep">\n'
             '<section class="rep-kap rep-start" id="start">\n  ' + start_bg + '\n'
             '  <div class="rep-titel">\n'
             '    <div class="art-eyebrow">' + eyebrow + '</div>\n'
             '    <h1 class="art-headline">' + titel + '</h1>\n'
             '    <p class="rep-sub">' + subline + '</p>\n'
             '    <div class="art-meta-row">' + meta + '</div>\n'
             '    <a class="rep-pfeil" href="#einstieg" aria-label="Weiter nach unten">&#8595;</a>\n'
             '  </div>\n'
             '  <div class="rep-einleitung" id="einstieg"><div class="rep-spalte art-body">' + einleitung + '</div></div>\n'
             '</section>\n'
             '<nav class="rep-nav" aria-label="Kapitel"><a class="rep-home" href="#start">'
             + html_mod.escape(cfg["home"]) + '</a>' + nav + '<span class="rep-fort"></span></nav>'
             + "".join(sektionen) + '\n<div class="rep-ende">' + colophon + '</div>\n</main>'
             + NAV_JS + trailer)
    ziel = ROOT / "artikel" / (slug + ".html")
    ziel.write_text(seite, encoding="utf-8")
    print("%s: %d Kapitel, %d Zeichen -> %s" % (slug, len(sektionen), len(seite), ziel.relative_to(ROOT)))


CSS = """
<style>
/* ── Reportage-Buehne (tools/reportage.py, 25.09.26) ──────────────────── */
html{scroll-behavior:smooth;}
#genesis-wrap,#bg-overlay,#read-progress{display:none !important;}
#main-content.rep{--rep-nav:52px;background:#05070b !important;color:#e8edf3;}
.rep-kap{position:relative;scroll-margin-top:108px;}
.rep-bg{position:sticky;top:0;height:100vh;height:100svh;overflow:hidden;z-index:0;background:#05070b;}
.rep-bg img,.rep-bg video{width:100%;height:100%;object-fit:cover;filter:brightness(.5) saturate(1.05);
  transform:scale(1.06);transition:transform 1.6s ease,filter 1.6s ease;}
.rep-kap.sichtbar .rep-bg img,.rep-kap.sichtbar .rep-bg video{transform:scale(1);filter:brightness(.42) saturate(1.05);}
.rep-bg::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(5,7,11,.15) 0%,rgba(5,7,11,.05) 40%,rgba(5,7,11,.75) 100%);}
/* Kapitel ohne Foto: typografische Buehne */
.rep-typo{background:
  radial-gradient(60% 55% at 78% 22%,hsla(var(--rep-h),90%,55%,.30),transparent 70%),
  radial-gradient(50% 50% at 12% 88%,hsla(calc(var(--rep-h) + 60),85%,50%,.22),transparent 70%),
  #05070b;}
.rep-typo::before{content:'';position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);
  background-size:56px 56px;-webkit-mask-image:radial-gradient(ellipse at 60% 40%,#000 20%,transparent 75%);mask-image:radial-gradient(ellipse at 60% 40%,#000 20%,transparent 75%);}
.rep-riesen{position:absolute;right:-2vw;top:50%;transform:translateY(-55%);font:700 clamp(220px,42vw,560px)/.8 'Space Grotesk',sans-serif;
  color:transparent;-webkit-text-stroke:2px hsla(var(--rep-h),90%,65%,.35);letter-spacing:-.04em;transition:opacity 1.6s ease,transform 1.6s ease;opacity:.6;}
.rep-kap.sichtbar .rep-riesen{opacity:1;transform:translateY(-50%);}
.rep-cap{position:absolute;right:16px;bottom:14px;z-index:1;max-width:46ch;font:11px/1.4 'Work Sans',sans-serif;color:rgba(255,255,255,.6);text-align:right;}
.rep-flow{position:relative;z-index:1;margin-top:-100vh;margin-top:-100svh;padding:62vh 16px 55vh;}
.rep-h2{max-width:760px;margin:0 auto 34vh;font:700 clamp(30px,5vw,56px)/1.08 'Space Grotesk',sans-serif;color:#fff;text-shadow:0 2px 30px rgba(0,0,0,.6);}
.rep-nr{display:block;font:600 12px/1 monospace;letter-spacing:.2em;text-transform:uppercase;color:var(--accent,#00d4ff);margin-bottom:14px;}
.rep-spalte{max-width:680px;margin:0 auto;background:rgba(8,11,17,.8);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:30px 30px 10px;font-size:17px;line-height:1.7;}
.rep-spalte,.rep-einleitung{font-family:'Work Sans',sans-serif;}
.rep-spalte p,.rep-spalte li{color:#dfe5ec;}
/* Spalte traegt art-body (Komponenten-Stile der Quelle), Schrift wie im abgenommenen Prototyp */
#main-content.rep .rep-spalte.art-body p,#main-content.rep .rep-spalte.art-body li{font-family:'Work Sans',sans-serif;font-size:inherit;line-height:1.7;color:#dfe5ec;}
.rep-spalte p{margin:0 0 1.05em;}
.rep-spalte ul{margin:0 0 1.1em;padding-left:1.2em;}
.rep-spalte figure{margin:24px -8px;}
.rep-spalte img{border-radius:8px;max-width:100%;height:auto;}
.rep-spalte table{display:block;overflow-x:auto;max-width:100%;}
/* Start */
.rep-start .rep-bg img,.rep-start .rep-bg video{filter:brightness(.38);}
.rep-titel{position:relative;z-index:1;margin-top:-100vh;margin-top:-100svh;min-height:100vh;min-height:100svh;display:flex;flex-direction:column;justify-content:center;
  max-width:880px;margin-left:auto;margin-right:auto;padding:90px 20px 40px;text-align:center;}
.rep-titel .art-eyebrow{justify-content:center;margin-bottom:22px;flex-wrap:wrap;}
.rep-titel h1.art-headline{font:700 clamp(38px,7vw,84px)/1.02 'Space Grotesk',sans-serif;color:#fff;margin:0 0 22px;text-shadow:0 2px 40px rgba(0,0,0,.6);}
.rep-titel .rep-sub{font-size:clamp(17px,2.2vw,22px);line-height:1.5;color:rgba(255,255,255,.85);max-width:60ch;margin:0 auto 20px;}
.rep-titel .art-meta-row{justify-content:center;flex-wrap:wrap;color:rgba(255,255,255,.65);}
.rep-pfeil{margin:40px auto 0;width:34px;height:34px;border-radius:50%;border:1px solid rgba(255,255,255,.4);display:flex;align-items:center;justify-content:center;
  color:#fff;text-decoration:none;animation:repHuepf 2.2s ease-in-out infinite;}
@keyframes repHuepf{0%,100%{transform:translateY(0)}50%{transform:translateY(8px)}}
@media (prefers-reduced-motion:reduce){.rep-pfeil{animation:none}.rep-bg img,.rep-bg video,.rep-riesen{transition:none;transform:none}html{scroll-behavior:auto}}
.rep-einleitung{position:relative;z-index:1;max-width:680px;margin:0 auto;padding:0 16px 30vh;}
/* Kapitelleiste */
.rep-nav{position:sticky;top:56px;z-index:45;display:flex;gap:4px;align-items:center;overflow-x:auto;scrollbar-width:none;
  background:rgba(5,7,11,.88);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid rgba(255,255,255,.08);padding:0 12px;height:var(--rep-nav);}
.rep-nav::-webkit-scrollbar{display:none;}
.rep-nav a{flex:0 0 auto;font:600 13px/1 'Space Grotesk',sans-serif;color:rgba(255,255,255,.62);text-decoration:none;padding:10px 12px;border-radius:999px;}
.rep-nav a:hover{color:#fff;}
.rep-nav a.aktiv{color:#000;background:var(--accent,#00d4ff);}
.rep-nav .rep-home{color:#fff;margin-right:8px;}
.rep-fort{position:absolute;left:0;bottom:0;height:2px;background:var(--accent,#00d4ff);width:0;}
.rep-ende{background:#05070b;padding:60px 16px 80px;}
.rep-ende .art-colophon{max-width:680px;margin:0 auto;}
@media(max-width:767px){.rep-spalte{padding:22px 18px 6px;font-size:16px;}.rep-flow{padding-top:55vh}.rep-h2{margin-bottom:26vh}.rep-riesen{right:-8vw;}}
</style>
"""

DUNKEL_JS = """<script>
/* Reportage ist immer dunkel (Fotos als Buehne). Das Seiten-Theme setzt html.light,
   das wuerde Fliesstext dunkel auf dunkle Spalte legen -> hier dauerhaft entfernen. */
(function(){ var h=document.documentElement;
  function dunkel(){ if(h.classList.contains('light')){ h.classList.remove('light'); h.classList.add('dark'); } }
  dunkel(); new MutationObserver(dunkel).observe(h,{attributes:true,attributeFilter:['class']}); })();
</script>
"""

NAV_JS = """
<script>
(function(){
  var kap = [].slice.call(document.querySelectorAll('.rep-kap'));
  var links = {}; [].forEach.call(document.querySelectorAll('.rep-nav a[data-k]'), function(a){ links[a.getAttribute('data-k')] = a; });
  var fort = document.querySelector('.rep-fort');
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){
      if (e.isIntersecting) e.target.classList.add('sichtbar');
      if (e.isIntersecting && links[e.target.id]) {
        Object.keys(links).forEach(function(k){ links[k].classList.toggle('aktiv', k === e.target.id); });
        var nav = links[e.target.id].parentNode, a = links[e.target.id];
        nav.scrollTo({left: a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2, behavior: 'smooth'});
      }
    });
  }, {rootMargin: '-45% 0px -45% 0px'});
  kap.forEach(function(k){ io.observe(k); });
  function fortschritt(){
    var h = document.documentElement, max = h.scrollHeight - innerHeight;
    fort.style.width = (max > 0 ? Math.min(100, 100 * h.scrollTop / max) : 0) + '%';
  }
  addEventListener('scroll', fortschritt, {passive:true}); fortschritt();
})();
</script>
"""


if __name__ == "__main__":
    konf = json.loads(CONFIG.read_text(encoding="utf-8"))
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    if sys.argv[1] == "alle":
        for slug in konf:
            if not slug.startswith("_"):
                baue(slug, pathlib.Path(sys.argv[2]) / (slug + ".html"), konf[slug])
    else:
        baue(sys.argv[1], sys.argv[2], konf[sys.argv[1]])
