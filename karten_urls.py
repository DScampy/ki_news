#!/usr/bin/env python3
"""Karten DIESES Laufs in cards.json an den Ort der Medien anpassen (07.11.26, Rueckfall Video-Repo).

Seit 07.11.26 liegen die Karten-Videos in einem eigenen Repo (KARTEN_REPO in ki_news.yml,
ki_news_videos), die Bilder bleiben in ki_news_media. generate_news_cards.py schreibt die
URLs schon vor dem Hochladen in cards.json. Klappt das Hochladen nicht, muss cards.json zum
tatsaechlichen Ort der Dateien passen.

"Dieses Laufs" heisst: die Datei liegt in assets/cards. Dort stehen nur die Karten, die
generate_news_cards.py in diesem Lauf gerendert hat. Aeltere Eintraege bleiben, wie sie sind,
ihre Dateien liegen ja weiter im jeweiligen Medien-Repo.

  python3 karten_urls.py umstellen ki_news_videos ki_news_media
      Stufe 2 im Schritt "Karten ins Medien-Repo": Video-Repo nicht nutzbar, die Dateien
      gehen nach ki_news_media. Die URLs dieser Karten zeigen danach dorthin.
  python3 karten_urls.py entfernen ki_news_media ki_news_videos
      Stufe 3 im Schritt "Commit generated cards": kein Medien-Repo erreichbar. Die Medien
      kommen NICHT nach ki_news (das Repo wuchs so auf 1,9 GB). Die Karten dieses Laufs fallen
      aus cards.json, ihr Video liegt nirgends. Stand die Karte schon vor diesem Lauf in
      cards.json (HEAD, z. B. bei force_render), kommt der alte Eintrag zurueck.

Fehlt cards.json oder ist sie kaputt: nichts aendern, Exit 0. Jeder andere Fehler wirft
(Exit 1), der Workflow meldet dann eine Warnung.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PAGES = "https://dscampy.github.io/{}/cards/"
FELDER = ("mp4_url", "poster_url", "mp4_hoch_url")


def _praefixe(repos):
    return [PAGES.format(r) for r in repos if r]


def _datei_des_laufs(url, lauf, praefixe):
    """Dateiname, wenn url auf eine Datei dieses Laufs in einem der Repos zeigt, sonst None."""
    if isinstance(url, str):
        for p in praefixe:
            if url.startswith(p) and url[len(p):] in lauf:
                return url[len(p):]
    return None


def umstellen(karten, lauf, von_repos, nach_repo):
    """Felder mit Datei dieses Laufs auf nach_repo umstellen. Liefert die Zahl der Felder."""
    praefixe = _praefixe(von_repos)
    n = 0
    for k in karten:
        if not isinstance(k, dict):
            continue
        for feld in FELDER:
            datei = _datei_des_laufs(k.get(feld), lauf, praefixe)
            if datei:
                k[feld] = PAGES.format(nach_repo) + datei
                n += 1
    return n


def entfernen(karten, lauf, von_repos, alt_karten):
    """Karten dieses Laufs raus, alte Eintraege gleicher id zurueck. Liefert (Liste, raus, zurueck)."""
    praefixe = _praefixe(von_repos)
    alt = {k["id"]: k for k in alt_karten if isinstance(k, dict) and k.get("id")}
    ergebnis, raus, zurueck = [], 0, 0
    for k in karten:
        if isinstance(k, dict) and any(_datei_des_laufs(k.get(f), lauf, praefixe) for f in FELDER):
            if k.get("id") in alt:
                ergebnis.append(alt[k["id"]])
                zurueck += 1
            else:
                raus += 1
            continue
        ergebnis.append(k)
    return ergebnis, raus, zurueck


def _head_karten(basis):
    """cards.json aus HEAD (Stand vor diesem Lauf), [] wenn nicht lesbar."""
    try:
        r = subprocess.run(["git", "-C", str(basis), "show", "HEAD:cards.json"],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        daten = json.loads(r.stdout) if r.returncode == 0 else []
    except Exception:  # noqa: BLE001 - ohne HEAD-Stand wird nur entfernt
        return []
    return daten if isinstance(daten, list) else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modus", choices=("umstellen", "entfernen"))
    ap.add_argument("repos", nargs="+", help="umstellen: VON NACH, entfernen: alle Medien-Repos")
    ap.add_argument("--basis", default=str(BASE), help="Repo-Wurzel mit cards.json und assets/cards")
    a = ap.parse_args(argv)
    if a.modus == "umstellen" and len(a.repos) != 2:
        ap.error("umstellen braucht genau zwei Repos: VON NACH")

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

    if a.modus == "umstellen":
        n = umstellen(karten, lauf, a.repos[:1], a.repos[1])
        text = f"{n} URLs auf {PAGES.format(a.repos[1])} umgestellt"
    else:
        karten, n, zurueck = entfernen(karten, lauf, a.repos, _head_karten(basis))
        text = f"{n} Karten ohne Video aus cards.json genommen, {zurueck} alte Eintraege zurueck"
        n += zurueck
    if n:
        # gleiches Format wie generate_news_cards.py
        pfad.write_text(json.dumps(karten, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"karten_urls {a.modus}: {text} ({len(lauf)} Dateien in diesem Lauf)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
