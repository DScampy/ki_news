#!/usr/bin/env python3
"""HuggingNews als Finder, SCHATTENBETRIEB (17.11.26, Plan X1, Daniel).

Daniel am 17.11.26: Die groesste Story bei HuggingNews brauchen wir auf jeden Fall, und die
X-Posts dort sollen helfen, Meldungen zu finden. Am 17.11. fehlte uns HN-Platz 1 (China droht
Gegenmassnahmen gegen die US-Chipregeln, 1176 Tweets) ganz.

Dieses Skript schreibt NUR hn_finder_shadow.json und Logzeilen. Es aendert keine Meldung,
keinen Score und keine Karte. Je Lauf:
  1. HN-Feed lesen (3 Tage), Storys ab MIN_TWEETS Tweets, ohne ueberholte Storys.
  2. Haben wir die Story? Der erste Treffer zaehlt:
     a) themenketten.json ordnet einen unserer Artikel als dasselbe Ereignis zu,
        auch ueber eine Ereignis-Gruppe (gruppe_von),
     b) der t.co-Link eines source/support-Posts fuehrt auf einen Link, den wir haben,
     c) Wortueberdeckung des HN-Titels mit unseren englischen Originaltiteln
        (summary-cache.json, title_orig) ab TITEL_SICHER. Seltene Woerter zaehlen mehr als
        haeufige wie Nvidia, Huang oder CEO (Gewicht nach Seltenheit in unseren Titeln).
     Liegt die beste Ueberdeckung zwischen TITEL_UNKLAR und TITEL_SICHER, heisst es "unklar".
  3. Fehlt sie oder ist sie unklar: Originalquelle suchen.
     Erst die t.co-Links der source/support-Posts. Sie lassen sich ohne Login aufloesen
     (Messung 17.11.: 6 von 10 grossen Storys fuehren so auf eine externe Seite). Der Titel
     kommt aus og:title der Zielseite. Dann eine Google-News-Suche mit den Stichworten der
     Story, die beste Ueberdeckung zaehlt. Der Suchzeitraum zaehlt ab dem Ereignis.
     Wiederholung (18.11.26): Im ersten echten Lauf fand die Suche fuer die Huang-Anhoerung
     nichts, lokal kurz danach 10 Treffer. Ein Fehlschlag sah aus wie "keine Quelle" und wurde
     nie wiederholt. Darum steht jetzt der Suchstatus in der Datei und im Log. Nach einem
     Fehler sucht der naechste Lauf noch einmal, ohne Treffer erst nach SUCHE_WIEDERHOLEN_H
     Stunden. Hoechstens SUCHE_VERSUCHE Suchen je Story.

HN-Texte werden nicht gespeichert (robots.txt use=reference). In der Datei stehen nur Slugs,
Zahlen, Zeiten, unsere Links und Titel der Originalquellen. HN-Titel dienen nur im Speicher
zum Abgleich und als Suchwoerter. Eine eigene Meldung entsteht spaeter, wenn Daniel es so
entscheidet, nur aus der Originalquelle, nie aus HN- oder X-Texten.

Nie blockieren: jeder Fehler wird geloggt, der Exit-Code bleibt 0.
Kill-Switch: AKTIV = False oder den Workflow-Schritt entfernen.

Aufruf: python3 hn_finder_shadow.py [--basis DIR] [--ausgabe DATEI]
"""
import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

AKTIV = True
DATEI = "hn_finder_shadow.json"
HN_API = "https://api.huggingnews.com/api/stories"
GN_SUCHE = "https://news.google.com/rss/search?"
MIN_TWEETS = 80          # ab hier gilt eine HN-Story als gross
MAX_STORYS = 30          # hoechstens so viele Storys je Lauf (die groessten zuerst)
TITEL_SICHER = 0.5       # gewichteter Dice-Wert HN-Titel gegen title_orig, ab hier "bei uns"
TITEL_UNKLAR = 0.3       # darunter "fehlt"
SUCHE_MIN = 0.3          # Google-News-Treffer erst ab diesem Dice-Wert
SUCHE_VERSUCHE = 4       # hoechstens so viele Quellensuchen je Story
SUCHE_WIEDERHOLEN_H = 6  # ohne Treffer erst nach so vielen Stunden noch einmal suchen
SUCHE_FENSTER_MAX = 10   # Google-News-Zeitraum in Tagen, ab dem Ereignis gerechnet
VORLAUF_TAGE = 2         # eigene Titel zaehlen ab 2 Tage vor der Story
HALTEN_TAGE = 10         # Storys so lange in der Datei halten
MAX_LAEUFE = 80          # Laufzusammenfassungen (10 Tage bei 8 Laeufen)
ZEIT_BUDGET_S = 150
TIMEOUT_S = 12
UA_HN = "ki-news.live"
UA_SEITE = "Mozilla/5.0 (compatible; ki-news.live; +https://ki-news.live)"
X_HOSTS = ("x.com", "twitter.com", "t.co", "twimg.com")

