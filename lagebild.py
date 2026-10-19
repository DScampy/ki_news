#!/usr/bin/env python3
"""Taegliches Lagebild per Telegram (19.10.26, Idee "automatisches Lagebild", Daniel).

Misst die letzten 24 Stunden und schickt eine kurze Nachricht an Daniels Telegram-Chat:
Laeufe (gruen/rot/von der Doppellauf-Sperre uebersprungen), Medien-Repo-Platz, Karten
(neu, doppelte Links, Stufe-3-Treffer, Wort-Sync, Jev-Deckung), Uebersetzer-Quote je Modell,
Umlaut-Umschrift in neuen Meldungen, Gedaechtnis der Link-/Telegram-Sperre. Auffaelligkeiten
stehen oben mit Warnzeichen.

Quellen: Dateien im Repo (ki_news.log, news.json, cards.json, card_state.json,
telegram_state.json) und die GitHub-API (Laeufe, Jobs, Job-Logs). API ueber GITHUB_TOKEN
(Workflow) oder, lokal, ueber die angemeldete GitHub-CLI (gh). Jede Messung ist einzeln
abgesichert: faellt eine aus, steht dort "n/a", die Nachricht kommt trotzdem.

Aufruf: python3 lagebild.py [--basis DIR] [--trocken] [--stunden 24]
Exit-Code: 0 = gesendet (oder --trocken), 2 = nicht gesendet (kein Token / Fehler),
3 = Ausloeser war ein uebersprungener Lauf (Env AUSLOESER_RUN_ID) -> spaeter erneut versuchen.
Der Workflow setzt die Tagesmarke nur bei 0.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = os.environ.get("GITHUB_REPOSITORY", "DScampy/ki_news")
WORKFLOW = "ki_news.yml"
API_BUDGET_S = 150          # Gesamtzeit fuer Laeufe/Jobs/Logs, danach "n/a" und trotzdem senden

# Schwellen fuer Warnungen
WARN_SITE_MB = 800
WARN_UMLAUT_PROZENT = 5
WARN_WORTSYNC_PROZENT = 70
WARN_UEBERSETZER_FEHLER_PROZENT = 40
WARN_STUNDEN_OHNE_LAUF = 8

UMSCHRIFT_RE = re.compile(r"\b\w*(fuer|ueber|koenn|moeg|veroeffentl|waehr|fuehr|gruend|geraet|staerk|naechst)\w*",
                          re.I)
ZEIT_RE = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


# ---------------------------------------------------------------- GitHub-API
class _OhneUmleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _api_roh(pfad):
    """GET auf api.github.com/repos/REPO/<pfad>; liefert Bytes. Folgt Umleitungen OHNE Token
    (Job-Logs liegen auf einem Blob-Speicher, der den Authorization-Header ablehnt)."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        gh = os.environ.get("GH_EXE", "gh")
        extra = ["--allow-escape-sequences"] if pfad.endswith("/logs") else []
        r = subprocess.run([gh, "api", *extra, f"repos/{REPO}/{pfad}"], capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"gh api {pfad}: {r.stderr[:200]!r}")
        return r.stdout
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{pfad}",
                                 headers={"Authorization": f"Bearer {token}",
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


def _build_uebersprungen(jobs):
    b = [j for j in jobs if j["name"] == "build"]
    return bool(b) and b[0].get("conclusion") == "skipped"


# ---------------------------------------------------------------- Messungen
def laeufe(seit, frist):
    """Laeufe des Haupt-Workflows im Fenster + Job-Logs (neueste zuerst) fuer die Log-Zaehler."""
    runs = _api(f"actions/workflows/{WORKFLOW}/runs?per_page=30&branch=main")["workflow_runs"]
    runs = [r for r in runs if _zeit(r["created_at"]) >= seit]
    erg = {"gesamt": len(runs), "gruen": 0, "rot": 0, "uebersprungen": 0, "laufend": 0,
           "rote_nummern": [], "letzter_build": None, "logs_fehlen": 0}
    logs = []                       # (run_created_at, text), neueste zuerst
    for r in runs:
        if r["status"] != "completed":
            erg["laufend"] += 1
            continue
        if time.monotonic() > frist:
            erg["logs_fehlen"] += 1
            continue
        jobs = _api(f"actions/runs/{r['id']}/jobs")["jobs"]
        if _build_uebersprungen(jobs):
            erg["uebersprungen"] += 1
            continue
        if r["conclusion"] == "success":
            erg["gruen"] += 1
            ende = _zeit(r["updated_at"])
            if not erg["letzter_build"] or ende > erg["letzter_build"]:
                erg["letzter_build"] = ende
        elif r["conclusion"] != "cancelled":
            erg["rot"] += 1
            erg["rote_nummern"].append(r["run_number"])
        for j in jobs:
            if j.get("conclusion") not in ("success", "failure") or time.monotonic() > frist:
                continue
            try:
                logs.append((r["created_at"], _api_roh(f"actions/jobs/{j['id']}/logs").decode("utf-8", "replace")))
            except Exception:
                erg["logs_fehlen"] += 1
    return erg, logs


def log_zaehler(logs):
    text = "\n".join(t for _, t in logs)
    medien = [int(x) for _, t in logs for x in re.findall(r"medien_aufraeumen \[.*?\((\d+) MB\)", t)[-1:]]
    return {
        "wortsync_ok": len(re.findall(r"✓ Wort-Sync:", text)),
        "wortsync_aus": len(re.findall(r"\[INFO\] Wort-Sync:", text)),
        "dublette": len(re.findall(r"\[DUBLETTE-JEV (?:schatten|skip) p=", text)),
        "deckung_ok": len(re.findall(r"JEV-DECKUNG ok", text)),
        "deckung_nein": len(re.findall(r"JEV-DECKUNG nicht bestanden", text)),
        "medien_weg_mb": sum(medien),
        "medien_weg_letzter": medien[0] if medien else 0,   # logs sind neueste zuerst
    }


def site_mb(log, seit):
    # Die bilder_spiegel-Zeile hat keinen eigenen Zeitstempel -> letzter Zeitstempel davor zaehlt.
    # Achtung: gemessen VOR dem Aufraeumen der Karten im selben Lauf.
    werte, letzte_zeit = [], ""
    for z in log.splitlines():
        t = ZEIT_RE.match(z)
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
        t = ZEIT_RE.match(z)
        if not t or t.group(1) < grenze:
            continue
        m = re.search(r"Batch \d+ OK mit (\S+)", z)
        if m:
            ok[m.group(1)] += 1
            continue
        if "fehlgeschlagen" in z or "Batch verworfen" in z or "Rate-Limit (429)" in z or "HTTP 429" in z:
            m = re.search(r"Batch \d+(?: mit|:) (\S+)", z)
            if m:
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
    # nur neue Vorfaelle: mindestens eine der Karten ist im Fenster (Kalendertag) entstanden
    doppelt = [u for u, ids in links.items() if len(ids) > 1 and ids & neu_ids]
    return len(neu), doppelt


# ---------------------------------------------------------------- Nachricht
def bauen(basis: Path, stunden: int):
    jetzt = datetime.now(timezone.utc)
    seit = jetzt - timedelta(hours=stunden)
    frist = time.monotonic() + API_BUDGET_S
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
    z = None
    try:
        l, logs = laeufe(seit, frist)
        z = log_zaehler(logs)
        zeile = f"Läufe: {l['gruen']} ✓ · {l['rot']} ✗"
        if l["uebersprungen"]:
            zeile += f" · {l['uebersprungen']} übersprungen (Doppellauf-Sperre)"
        if l["laufend"]:
            zeile += f" · {l['laufend']} läuft"
        if l["logs_fehlen"]:
            zeile += f" · {l['logs_fehlen']} Logs nicht gelesen"
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
        zeilen.append(f"Läufe: n/a ({e.__class__.__name__})")

    # Medien-Repo (Wert aus ki_news.log ist VOR dem Aufraeumen des letzten Laufs gemessen)
    try:
        mb, delta = site_mb(log, seit)
        if mb is None:
            zeilen.append("Medien-Repo: n/a")
        else:
            nach = mb - (z["medien_weg_letzter"] if z else 0)
            d = f", 24 h: {delta:+d} MB" if delta is not None else ""
            zeilen.append(f"Medien-Repo: ca. {nach} von 1024 MB (vor Aufräumen {mb}{d})")
            if nach > WARN_SITE_MB:
                warn.append(f"Medien-Repo ca. {nach} MB (Grenze 1024)")
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

    # Umlaute (news.json kennt nur das Datum -> Kalendertage gestern + heute)
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


def ausloeser_uebersprungen():
    """True, wenn der ausloesende KI-News-Lauf von der Doppellauf-Sperre uebersprungen wurde."""
    rid = os.environ.get("AUSLOESER_RUN_ID", "").strip()
    if not rid:
        return False
    try:
        return _build_uebersprungen(_api(f"actions/runs/{rid}/jobs")["jobs"])
    except Exception:
        return False


def senden(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("lagebild: kein TELEGRAM_TOKEN - nur ausgegeben.")
        return False
    daten = json.dumps({"chat_id": (os.environ.get("TELEGRAM_CHAT_ID") or "9096438").strip(),
                        "text": text[:4000], "disable_web_page_preview": True}).encode()
    for versuch in (1, 2):
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=daten,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20).read()
            return True
        except Exception as e:
            print(f"lagebild: Senden Versuch {versuch} fehlgeschlagen ({e.__class__.__name__})")
            time.sleep(3)
    return False


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default=str(BASE))
    ap.add_argument("--stunden", type=int, default=24)
    ap.add_argument("--trocken", action="store_true")
    a = ap.parse_args(argv)
    if ausloeser_uebersprungen():
        print("lagebild: Ausloeser war ein uebersprungener Lauf - kein Lagebild, naechster Lauf versucht es.")
        return 3
    text, _ = bauen(Path(a.basis), a.stunden)
    print(text)
    if a.trocken:
        return 0
    if senden(text):
        print("lagebild: gesendet.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
