#!/usr/bin/env python3
"""Meldungsbilder ins Medien-Repo spiegeln (28.09.26, Auftrag 10 Punkt 3, Daniel).

Jedes Meldungsbild (Feld `image` in news.json/archive.json) wird einmal geladen und als
WebP abgelegt:
  <ziel>/640/<hash>.webp   Startseite, Karten           -> Feld image_local
  <ziel>/1600/<hash>.webp  Dossiers, Artikel-Hintergrund -> Feld image_local_gross
Dateiname = sha1 der Original-URL (stabil, unabhaengig von story_id). Bereits vorhandene
Dateien werden nicht neu geladen. Die Seiten nutzen image_local, sonst das Original.
So bleiben Bilder fuers Archiv und die Dossiers erhalten, wenn die Quelle sie loescht.

Platz (GitHub Pages: max. 1 GB je Site): 640 px bleibt dauerhaft, 1600 px wird nach
GROSS_TAGE Tagen geloescht (Env BILDER_GROSS_TAGE, 0 = nie). Das Skript meldet die Groesse.

Aufruf: python3 bilder_spiegel.py --ziel /tmp/ki_news_media/bilder [--basis URL] [--max N] [--dry-run]
Braucht Pillow (mit WebP). Fehler an einzelnen Bildern sind egal: dann bleibt das Original.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
BASIS_URL = "https://dscampy.github.io/ki_news_media/bilder"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MAX_BYTES = 15_000_000
GROESSEN = {"640": 640, "1600": 1600}
QUALITAET = {"640": 72, "1600": 78}


def schluessel(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def lade(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        daten = r.read(MAX_BYTES + 1)
    if len(daten) > MAX_BYTES:
        raise ValueError("zu gross")
    return daten


def spiegeln(url, ziel):
    """Legt beide Groessen an; True wenn danach die 640er-Datei existiert."""
    from PIL import Image
    h = schluessel(url)
    fehlt = [g for g in GROESSEN if not (ziel / g / f"{h}.webp").exists()]
    if not fehlt:
        return True
    try:
        bild = Image.open(io.BytesIO(lade(url)))
        bild.load()
    except Exception:
        return (ziel / "640" / f"{h}.webp").exists()
    if bild.mode not in ("RGB", "RGBA"):
        bild = bild.convert("RGBA" if "A" in bild.getbands() else "RGB")
    for g in fehlt:
        breite = GROESSEN[g]
        kopie = bild.copy()
        if kopie.width > breite:
            kopie = kopie.resize((breite, max(1, round(kopie.height * breite / kopie.width))), Image.LANCZOS)
        (ziel / g).mkdir(parents=True, exist_ok=True)
        kopie.save(ziel / g / f"{h}.webp", "WEBP", quality=QUALITAET[g], method=4)
    return True


def lade_index(ziel):
    # Datum der ersten Spiegelung je Hash; Dateidaten taugen nicht (git clone setzt alle neu)
    try:
        return json.loads((ziel / "index.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def aufraeumen(ziel, tage, index):
    if tage <= 0:
        return 0
    grenze = time.strftime("%Y-%m-%d", time.gmtime(time.time() - tage * 86400))
    weg = 0
    for f in (ziel / "1600").glob("*.webp"):
        if index.get(f.stem, "9999") < grenze:
            f.unlink()
            weg += 1
    return weg


def groesse_mb(ziel):
    return sum(f.stat().st_size for f in ziel.rglob("*.webp")) / 1048576


def eintragen(eintraege, ziel, basis):
    n = 0
    for a in eintraege:
        url = a.get("image") if isinstance(a, dict) else None
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        h = schluessel(url)
        if (ziel / "640" / f"{h}.webp").exists():
            neu = f"{basis}/640/{h}.webp"
            gross = f"{basis}/1600/{h}.webp" if (ziel / "1600" / f"{h}.webp").exists() else ""
            if a.get("image_local") != neu or a.get("image_local_gross", "") != gross:
                a["image_local"] = neu
                if gross:
                    a["image_local_gross"] = gross
                else:
                    a.pop("image_local_gross", None)
                n += 1
    return n


def schreibe(pfad, daten):
    roh = pfad.read_text(encoding="utf-8")
    einrueckung = 2 if roh.lstrip().startswith(("{\n  ", "[\n  ")) else None
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=einrueckung)
                    + ("\n" if roh.endswith("\n") else ""), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ziel", required=True)
    ap.add_argument("--basis", default=BASIS_URL)
    ap.add_argument("--max", type=int, default=400, help="hoechstens N neue Bilder je Lauf")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ziel = Path(a.ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    news_pfad, archiv_pfad = BASE / "news.json", BASE / "archive.json"
    news = json.loads(news_pfad.read_text(encoding="utf-8"))
    archiv = json.loads(archiv_pfad.read_text(encoding="utf-8")) if archiv_pfad.exists() else []
    alle = list(news.get("news") or []) + list(archiv)
    urls = list(dict.fromkeys(x["image"] for x in alle if isinstance(x, dict)
                              and isinstance(x.get("image"), str) and x["image"].startswith("https://")))
    offen = [u for u in urls if not (ziel / "640" / f"{schluessel(u)}.webp").exists()][: a.max]
    print(f"bilder_spiegel: {len(urls)} Bilder, {len(offen)} neu zu laden")
    if a.dry_run:
        return 0
    index = lade_index(ziel)
    with ThreadPoolExecutor(8) as pool:
        ergebnisse = list(pool.map(lambda u: spiegeln(u, ziel), offen))
    ok = sum(ergebnisse)
    heute = time.strftime("%Y-%m-%d", time.gmtime())
    for f in (ziel / "640").glob("*.webp"):
        index.setdefault(f.stem, heute)
    weg = aufraeumen(ziel, int(os.environ.get("BILDER_GROSS_TAGE", "60")), index)
    (ziel / "index.json").write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
    n_news = eintragen(news.get("news") or [], ziel, a.basis)
    n_arch = eintragen(archiv, ziel, a.basis)
    if n_news:
        schreibe(news_pfad, news)
    if n_arch:
        schreibe(archiv_pfad, archiv)
    mb = groesse_mb(ziel)
    print(f"bilder_spiegel: {ok}/{len(offen)} neu gespiegelt, {weg} alte 1600er geloescht, "
          f"image_local gesetzt: news {n_news}, archiv {n_arch}, Ordner {mb:.0f} MB")
    if mb > 700:
        print(f"::warning::Bilder-Spiegel {mb:.0f} MB - GitHub Pages erlaubt 1 GB je Site. BILDER_GROSS_TAGE senken.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
