#!/usr/bin/env python3
"""Morgenlage zum Hoeren (20.10.26, Daniel): die fuenf Meldungen der Morgenlage als
gesprochene Folge von etwa 90 Sekunden.

Ablauf (gesteuert von .github/workflows/morgenlage_audio.yml):
  1. Morgenlage aus news.json lesen (briefing, von ki_news.py einmal am Tag eingefroren).
  2. Sprechtext aus fester Vorlage bauen: Begruessung, je Meldung Titel plus Zusammenfassung,
     Abschied. Bewusst KEIN Sprachmodell: es wird nur vorgelesen, was schon auf der Seite
     steht, also kann nichts dazuerfunden werden.
  3. Google-TTS mit der Studio-Stimme der Karten (de-DE-Studio-C), dieselbe Aussprache-
     Aufbereitung (build_tts_ssml aus generate_news_cards.py).
  4. Ausgabe: <out>/morgenlage-YYYY-MM-DD.mp3 und .txt (Sprechtext). Mit ffmpeg wird jeder
     Abschnitt einzeln gesprochen und zusammengesetzt (21.10.26, fuer "Die 5 des Tages"): dann
     steht in <out>/morgenlage-YYYY-MM-DD.json, wann welche Meldung beginnt (Zeitmarken im SSML
     gehen mit Studio-Stimmen nicht, Test 19.10.26). Ohne ffmpeg: ein Aufruf, kein JSON.
  5. --feed: Folge oben in morgenlage.xml (Podcast-RSS) eintragen, max. FEED_MAX Folgen.
  6. --senden: MP3 per Telegram sendAudio an MORGENLAGE_CHAT_ID (Standard: Daniels Chat).

Exit-Codes: 0 = fertig, 2 = Fehler (Workflow wird rot, Tagesmarke bleibt frei),
            3 = nichts zu tun (Morgenlage nicht von heute) - kein Fehler.

Lokal testen (ohne Schluessel nur Text):
  python morgenlage_audio.py --basis . --egal-datum --out out
Kill-Switch: Workflow "Morgenlage zum Hoeren" im Actions-Tab deaktivieren.
"""

import argparse
import base64
import email.utils
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_news_cards as karten  # noqa: E402  (build_tts_ssml, GOOGLE_TTS_VOICES)

try:
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:                  # Windows ohne tzdata: lokale Zeit reicht zum Testen
    BERLIN = None
STIMME = "de-DE-Studio-C"          # Studio-B ist noch nicht abgehoert (offen seit 16.07.)
SPRECH_TEMPO = 1.12                # Karten: 1.18 - fuer 90 s am Stueck etwas ruhiger
PAUSE_MS = 650                     # Pause zwischen den Meldungen
MAX_WOERTER_ZUSAMMENFASSUNG = 40   # laengere Zusammenfassungen am Satzende kappen
FEED_MAX = 30                      # so viele Folgen bleiben im Feed (und als Release-Datei)
SITE = "https://ki-news.live"
REPO = "DScampy/ki_news"
RELEASE_TAG = "morgenlage"
FEED_DATEI = "morgenlage.xml"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
ORDNUNG = ["Erstens", "Zweitens", "Drittens", "Viertens", "Fünftens", "Sechstens"]
ZAHLWORT = {1: "Eine Meldung", 2: "Zwei Meldungen", 3: "Drei Meldungen",
            4: "Vier Meldungen", 5: "Fünf Meldungen", 6: "Sechs Meldungen"}
# "KI" wird von build_tts_ssml buchstabiert, "ki-news.live" klein geschrieben dagegen nicht
SEITE_GESPROCHEN = "KI News Punkt Live"


# ─── Text ─────────────────────────────────────────────────────────────────────

def _woerter(text):
    return {w for w in re.findall(r"[a-zäöüß0-9]{4,}", text.lower())}


def _satzende(text):
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _kappen(text, max_woerter=MAX_WOERTER_ZUSAMMENFASSUNG):
    """Ganze Saetze behalten, bis max_woerter erreicht sind (mindestens einen)."""
    saetze = re.split(r"(?<=[.!?])\s+", text.strip())
    raus, n = [], 0
    for s in saetze:
        w = len(s.split())
        if raus and n + w > max_woerter:
            break
        raus.append(s)
        n += w
    return " ".join(raus)


def wiederholt_titel(titel, zusammenfassung):
    """True, wenn die Zusammenfassung den Titel nur ausfuehrlicher nacherzaehlt (kommt oft
    vor: 'DHS ordnet an ...' / 'Das Department of Homeland Security ordnet an ...'). Dann
    wird nur die Zusammenfassung gesprochen, sonst hoert man dieselbe Meldung zweimal."""
    tw = _woerter(titel)
    return bool(tw) and len(tw & _woerter(zusammenfassung)) / len(tw) >= 0.5