STOP = set("""the a an and or for with from over after before says said say report reports
reported new its it into about amid as at by in of on to is are was were be been will would
could may might than that this these those their his her them they he she we you our your
not yes more most less out off down via per plus amp just also how why what when who which
where while still now has have had get gets got set sets""".split())
# Nur fuer die Suchwoerter: Kennzeichen von Agenturmeldungen, keine Inhalte (Messung 18.11.:
# "UPDATE" und "000" aus einer Zahl mit Tausenderkomma verdarben zwei Suchen).
NICHT_SUCHEN = set("update updated breaking exclusive live watch video opinion analysis".split())

_start = time.monotonic()


def _log(msg):
    print("[HN-FINDER] " + msg, flush=True)


def _rest_s():
    return ZEIT_BUDGET_S - (time.monotonic() - _start)


def _jetzt():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _zeit(text):
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _lade(pfad, leer):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return leer


def _host(url):
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _ist_x(url):
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in X_HOSTS)


def _norm_link(url):
    """Link ohne Schema, www, Query und Schraegstrich am Ende, fuer den Abgleich."""
    try:
        t = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return ""
    return (_host(url) + t.path.rstrip("/")).lower()


def _woerter(text):
    out = set()
    for w in re.sub(r"[^a-z0-9.%$]+", " ", str(text or "").lower()).split():
        w = w.strip(".")
        if (len(w) < 3 and not any(c.isdigit() for c in w)) or w in STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _dice(a, b, g=None):
    """Wortueberdeckung 0 bis 1. Mit Gewicht g zaehlt jedes Wort nach seiner Seltenheit."""
    if not a or not b:
        return 0.0
    if g is None:
        return round(2 * len(a & b) / (len(a) + len(b)), 2)
    return round(2 * sum(map(g, a & b)) / (sum(map(g, a)) + sum(map(g, b))), 2)


def _gewicht(titel):
    """Gewicht je Wort nach Seltenheit in unseren Originaltiteln (IDF). Messung 17.11.: ungewichtet
    hielt der Finder "SEC prueft Nvidia" fuer "Huang will zurueck" (0,53), nur wegen Nvidia, CEO,
    Jensen und Huang. Gewichtet 0,37, dafuer findet er bei drei Storys den passenderen Artikel."""
    df = {}
    for _, w, _ in titel:
        for x in w:
            df[x] = df.get(x, 0) + 1
    n = len(titel)
    return lambda w: math.log((n + 1) / (df.get(w, 0) + 1)) + 0.5


def _suchwoerter(titel, n=8):
    titel = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(titel or ""))   # "4,000" bleibt ein Wort
    gesehen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9$%.]+", titel):
        k = w.lower().strip(".")
        if len(k) < 3 or k in STOP or k in NICHT_SUCHEN or k in gesehen or set(k) <= set("0."):
            continue
        gesehen.add(k)
        out.append(w.strip("."))
    return " ".join(out[:n])


def _hn(url, key):
    kopf = {"User-Agent": UA_HN}
    if key:
        kopf["Authorization"] = "Bearer " + key
    for i in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i == 0:
                time.sleep(3)
                continue
            raise


def _tco_ziel(url):
    """t.co per HEAD aufloesen (ohne Login). Liefert das Ziel oder ""."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA_SEITE})
        opener = urllib.request.build_opener(_KeinRedirect)
        with opener.open(req, timeout=TIMEOUT_S) as r:
            return r.headers.get("Location") or ""
    except urllib.error.HTTPError as e:
        return e.headers.get("Location") or ""
    except Exception:
        return ""


class _KeinRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _seite(url):
    """Zielseite laden (Weiterleitungen folgen). Liefert (endgueltige URL, HTTP-Code, og:title)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA_SEITE, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            ende, code = r.geturl(), r.status
            roh = r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.geturl() or url, e.code, ""
    except Exception:
        return url, 0, ""
    titel = ""
    for muster in (r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
                   r"<title[^>]*>([^<]+)</title>"):
        m = re.search(muster, roh, re.I)
        if m:
            titel = html.unescape(m.group(1)).strip()
            break
    return ende, code, titel[:200]


