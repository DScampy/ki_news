#!/usr/bin/env python3
"""Pruefer-Vergleich (30.10.26): welches Sprachmodell taugt als Faktenpruefer fuer recherche_artikel.py?

Nimmt zwei echte Recherche-Entwuerfe aus artikel/entwurf/ (Gemini 4 Carbon, Mistral Large 4), laedt
deren Quellen frisch, baut die Fundstellen wie die Pipeline (recherche_artikel.pruefer_material) und
setzt 5 Fehler ein: falsche Zahl, Verzerrung, zwei falsche Zuordnungen, eine erfundene Aussage. Jedes
Modell prueft beide Artikel (je ein Aufruf, wie in der Pipeline) und RUNDEN mal.

Gemessen je Modell: gefundene Fehler (von 5 je Runde), Fehlalarme auf unveraenderten Absaetzen,
Ausfaelle (HTTP, leer, kaputtes JSON), Sekunden, Kosten laut OpenRouter. Alle Meldungen werden
ausgegeben, damit man Fehlalarme selbst beurteilen kann (manche sind evtl. berechtigt).

Kein fremder Artikeltext im Repo: die Quellen werden zur Laufzeit geladen. Schreibt nichts.
Aufruf: OPENROUTER_KEY=... python3 tools/pruefer_vergleich.py [--runden 2] [--modelle a,b]
"""
import argparse
import html
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import recherche_artikel as ra  # noqa: E402

# Auswahl nach dem Richter-Vergleich 02.10. (Sieger je Klasse: gpt-6-luna, qwen3.7-plus, gemini-3.8-flash;
# deepseek-v4-flash dort mit vielen leeren Urteilen, darum nicht dabei) plus Nemotron (Daniel) und Haiku 5.5.
MODELLE = ["nvidia/nemotron-3-ultra-550b-a55b:free", "google/gemini-3.8-flash", "openai/gpt-6-luna",
           "qwen/qwen3.7-plus", "anthropic/claude-haiku-5.5"]
ENTWUERFE = {
    "G": "artikel/entwurf/recherche-gemini-4-carbon-erreicht-im-artificial-analysis-intelligence-index-59.html",
    "M": "artikel/entwurf/recherche-mistral-stellt-large-4-mit-rund-einer-billion-parametern-als-offenes.html",
}
# (Artikel, Absatz, alt, neu, Art) - "alt" leer = Satz anhaengen
STOERUNGEN = [
    ("M", None, "62 Punkten", "68 Punkten", "falsche Zahl"),
    ("G", None, "halbieren", "verdreifachen", "Verzerrung"),
    ("G", None, "vier Wochen laut Heise, zwei Wochen laut The Decoder",
     "vier Wochen laut The Decoder, zwei Wochen laut Heise", "falsche Zuordnung"),
    ("G", None, "The Verge nennt", "Golem nennt", "falsche Zuordnung"),
    ("M", 6, "", " Mistral will Large 4 im Dezember zusätzlich als eigene iPhone-App anbieten.", "erfunden"),
]


