# -*- coding: utf-8 -*-
"""
Kontaktbogen Karten alt vs. neu (Auftrag 6, 28.09.2026).

Nimmt die 12 neuesten v2-Karten aus cards.json und baut je Meldung zwei Karten-HTMLs:
  alt = Motiv und Stil wie live gerendert (Feld "karte" in cards.json)
  neu = gleiches Motiv, einer der neuen Stile (neon, typo, riso), reihum gesetzt
Danach rendert tools/karten_kontaktbogen.js Poster-PNGs (t = 6 s wie make_poster) und
einige MP4 (ohne Ton) und schreibt _vorschau/index.html.

Aendert nichts am Live-Rendering: die neuen Stile laufen nur ueber KARTEN_STIL_ZWANG
in diesem Prozess. Aufruf:  python3 tools/karten_kontaktbogen.py [--mp4 3] [--anzahl 12]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import karten_v2  # noqa: E402

AUS = ROOT / "_vorschau"


def datum_de(iso):
    j, m, t = (iso or "").split("-") if iso and iso.count("-") == 2 else ("", "", "")
    return "%s.%s.%s" % (t, m, j) if j else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anzahl", type=int, default=12)
    ap.add_argument("--mp4", type=int, default=3, help="wie viele neue Karten zusaetzlich als MP4")
    ap.add_argument("--nur-html", action="store_true")
    a = ap.parse_args()

    karten = [c for c in json.loads((ROOT / "cards.json").read_text(encoding="utf-8"))
              if str(c.get("karte", "")).startswith("v2:")][:a.anzahl]
    vorlage = (ROOT / "breaking_news_card_v2.html").read_text(encoding="utf-8")
    (AUS / "html").mkdir(parents=True, exist_ok=True)
    os.environ.pop("KARTEN_NEUE_STILE", None)
    liste = []
    for i, c in enumerate(karten):
        motiv, stil_alt = c["karte"][3:].split("/", 1)
        stil_neu = karten_v2.NEUE_STILE[i % len(karten_v2.NEUE_STILE)]
        eintrag = {"id": c["id"], "titel": c["headline"], "quelle": c.get("source", ""), "motiv": motiv,
                   "datum": c.get("date", ""), "dauer": int(c.get("duration") or 20)}
        for art, stil in (("alt", stil_alt), ("neu", stil_neu)):
            os.environ["KARTEN_STIL_ZWANG"] = stil
            k = karten_v2.karte_daten(c["headline"], c.get("einordnung", ""), "", c.get("source", ""),
                                      datum_de(c.get("date")), eintrag["dauer"], "Aktuell", motiv_vorgabe=motiv)
            html = vorlage.replace("{{KARTE_JSON}}", json.dumps(k, ensure_ascii=False).replace("</", "<\\/"))
            name = "%02d_%s.html" % (i + 1, art)
            (AUS / "html" / name).write_text(html, encoding="utf-8")
            eintrag[art] = {"stil": k["stil"], "html": "html/" + name, "png": "png/%02d_%s.png" % (i + 1, art)}
        liste.append(eintrag)
    os.environ.pop("KARTEN_STIL_ZWANG", None)
    # MP4: je neuem Stil die erste Karte
    gesehen = set()
    for e in liste:
        if len(gesehen) >= a.mp4:
            break
        if e["neu"]["stil"] not in gesehen:
            gesehen.add(e["neu"]["stil"])
            e["neu"]["mp4"] = "mp4/%s_%s.mp4" % (e["id"][:40], e["neu"]["stil"])
    (AUS / "kontaktbogen.json").write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  %d Meldungen vorbereitet -> %s" % (len(liste), AUS / "kontaktbogen.json"))
    if a.nur_html:
        return 0
    return subprocess.call(["node", str(ROOT / "tools" / "karten_kontaktbogen.js"), str(AUS)])


if __name__ == "__main__":
    sys.exit(main())
