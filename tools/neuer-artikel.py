#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
neuer-artikel.py — Artikel-Pipeline für ki-news.live
=====================================================
Erzeugt aus einem Body-HTML-Fragment eine vollständige Artikel-Seite
im Site-Design (Template: tools/artikel-template.html, Chrome: ki-layout.js)
und registriert sie überall, wo sie hingehört:

  1. artikel/<slug>.html          (fertige Seite)
  2. artikel/artikel-index.json   (Longform-Liste auf artikel.html, neueste zuerst)
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

    # Share-Card automatisch nutzen, wenn vorhanden (tools/og-card.py)
    if a.ogimage == "https://ki-news.live/s-logo.png" and \
       os.path.exists(os.path.join(ROOT, "artikel", a.slug + "-og.png")):
        a.ogimage = "https://ki-news.live/artikel/%s-og.png" % a.slug
        print("· Share-Card gefunden -> og:image gesetzt")

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

    # ── artikel.html: KEINE Karte mehr einfuegen (02.10.26) ──
    # Die Seite laedt ihre Longform-Liste seit dem 28.09. aus artikel/artikel-index.json.
    # Bis heute suchte dieses Skript hier noch "#longform-list", brach ab ("nicht in
    # artikel.html gefunden") und erreichte Sitemap und Index nie. Zudem war die Datei
    # nach "import json" abgeschnitten - der Index-Teil fehlte ganz.

    # ── sitemap.xml ──
    sm_path = os.path.join(ROOT, "sitemap.xml")
    sm = io.open(sm_path, encoding="utf-8", newline="").read()
    loc = "https://ki-news.live/artikel/%s.html" % a.slug
    if loc in sm:
        print("· sitemap.xml hat den Eintrag schon — übersprungen")
    else:
        nl = "\r\n" if "\r\n" in sm else "\n"
        entry = nl.join(["  <url>", "    <loc>%s</loc>" % loc, "    <lastmod>%s</lastmod>" % a.datum,
                         "    <changefreq>monthly</changefreq>", "    <priority>0.7</priority>", "  </url>", ""])
        sm = sm.replace("</urlset>", entry + "</urlset>")
        io.open(sm_path, "w", encoding="utf-8", newline="").write(sm)
        print("✓ sitemap.xml ergänzt")

    # ── artikel/artikel-index.json (Longform-Liste auf artikel.html + "Weiterlesen") ──
    import json
    idx_path = os.path.join(ROOT, "artikel", "artikel-index.json")
    roh = io.open(idx_path, encoding="utf-8", newline="").read() if os.path.exists(idx_path) else "[]"
    nl = "\r\n" if "\r\n" in roh else "\n"
    eintraege = json.loads(roh or "[]")
    bild = ""
    if a.ogimage.startswith("https://ki-news.live/artikel/"):
        bild = "artikel/" + a.ogimage.rsplit("/", 1)[-1]
    neu = {"slug": a.slug, "titel": a.titel, "desc": a.desc, "tags": tags,
           "datum": a.datum, "lesezeit": int(a.lesezeit) if str(a.lesezeit).isdigit() else a.lesezeit}
    if bild:
        neu["bild"] = bild          # artikel.html nimmt "bild" vor ihrer festen Bilderliste
    eintraege = [e for e in eintraege if e.get("slug") != a.slug] + [neu]
    eintraege.sort(key=lambda e: e.get("datum", ""), reverse=True)
    text = json.dumps(eintraege, ensure_ascii=False, indent=2).replace("\n", nl) + nl
    io.open(idx_path, "w", encoding="utf-8", newline="").write(text)
    print("✓ artikel/artikel-index.json: %s eingetragen (%d Artikel)" % (a.slug, len(eintraege)))

    print("Fertig. Pruefen: python tools/site_check.py")


if __name__ == "__main__":
    main()
