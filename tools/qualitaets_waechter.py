#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qualitaets_waechter.py: prueft nach jedem Lauf die Seite so, wie Leser sie sehen.

23.11.26 (Daniel: "das nervt, das nacharbeiten. was können wir machen damit die qualtät endlich
mal stimmmig ist"). Bis dahin hat Daniel Fehler selbst gefunden, z. B. zwei Meldungen zum selben
Ereignis im Fokus oder ein neues Modell, das im Modellatlas nur als kleines Schild stand.

Geprueft wird:
  1. Fokus (window.__pxHeroTop): keine zwei Meldungen zum selben Ereignis. Zaehlt als gleich:
     gleiche Story, gleiche Linie, Doppel (dub_von), Jev-Titelurteil ab 0,7 im Cache
     jev_urteile.json, oder sehr aehnliche Originaltitel, zu denen Jev nichts gesagt hat.
  2. Liste der Startseite: kein Titel doppelt, kein Doppel (dub_von) als eigene Zeile.
  3. Modellatlas: Das neueste Modell jedes Herstellers steht sichtbar auf einer Karte oder einem
     Schild (nicht nur im Tooltip).
  4. OpenRouter: Modelle der letzten 14 Tage, die in registry/registry.json fehlen.
  5. HuggingNews: Storys ab 300 Tweets aus den letzten 24 Stunden, die der Finder
     (hn_finder_shadow.json) nicht bei uns gefunden hat. Es werden keine HN-Texte gespeichert.

Gemeldet wird nur, was neu ist (Zustandsdatei). Ein Fund macht den Lauf nie rot. Rot heisst:
der Waechter selbst ist kaputt.

Aufruf:
  python tools/qualitaets_waechter.py                       Live-Seite ki-news.live
  python tools/qualitaets_waechter.py --lokal .             Dateien aus einem Ordner, ohne Netz-Seite
  Optionen: --zustand DATEI  --telegram  --warten SEKUNDEN

Kill-Switch: Im Actions-Tab den Workflow "Qualitaetswaechter" deaktivieren. Nur die
Telegram-Meldung abschalten: TELEGRAM_MELDEN = False.
"""
import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

TELEGRAM_MELDEN = True
BASIS_URL = "https://ki-news.live"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
JEV_GLEICH = 0.7            # wie CLUSTER_JEV_SCHWELLE in ki_news.py
TITEL_AEHNLICH = 0.6        # Dice der Originaltitel-Woerter, nur wenn Jev das Paar nicht kennt
OR_TAGE = 14
HN_MIN_TWEETS = 300
HN_STUNDEN = 24
ZUSTAND_TAGE = 7            # ein Fund, der so lange nicht mehr auftaucht, gilt danach wieder als neu

ROOT = Path(__file__).resolve().parent.parent
STOPP = set("the a an of to in for and on with is its at by as from after over new says will has are be "
            "how why what this that it into about than more who now just".split())

JS_START = r"""async () => {
  const mehr = document.getElementById('pxk-news-more');
  for (let i = 0; i < 80 && mehr && !mehr.hidden; i++) { mehr.click(); await new Promise(r => setTimeout(r, 120)); }
  const zeilen = [...document.querySelectorAll('.pxz-t')].filter(e => e.checkVisibility()).map(e => e.textContent.trim());
  const feld = n => ({link: n.link || '', story_id: n.story_id || '', linie: n.linie || '', dub_von: n.dub_von || '',
                      title: n.title || '', title_orig: n.title_orig || '', source: n.source || '', score: n.score || 0});
  return {
    top: (window.__pxHeroTop || []).map(feld),
    news: (window.KI_NEWS || []).map(feld),
    zeilen
  };
}"""

JS_ATLAS = r"""() => [...document.querySelectorAll('section.px-maker')].map(sec => ({
  anbieter: (sec.querySelector('h2') || {}).textContent || '',
  kopf: ((sec.querySelector('.px-maker-latest') || {}).textContent || '').replace(/\s+/g, ' '),
  karten: [...sec.querySelectorAll('.px-gen')].map(g => ({
    name: (g.querySelector('.px-gen-name') || {}).textContent || '',
    datum: (g.querySelector('.px-gen-date') || {}).textContent || '',
    schilder: [...g.querySelectorAll('.px-stufe')].map(c => ({text: c.textContent, title: c.title}))
  }))
}))"""

DATUM = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def log(*a):
    print(*a, flush=True)


def lade_json(pfad, leer=None):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return leer


def hole(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "ki-news-qualitaetswaechter"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── Seite laden ─────────────────────────────────────────────────────────────

def warte_auf_live(stand_repo, sekunden):
    """Wartet, bis die Live-Seite die news.json aus dem Repo ausliefert (GitHub Pages braucht etwas)."""
    ende = time.time() + sekunden
    while True:
        try:
            live = json.loads(hole("%s/news.json?w=%d" % (BASIS_URL, time.time())).decode("utf-8"))
            if live.get("stand") == stand_repo:
                return True, stand_repo
            stand_live = live.get("stand")
        except Exception as e:
            stand_live = "Fehler: %s" % e
        if time.time() >= ende:
            return False, stand_live
        time.sleep(30)


def seite_lesen(lokal):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        if lokal:
            host = "http://w%d.localhost:8765" % int(time.time() * 1000 % 1e9)

            def bediene(route):
                url = route.request.url
                if not url.startswith(host):
                    return route.abort()
                pfad = url[len(host):].split("?")[0].split("#")[0].lstrip("/") or "index.html"
                f = Path(lokal) / pfad
                if not f.is_file():
                    return route.fulfill(status=404, body="")
                typ = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                return route.fulfill(status=200, content_type=typ, body=f.read_bytes())
            ctx.route("**/*", bediene)
            basis = host
        else:
            basis = BASIS_URL
        fehler = []
        page = ctx.new_page()
        page.on("pageerror", lambda e: fehler.append("Startseite: " + str(e)[:160]))
        page.goto(basis + "/?w=%d" % time.time(), wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector(".pxz-t", timeout=90000)
        page.wait_for_timeout(3000)
        start = page.evaluate(JS_START)
        page.close()

        page = ctx.new_page()
        page.on("pageerror", lambda e: fehler.append("Modellatlas: " + str(e)[:160]))
        page.goto(basis + "/modelle.html?w=%d" % time.time(), wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector(".px-gen", state="attached", timeout=90000)
        page.wait_for_timeout(1500)
        atlas = page.evaluate(JS_ATLAS)
        browser.close()
    return start, atlas, fehler


# ── Pruefungen ──────────────────────────────────────────────────────────────

def woerter(t):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]+", (t or "").lower()) if w not in STOPP and len(w) > 2}


def dice(a, b):
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def kurz(n, laenge=70):
    t = (n.get("title") or "").strip()
    return "%s: %s" % (n.get("source") or "?", t[:laenge] + ("..." if len(t) > laenge else ""))


def pruefe_fokus(top, news, jev):
    """Paare im Fokus, die dasselbe Ereignis zeigen."""
    funde = []
    urteile = (jev or {}).get("urteile") or {}
    mitglieder = {}
    for n in news:
        if n.get("story_id"):
            mitglieder.setdefault(n["story_id"], []).append(n)
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            gruende = []
            if a["story_id"] and a["story_id"] == b["story_id"]:
                gruende.append("gleiche Story")
            if a["linie"] and a["linie"] == b["linie"]:
                gruende.append("gleiche Linie")
            if a["link"] and (a["dub_von"] == b["link"] or b["dub_von"] == a["link"]):
                gruende.append("Doppel (dub_von)")
            # Jev-Urteile ueber alle Meldungen beider Storys
            ma = mitglieder.get(a["story_id"]) or [a]
            mb = mitglieder.get(b["story_id"]) or [b]
            best, best_text, gefragt = None, None, False
            for x in ma:
                for y in mb:
                    k = "|".join(sorted([x["link"], y["link"]]))
                    u = urteile.get(k)
                    if u is None:
                        continue
                    gefragt = True
                    p = u.get("p") if isinstance(u, dict) else None
                    if p is not None and (best is None or p > best):
                        best = p
                        t = urteile.get("text|" + k)
                        best_text = t.get("p") if isinstance(t, dict) else None
            if best is not None and best >= JEV_GLEICH:
                gruende.append("Jev Titel p=%.2f%s" % (best, "" if best_text is None else ", Kurztext %.2f" % best_text))
            if not gefragt:
                d = dice(woerter(a["title_orig"] or a["title"]), woerter(b["title_orig"] or b["title"]))
                if d >= TITEL_AEHNLICH:
                    gruende.append("aehnliche Titel (%.2f), Jev hat das Paar nicht beurteilt" % d)
            if gruende:
                schluessel = "fokus:" + "|".join(sorted([a["link"], b["link"]]))
                funde.append({"art": "Fokus", "schluessel": schluessel,
                              "text": "Fokus %d und %d zeigen dasselbe Ereignis (%s): %s / %s" % (
                                  top.index(a) + 1, top.index(b) + 1, ", ".join(gruende), kurz(a), kurz(b))})
    return funde


def pruefe_liste(news, zeilen):
    funde = []
    gesehen = {}
    for z in zeilen:
        gesehen[z] = gesehen.get(z, 0) + 1
    for titel, zahl in gesehen.items():
        if zahl > 1:
            funde.append({"art": "Liste", "schluessel": "liste-gleich:" + titel[:120],
                          "text": "Titel steht %d-mal in der Liste: %s" % (zahl, titel[:90])})
    je_link = {n["link"]: n for n in news if n["link"]}
    sichtbar = set(zeilen)
    for n in news:
        ziel = je_link.get(n["dub_von"]) if n["dub_von"] else None
        if not ziel:
            continue
        tn, tz = n["title"].strip(), ziel["title"].strip()
        if tn != tz and tn in sichtbar and tz in sichtbar:
            funde.append({"art": "Liste", "schluessel": "liste-dub:" + n["link"],
                          "text": "Doppel steht als eigene Zeile: %s (Doppel von %s)" % (kurz(n), kurz(ziel))})
    return funde


def iso(d):
    t, m, j = d.split(".")
    return j + "-" + m + "-" + t


def pruefe_atlas(atlas):
    funde = []
    for a in atlas:
        sichtbar = set()
        for k in a["karten"]:
            sichtbar.update(DATUM.findall(k["datum"]))
            for s in k["schilder"]:
                sichtbar.update(DATUM.findall(s["text"]))
        stand = DATUM.findall(a["kopf"])
        if stand and stand[0] not in sichtbar:
            versteckt = [s["title"].split(" · ")[0] for k in a["karten"] for s in k["schilder"]
                         if stand[0] in s["title"]]
            funde.append({"art": "Modellatlas", "schluessel": "atlas:%s:%s" % (a["anbieter"], stand[0]),
                          "text": "Modellatlas %s: neuester Stand %s steht auf keiner Karte%s" % (
                              a["anbieter"], stand[0],
                              " (nur im Tooltip: %s)" % ", ".join(versteckt[:3]) if versteckt else "")})
    return funde


def pruefe_openrouter(registry, jetzt):
    """Neue OpenRouter-Modelle, die bei uns fehlen. Nur Modelle, die schon vor dem Registry-Bau da waren."""
    funde = []
    modelle = (registry or {}).get("modelle") or []
    if not modelle:
        return [{"art": "Fehler", "schluessel": "fehler:registry", "text": "registry/registry.json fehlt oder ist leer"}]
    bekannt = set()
    for m in modelle:
        bekannt.update(x for x in (m.get("s"), m.get("i")) if x)
    try:
        stand = dt.datetime.fromisoformat(registry.get("stand", "").replace("Z", "+00:00")).timestamp()
    except Exception:
        stand = jetzt
    daten = json.loads(hole(OPENROUTER_URL, timeout=60).decode("utf-8"))
    for x in daten.get("data") or []:
        if x.get("alias_target"):
            continue
        erstellt = x.get("created") or 0
        if not erstellt or erstellt < jetzt - OR_TAGE * 86400 or erstellt >= stand:
            continue
        mid = (x.get("id") or "").split(":")[0]
        if x.get("canonical_slug") in bekannt or x.get("id") in bekannt or mid in bekannt:
            continue
        funde.append({"art": "OpenRouter", "schluessel": "or:%s" % (x.get("canonical_slug") or x.get("id")),
                      "text": "OpenRouter-Modell fehlt in der Registry: %s (%s, seit %s)" % (
                          x.get("name") or x.get("id"), x.get("id"),
                          dt.datetime.fromtimestamp(erstellt, dt.timezone.utc).strftime("%d.%m.%Y"))})
    return funde


def pruefe_huggingnews(hn):
    """Grosse HN-Storys, die der Finder nicht bei uns gefunden hat. Keine HN-Titel in der Ausgabe."""
    funde = []
    if not hn:
        return funde
    try:
        stand = dt.datetime.fromisoformat(hn.get("stand", "").replace("Z", "+00:00"))
    except Exception:
        return funde
    for schluessel, s in (hn.get("storys") or {}).items():
        if (s.get("tweets") or 0) < HN_MIN_TWEETS or s.get("status") not in ("fehlt", "unklar"):
            continue
        try:
            zuletzt = dt.datetime.fromisoformat((s.get("zuletzt") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if (stand - zuletzt).total_seconds() > HN_STUNDEN * 3600:
            continue
        kandidat = s.get("titel_kandidat") or s.get("eigener_link") or ""
        funde.append({"art": "HuggingNews", "schluessel": "hn:" + schluessel,
                      "text": "HuggingNews-Story mit %d Tweets, Status %s%s" % (
                          s.get("tweets") or 0, s.get("status"),
                          (", naechster Kandidat bei uns (Wert %s): %s" % (s.get("titel_wert"), kandidat[:120]))
                          if kandidat else ", kein Kandidat bei uns"),
                      "privat": "HN-Schluessel " + schluessel[:80]})
    return funde


# ── Zustand, Ausgabe, Telegram ──────────────────────────────────────────────

def zustand_abgleichen(pfad, funde, jetzt_iso, jetzt):
    zustand = lade_json(pfad, {}) if pfad else {}
    if not isinstance(zustand, dict):
        zustand = {}
    neu = []
    for f in funde:
        alt = zustand.get(f["schluessel"])
        if not alt:
            neu.append(f)
            zustand[f["schluessel"]] = {"erst": jetzt_iso, "zuletzt": jetzt_iso}
        else:
            alt["zuletzt"] = jetzt_iso
    grenze = jetzt - ZUSTAND_TAGE * 86400
    for k in list(zustand):
        try:
            z = dt.datetime.fromisoformat(zustand[k]["zuletzt"]).timestamp()
        except Exception:
            z = 0
        if z < grenze:
            del zustand[k]
    if pfad:
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        Path(pfad).write_text(json.dumps(zustand, ensure_ascii=False, indent=1), encoding="utf-8")
    return neu


def zusammenfassung(funde, neu, kopf):
    zeilen = ["## Qualitaetswaechter", "", kopf, ""]
    if not funde:
        zeilen.append("Keine Funde.")
    neu_schl = {f["schluessel"] for f in neu}
    for f in funde:
        zeilen.append("- %s**%s**: %s" % ("NEU " if f["schluessel"] in neu_schl else "", f["art"], f["text"]))
    return "\n".join(zeilen) + "\n"


def telegram(neu, kopf):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "9096438"
    if not token:
        log("Telegram: kein TELEGRAM_TOKEN, nichts gesendet")
        return False
    teile = ["Qualitaetswaechter: %d neue%s Fund%s" % (len(neu), "r" if len(neu) == 1 else "", "" if len(neu) == 1 else "e"), kopf, ""]
    for f in neu[:12]:
        teile.append("- %s: %s%s" % (f["art"], f["text"], (" (%s)" % f["privat"]) if f.get("privat") else ""))
    if len(neu) > 12:
        teile.append("... und %d weitere" % (len(neu) - 12))
    lauf = os.environ.get("LAUF_URL", "")
    if lauf:
        teile += ["", lauf]
    daten = json.dumps({"chat_id": chat, "text": "\n".join(teile)[:4000],
                        "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token, data=daten,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = json.loads(r.read()).get("ok")
    except Exception as e:
        log("Telegram: Fehler %s" % type(e).__name__)
        return False
    log("Telegram: gesendet" if ok else "Telegram: ok=false")
    return bool(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lokal", help="Ordner mit index.html, news.json usw. statt der Live-Seite")
    ap.add_argument("--zustand", help="JSON mit schon gemeldeten Funden")
    ap.add_argument("--telegram", action="store_true", help="neue Funde per Telegram melden")
    ap.add_argument("--warten", type=int, default=0, help="Sekunden warten, bis die Live-Seite den Repo-Stand hat")
    ap.add_argument("--ohne-netz", action="store_true", help="OpenRouter nicht abfragen")
    args = ap.parse_args()

    daten = Path(args.lokal) if args.lokal else ROOT
    jetzt = time.time()
    jetzt_iso = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    news_repo = lade_json(daten / "news.json", {}) or {}
    stand_repo = news_repo.get("stand", "")
    kopf = "Stand news.json %s" % stand_repo

    if not args.lokal and args.warten:
        gleich, stand_live = warte_auf_live(stand_repo, args.warten)
        if not gleich:
            kopf += ", Live-Seite zeigt noch %s (nach %d s Warten)" % (stand_live, args.warten)

    funde = []
    start, atlas, js_fehler = seite_lesen(str(daten) if args.lokal else None)
    for f in js_fehler[:5]:
        funde.append({"art": "JS-Fehler", "schluessel": "js:" + f[:100], "text": f})
    log("Fokus:", ["%s %s" % (n["story_id"], kurz(n, 50)) for n in start["top"]])

    pruefungen = [
        ("Fokus", lambda: pruefe_fokus(start["top"], start["news"], lade_json(daten / "jev_urteile.json", {}))),
        ("Liste", lambda: pruefe_liste(start["news"], start["zeilen"])),
        ("Modellatlas", lambda: pruefe_atlas(atlas)),
        ("HuggingNews", lambda: pruefe_huggingnews(lade_json(daten / "hn_finder_shadow.json", {}))),
    ]
    if not args.ohne_netz:
        pruefungen.append(("OpenRouter", lambda: pruefe_openrouter(lade_json(daten / "registry" / "registry.json", {}), jetzt)))
    for name, pruefe in pruefungen:
        try:
            erg = pruefe()
            log("%-12s %d Funde" % (name, len(erg)))
            funde += erg
        except Exception as e:
            log("%-12s Pruefung fehlgeschlagen: %s" % (name, e))
            funde.append({"art": "Fehler", "schluessel": "fehler:" + name,
                          "text": "Pruefung %s fehlgeschlagen: %s" % (name, str(e)[:160])})

    neu = zustand_abgleichen(args.zustand, funde, jetzt_iso, jetzt)
    text = zusammenfassung(funde, neu, kopf + ", %d Funde, davon %d neu" % (len(funde), len(neu)))
    log(text)
    ziel = os.environ.get("GITHUB_STEP_SUMMARY")
    if ziel:
        with open(ziel, "a", encoding="utf-8") as f:
            f.write(text)
    if neu and args.telegram and TELEGRAM_MELDEN:
        telegram(neu, kopf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
