#!/usr/bin/env python3
"""Medien-URLs der Karten DIESES Laufs in cards.json umstellen (07.11.26, Rueckfall Video-Repo).

Seit 07.11.26 liegen die Karten-Videos in einem eigenen Repo (KARTEN_REPO in ki_news.yml,
ki_news_videos), die Bilder bleiben in ki_news_media. generate_news_cards.py schreibt die
URLs schon vor dem Hochladen in cards.json. Klappt das Hochladen nicht, muessen die URLs der
neuen Karten auf den Ort zeigen, an dem die Dateien wirklich landen.

"Dieses Laufs" heisst: die Datei liegt in assets/cards. Dort stehen nur die Karten, die
generate_news_cards.py in diesem Lauf gerendert hat. Aeltere Eintraege behalten ihre URL,
ihre Dateien liegen ja weiter im jeweiligen Medien-Repo.

  python3 karten_urls.py umstellen ki_news_videos ki_news_media
      Stufe 2 im Schritt "Karten ins Medien-Repo": Video-Repo nicht nutzbar, die Dateien
      gehen nach ki_news_media.
  python3 karten_urls.py relativ ki_news_media ki_news_videos
      Stufe 3 im Schritt "Commit generated cards": kein Medien-Repo erreichbar, die Dateien
      gehen nach ki_news (assets/cards/...). mp4_hoch_url dieser Karten faellt weg,
      Hochkant-Videos kommen nie ins Hauptrepo.

Fehlt cards.json oder ist sie kaputt: nichts aendern, Exit 0. Jeder andere Fehler wirft
(Exit 1), der Workflow geht dann in die naechste Rueckfall-Stufe.
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PAGES = "https://dscampy.github.io/{}/cards/"
FELDER = ("mp4_url", "poster_url", "mp4_hoch_url")


def umstellen(karten, lauf, von_repos, nach_repo):
    """Stellt Felder um, deren Datei in `lauf` liegt. nach_repo None = relativ (assets/cards/).

    Liefert die Zahl der geaenderten Felder."""
    praefixe = [PAGES.format(r) for r in von_repos if r]
    n = 0
    for k in karten:
        if not isinstance(k, dict):
            continue
        for feld in FELDER:
            url = k.get(feld)
            if not isinstance(url, str):
                continue
            for p in praefixe:
                datei = url[len(p):]
                if not url.startswith(p) or datei not in lauf:
                    continue
                if nach_repo is not None:
                    k[feld] = PAGES.format(nach_repo) + datei
                elif feld == "mp4_hoch_url":
                    k.pop(feld)
                else:
                    k[feld] = "assets/cards/" + datei
                n += 1
                break
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modus", choices=("umstellen", "relativ"))
    ap.add_argument("repos", nargs="+", help="umstellen: VON NACH; relativ: alle Medien-Repos")
    ap.add_argument("--basis", default=str(BASE), help="Repo-Wurzel mit cards.json und assets/cards")
    a = ap.parse_args(argv)
    if a.modus == "umstellen":
        if len(a.repos) != 2:
            ap.error("umstellen braucht genau zwei Repos: VON NACH")
        von, nach = a.repos[:1], a.repos[1]
    else:
        von, nach = a.repos, None

    basis = Path(a.basis)
    ordner = basis / "assets" / "cards"
    lauf = {f.name for f in ordner.iterdir() if f.is_file()} if ordner.is_dir() else set()
    pfad = basis / "cards.json"
    try:
        karten = json.loads(pfad.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - fehlende/kaputte Datei: nichts tun
        print(f"karten_urls: cards.json nicht lesbar ({e.__class__.__name__}) - nichts geaendert")
        return 0
    if not isinstance(karten, list):
        print("karten_urls: cards.json ist keine Liste - nichts geaendert")
        return 0

    n = umstellen(karten, lauf, von, nach)
    if n:
        # gleiches Format wie generate_news_cards.py
        pfad.write_text(json.dumps(karten, ensure_ascii=False, indent=2), encoding="utf-8")
    ziel = PAGES.format(nach) if nach else "assets/cards/"
    print(f"karten_urls {a.modus}: {n} URLs umgestellt auf {ziel} ({len(lauf)} Dateien in diesem Lauf)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
