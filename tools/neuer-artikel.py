#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
neuer-artikel.py — Artikel-Pipeline für ki-news.live
=====================================================
Erzeugt aus einem Body-HTML-Fragment eine vollständige Artikel-Seite
im Site-Design (Template: tools/artikel-template.html, Chrome: ki-layout.js)
und registriert sie überall, wo sie hingehört:

  1. artikel/<slug>.html          (fertige Seite)
  2. artikel.html                 (Karte in der Longform-Liste, neueste zuerst)
  3. sitemap.xml                  (<url>-Eintrag)

Aufruf (vom Repo-Root):
  python tools/neuer-artikel.py \
    --slug rtx-spark-im-check \
    --titel "RTX Spark im Check" \
    --untertitel "Revolution oder Hype?" \
    --desc "Meta-Description für Google/OG (max ~160 Zeichen)" \
    --tags "Analyse,Hardware,Nvidia" \
    --datum 2026-06-10 \
    --lesezeit 6 \
    --body pfad/zum/body.html \
    [--headline "Überschrift mit Punkt am Ende."] \
    [--autor CScampy] [--x-link https://x.com/...] \
    [--og-image https://ki-news.live/artikel/bild.png] [--force]

Der Body ist NUR das Innere von <article> — verfügbare CSS-Klassen:
  .skinny-box (Stichpunkt-Kasten), .benchmark-tbl (Tabelle),
  .art-img + .art-img-cap (Bild + Bildunterschrift),
  <h2>, <p>, <blockquote>, .source-note (Quellen am Ende)
"""
import argparse, io, os, re, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONATE = ["Januar","Februar","März","April","Mai","Juni","Juli","August",
          "September","Oktober","November","Dezember"]

def fail(msg):
    print("FEHLER:", msg); sys.exit(1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--titel", required=True)
    ap.add_argument("--untertitel", required=True)
    ap.add_argument("--desc", required=True)
    ap.add_argument("--tags", required=True, help="Komma-getrennt; erster Tag = gefüllter Badge")
    ap.add_argument("--datum", required=True, help="YYYY-MM-DD")
    ap.add_argument("--lesezeit", required=True)
    ap.add_argument("--body", required=True, help="Datei mit Body-HTML (Inneres von <article>)")
    ap.add_argument("--headline", default=None, help="abweichende H1 (Default: --titel + '.')")
    ap.add_argument("--autor", default="ScampyKI")
    ap.add_argument("--x-link", dest="xlink", default=None)
    ap.add_argument("--og-image", dest="ogimage", default="https://ki-news.live/s-logo.png")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9-]+", a.slug):
        fail("Slug darf nur a-z, 0-9 und - enthalten: " + a.slug)
    try:
        d = datetime.date.fromisoformat(a.datum)
    except ValueError:
        fail("Datum muss YYYY-MM-DD sein: " + a.datum)
    date_de = "%d. %s %d" % (d.day, MONATE[d.month-1], d.year)

    out_path = os.path.join(ROOT, "artikel", a.slug + ".html")
    if os.path.exists(out_path) and not a.force:
        fail("artikel/%s.html existiert schon (--force zum Überschreiben)" % a.slug)

    body = io.open(a.body, encoding="utf-8").read().strip()
    if "<html" in body.lower() or "<head" in body.lower():
        fail("--body soll nur das Artikel-Innere sein, kein komplettes HTML-Dokument")

    tpl = io.open(os.path.join(ROOT, "tools", "artikel-template.html"), encoding="utf-8").read()

    tags = [t.strip() for t in a.tags.split(",") if t.strip()]
    if not tags: fail("Mindestens ein Tag")
    tags_html = '    <span class="art-tag">%s</span>\n' % tags[0]
    for t in tags[1:]:
        tags_html += '    <span class="art-tag-outline">%s</span>\n' % t

    xlink_html = ""
    if a.xlink:
        xlink_html = ('\n    <span class="dot"></span>\n'
                      '    <a href="%s" target="_blank">Original auf X ↗</a>' % a.xlink)

    page = tpl
    for k, v in {
        "{{TITLE}}": a.titel,
        "{{SUBTITLE}}": a.untertitel,
        "{{DESC}}": a.desc,
        "{{SLUG}}": a.slug,
        "{{DATE_ISO}}": a.datum,
        "{{DATE_DE}}": date_de,
        "{{READ_MIN}}": str(a.lesezeit),
        "{{HEADLINE}}": a.headline or (a.titel.rstrip(".") + "."),
        "{{TAGS_HTML}}": tags_html,
        "{{AUTHOR_HANDLE}}": a.autor,
        "{{X_LINK_HTML}}": xlink_html,
        "{{OG_IMAGE}}": a.ogimage,
        "{{BODY}}": body,
    }.items():
        page = page.replace(k, v)

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if leftover: fail("Unersetzte Platzhalter: %s" % set(leftover))

    io.open(out_path, "w", encoding="utf-8").write(page)
    print("✓ artikel/%s.html geschrieben" % a.slug)

    # ── Karte in artikel.html (#longform-list, neueste zuerst) ──
    art_list = os.path.join(ROOT, "artikel.html")
    html = io.open(art_list, encoding="utf-8").read()
    if ("artikel/%s.html" % a.slug) in html:
        print("· Karte existiert schon in artikel.html — übersprungen")
    else:
        badge = ('<span style="display:inline-flex;padding:3px 10px;font-family:\'Space Grotesk\',sans-serif;'
                 'font-size:10px;font-weight:800;letter-spacing:0.14em;text-transform:uppercase;color:#fff;'
                 'background:var(--accent);border-radius:3px;">%s</span>' % tags[0])
        outline = "".join('\n            <span style="display:inline-flex;padding:3px 8px;font-family:\'Space Grotesk\',sans-serif;'
                          'font-size:10px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;'
                          'color:rgba(var(--neon-rgb),0.85);border:1px solid rgba(var(--neon-rgb),0.3);'
                          'border-radius:3px;">%s</span>' % t for t in tags[1:])
        card = '''
        <a href="artikel/{slug}.html" style="display:flex;flex-direction:column;gap:12px;padding:24px;border-radius:12px;border:1px solid rgba(var(--neon-rgb),0.35);background:rgba(10,14,22,0.6);text-decoration:none;transition:border-color 0.2s,box-shadow 0.2s;backdrop-filter:blur(8px);"
           onmouseenter="this.style.borderColor='rgba(var(--neon-rgb),0.7)';this.style.boxShadow='0 0 22px rgba(var(--neon-rgb),0.28)'"
           onmouseleave="this.style.borderColor='rgba(var(--neon-rgb),0.35)';this.style.boxShadow='none'">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            {badge}{outline}
          </div>
          <h3 style="font-family:'Space Grotesk',sans-serif;font-size:clamp(18px,2vw,24px);font-weight:700;color:#dfe3ea;letter-spacing:-0.01em;line-height:1.2;">{titel}</h3>
          <p style="font-family:'Work Sans',sans-serif;font-size:14px;color:rgba(255,255,255,0.6);line-height:1.6;">{desc}</p>
          <div style="display:flex;align-items:center;gap:12px;font-family:monospace;font-size:11px;color:rgba(255,255,255,0.38);letter-spacing:0.05em;flex-wrap:wrap;">
            <span>@{autor}</span>
            <span style="width:3px;height:3px;border-radius:50%;background:currentColor;display:inline-block;opacity:0.5;"></span>
            <span>{datum}</span>
            <span style="width:3px;height:3px;border-radius:50%;background:currentColor;display:inline-block;opacity:0.5;"></span>
            <span>≈ {min} Min. Lesezeit</span>
            <span style="margin-left:auto;color:rgba(var(--neon-rgb),0.6);font-weight:700;">Artikel lesen →</span>
          </div>
        </a>'''.format(slug=a.slug, badge=badge, outline=outline, titel=a.titel,
                       desc=a.desc, autor=a.autor, datum=date_de, min=a.lesezeit)
        marker = '<div id="longform-list" style="display:flex;flex-direction:column;gap:16px;margin-bottom:32px;">'
        if marker not in html: fail("#longform-list nicht in artikel.html gefunden")
        html = html.replace(marker, marker + card, 1)
        io.open(art_list, "w", encoding="utf-8").write(html)
        print("✓ Karte in artikel.html eingefügt")

    # ── sitemap.xml ──
    sm_path = os.path.join(ROOT, "sitemap.xml")
    sm = io.open(sm_path, encoding="utf-8").read()
    loc = "https://ki-news.live/artikel/%s.html" % a.slug
    if loc in sm:
        print("· sitemap.xml hat den Eintrag schon — übersprungen")
    else:
        entry = ('  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n'
                 '    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>\n' % (loc, a.datum))
        sm = sm.replace("</urlset>", entry + "</urlset>")
        io.open(sm_path, "w", encoding="utf-8").write(sm)
        print("✓ sitemap.xml ergänzt")

    print("\nFertig. Lokal prüfen, dann deployen.")

if __name__ == "__main__":
    main()