def lade_entwurf(pfad, dp):
    s = (BASE / pfad).read_text(encoding="utf-8")
    a = {"titel": html.unescape(re.search(r"<h1>(.*?)</h1>", s).group(1)),
         "anriss": html.unescape(re.search(r'<p class="anriss">(.*?)</p>', s).group(1)), "absaetze": []}
    for p in re.findall(r"<p>(.*?)</p>", s):
        nrs = [int(n) for n in re.findall(r'href="#q(\d+)"', p)]
        if nrs:
            a["absaetze"].append({"text": html.unescape(re.sub(r"<sup>.*", "", p)), "quellen": nrs})
    quellen = []
    for nr, medium, link, titel in re.findall(r'<li id="q(\d+)">(.*?): <a href="([^"]*)"[^>]*>(.*?)</a>', s):
        text = ra._quelltext({"link": html.unescape(link)}, dp)
        quellen.append({"nr": int(nr), "medium": html.unescape(medium), "titel": html.unescape(titel),
                        "text": ra._sauber(text)[:ra.TEXT_JE_QUELLE], "link": link})
    return a, quellen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runden", type=int, default=2)
    ap.add_argument("--modelle", default=",".join(MODELLE))
    args = ap.parse_args()
    key = os.environ.get("OPENROUTER_KEY", "").strip()
    if not key:
        print("kein OPENROUTER_KEY")
        return 1
    dp = ra._deckung()

    artikel = {}
    for kz, pfad in ENTWUERFE.items():
        a, quellen = lade_entwurf(pfad, dp)
        ohne = [q["medium"] for q in quellen if len(q["text"]) < dp.MIN_QUELLTEXT]
        print(f"{kz}: {len(a['absaetze'])} Absätze, {len(quellen)} Quellen, ohne Text: {ohne or 'keine'}")
        artikel[kz] = (a, quellen)

    # Stoerungen setzen; Soll je Absatz-id merken (None = unveraendert)
    soll = {}
    for kz, absatz, alt, neu, art in STOERUNGEN:
        a = artikel[kz][0]
        if not alt:
            a["absaetze"][absatz - 1]["text"] += neu
            soll[(kz, f"P{absatz}")] = art
            continue
        for i, x in enumerate(a["absaetze"], 1):
            if alt in x["text"]:
                x["text"] = x["text"].replace(alt, neu)
                soll[(kz, f"P{i}")] = art
                break
        else:
            print(f"!! Stoerung nicht gesetzt ({kz}: {alt!r} nicht gefunden)")

    material = {}
    for kz, (a, quellen) in artikel.items():
        teile = ra.pruefer_material(a, quellen, dp)
        mit_text = {q["nr"] for q in quellen if len(q["text"]) >= dp.MIN_QUELLTEXT}
        nicht_bewertbar = {f"P{i}" for i, x in enumerate(a["absaetze"], 1) if not set(x["quellen"]) & mit_text}
        material[kz] = (teile, nicht_bewertbar)
        print(f"{kz}: Prüfer-Prompt {len(ra.pruefer_prompt(teile))} Zeichen, nicht bewertbar: {sorted(nicht_bewertbar) or 'keine'}")
    print("Eingebaute Fehler:", {f"{k[0]}{k[1]}": v for k, v in soll.items()})

    zeilen = []
    for modell in args.modelle.split(","):
        treffer = fehlalarm = ausfall = 0
        sekunden, kosten, meldungen = [], 0.0, []
        for runde in range(args.runden):
            for kz, (teile, nicht_bewertbar) in material.items():
                start = time.time()
                try:
                    urteil, usage = ra.pruefer_urteil(teile, modell, key)
                except Exception as e:
                    ausfall += 1
                    meldungen.append(f"  R{runde + 1} {kz}: AUSFALL {type(e).__name__} {getattr(e, 'code', '')} "
                                     f"{(getattr(e, 'text', '') or str(e))[:160]}")
                    continue
                sekunden.append(time.time() - start)
                kosten += float(usage.get("cost") or 0)
                for i, liste in urteil.items():
                    if i in nicht_bewertbar:
                        continue
                    art = soll.get((kz, i))
                    if art and liste:
                        treffer += 1
                    elif not art and liste:
                        fehlalarm += 1
                    for x in liste:
                        meldungen.append(f"  R{runde + 1} {kz}{i} [{'Fehler: ' + art if art else 'unverändert'}] {x[:180]}")
                    if art and not liste:
                        meldungen.append(f"  R{runde + 1} {kz}{i} [Fehler: {art}] NICHT GEFUNDEN")
                time.sleep(2)
        moeglich = len(soll) * args.runden
        zeilen.append((modell, treffer, moeglich, fehlalarm, ausfall, sekunden, kosten))
        print(f"\n=== {modell}")
        print("\n".join(meldungen) or "  (keine Meldungen)")

    print("\n\nErgebnis (je Modell %d Runden, 2 Artikel je Runde):" % args.runden)
    print(f"{'Modell':42s} {'Fehler gefunden':>16s} {'Fehlalarme':>11s} {'Ausfälle':>9s} {'Ø Sek.':>7s} {'Kosten $':>9s}")
    for modell, t, m, f, a, s, k in zeilen:
        print(f"{modell:42s} {f'{t}/{m}':>16s} {f:>11d} {a:>9d} {(sum(s) / len(s) if s else 0):>7.1f} {k:>9.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
