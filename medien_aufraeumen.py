#!/usr/bin/env python3
"""Karten-Medien im Medien-Repo aufraeumen: nach Verweis statt nur nach Alter (19.10.26).

Bisher (Schritt "Karten ins Medien-Repo" in ki_news.yml): alle MP4/JPG der letzten 10 Tage
bleiben liegen. cards.json zeigt aber nur MAX_CARDS_DISPLAY = 150 Karten (bei 20-33 Karten
pro Tag ca. 5-6 Tage). Messung 19.10.26: 617 MB Karten-Medien, davon 291 MB ohne jeden
Verweis in cards.json. Die Site lag bei 830 von 1024 MB (GitHub-Pages-Grenze 1 GB).

Neue Regel je Datei <cards>/<YYYY-MM-DD>-<slug>.(mp4|jpg):
  juenger als --min-tage            -> bleibt immer (frische Karten, Telegram-/Insta-Queue)
  aelter als --max-tage             -> weg (wie bisher die 10-Tage-Regel)
  dazwischen                        -> bleibt nur, wenn der Dateistamm (ohne Endung) in einer
                                       Verweis-Datei vorkommt: cards.json und artikel/**/*.html
                                       (Dossiers + Entwuerfe). MP4 und JPG gleichen Namens
                                       bleiben deshalb immer zusammen.
Zusaetzlich zaehlt die cards.json aus HEAD (live vor diesem Lauf), damit nichts verschwindet,
was die Website bis zum naechsten Deploy noch zeigt.
Sicherheitsnetz: cards.json fehlt, ist kaputt oder hat weniger als --min-karten Eintraege
-> keine Verweis-Loeschung, nur die alte Altersregel. Insta (check_insta_queue.py) postet
nur Karten aus cards.json, die bleiben also immer erhalten.

Aufruf: python3 medien_aufraeumen.py --cards /tmp/ki_news_media/cards [--min-tage 2]
        [--max-tage 10] [--min-karten 20] [--trocken]
Kill-Switch: Env MEDIEN_NACH_VERWEIS=0 -> nur Altersregel (altes Verhalten).
Exit-Code immer 0 bei Datenproblemen; nur Programmfehler werfen (dann greift im Workflow
der Rueckfall auf die alte Schleife).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATUM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def verweis_text(basis: Path, min_karten: int):
    """Liefert (Text aller Verweis-Dateien, Grund) oder (None, Grund) beim Sicherheitsnetz."""
    p = basis / "cards.json"
    try:
        karten = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"cards.json nicht lesbar ({e.__class__.__name__})"
    if isinstance(karten, dict):
        karten = karten.get("cards", [])
    if not isinstance(karten, list) or len(karten) < min_karten:
        n = len(karten) if isinstance(karten, list) else 0
        return None, f"cards.json hat nur {n} Karten (< {min_karten})"
    teile = [json.dumps(karten, ensure_ascii=False)]
    # Auch die noch LIVE stehende cards.json (Stand des Checkouts, HEAD) zaehlt als Verweis:
    # das Medien-Repo wird vor dem Commit der neuen cards.json gepusht, sonst fehlten Karten,
    # die gerade aus den 150 fallen, bis zum Pages-Deploy (oder laenger, wenn der Push scheitert).
    try:
        alt = subprocess.run(["git", "-C", str(basis), "show", "HEAD:cards.json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
        if alt.returncode == 0:
            teile.append(alt.stdout)
    except Exception:
        pass
    n_html = 0
    for h in sorted((basis / "artikel").rglob("*.html")) if (basis / "artikel").is_dir() else []:
        try:
            teile.append(h.read_text(encoding="utf-8", errors="replace"))
            n_html += 1
        except OSError:
            pass
    return "\n".join(teile), f"{len(karten)} Karten, {n_html} Artikel-Seiten"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", required=True, help="Ordner cards/ im geklonten Medien-Repo")
    ap.add_argument("--basis", default=str(BASE), help="Repo-Wurzel mit cards.json und artikel/")
    ap.add_argument("--min-tage", type=int, default=2)
    ap.add_argument("--max-tage", type=int, default=10)
    ap.add_argument("--min-karten", type=int, default=20)
    ap.add_argument("--heute", default="", help="nur fuer Tests: YYYY-MM-DD")
    ap.add_argument("--trocken", action="store_true", help="nichts loeschen, nur melden")
    a = ap.parse_args(argv)

    heute = date.fromisoformat(a.heute) if a.heute else date.today()
    grenze_alt = (heute - timedelta(days=a.max_tage)).isoformat()
    grenze_frisch = (heute - timedelta(days=a.min_tage)).isoformat()

    nach_verweis = os.environ.get("MEDIEN_NACH_VERWEIS", "1") != "0"
    text, grund = (None, "MEDIEN_NACH_VERWEIS=0") if not nach_verweis else \
        verweis_text(Path(a.basis), a.min_karten)

    ordner = Path(a.cards)
    if not ordner.is_dir():
        print(f"medien_aufraeumen: {ordner} fehlt - nichts zu tun.")
        return 0

    behalten = weg_alt = weg_verweis = 0
    mb_weg = 0.0
    for f in sorted(ordner.iterdir()):
        if not f.is_file():
            continue
        m = DATUM_RE.match(f.name)
        if not m:
            behalten += 1          # ohne Datum: nie anfassen
            continue
        d = m.group(1)
        if d < grenze_alt:
            grund_weg = "alt"
        elif d >= grenze_frisch or text is None or f.stem in text:
            behalten += 1
            continue
        else:
            grund_weg = "verweis"
        mb_weg += f.stat().st_size / 1e6
        if grund_weg == "alt":
            weg_alt += 1
        else:
            weg_verweis += 1
        if not a.trocken:
            f.unlink()

    modus = "nach Verweis" if text is not None else f"nur Alter ({grund})"
    print(f"medien_aufraeumen [{modus}{', trocken' if a.trocken else ''}]: "
          f"behalten {behalten}, weg {weg_alt} alt + {weg_verweis} ohne Verweis "
          f"({mb_weg:.0f} MB); Verweise: {grund}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
