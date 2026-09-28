# -*- coding: utf-8 -*-
"""
Vorschau-Seiten *-neu.html aus den Arbeitsstaenden bauen (28.09.2026).

Daniel prueft neue Fassungen auf dem Handy, bevor sie die Originale ersetzen. Dieses Skript
kopiert die Quelle, setzt noindex, entfernt canonical/hreflang und traegt einen Hinweis ein.
index-neu.html: Morgenlage und Neueste Analysen laden im Browser (siehe index.html), der
SSR-Stand zwischen den Markern wird geleert, damit dort nie ein veralteter Stand steht.

Aufruf: python3 tools/vorschau_seiten.py [quelle ziel] ...   (ohne Argumente: nur index)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = [("index.html", "index-neu.html")]


def baue(quelle, ziel):
    s = (ROOT / quelle).read_text(encoding="utf-8")
    s = re.sub(r'\s*<meta name="robots"[^>]*>', "", s)
    s = re.sub(r'\s*<link rel="canonical"[^>]*>', "", s)
    s = re.sub(r'\s*<link rel="alternate" hreflang[^>]*>', "", s)
    hinweis = ("<!-- VORSCHAU (28.09.26): gebaut aus %s mit tools/vorschau_seiten.py, nicht verlinkt, noindex. "
               "Daniel gibt einzeln frei; bis dahin bleibt %s live. -->" % (quelle, quelle))
    s, n = re.subn(r"(<head[^>]*>)", lambda m: m.group(1) + "\n" + hinweis +
                   '\n<meta name="robots" content="noindex, nofollow"/>', s, count=1)
    if n != 1:
        raise SystemExit("kein <head> in " + quelle)
    if ziel == "index-neu.html":
        for marke in ("BRIEFING", "ARTIKEL"):
            s, n = re.subn(r"(<!-- SSR:%s:START -->).*?(\s*<!-- SSR:%s:END -->)" % (marke, marke),
                           r"\1\2", s, count=1, flags=re.S)
            if n != 1:
                raise SystemExit("Marker SSR:%s fehlt" % marke)
    (ROOT / ziel).write_text(s, encoding="utf-8", newline="")
    print("  %s -> %s (%d Zeichen)" % (quelle, ziel, len(s)))


if __name__ == "__main__":
    a = sys.argv[1:]
    paare = list(zip(a[::2], a[1::2])) if a else STANDARD
    for q, z in paare:
        baue(q, z)
