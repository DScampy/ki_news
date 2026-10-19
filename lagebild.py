#!/usr/bin/env python3
"""Taegliches Lagebild per Telegram (19.10.26, Idee "automatisches Lagebild", Daniel).

Misst die letzten 24 Stunden und schickt eine kurze Nachricht an Daniels Telegram-Chat:
Laeufe (gruen/rot/von der Doppellauf-Sperre uebersprungen), Medien-Repo-Platz, Karten
(neu, doppelte Links, Stufe-3-Treffer, Wort-Sync), Uebersetzer-Quote je Modell, Umlaut-
Umschrift in neuen Meldungen, Gedaechtnis der Link-/Telegram-Sperre. Auffaelligkeiten
stehen oben mit Warnzeichen. Alles, was heute von Hand gemessen wurde, kommt so jeden
Morgen von allein.

Quellen: Dateien im Repo (ki_news.log, news.json, cards.json, card_state.json,
telegram_state.json) und die GitHub-API (Laeufe, Jobs, Job-Logs). API ueber GITHUB_TOKEN
(Workflow) oder, lokal, ueber die angemeldete GitHub-CLI (gh). Jede Messung ist einzeln
abgesichert: faellt eine aus, steht dort "n/a", die Nachricht kommt trotzdem.

Aufruf: python3 lagebild.py [--basis DIR] [--trocken] [--stunden 24]
  --trocken: nur ausgeben, nichts senden. Ohne TELEGRAM_TOKEN wird ebenfalls nur ausgegeben.
"""
import argparse
import collections
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = os.environ.get("GITHUB_REPOSITORY", "DScampy/ki_news")
WORKFLOW = "ki_news.yml"

# Schwellen fuer Warnungen
WARN_SITE_MB = 800
WARN_UMLAUT_PROZENT = 5
WARN_WORTSYNC_PROZENT = 70
WARN_UEBERSETZER_FEHLER_PROZENT = 40
WARN_STUNDEN_OHNE_LAUF = 8

UMSCHRIFT_RE = re.compile(r"\b\w*(fuer|ueber|koenn|moeg|veroeffentl|waehr|fuehr|gruend|geraet|staerk|naechst)\w*",
                          re.I)


