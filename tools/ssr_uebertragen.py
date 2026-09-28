#!/usr/bin/env python3
"""index.html ist Vorlage UND Generat (28.09.26).

ki_news.py schreibt in index.html nur die SSR-Bereiche (<!-- SSR:X:START --> ... END)
und die Zeile id="stand-label". Alles andere ist Vorlage, die per PR geaendert wird.
Wird ein Vorlagen-PR WAEHREND eines Pipeline-Laufs gemergt, hat der Workflow beim
Push-Konflikt bisher seine alte, vor dem Merge erzeugte index.html uebernommen und
den PR still zurueckgedreht (belegt: PR #18 durch e021015, 28.09.26 23:33).

Dieses Werkzeug nimmt die Vorlage aus <vorlage> (z.B. origin/main) und uebertraegt
die generierten Teile aus <generat> hinein. Ergebnis nach <ziel>.
Findet es einen Bereich in einer der Dateien nicht, bricht es ab (exit 1) und laesst
<ziel> unveraendert - der Workflow nimmt dann wie frueher das Generat.

Aufruf: python3 tools/ssr_uebertragen.py <vorlage> <generat> <ziel>
"""
import re
import sys

BEREICH = re.compile(r"<!-- SSR:(\w+):START -->.*?<!-- SSR:\1:END -->", re.S)
STAND = re.compile(r'<span id="stand-label"[^>]*>[^<]*</span>')


def uebertragen(vorlage, generat):
    gen = {m.group(1): m.group(0) for m in BEREICH.finditer(generat)}
    vor = {m.group(1) for m in BEREICH.finditer(vorlage)}
    if not gen or set(gen) != vor:
        raise ValueError("SSR-Bereiche passen nicht: Vorlage %s, Generat %s" % (sorted(vor), sorted(gen)))
    out = BEREICH.sub(lambda m: gen[m.group(1)], vorlage)
    s_gen = STAND.search(generat)
    if s_gen and STAND.search(out):
        out = STAND.sub(lambda m: s_gen.group(0), out, count=1)
    return out


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    vorlage = open(argv[1], encoding="utf-8").read()
    generat = open(argv[2], encoding="utf-8").read()
    try:
        out = uebertragen(vorlage, generat)
    except ValueError as e:
        print("ssr_uebertragen: %s" % e)
        return 1
    with open(argv[3], "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print("ssr_uebertragen: Vorlage uebernommen, %d SSR-Bereiche + Stand aus dem Generat" % len(BEREICH.findall(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