def datum_gesprochen(tag):
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE[tag.month - 1]}"


def abschnitte(briefing, news):
    """Liste der Sprech-Abschnitte (Klartext). Zwischen den Abschnitten kommt eine Pause."""
    tag = datetime.strptime(briefing["datum"], "%Y-%m-%d").date()
    nach_link = {n.get("link"): n for n in news if n.get("link")}
    storys = briefing.get("stories") or []
    teile = [f"Guten Morgen. Hier ist die Morgenlage von {SEITE_GESPROCHEN}, "
             f"für {datum_gesprochen(tag)}. {ZAHLWORT.get(len(storys), f'{len(storys)} Meldungen')}."]
    for i, s in enumerate(storys):
        titel = _satzende(s.get("title", ""))
        zf = _satzende(_kappen((nach_link.get(s.get("link")) or {}).get("summary", "") or ""))
        if not zf:
            inhalt = titel
        elif wiederholt_titel(titel, zf):
            inhalt = zf
        else:
            inhalt = f"{titel} {zf}"
        teile.append(f"{ORDNUNG[i] if i < len(ORDNUNG) else 'Und'}. {inhalt}")
    teile.append(f"Alle Quellen findest du auf {SEITE_GESPROCHEN}. Bis morgen.")
    return teile


def ssml(teile):
    innen = [karten.build_tts_ssml(t)[len("<speak>"):-len("</speak>")] for t in teile]
    return "<speak>" + f'<break time="{PAUSE_MS}ms"/>'.join(innen) + "</speak>"


# ─── Audio ────────────────────────────────────────────────────────────────────

def sprechen(ssml_text, ziel: Path):
    key = os.environ.get("GOOGLE_TTS_KEY", "").strip()
    if not key:
        print("morgenlage: kein GOOGLE_TTS_KEY - nur Text.")
        return False
    geschlecht = dict(karten.GOOGLE_TTS_VOICES).get(STIMME, "FEMALE")
    daten = json.dumps({
        "input": {"ssml": ssml_text},
        "voice": {"languageCode": "de-DE", "name": STIMME, "ssmlGender": geschlecht},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": SPRECH_TEMPO},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
        data=daten, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            ziel.write_bytes(base64.b64decode(json.loads(r.read())["audioContent"]))
        return True
    except urllib.error.HTTPError as e:
        print(f"morgenlage: TTS HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except Exception as e:
        print(f"morgenlage: TTS Fehler: {e}")
    return False


def _ffmpeg_da():
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def sprechen_teile(teile, ziel: Path, arbeit: Path):
    """Jeden Abschnitt einzeln sprechen, mit PAUSE_MS Stille dazwischen zusammensetzen.
    Gibt [(start, ende), ...] je Abschnitt zurueck oder None (dann einteilig sprechen)."""
    if not _ffmpeg_da():
        print("morgenlage: kein ffmpeg - einteilig, ohne Zeiten.")
        return None
    arbeit.mkdir(parents=True, exist_ok=True)
    stille = arbeit / "stille.mp3"
    teil_pfade = []
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{PAUSE_MS / 1000:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "64k", str(stille)], check=True, timeout=60)
        for i, t in enumerate(teile):
            tp = arbeit / f"teil{i:02d}.mp3"
            if not sprechen(karten.build_tts_ssml(t), tp):
                return None
            teil_pfade.append(tp)
        liste = arbeit / "liste.txt"
        zeilen = []
        for i, tp in enumerate(teil_pfade):
            if i:
                zeilen.append(f"file '{stille.resolve().as_posix()}'")
            zeilen.append(f"file '{tp.resolve().as_posix()}'")
        liste.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(liste), "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "24000",
                        "-ac", "1", str(ziel)], check=True, timeout=120)
    except Exception as e:
        print(f"morgenlage: Zusammensetzen fehlgeschlagen ({e}) - einteilig.")
        return None
    pause = dauer_sekunden(stille)
    zeiten, t = [], 0.0
    for i, tp in enumerate(teil_pfade):
        if i:
            t += pause
        d = dauer_sekunden(tp)
        zeiten.append((round(t, 3), round(t + d, 3)))
        t += d
    return zeiten