# ---------------------------------------------------------------- GitHub-API
class _OhneUmleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _api_roh(pfad):
    """GET auf api.github.com/repos/REPO/<pfad>; liefert Bytes. Folgt Umleitungen OHNE Token
    (Job-Logs liegen auf einem Blob-Speicher, der den Authorization-Header ablehnt)."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    url = f"https://api.github.com/repos/{REPO}/{pfad}"
    if not token:
        gh = os.environ.get("GH_EXE", "gh")
        extra = ["--allow-escape-sequences"] if pfad.endswith("/logs") else []
        r = subprocess.run([gh, "api", *extra, f"repos/{REPO}/{pfad}"], capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"gh api {pfad}: {r.stderr[:200]!r}")
        return r.stdout
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "Accept": "application/vnd.github+json",
                                               "User-Agent": "ki-news-lagebild"})
    opener = urllib.request.build_opener(_OhneUmleitung)
    try:
        return opener.open(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return urllib.request.urlopen(e.headers["Location"], timeout=120).read()
        raise


def _api(pfad):
    return json.loads(_api_roh(pfad))


def _zeit(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- Messungen
def laeufe(seit):
    """Laeufe des Haupt-Workflows im Fenster + Text aller Job-Logs (fuer die Log-Zaehler)."""
    runs = _api(f"actions/workflows/{WORKFLOW}/runs?per_page=30")["workflow_runs"]
    runs = [r for r in runs if _zeit(r["created_at"]) >= seit]
    erg = {"gesamt": len(runs), "gruen": 0, "rot": 0, "uebersprungen": 0, "laufend": 0,
           "rote_nummern": [], "letzter_build": None}
    logs = []
    for r in runs:
        if r["status"] != "completed":
            erg["laufend"] += 1
            continue
        jobs = _api(f"actions/runs/{r['id']}/jobs")["jobs"]
        build = [j for j in jobs if j["name"] == "build"]
        if build and build[0].get("conclusion") == "skipped":
            erg["uebersprungen"] += 1
        elif r["conclusion"] == "success":
            erg["gruen"] += 1
            ende = _zeit(r["updated_at"])
            if not erg["letzter_build"] or ende > erg["letzter_build"]:
                erg["letzter_build"] = ende
        else:
            erg["rot"] += 1
            erg["rote_nummern"].append(r["run_number"])
        for j in jobs:
            if j.get("conclusion") in ("success", "failure"):
                try:
                    logs.append(_api_roh(f"actions/jobs/{j['id']}/logs").decode("utf-8", "replace"))
                except Exception:
                    pass
    return erg, "\n".join(logs)


def log_zaehler(text):
    return {
        "wortsync_ok": len(re.findall(r"✓ Wort-Sync:", text)),
        "wortsync_aus": len(re.findall(r"\[INFO\] Wort-Sync:", text)),
        "dublette": len(re.findall(r"\[DUBLETTE-JEV (?:schatten|skip) p=", text)),
        "deckung_ok": len(re.findall(r"JEV-DECKUNG ok", text)),
        "deckung_nein": len(re.findall(r"JEV-DECKUNG nicht bestanden", text)),
        "sperre": len(re.findall(r"Doppellauf-Sperre: laufen=false", text)),
        "medien_weg_mb": sum(int(x) for x in re.findall(r"medien_aufraeumen \[.*?\((\d+) MB\)", text)),
    }


def site_mb(log, seit):
    # Die bilder_spiegel-Zeile hat keinen eigenen Zeitstempel -> letzter Zeitstempel davor zaehlt
    werte, letzte_zeit = [], ""
    for z in log.splitlines():
        t = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", z)
        if t:
            letzte_zeit = t.group(1)
        m = re.search(r"Site gesamt (\d+) MB", z)
        if m:
            werte.append((letzte_zeit, int(m.group(1))))
    if not werte:
        return None, None
    jetzt = werte[-1][1]
    grenze = seit.strftime("%Y-%m-%d %H:%M:%S")
    vorher = [w for ts, w in werte if ts and ts < grenze]
    return jetzt, (jetzt - vorher[-1]) if vorher else None


def uebersetzer(log, seit):
    grenze = seit.strftime("%Y-%m-%d %H:%M:%S")
    ok, fehler = collections.Counter(), collections.Counter()
    for z in log.splitlines():
        t = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", z)
        if not t or t.group(1) < grenze:
            continue
        m = re.search(r"Batch \d+ OK mit (\S+)", z)
        if m:
            ok[m.group(1)] += 1
        m = re.search(r"Batch \d+(?: mit|:) (\S+)", z)
        if m and ("fehlgeschlagen" in z or "429" in z):
            fehler[m.group(1)] += 1
    return ok, fehler


def kurzname(modell):
    n = modell.split("/")[-1].split(":")[0]
    for alt, neu in (("nemotron-3-ultra", "ultra"), ("llama-3.3-70b", "llama"), ("gemini", "gemini"),
                     ("nemotron-3-super", "super"), ("deepseek", "deepseek"), ("gemma", "gemma")):
        if alt in n:
            return neu
    return n[:14]


def umlaute(news, seit):
    neu = [i for i in news if (i.get("first_seen") or i.get("date") or "") >= seit.strftime("%Y-%m-%d")]
    schlecht = [i for i in neu if UMSCHRIFT_RE.search((i.get("title") or "") + " " + (i.get("summary") or ""))]
    return len(neu), len(schlecht)


def karten(cards, seit):
    tage = {seit.strftime("%Y-%m-%d"), datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    neu = [k for k in cards if (k.get("date") or "")[:10] in tage]
    neu_ids = {k.get("id") for k in neu}
    links = collections.defaultdict(set)
    for k in cards:
        for l in k.get("links") or []:
            u = l if isinstance(l, str) else (l.get("url") or "")
            if u:
                links[u].add(k.get("id"))
    # nur neue Vorfaelle: mindestens eine der Karten ist im Fenster entstanden
    doppelt = [u for u, ids in links.items() if len(ids) > 1 and ids & neu_ids]
    return len(neu), doppelt


# ---------------------------------------------------------------- Nachricht
def bauen(basis: Path, stunden: int):
    jetzt = datetime.now(timezone.utc)
    seit = jetzt - timedelta(hours=stunden)
    warn, zeilen = [], []

    def lade(name, default):
        try:
            return json.loads((basis / name).read_text(encoding="utf-8"))
        except Exception:
            return default

    log = ""
    try:
        log = (basis / "ki_news.log").read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Laeufe + Job-Logs
    try:
        l, jobtext = laeufe(seit)
        z = log_zaehler(jobtext)
        zeile = f"Läufe: {l['gruen']} ✓ · {l['rot']} ✗"
        if l["uebersprungen"]:
            zeile += f" · {l['uebersprungen']} übersprungen (Doppellauf-Sperre)"
        if l["laufend"]:
            zeile += f" · {l['laufend']} läuft"
        zeilen.append(zeile)
        if l["rot"]:
            warn.append(f"Rote Läufe: #{', #'.join(map(str, l['rote_nummern']))}")
        if l["letzter_build"]:
            h = (jetzt - l["letzter_build"]).total_seconds() / 3600
            if h > WARN_STUNDEN_OHNE_LAUF:
                warn.append(f"Letzter erfolgreicher Lauf vor {h:.0f} h")
        elif l["gesamt"] == 0:
            warn.append(f"Kein Lauf in {stunden} h")
    except Exception as e:
        z = None
        zeilen.append(f"Läufe: n/a ({e.__class__.__name__})")

    # Medien-Repo
    try:
        mb, delta = site_mb(log, seit)
        if mb is None:
            zeilen.append("Medien-Repo: n/a")
        else:
            d = f" ({delta:+d} MB)" if delta is not None else ""
            weg = f", aufgeräumt {z['medien_weg_mb']} MB" if z and z["medien_weg_mb"] else ""
            zeilen.append(f"Medien-Repo: {mb} von 1024 MB{d}{weg}")
            if mb > WARN_SITE_MB:
                warn.append(f"Medien-Repo {mb} MB (Grenze 1024)")
    except Exception as e:
        zeilen.append(f"Medien-Repo: n/a ({e.__class__.__name__})")

    # Karten
    try:
        cards = lade("cards.json", [])
        n_neu, doppelt = karten(cards, seit)
        zeile = f"Karten: {n_neu} neu · doppelte Links {len(doppelt)}"
        if z:
            zeile += f" · Stufe 3: {z['dublette']} Treffer"
        zeilen.append(zeile)
        if doppelt:
            warn.append(f"{len(doppelt)} Link(s) mit zwei Karten")
        if z and (z["wortsync_ok"] + z["wortsync_aus"]):
            gesamt = z["wortsync_ok"] + z["wortsync_aus"]
            pz = 100 * z["wortsync_ok"] / gesamt
            zeilen.append(f"Wort-Sync: {z['wortsync_ok']} von {gesamt} Karten ({pz:.0f} %)")
            if pz < WARN_WORTSYNC_PROZENT:
                warn.append(f"Wort-Sync nur {pz:.0f} %")
        if z and (z["deckung_ok"] + z["deckung_nein"]):
            g = z["deckung_ok"] + z["deckung_nein"]
            zeilen.append(f"Einordnung (Jev-Deckung): {z['deckung_ok']} von {g} Versuchen bestanden")
    except Exception as e:
        zeilen.append(f"Karten: n/a ({e.__class__.__name__})")

    # Uebersetzer
    try:
        ok, fehler = uebersetzer(log, seit)
        if ok or fehler:
            teile = []
            for m in sorted(set(ok) | set(fehler), key=lambda m: -(ok[m] + fehler[m])):
                teile.append(f"{kurzname(m)} {ok[m]}/{ok[m] + fehler[m]}")
            zeilen.append("Übersetzer (OK/Versuche): " + " · ".join(teile))
            versuche = sum(ok.values()) + sum(fehler.values())
            fq = 100 * sum(fehler.values()) / versuche
            if fq > WARN_UEBERSETZER_FEHLER_PROZENT:
                warn.append(f"Übersetzer-Fehlerquote {fq:.0f} %")
        else:
            zeilen.append("Übersetzer: keine Batches im Fenster")
    except Exception as e:
        zeilen.append(f"Übersetzer: n/a ({e.__class__.__name__})")

    # Umlaute
    try:
        nj = lade("news.json", {})
        news = nj.get("news", []) if isinstance(nj, dict) else nj
        n, schlecht = umlaute(news, seit)
        if n:
            pz = 100 * schlecht / n
            zeilen.append(f"Umlaut-Umschrift: {schlecht} von {n} neuen Meldungen ({pz:.0f} %)")
            if pz > WARN_UMLAUT_PROZENT:
                warn.append(f"Umlaut-Umschrift {pz:.0f} % (fuer/koennte)")
    except Exception as e:
        zeilen.append(f"Umlaute: n/a ({e.__class__.__name__})")

    # Gedaechtnis der Sperren
    try:
        cs = lade("card_state.json", {}).get("sent_links", {})
        tg = lade("telegram_state.json", {}).get("sent_links", {})
        alt = lambda d: min(str(v)[:10] for v in d.values()) if d else "-"
        zeilen.append(f"Sperren: Karten {len(cs)} Links (ab {alt(cs)[5:]}), Telegram {len(tg)} (ab {alt(tg)[5:]})")
    except Exception as e:
        zeilen.append(f"Sperren: n/a ({e.__class__.__name__})")

    try:
        from zoneinfo import ZoneInfo
        berlin = ZoneInfo("Europe/Berlin")
    except Exception:
        berlin = timezone(timedelta(hours=1))
    kopf = f"🩺 ki-news Lagebild {jetzt.astimezone(berlin).strftime('%d.%m. %H:%M')} (letzte {stunden} h)"
    teile = [kopf]
    teile += [f"⚠️ {w}" for w in warn] or ["✅ Keine Auffälligkeiten"]
    teile += [""] + zeilen
    return "\n".join(teile), warn


def senden(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("lagebild: kein TELEGRAM_TOKEN - nur ausgegeben.")
        return False
    daten = json.dumps({"chat_id": (os.environ.get("TELEGRAM_CHAT_ID") or "9096438").strip(),
                        "text": text[:4000], "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=daten,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default=str(BASE))
    ap.add_argument("--stunden", type=int, default=24)
    ap.add_argument("--trocken", action="store_true")
    a = ap.parse_args(argv)
    text, warn = bauen(Path(a.basis), a.stunden)
    print(text)
    if not a.trocken:
        try:
            if senden(text):
                print("lagebild: gesendet.")
        except Exception as e:
            print(f"lagebild: Senden fehlgeschlagen ({e.__class__.__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
