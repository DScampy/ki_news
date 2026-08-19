# -*- coding: utf-8 -*-
"""
Altbestand-Reparatur fuer archive.json / news.json — Encoding-Reste.

Der Encoding-Fix in ki_news.py wirkt nur beim EINLESEN neuer Modellantworten.
Was vor dem Fix ins Archiv gelangt ist, bleibt dort kaputt. Dieses Skript
raeumt den Altbestand auf.

ZWEISTUFIG, schreibt nie ungefragt:

    python cleanup-archive-encoding.py            # nur Bericht, aendert nichts
    python cleanup-archive-encoding.py --schreiben  # schreibt, nach Backup

Betroffene Muster:
    {"o} {"u} {"a} {"O} {"U} {"A}   LaTeX-Escapes mit Klammern
    ungesch"uzt                      klammerlos, nur zwischen Kleinbuchstaben
    {\\ss}                            scharfes s

Fremdschrift (kyrillisch/CJK) wird NUR gemeldet, nicht angefasst — ein
"senderстви" zu "sender" zu kuerzen waere stiller Textverlust. Solche
Eintraege gehoeren von Hand angesehen oder beim naechsten Lauf neu uebersetzt.
"""
import io
import json
import os
import re
import shutil
import sys

DATEIEN = ("archive.json", "news.json")

_KLAMMER = {
    '{"o}': "ö", '{"O}': "Ö", '{"u}': "ü", '{"U}': "Ü",
    '{"a}': "ä", '{"A}': "Ä", "{\\ss}": "ß", "\\ss ": "ß ",
}
_INLINE = re.compile(r'(?<=[a-zäöüß])"([oua])(?=[a-zäöüß])')
_INLINE_MAP = {"o": "ö", "u": "ü", "a": "ä"}
_FREMD = re.compile(r"[一-鿿぀-ヿ가-힣Ѐ-ӿ]")

FELDER = ("title", "summary", "title_de")


def fix(text):
    t = text or ""
    if "{" not in t and "\\ss" not in t and '"' not in t:
        return t
    for esc, ch in _KLAMMER.items():
        t = t.replace(esc, ch)
    if '"' in t:
        t = _INLINE.sub(lambda m: _INLINE_MAP[m.group(1)], t)
    return t


def eintraege(data):
    """archive.json ist eine Liste, news.json ein Dict mit 'news'-Liste."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        out = []
        for key in ("news", "posts", "roundups"):
            v = data.get(key)
            if isinstance(v, list):
                out.extend(v)
        return out
    return []


def main():
    schreiben = "--schreiben" in sys.argv
    gesamt_fix = 0
    gesamt_fremd = 0

    for pfad in DATEIEN:
        if not os.path.exists(pfad):
            print("%s: nicht vorhanden, uebersprungen" % pfad)
            continue
        data = json.load(io.open(pfad, encoding="utf-8"))
        items = eintraege(data)
        geaendert = 0
        print("\n=== %s (%d Eintraege) ===" % (pfad, len(items)))

        for x in items:
            for feld in FELDER:
                alt = x.get(feld)
                if not isinstance(alt, str):
                    continue
                neu = fix(alt)
                if neu != alt:
                    geaendert += 1
                    print("  [%s] %s" % (feld, x.get("date") or x.get("first_seen") or "?"))
                    print("      vorher : %s" % alt[:100])
                    print("      nachher: %s" % neu[:100])
                    if schreiben:
                        x[feld] = neu
                if _FREMD.search(neu):
                    gesamt_fremd += 1
                    print("  [%s] FREMDSCHRIFT, nicht angefasst - %s" % (feld, neu[:100]))

        gesamt_fix += geaendert
        if geaendert and schreiben:
            shutil.copy(pfad, pfad + ".bak")
            with io.open(pfad, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("  -> geschrieben, Backup: %s.bak" % pfad)
        elif geaendert:
            print("  -> %d Stellen reparierbar (Probelauf, nichts geschrieben)" % geaendert)
        else:
            print("  keine Encoding-Reste gefunden")

    print("\nGesamt: %d reparierbare Stellen, %d Eintraege mit Fremdschrift (nur gemeldet)."
          % (gesamt_fix, gesamt_fremd))
    if gesamt_fix and not schreiben:
        print("Zum Schreiben:  python cleanup-archive-encoding.py --schreiben")
    if gesamt_fix and schreiben:
        print("ACHTUNG: geaenderte JSON-Dateien muessen hochgeladen werden, sonst")
        print("ueberschreibt der naechste Lauf sie wieder mit dem Repo-Stand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