def zeiten_json(briefing, news, teile, zeiten, gesamt):
    """Ablauf fuer das Video: wann welche Meldung laeuft, was angezeigt wird."""
    nach_link = {n.get("link"): n for n in news if n.get("link")}
    storys = briefing.get("stories") or []
    seg = [{"art": "intro", "start": zeiten[0][0], "ende": zeiten[0][1]}]
    for i, s in enumerate(storys):
        n = nach_link.get(s.get("link")) or {}
        zf = _kappen(n.get("summary", "") or "")
        bild = n.get("image_local_gross") or n.get("image_local") or ""
        seg.append({
            "art": "meldung", "nr": i + 1,
            "start": zeiten[i + 1][0], "ende": zeiten[i + 1][1],
            "titel": s.get("title", ""),
            "text": "" if wiederholt_titel(s.get("title", ""), zf) and len(zf) < 90 else zf,
            "quelle": s.get("source", ""), "link": s.get("link", ""),
            # nur eigene Kopien aus dem Medien-Repo, nie Fremd-URLs direkt
            "bild": bild if bild.startswith("https://dscampy.github.io/") else "",
        })
    seg.append({"art": "outro", "start": zeiten[-1][0], "ende": zeiten[-1][1]})
    tag = datetime.strptime(briefing["datum"], "%Y-%m-%d").date()
    return {"datum": briefing["datum"], "datum_text": datum_gesprochen(tag),
            "datum_kurz": tag.strftime("%d.%m."), "dauer": round(gesamt, 3),
            "segmente": seg, "sprechtext": teile}


def dauer_sekunden(mp3: Path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(mp3)], capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip())
    except Exception:
        # Kein ffprobe auf dem Runner (ubuntu-24.04, 20.10. gemessen). Google liefert MP3 mit
        # konstanter Bitrate, am 20.10. gemessen 64 kbit/s bei 24 kHz (588 KB = 73,6 s).
        return mp3.stat().st_size * 8 / 64000


def mmss(sek):
    sek = int(round(sek))
    return f"{sek // 60}:{sek % 60:02d}"


# ─── Feed ─────────────────────────────────────────────────────────────────────

def _item(briefing, mp3_name, groesse, sek, jetzt):
    tag = datetime.strptime(briefing["datum"], "%Y-%m-%d").date()
    titel = f"Morgenlage {tag.strftime('%d.%m.%Y')}"
    zeilen = "".join(
        f'<li><a href="{html.escape(s.get("link", ""))}">{html.escape(s.get("title", ""))}</a>'
        f' ({html.escape(s.get("source", ""))})</li>'
        for s in briefing.get("stories") or [])
    url = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{mp3_name}"
    return (
        "    <item>\n"
        f"      <title>{html.escape(titel)}</title>\n"
        f"      <guid isPermaLink=\"false\">ki-news-morgenlage-{briefing['datum']}</guid>\n"
        f"      <pubDate>{email.utils.format_datetime(jetzt)}</pubDate>\n"
        f"      <link>{SITE}/</link>\n"
        f"      <description><![CDATA[<ol>{zeilen}</ol>]]></description>\n"
        f"      <enclosure url=\"{url}\" length=\"{groesse}\" type=\"audio/mpeg\"/>\n"
        f"      <itunes:duration>{int(round(sek))}</itunes:duration>\n"
        "      <itunes:explicit>false</itunes:explicit>\n"
        "    </item>\n"
    )


KOPF = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>ki-news.live Morgenlage</title>
    <link>https://ki-news.live/</link>
    <atom:link href="https://ki-news.live/morgenlage.xml" rel="self" type="application/rss+xml"/>
    <description>Die fünf wichtigsten KI-Meldungen des Morgens in etwa 90 Sekunden. Automatisch aus der Morgenlage von ki-news.live, gesprochen mit einer Google-Studio-Stimme.</description>
    <language>de-DE</language>
    <itunes:author>ki-news.live</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Technology"/>
