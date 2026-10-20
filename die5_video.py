#!/usr/bin/env python3
"""Die 5 des Tages (21.10.26, Daniel): die Morgenlage als Hochkant-Video 1080 x 1920.

Baut auf morgenlage_audio.py auf: dessen <out>/morgenlage-YYYY-MM-DD.json sagt, wann welche
Meldung gesprochen wird, die MP3 daneben ist die Tonspur. Die Vorlage die5_hoch.html wird mit
diesen Daten gefuellt und von record.js bildgenau aufgenommen (KI_RENDER_AT), Ton dazu.

  python die5_video.py --out out              -> out/die5-YYYY-MM-DD.mp4 (+ 3 Standbilder)
  python die5_video.py --out out --senden     -> fertiges MP4 per Telegram sendVideo

Exit-Codes: 0 = fertig, 2 = Fehler (kostet nur das Video, die Audio-Folge ist davon unberuehrt).
Kill-Switch: DIE5_VIDEO: "0" in .github/workflows/morgenlage_audio.yml.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HIER = Path(__file__).resolve().parent
VORLAGE = HIER / "die5_hoch.html"
RECORD_JS = HIER / "record.js"
BREITE, HOEHE = 420, 747          # CSS-px wie Karten v2 im Hochformat
AUS_W, AUS_H = 1080, 1920
FPS = os.environ.get("DIE5_FPS", "24")
CRF = os.environ.get("DIE5_CRF", "26")


def neuester_ablauf(out: Path):
    kandidaten = sorted(out.glob("morgenlage-????-??-??.json"))
    return kandidaten[-1] if kandidaten else None


def bauen(out: Path):
    ablauf = neuester_ablauf(out)
    if not ablauf:
        print("die5: kein morgenlage-*.json in", out, "- ohne Zeiten kein Video.")
        return None
    daten = json.loads(ablauf.read_text(encoding="utf-8"))
    mp3 = ablauf.with_suffix(".mp3")
    if not mp3.exists():
        print("die5:", mp3, "fehlt.")
        return None
    vorlage = VORLAGE.read_text(encoding="utf-8")
    if "{{DIE5_JSON}}" not in vorlage:
        print("die5: Platzhalter {{DIE5_JSON}} fehlt in der Vorlage.")
        return None
    nutz = {k: daten[k] for k in ("datum", "datum_text", "datum_kurz", "dauer", "segmente")}
    # "</" im JSON unschaedlich machen, sonst beendet ein Titel mit "</script>" den Block
    roh = json.dumps(nutz, ensure_ascii=False).replace("</", "<\\/")
    html_pfad = out / f"die5-{daten['datum']}.html"
    html_pfad.write_text(vorlage.replace("{{DIE5_JSON}}", roh), encoding="utf-8")
    mp4 = out / f"die5-{daten['datum']}.mp4"
    dauer = math.ceil(daten["dauer"] + 0.8)
    env = dict(os.environ, CARD_OUT_W=str(AUS_W), CARD_OUT_H=str(AUS_H), CARD_CRF=CRF,
               CARD_PRESET="medium", CARD_FPS=FPS)
    print(f"die5: nehme {mp4.name} auf, {dauer} s, {FPS} fps ...")
    try:
        r = subprocess.run(["node", str(RECORD_JS), str(html_pfad), str(mp4), str(BREITE), str(HOEHE),
                            str(dauer), str(mp3)], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1500)
    except Exception as e:
        print("die5: record.js nicht gelaufen:", e)
        return None
    print("\n".join(z for z in r.stdout.splitlines() if "[record.js]" in z and "FFmpeg:" not in z))
    if r.returncode != 0 or not mp4.exists():
        print("die5: record.js Fehler:\n", r.stderr[-800:])
        return None
    print(f"die5: {mp4.name} {mp4.stat().st_size // 1024} KB")
    # Standbilder zur Abnahme: Vorspann, Meldung 3, Abspann
    segs = daten["segmente"]
    zeiten = [("vorspann", 1.5), ("meldung3", segs[3]["start"] + 3.0 if len(segs) > 4 else 10),
              ("abspann", segs[-1]["start"] + 1.5)]
    for name, t in zeiten:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(mp4),
                        "-frames:v", "1", "-vf", "scale=540:-1", str(out / f"die5-standbild-{name}.jpg")],
                       timeout=60)
    return mp4


def pruefzeile(out: Path):
    """Ergebnis von die5_pruefen.py (eine Zeile), falls vorhanden."""
    try:
        return "\n" + (out / "pruefung.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def senden(mp4: Path, daten):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("die5: kein TELEGRAM_TOKEN - nicht gesendet.")
        return False
    chat = (os.environ.get("MORGENLAGE_CHAT_ID") or "9096438").strip()
    grenze = uuid.uuid4().hex
    felder = {"chat_id": chat, "width": str(AUS_W), "height": str(AUS_H), "supports_streaming": "true",
              "duration": str(int(round(daten["dauer"]))),
              "caption": f"Die 5 des Tages · {daten['datum_kurz']} · 9:16 für Reels/Shorts" + pruefzeile(mp4.parent)}
    koerper = b""
    for k, v in felder.items():
        koerper += (f"--{grenze}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    koerper += (f"--{grenze}\r\nContent-Disposition: form-data; name=\"video\"; filename=\"{mp4.name}\"\r\n"
                f"Content-Type: video/mp4\r\n\r\n").encode("utf-8")
    koerper += mp4.read_bytes() + f"\r\n--{grenze}--\r\n".encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendVideo", data=koerper,
                                 headers={"Content-Type": f"multipart/form-data; boundary={grenze}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            ok = json.loads(r.read()).get("ok")
        print(f"die5: Telegram sendVideo ok={ok}")
        return bool(ok)
    except urllib.error.HTTPError as e:
        print(f"die5: Telegram HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception as e:
        print(f"die5: Telegram Fehler: {e}")
    return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out", help="Ordner mit morgenlage-*.json/.mp3 von morgenlage_audio.py")
    ap.add_argument("--senden", action="store_true", help="nur senden: fertiges die5-*.mp4 per Telegram")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.senden:
        ablauf = neuester_ablauf(out)
        mp4 = out / f"die5-{ablauf.stem.split('-', 1)[1]}.mp4" if ablauf else None
        if not mp4 or not mp4.exists():
            print("die5: kein fertiges Video zum Senden.")
            return 2
        return 0 if senden(mp4, json.loads(ablauf.read_text(encoding="utf-8"))) else 2
    return 0 if bauen(out) else 2


if __name__ == "__main__":
    sys.exit(main())
