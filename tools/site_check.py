#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
site_check.py — Drift-Wächter für ki-news.live
Läuft lokal (python tools/site_check.py) und in der GitHub Action.
Prüft genau die Fehlerklassen, die früher unbemerkt live gingen:

  1. Jede Seite bindet assets/ki-layout.js ein (Single Source of Truth)
  2. Keine Seite hat wieder eigenes Chrome-Markup (Sidebar/Nav-Kopien)
  3. Alle internen Links zeigen auf existierende Dateien
  4. Alle assets/*.js sind syntaktisch gültig (node --check)
  5. Jeder Artikel steht in sitemap.xml und artikel-index.json
  6. Jede Seite hat ein Favicon

Exit-Code 0 = alles ok, 1 = Drift gefunden (Action schlägt fehl).
"""
import io, os, re, subprocess, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
errors = []

PAGES = ["index.html", "artikel.html", "Archiv.html", "stats.html", "profil.html"]
ARTICLES = sorted("artikel/" + f for f in os.listdir("artikel")
                  if f.endswith(".html") and not f.startswith("_"))
ALL = PAGES + ARTICLES

# ── 1+2: Layout eingebunden, kein Chrome-Duplikat ──
for p in ALL:
    s = io.open(p, encoding="utf-8").read()
    if "ki-layout.js" not in s:
        errors.append("%s: ki-layout.js fehlt" % p)
    if re.search(r'<aside id="sidebar"', s):
        errors.append("%s: eigenes Sidebar-Markup gefunden (gehört in ki-layout.js!)" % p)
    if re.search(r'<nav class="fixed', s):
        errors.append("%s: eigenes Topbar-Markup gefunden (gehört in ki-layout.js!)" % p)
    # 6: Favicon
    if 'rel="icon"' not in s and 'rel="shortcut' not in s:
        errors.append("%s: kein Favicon" % p)

# ── 3: interne Links ──
for p in ALL + ["Impressum.html", "Datenschutz.html"]:
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding="utf-8").read()
    base = os.path.dirname(p)
    for m in re.finditer(r'href="([^"#][^"]*)"', s):
        h = m.group(1)
        if h.startswith(("http", "mailto:", "tel:", "javascript:")) or "${" in h or "'" in h or "+" in h:
            continue
        if h.startswith("/cdn-cgi/"):
            continue
        target = (h.lstrip("/") or "index.html") if h.startswith("/") else os.path.normpath(os.path.join(base, h))
        target = target.split("?")[0].split("#")[0]
        if target and not os.path.exists(target):
            errors.append("%s: toter Link -> %s" % (p, h))

# ── 4: JS-Syntax ──
for f in sorted(os.listdir("assets")):
    if f.endswith(".js"):
        r = subprocess.run(["node", "--check", os.path.join("assets", f)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            errors.append("assets/%s: Syntaxfehler — %s" % (f, r.stderr.strip().splitlines()[-1][:80]))

# ── 5: Artikel-Registrierung ──
sitemap = io.open("sitemap.xml", encoding="utf-8").read() if os.path.exists("sitemap.xml") else ""
try:
    idx = json.load(io.open("artikel/artikel-index.json", encoding="utf-8"))
    idx_slugs = {e.get("slug") for e in idx}
except Exception:
    idx, idx_slugs = [], set()
    errors.append("artikel/artikel-index.json fehlt oder ist kein gültiges JSON")
for art in ARTICLES:
    slug = os.path.basename(art)[:-5]
    if ("artikel/%s.html" % slug) not in sitemap:
        errors.append("sitemap.xml: %s fehlt" % art)
    if slug not in idx_slugs:
        errors.append("artikel-index.json: %s fehlt" % slug)

# ── Ergebnis ──
if errors:
    print("DRIFT GEFUNDEN (%d Probleme):" % len(errors))
    for e in errors:
        print("  ✗", e)
    sys.exit(1)
print("✓ Site-Check bestanden: %d Seiten, keine Drift." % len(ALL))