"""
FUSS = "  </channel>\n</rss>\n"


def feed_eintragen(feed: Path, briefing, mp3: Path, sek):
    """Neue Folge oben einsetzen. Gleiches Datum ersetzt die alte Fassung (Wiederholungslauf)."""
    alt = feed.read_text(encoding="utf-8") if feed.exists() else ""
    items = re.findall(r"    <item>\n.*?    </item>\n", alt, flags=re.S)
    guid = f"ki-news-morgenlage-{briefing['datum']}"
    items = [i for i in items if guid not in i]
    neu = _item(briefing, mp3.name, mp3.stat().st_size, sek, datetime.now(timezone.utc))
    items = [neu] + items[:FEED_MAX - 1]
    feed.write_text(KOPF + "".join(items) + FUSS, encoding="utf-8", newline="\n")
    print(f"morgenlage: Feed {feed.name} mit {len(items)} Folgen geschrieben.")
    return [re.search(r'/download/[^/]+/([^"]+)"', i).group(1) for i in items]


# ─── Telegram ─────────────────────────────────────────────────────────────────

def senden(mp3: Path, titel, beschriftung):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("morgenlage: kein TELEGRAM_TOKEN - nicht gesendet.")
        return False
    chat = (os.environ.get("MORGENLAGE_CHAT_ID") or "9096438").strip()
    grenze = uuid.uuid4().hex
    felder = {"chat_id": chat, "title": titel, "performer": "ki-news.live", "caption": beschriftung}
    koerper = b""
    for k, v in felder.items():
        koerper += (f"--{grenze}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                    f"{v}\r\n").encode("utf-8")
    koerper += (f"--{grenze}\r\nContent-Disposition: form-data; name=\"audio\"; "
                f"filename=\"{mp3.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode("utf-8")
    koerper += mp3.read_bytes() + f"\r\n--{grenze}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendAudio", data=koerper,
        headers={"Content-Type": f"multipart/form-data; boundary={grenze}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ok = json.loads(r.read()).get("ok")
        print(f"morgenlage: Telegram sendAudio ok={ok}")
        return bool(ok)
    except urllib.error.HTTPError as e:
        print(f"morgenlage: Telegram HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception as e:
        print(f"morgenlage: Telegram Fehler: {e}")
    return False


# ─── Ablauf ───────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default=".", help="Ordner mit news.json (und morgenlage.xml)")
    ap.add_argument("--out", default="out", help="Zielordner fuer MP3 und Text")
    ap.add_argument("--egal-datum", action="store_true", help="auch eine Morgenlage von gestern vertonen")
    ap.add_argument("--feed", action="store_true", help="Folge in morgenlage.xml eintragen")
    ap.add_argument("--senden", action="store_true",
                    help="nur senden: die schon erzeugte MP3 aus --out per Telegram schicken")
    a = ap.parse_args(argv)

    basis, out = Path(a.basis), Path(a.out)
    daten = json.loads((basis / "news.json").read_text(encoding="utf-8"))
    briefing = daten.get("briefing") or {}
    heute = (datetime.now(BERLIN) if BERLIN else datetime.now().astimezone()).strftime("%Y-%m-%d")
    if not briefing.get("stories"):
        print("morgenlage: keine Morgenlage in news.json.")
        return 3
    if briefing.get("datum") != heute and not a.egal_datum:
        print(f"morgenlage: Morgenlage ist vom {briefing.get('datum')}, heute ist {heute} - nichts zu tun.")
        return 3

    name = f"morgenlage-{briefing['datum']}"
    mp3 = out / f"{name}.mp3"
    tag = datetime.strptime(briefing["datum"], "%Y-%m-%d").date()

    if a.senden:
        # Eigener Schritt NACH Release-Upload und Feed-Commit (Workflow): erst wenn die
        # Folge oeffentlich liegt, geht sie raus.
        if not mp3.exists():
            print(f"morgenlage: {mp3} fehlt - nichts zu senden.")
            return 2
        titel = f"Morgenlage {tag.strftime('%d.%m.')}"
        beschriftung = (f"{titel} · {len(briefing['stories'])} Meldungen · "
                        f"{mmss(dauer_sekunden(mp3))} min\n{SITE}/{FEED_DATEI}")
        return 0 if senden(mp3, titel, beschriftung) else 2

    teile = abschnitte(briefing, daten.get("news") or [])
    text = "\n\n".join(teile)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
    print(f"morgenlage: Sprechtext ({len(text.split())} Wörter, {len(text)} Zeichen):\n")
    print(text + "\n")

    zeiten = sprechen_teile(teile, mp3, out / "_teile")
    if zeiten is None and not sprechen(ssml(teile), mp3):
        return 2 if a.feed else 0
    sek = dauer_sekunden(mp3)
    print(f"morgenlage: {mp3.name} {mp3.stat().st_size // 1024} KB, {mmss(sek)} min"
          + (f", {len(zeiten)} Abschnitte mit Zeiten" if zeiten else ""))
    if zeiten:
        (out / f"{name}.json").write_text(json.dumps(
            zeiten_json(briefing, daten.get("news") or [], teile, zeiten, sek),
            ensure_ascii=False, indent=1), encoding="utf-8")

    if a.feed:
        behalten = feed_eintragen(basis / FEED_DATEI, briefing, mp3, sek)
        (out / "feed_behalten.txt").write_text("\n".join(behalten) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
