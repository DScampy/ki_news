#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modell-Waechter -- prueft alle Modell-IDs im Repo gegen den OpenRouter-Katalog
=============================================================================
Findet Modelle, die es nicht mehr gibt, BEVOR sie im Log hunderte 404er
produzieren.

Warum es das gibt
-----------------
Dreimal dasselbe Muster in acht Tagen:

    14.08.  meta-llama/llama-3.3-70b-instruct:free faellt weg
            -> in ki_news.py und story_registry_shadow.py getauscht,
               in add_reactions.py und generate_news_cards.py uebersehen
    21.08.  openai/gpt-oss-20b:free faellt weg -- der Slot, ueber den die
            meisten Uebersetzungen liefen
            -> 63x HTTP 404 + 52x leere Antwort + 7x 429 in einem einzigen
               Log-Fenster, rund 135 Fehlaufrufe, und als Folgeschaden
               scheiterten Uebersetzungen, worauf der Sprach-Guard Artikel
               still verwarf
    22.08.  vier weitere Leichen beim repo-weiten Abgleich gefunden

Jedes Mal war die Ursache dieselbe: ein Modell verschwindet lautlos aus dem
Katalog, und der Code merkt es erst, wenn die Fehler im Log auffallen. Dieser
Abgleich dauert zwanzig Sekunden.

    python3 modell_check.py            # Bericht, Exit 0 auch bei Funden
    python3 modell_check.py --streng   # Exit 1 bei Funden, fuer CI

Stand 22.08.2026.
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
KATALOG_URL = "https://openrouter.ai/api/v1/models"

# Dateien, deren Modell-IDs NICHT von OpenRouter kommen. Groq hat einen
# eigenen Katalog mit teils gleich lautenden IDs -- "openai/gpt-oss-20b" gibt
# es dort weiterhin, waehrend "openai/gpt-oss-20b:free" bei OpenRouter tot ist.
# Diese Verwechslung hat am 22.08. schon einmal Zeit gekostet.
FREMDE_ANBIETER = {
    os.path.join("registry_bau", "klassifiziere.py"): "Groq",
}

# Nur diese Praefixe gelten als Modell-ID. Sonst matchen auch Pfade und URLs.
PRAEFIXE = (
    "openai/", "google/", "meta-llama/", "nvidia/", "qwen/", "z-ai/",
    "mistralai/", "deepseek/", "nousresearch/", "anthropic/", "cohere/",
    "x-ai/", "stealth/", "thinkingmachines/", "poolside/", "liquid/",
    "dots-studio/", "moonshotai/", "microsoft/", "amazon/",
)

ID = re.compile(r'"([a-z0-9\-]+/[A-Za-z0-9._\-]+(?::free)?)"')


def katalog():
    req = urllib.request.Request(KATALOG_URL, headers={"User-Agent": "ki-news-modellcheck/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {m["id"]: m for m in json.load(r)["data"]}


def sammeln():
    """Alle Modell-IDs aus den Python-Dateien des Repos, mit Fundstelle."""
    treffer = []
    dateien = sorted(glob.glob(os.path.join(HIER, "*.py"))
                     + glob.glob(os.path.join(HIER, "registry_bau", "*.py")))
    for pfad in dateien:
        rel = os.path.relpath(pfad, HIER)
        if os.path.basename(pfad) == "modell_check.py":
            continue          # die Praefixliste hier ist keine Modellliste
        with open(pfad, encoding="utf-8", errors="replace") as f:
            for nr, zeile in enumerate(f, 1):
                if zeile.lstrip().startswith("#"):
                    continue
                for mid in ID.findall(zeile):
                    if mid.startswith(PRAEFIXE):
                        treffer.append((rel, nr, mid))
    return treffer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--streng", action="store_true",
                    help="Exit-Code 1, wenn tote IDs gefunden werden")
    args = ap.parse_args()

    try:
        kat = katalog()
    except Exception as e:
        print("Katalog nicht erreichbar (%s) -- Pruefung uebersprungen." % e)
        return 0
    print("OpenRouter-Katalog: %d Modelle\n" % len(kat))

    treffer = sammeln()
    tot, fremd, ok = [], [], []
    for rel, nr, mid in treffer:
        if rel in FREMDE_ANBIETER:
            fremd.append((rel, nr, mid))
        elif mid in kat:
            ok.append((rel, nr, mid))
        else:
            tot.append((rel, nr, mid))

    if tot:
        print("TOT -- nicht mehr im Katalog:")
        for rel, nr, mid in tot:
            print("   %-38s %s" % ("%s:%d" % (rel, nr), mid))
        print()

    # Gratis-Modelle koennen ohne Vorwarnung kostenpflichtig werden oder
    # verschwinden. Sichtbar machen, nicht bemaengeln.
    gratis = [(r, n, m) for r, n, m in ok
              if float(kat[m].get("pricing", {}).get("prompt", 1)) == 0
              and float(kat[m].get("pricing", {}).get("completion", 1)) == 0]
    if gratis:
        print("Gratis im Einsatz (koennen jederzeit wegfallen):")
        for rel, nr, mid in gratis:
            print("   %-38s %s" % ("%s:%d" % (rel, nr), mid))
        print()

    if fremd:
        print("Nicht geprueft (anderer Anbieter):")
        for rel, nr, mid in fremd:
            print("   %-38s %-42s %s" % ("%s:%d" % (rel, nr), mid,
                                         FREMDE_ANBIETER[rel]))
        print()

    print("%d IDs geprueft: %d ok, %d tot, %d fremd"
          % (len(treffer), len(ok), len(tot), len(fremd)))
    if tot:
        print("\nJede tote ID kostet pro Lauf einen Fehlversuch samt Latenz "
              "und faellt erst im Log auf.")
        return 1 if args.streng else 0
    print("Keine toten OpenRouter-IDs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