def _gn_suche(titel, tage=3):
    """Google-News-RSS mit den Stichworten der Story, Zeitraum `tage` Tage.
    Liefert (Liste (titel, quelle, link), Status). Der Status lautet "n Treffer", "HTTP 429",
    "Fehler <Art>" oder "keine Suchwoerter", damit ein Fehlschlag nicht wie "keine Quelle" aussieht."""
    q = _suchwoerter(titel)
    if not q:
        return [], "keine Suchwoerter"
    url = GN_SUCHE + urllib.parse.urlencode({"q": "%s when:%dd" % (q, tage), "hl": "en-US",
                                              "gl": "US", "ceid": "US:en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA_SEITE})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            wurzel = ET.fromstring(r.read(2_000_000))
    except urllib.error.HTTPError as e:
        return [], "HTTP %s" % e.code
    except Exception as e:
        return [], "Fehler " + type(e).__name__
    out = []
    for item in wurzel.iter("item"):
        t = (item.findtext("title") or "").strip()
        quelle = (item.findtext("source") or "").strip()
        if quelle and t.endswith(" - " + quelle):
            t = t[: -len(quelle) - 3].strip()
        out.append((t, quelle, (item.findtext("link") or "").strip()))
        if len(out) >= 10:
            break
    return out, "%d Treffer" % len(out)


def _fehlschlag(status):
    """Suche gescheitert (nicht nur ohne Treffer): HTTP-Fehler, Ausnahme oder Zeitbudget leer."""
    return str(status or "").startswith(("HTTP", "Fehler", "Zeitbudget"))


def _nochmal_suchen(vorher, jetzt):
    """Erste Suche immer. Danach nur, solange kein Suchtreffer und keine frei lesbare t.co-Quelle
    da ist und Versuche frei sind: nach einem Fehlschlag im naechsten Lauf, ohne Treffer erst
    nach SUCHE_WIEDERHOLEN_H Stunden. Eintraege von vor dem 18.11. zaehlen als ein Versuch."""
    if "quelle_geprueft" not in vorher:
        return True
    if vorher.get("suche") or (vorher.get("quelle") or {}).get("http") == 200:
        return False
    if int(vorher.get("suche_versuche") or 1) >= SUCHE_VERSUCHE:
        return False
    if _fehlschlag(vorher.get("suche_status")):
        return True
    zuletzt = _zeit(vorher.get("suche_zuletzt") or vorher.get("quelle_geprueft"))
    return not zuletzt or jetzt - zuletzt >= timedelta(hours=SUCHE_WIEDERHOLEN_H)


def _eigene_daten(basis):
    """Unsere Links (normalisiert) und englische Originaltitel mit Zeit."""
    cache = _lade(basis / "summary-cache.json", {})
    news = _lade(basis / "news.json", {})
    archiv = _lade(basis / "archive.json", [])
    liste = (news.get("news") if isinstance(news, dict) else news) or []
    links = {}
    for n in list(liste) + (archiv if isinstance(archiv, list) else []):
        if isinstance(n, dict) and n.get("link"):
            for feld in ("link", "link_verlag", "link_ursprung"):
                if n.get(feld):
                    links.setdefault(_norm_link(n[feld]), n["link"])
    gn = news.get("gn_aufloesung") if isinstance(news, dict) else None
    if isinstance(gn, dict):
        for gn_link, ziel in gn.items():
            if isinstance(ziel, str) and ziel.startswith("http"):
                links.setdefault(_norm_link(ziel), gn_link)
    titel = []
    for link, e in (cache.items() if isinstance(cache, dict) else []):
        if isinstance(e, dict) and e.get("title_orig"):
            links.setdefault(_norm_link(link), link)
            titel.append((link, _woerter(e["title_orig"]), _zeit(e.get("generated_at"))))
    return links, titel


def _ketten(basis):
    tk = _lade(basis / "themenketten.json", {})
    gruppe = tk.get("gruppe_von") or {}
    eigen = {}
    for link, z in (tk.get("zuordnung") or {}).items():
        if isinstance(z, dict) and z.get("rolle") == "ereignis" and z.get("hn_slug"):
            eigen.setdefault(z["hn_slug"], link)
    for slug, u in (tk.get("urteile_ereignis") or {}).items():
        if isinstance(u, dict) and u.get("ja"):
            eigen.setdefault(slug, u["ja"][0])
    je_gruppe = {}
    for slug, link in eigen.items():
        je_gruppe.setdefault(gruppe.get(slug, slug), link)
    return gruppe, eigen, je_gruppe


def _bester_titel(woerter, titel, ab, g):
    best = (0.0, None)
    for link, w, zeit in titel:
        if ab and zeit and zeit < ab:
            continue
        d = _dice(woerter, w, g)
        if d > best[0]:
            best = (d, link)
    return best


def _quelle_suchen(story, detail, links, titel, g, zeit):
    """Originalquelle einer fehlenden Story: t.co-Ziel und Google-News-Treffer.
    Liefert (quelle, suche, suchstatus)."""
    quelle = None
    for t in detail.get("selectedTweets") or []:
        if t.get("role") not in ("source", "support") or _rest_s() < 20:
            continue
        for kurz in re.findall(r"https://t\.co/[A-Za-z0-9]+", str(t.get("text") or "")):
            ziel = _tco_ziel(kurz)
            if not ziel or _ist_x(ziel):
                continue
            ende, code, og = _seite(ziel)
            if urllib.parse.urlsplit(ende).path in ("", "/"):
                continue   # Startseite (Messung 17.11.: ic3.gov), sagt nichts ueber die Story
            quelle = {"url": ende, "domain": _host(ende), "titel": og, "http": code,
                      "rolle": t.get("role"), "bei_uns": links.get(_norm_link(ende))}
            break
        if quelle:
            break
    suche, status = None, "Zeitbudget"
    if _rest_s() > 15:
        # Zeitraum ab dem Ereignis: Am 18.11. lag die Huang-Anhoerung schon 4 Tage zurueck,
        # "when:3d" haette die ersten Berichte nicht mehr erfasst.
        tage = 3
        if zeit:
            tage = min(SUCHE_FENSTER_MAX, max(3, (_jetzt() - zeit).days + 2))
        hn_w = _woerter(story.get("title"))
        best = None
        treffer, status = _gn_suche(story.get("title"), tage)
        for t, q, link in treffer:
            d = _dice(hn_w, _woerter(t))
            if d >= SUCHE_MIN and (not best or d > best["wert"]):
                best = {"titel": t[:200], "quelle": q, "link": link, "wert": d}
        if best:
            eigen_d, eigen_link = _bester_titel(_woerter(best["titel"]), titel, None, g)
            best["bei_uns"] = eigen_link if eigen_d >= 0.8 else None
            suche = best
        elif treffer:
            status += ", keiner ab %.1f" % SUCHE_MIN
    return quelle, suche, status


def lauf(basis, ausgabe):
    jetzt = _jetzt()
    key = os.environ.get("HUGGINGNEWS_API_KEY", "")
    feed = _hn(HN_API, key)
    alle = [s for g in feed.get("dayGroups", []) for s in g.get("stories", []) if s.get("slug")]
    gross = sorted([s for s in alle if (s.get("tweetCount") or 0) >= MIN_TWEETS],
                   key=lambda s: -(s.get("tweetCount") or 0))[:MAX_STORYS]

    def _detail(s):
        try:
            return s["slug"], _hn(HN_API + "/" + urllib.parse.quote(s["slug"]), key)
        except Exception:
            return s["slug"], {}
    with ThreadPoolExecutor(4) as pool:
        details = dict(pool.map(_detail, gross))

    links, titel = _eigene_daten(basis)
    g_wort = _gewicht(titel)
    gruppe, eigen, je_gruppe = _ketten(basis)
    alt = _lade(ausgabe, {})
    storys = alt.get("storys") or {}

    ergebnis = []
    for s in gross:
        d = details.get(s["slug"]) or {}
        if d.get("isSuperseded"):
            continue
        slug = s["slug"]
        g = gruppe.get(slug, slug)
        zeit = _zeit(s.get("eventTimeApprox") or s.get("publishedAt"))
        ab = zeit - timedelta(days=VORLAUF_TAGE) if zeit else None
        hn_w = _woerter(s.get("title"))
        wert, titel_link = _bester_titel(hn_w, titel, ab, g_wort)
        status, wie, eigener = "fehlt", "", None
        if slug in eigen or g in je_gruppe:
            status, wie, eigener = "bei_uns", "themenkette", eigen.get(slug) or je_gruppe.get(g)
        elif wert >= TITEL_SICHER:
            status, wie, eigener = "bei_uns", "titel", titel_link
        elif wert >= TITEL_UNKLAR:
            status, eigener = "unklar", titel_link
        ergebnis.append({"s": s, "d": d, "slug": slug, "gruppe": g, "zeit": zeit,
                         "status": status, "wie": wie, "eigener": eigener, "wert": wert,
                         "kandidat": titel_link})

    # Weg b: t.co-Ziel ist ein Link, den wir haben. Die Quellensuche laeuft nur fuer die
    # groesste Story je Ereignis-Gruppe, wiederholt nach den Regeln in _nochmal_suchen.
    erledigt = set()
    for e in ergebnis:
        if e["status"] == "bei_uns" or e["gruppe"] in erledigt:
            continue
        erledigt.add(e["gruppe"])
        vorher = storys.get(e["slug"]) or {}
        if _nochmal_suchen(vorher, jetzt) and _rest_s() > 25:
            q, su, st = _quelle_suchen(e["s"], e["d"], links, titel, g_wort, e["zeit"])
            e["quelle"] = q or vorher.get("quelle")
            e["suche"] = su or vorher.get("suche")
            e["suche_status"] = st
            e["suche_versuche"] = int(vorher.get("suche_versuche") or ("quelle_geprueft" in vorher)) + 1
            e["neu_gesucht"] = True
        elif "quelle_geprueft" in vorher:
            e["quelle"], e["suche"] = vorher.get("quelle"), vorher.get("suche")
        q = e.get("quelle") or {}
        if q.get("bei_uns"):
            e["status"], e["wie"], e["eigener"] = "bei_uns", "link", q["bei_uns"]

    # Gruppen zusammenfassen: hat ein Mitglied die Story bei uns, gilt sie fuer alle.
    rang = {"bei_uns": 2, "unklar": 1, "fehlt": 0}
    beste = {}
    for e in ergebnis:
        if e["gruppe"] not in beste or rang[e["status"]] > rang[beste[e["gruppe"]]["status"]]:
            beste[e["gruppe"]] = e

    stempel = _iso(jetzt)
    for e in ergebnis:
        b = beste[e["gruppe"]]
        status = b["status"]
        alt_e = storys.get(e["slug"]) or {}
        neu = {
            "erst": alt_e.get("erst") or stempel,
            "zuletzt": stempel,
            "tweets": max(int(e["s"].get("tweetCount") or 0), int(alt_e.get("tweets") or 0)),
            "ereignis": _iso(e["zeit"]) if e["zeit"] else None,
            "status": status,
            "wie": b["wie"] if b is not e else e["wie"],
            "eigener_link": b["eigener"],
            "titel_wert": e["wert"],
            "titel_kandidat": e["kandidat"],
            "gruppe": e["gruppe"] if e["gruppe"] != e["slug"] else None,
            "verlauf": list(alt_e.get("verlauf") or []),
        }
        if b is not e and status == "bei_uns" and not neu["wie"]:
            neu["wie"] = "gruppe"
        if not neu["verlauf"] or neu["verlauf"][-1][1] != status:
            neu["verlauf"].append([stempel, status])
        if status == "bei_uns" and any(v[1] != "bei_uns" for v in neu["verlauf"][:-1]):
            neu["bei_uns_ab"] = alt_e.get("bei_uns_ab") or stempel
        if "quelle" in e or "quelle_geprueft" in alt_e:
            neu["quelle_geprueft"] = alt_e.get("quelle_geprueft") or stempel
            neu["quelle"] = e.get("quelle", alt_e.get("quelle"))
            neu["suche"] = e.get("suche", alt_e.get("suche"))
            if e.get("neu_gesucht"):
                neu["suche_status"] = e["suche_status"]
                neu["suche_versuche"] = e["suche_versuche"]
                neu["suche_zuletzt"] = stempel
            else:
                for k in ("suche_status", "suche_versuche", "suche_zuletzt"):
                    if k in alt_e:
                        neu[k] = alt_e[k]
        storys[e["slug"]] = neu

    grenze = _iso(jetzt - timedelta(days=HALTEN_TAGE))
    storys = {k: v for k, v in storys.items() if str(v.get("zuletzt") or "") >= grenze}

    zaehl = {"bei_uns": 0, "unklar": 0, "fehlt": 0}
    wege = {}
    fehlt_mit_quelle = 0
    for b in beste.values():
        zaehl[b["status"]] += 1
        if b["status"] == "bei_uns":
            wege[b["wie"]] = wege.get(b["wie"], 0) + 1
        elif b.get("quelle") or b.get("suche"):
            fehlt_mit_quelle += 1
    gesucht = [e for e in ergebnis if e.get("neu_gesucht")]
    such_fehler = sum(1 for e in gesucht if _fehlschlag(e["suche_status"]))
    zusammen = {"zeit": stempel, "feed": len(alle), "gross": len(ergebnis), "ereignisse": len(beste),
                **zaehl, "wege": wege, "nicht_bei_uns_mit_quelle": fehlt_mit_quelle,
                "suchen": len(gesucht), "suche_fehler": such_fehler,
                "dauer_s": round(time.monotonic() - _start, 1)}
    laeufe = (alt.get("laeufe") or []) + [zusammen]

    daten = {
        "_hinweis": "SCHATTENBETRIEB, nur Beobachtung. Schreiber: hn_finder_shadow.py. "
                    "Keine HN-Texte (use=reference), nur Slugs, Zahlen, unsere Links und "
                    "Titel der Originalquellen.",
        "stand": stempel,
        "einstellungen": {"min_tweets": MIN_TWEETS, "titel_sicher": TITEL_SICHER,
                          "titel_unklar": TITEL_UNKLAR, "suche_min": SUCHE_MIN,
                          "suche_versuche": SUCHE_VERSUCHE,
                          "suche_wiederholen_h": SUCHE_WIEDERHOLEN_H,
                          "titelwert": "Dice nach Wortseltenheit gewichtet"},
        "laeufe": laeufe[-MAX_LAEUFE:],
        "storys": dict(sorted(storys.items(), key=lambda kv: -int(kv[1].get("tweets") or 0))),
    }
    tmp = Path(str(ausgabe) + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ausgabe)

    _log("Schatten: %d Storys ab %d Tweets (%d Ereignisse), %d bei uns (%s), %d unklar, "
         "%d fehlen, %d davon mit Quelle, %d Suchen (%d gescheitert), %.0f s"
         % (len(ergebnis), MIN_TWEETS, len(beste), zaehl["bei_uns"],
            ", ".join("%s %d" % kv for kv in sorted(wege.items())) or "-", zaehl["unklar"],
            zaehl["fehlt"], fehlt_mit_quelle, len(gesucht), such_fehler,
            time.monotonic() - _start))
    for b in sorted(beste.values(), key=lambda e: -(e["s"].get("tweetCount") or 0)):
        if b["status"] == "bei_uns":
            continue
        q, su = b.get("quelle") or {}, b.get("suche") or {}
        gespeichert = storys.get(b["slug"]) or {}
        such_info = "%s, Versuch %s%s" % (gespeichert.get("suche_status") or "Status unbekannt",
                                          gespeichert.get("suche_versuche") or 1,
                                          "" if b.get("neu_gesucht") else ", aus dem Speicher")
        _log("%s: %d Tweets, Ereignis %s, Titelwert %.2f, Quelle %s, Suche %s"
             % (b["status"], b["s"].get("tweetCount") or 0,
                b["zeit"].strftime("%d.%m. %H:%M UTC") if b["zeit"] else "?", b["wert"],
                ("%s (HTTP %s) '%s'" % (q.get("domain"), q.get("http"), q.get("titel", "")[:70]))
                if q else "-",
                ("%s '%s' (%.2f) [%s]" % (su.get("quelle"), su.get("titel", "")[:70],
                                          su.get("wert", 0), such_info))
                if su else "- [%s]" % such_info))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--ausgabe", default="")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not AKTIV:
        _log("aus (AKTIV = False)")
        return
    basis = Path(a.basis)
    try:
        lauf(basis, Path(a.ausgabe) if a.ausgabe else basis / DATEI)
    except Exception as e:
        _log("uebersprungen, Pipeline unbeeinflusst: %s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    main()
    sys.exit(0)
