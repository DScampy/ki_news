#!/usr/bin/env python3
"""Ursprungsquelle fuer Meldungen aus X-Sammlern (15.11.26, Daniel).

Anlass (Daniel 15.11.):
- AlignedNews liefert nur den X-Beitrag. Die eigentliche Quelle steht oft im Beitrag selbst
  oder in der ersten Antwort des Autors. Agile Robots: @roboticomarket schreibt den Text, der
  Link auf robotico.market steht erst in der Antwort darunter.
- Digg AI fasst X-Beitraege zu einer Seite zusammen. Welcher Beitrag die Quelle ist, hebt Digg
  selbst hervor ("Featured Source", in den Seitendaten hinter "original-post"). Kitesurf-Browser:
  die 15-Punkte-Liste von @gurtej__gill_. LangChain: @LangChain mit Link auf langchain.com.
Bisher zeigte die Meldungsseite bei beiden nur "Originalquelle: AlignedNews" bzw. "Digg AI".

Ergebnis je Meldung, nur wenn etwas gefunden wurde:
  link_ursprung   Adresse der Ursprungsquelle
  ursprung_name   Anzeige, zum Beispiel "robotico.market" oder "@gurtej__gill_ auf X"
  ursprung_art    "x-post"    Link steht im X-Beitrag selbst
                  "x-antwort" Link steht in einer Antwort desselben Autors
                  "digg-link" Artikel, auf den der von Digg hervorgehobene Beitrag verlinkt
                  "digg-x"    von Digg hervorgehobener X-Beitrag (ohne eigenen Link)
                  "digg"      von Digg hervorgehobene andere Seite
ACHTUNG Feldname: belege.html liest ein Feld "ursprung" als Dublettenverweis. Darum
link_ursprung, nie "ursprung".

Regeln:
- Es wird nur verlinkt, was die Quelle selbst nennt. Nichts wird geraten.
- Kurzlinks (goo.gle, ift.tt, bit.ly, Firmen-Kurzlinks wie crwv.co/uuGKv ...) werden einmal
  aufgeloest. Gelingt das nicht, bleibt der Kurzlink stehen. Tracking-Teile (utm_*, linkId,
  ncid ...) fallen weg.
- Speicher x_ursprung.json (Meldungslink -> Fund), AUFBEWAHREN_TAGE lang. Auch "nichts
  gefunden" wird gespeichert, damit nicht jeder Lauf neu fragt (geloeschter X-Beitrag zaehlt
  dazu). Digg-Seiten ohne hervorgehobene Quelle tragen "nochmal" und werden einmal am Tag neu
  gefragt. Netzfehler werden nicht gespeichert, die Meldung kommt im naechsten Lauf wieder dran.
- Nie blockieren: hoechstens MAX_ABRUFE neue Abrufe und ZEIT_S Sekunden je Lauf, jeder Fehler
  ergibt kein Feld.
Kill-Switch: X_URSPRUNG_AKTIV = False in ki_news.py.

Test ohne Pipeline:  python3 x_ursprung.py [news.json]   (liest nur, schreibt nichts)
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

SPEICHER = "x_ursprung.json"
AUFBEWAHREN_TAGE = 14
MAX_ABRUFE = 20
ZEIT_S = 60
TIMEOUT_S = 10
PARALLEL = 4
MAX_AUTOR_POSTS = 4          # Beitrag plus bis zu 3 Antworten desselben Autors
UA = "ki-news.live (+https://ki-news.live)"
UA_SEITE = "Mozilla/5.0 (compatible; ki-news.live; +https://ki-news.live)"
FX_THREAD = "https://api.fxtwitter.com/2/thread/"
FELDER = ("link_ursprung", "ursprung_name", "ursprung_art")

_X_HOSTS = ("x.com", "twitter.com", "t.co", "pbs.twimg.com", "video.twimg.com")
_KEINE_QUELLE = _X_HOSTS + ("digg.com", "news.google.com")
_KURZLINKS = {
    "goo.gle", "g.co", "ift.tt", "bit.ly", "buff.ly", "dlvr.it", "lnkd.in", "tinyurl.com",
    "ow.ly", "trib.al", "shorturl.at", "rebrand.ly", "apple.co", "amzn.to", "fb.me", "wp.me",
    "is.gd", "cutt.ly", "t.ly", "tiny.cc", "aka.ms", "msft.it", "nvda.ws", "ibm.biz", "spr.ly",
    "hubs.ly", "hubs.la", "social.ms", "bit.do", "lnk.to",
}
_TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "igshid", "si", "linkid", "ncid"}
_X_RE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")
_DIGG_RE = re.compile(r"^https?://(?:www\.)?digg\.com/ai/[A-Za-z0-9]+")
_RSC_MARKE = "self.__next_f.push([1,"
_DIGG_MARKE = '"original-post",'
_KURZ_PFAD_RE = re.compile(r"^/[A-Za-z0-9._-]{1,20}/?$")


def _log(msg):
    print(msg, flush=True)


def _host(url):
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _passt(host, liste):
    return any(host == d or host.endswith("." + d) for d in liste)


def _x_post(url):
    """(handle, id) eines X-Beitrags oder None."""
    m = _X_RE.match(str(url or ""))
    return (m.group(1), m.group(2)) if m else None


def _digg_seite(n):
    for u in (n.get("link_verlag"), n.get("link")):
        if isinstance(u, str) and _DIGG_RE.match(u):
            return u
    return ""


def _abruf(url, ua, json_antwort):
    kopf = {"User-Agent": ua, "Accept": "application/json" if json_antwort else "text/html"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=TIMEOUT_S) as r:
        roh = r.read(3_000_000)
    return json.loads(roh) if json_antwort else roh.decode("utf-8", "replace")


def _ist_kurzlink(url):
    """Bekannter Kurzlink-Dienst oder Firmen-Kurzlink: kurzer Host und genau ein kurzes
    Pfadstueck (Messung 15.11.: crwv.co/uuGKv, thein.fo/4zAGNcP, epic.gm/ue-5-9-preview,
    social.ora.cl/6018BHLpoG, go.meta.me/muse-ember)."""
    host = _host(url)
    if _passt(host, _KURZLINKS):
        return True
    try:
        t = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    pfad = t.path or ""
    # Ein reines Wort wie /papers oder /blog ist eine normale Seite, kein Kurzlink-Code.
    code = any(c.isdigit() or c.isupper() or c == "-" for c in pfad)
    return len(host) <= 14 and not t.query and code and bool(_KURZ_PFAD_RE.match(pfad))


def _aufloesen(url):
    """Kurzlink einmal aufloesen (Weiterleitungen folgen). Sonst unveraendert. Landet die
    Weiterleitung auf einer Zustimmungsseite oder auf X, bleibt der Kurzlink stehen."""
    if not _ist_kurzlink(url):
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA_SEITE})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            ziel = r.geturl()
    except Exception:
        return url
    h = _host(ziel or "")
    if not (ziel or "").startswith("http") or "consent" in h or _passt(h, _KEINE_QUELLE):
        return url
    return ziel


def _ohne_tracking(url):
    """utm_*, fbclid und Co. abschneiden (blog.google haengt utm_source=x an)."""
    try:
        t = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if not t.query:
        return url
    rest = [(k, v) for k, v in urllib.parse.parse_qsl(t.query, keep_blank_values=True)
            if not (k.lower().startswith("utm_") or k.lower() in _TRACKING)]
    return urllib.parse.urlunsplit(t._replace(query=urllib.parse.urlencode(rest)))


def _name(url, art):
    if art in ("digg-x",):
        p = _x_post(url)
        if p:
            return "@%s auf X" % p[0]
    return _host(url)


def _fund(url, art):
    url = _ohne_tracking(url)
    return {"u": url, "art": art, "name": _name(url, art)}


def _aus_x(link):
    """Ersten externen Link aus dem X-Beitrag oder den ersten Antworten desselben Autors."""
    handle, pid = _x_post(link)
    try:
        d = _abruf(FX_THREAD + pid, UA, True)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):                      # Beitrag geloescht: nichts zu finden
            return {"u": ""}
        raise
    st = d.get("status") if isinstance(d, dict) else None
    if not isinstance(st, dict) or not st.get("id"):
        raise ValueError("FxTwitter ohne status")
    autor = ((st.get("author") or {}).get("screen_name") or handle).lower()
    eigene = [p for p in (d.get("thread") or [])
              if isinstance(p, dict) and p.get("id") and p.get("id") != st.get("id")
              and ((p.get("author") or {}).get("screen_name") or "").lower() == autor]
    eigene.sort(key=lambda p: p.get("created_timestamp") or 0)
    for nr, p in enumerate([st] + eigene[:MAX_AUTOR_POSTS - 1]):
        for f in ((p.get("raw_text") or {}).get("facets") or []):
            if not isinstance(f, dict) or f.get("type") != "url":
                continue
            u = _aufloesen(f.get("replacement") or f.get("original") or "")
            if u.startswith("http") and not _passt(_host(u), _KEINE_QUELLE):
                return _fund(u, "x-post" if nr == 0 else "x-antwort")
    return {"u": ""}


def _rsc(h):
    """Seitendaten von Next.js: alle self.__next_f.push([1,"..."]) aneinanderhaengen."""
    teile, i = [], 0
    dec = json.JSONDecoder()
    while True:
        i = h.find(_RSC_MARKE, i)
        if i < 0:
            break
        j = i + len(_RSC_MARKE)
        if h[j:j + 1] == '"':
            s, i = dec.raw_decode(h, j)
            teile.append(s)
        else:
            i = j
    return "".join(teile)


def _aus_digg(seite):
    """Hervorgehobene Quelle ("Featured Source") einer Digg-AI-Seite.

    Digg legt sie in den Seitendaten als Objekt hinter "original-post" ab:
    {video, embedHtml, source, post: {href: X-Beitrag, linkPreview: {href: Artikel}}, quote}.
    Die ld+json-Liste "citation" ist nur nach Zeit sortiert und taugt nicht als Quelle.
    Messung 15.11.: 27 von 32 Digg-Seiten haben den Eintrag, 3 davon mit verlinktem Artikel.
    Die anderen 5 sind Sammlungen ohne hervorgehobene Quelle. Die werden nicht geraten, sondern
    hoechstens einmal am Tag neu gefragt (Digg kann die Quelle spaeter nachtragen)."""
    rsc = _rsc(_abruf(seite, UA_SEITE, False))
    if not rsc:
        raise ValueError("Digg-Seite ohne Seitendaten")
    k = rsc.find(_DIGG_MARKE)
    if k < 0:
        return {"u": "", "nochmal": 1}
    obj, _ = json.JSONDecoder().raw_decode(rsc, k + len(_DIGG_MARKE))
    if not isinstance(obj, dict):
        raise ValueError("Digg original-post ohne Objekt")
    post = obj.get("post") if isinstance(obj.get("post"), dict) else {}
    vorschau = post.get("linkPreview") if isinstance(post.get("linkPreview"), dict) else {}
    u = vorschau.get("href")
    if isinstance(u, str) and u.startswith("http"):
        u = _aufloesen(u)
        if not _passt(_host(u), _KEINE_QUELLE):
            return _fund(u, "digg-link")
    p = _x_post(post.get("href"))
    if p:
        return _fund("https://x.com/%s/status/%s" % p, "digg-x")
    quelle = obj.get("source")
    u = (quelle.get("href") or quelle.get("url")) if isinstance(quelle, dict) else quelle
    if isinstance(u, str) and u.startswith("http") and not _passt(_host(u), _KEINE_QUELLE):
        return _fund(_aufloesen(u), "digg")
    return {"u": "", "nochmal": 1}


def _pruefen(n):
    if _x_post(n.get("link")):
        return _aus_x(n["link"])
    return _aus_digg(_digg_seite(n))


def _anwenden(n, f):
    for feld in FELDER:
        n.pop(feld, None)
    if f and f.get("u"):
        n["link_ursprung"] = f["u"]
        n["ursprung_name"] = f.get("name") or _host(f["u"])
        n["ursprung_art"] = f.get("art") or ""


def _lade(pfad):
    try:
        d = json.loads(Path(pfad).read_text(encoding="utf-8"))
        return d.get("eintraege") if isinstance(d.get("eintraege"), dict) else {}
    except Exception:
        return {}


def nachtragen(base_dir, news_list, speichern=True):
    """Setzt link_ursprung/ursprung_name/ursprung_art an Meldungen von AlignedNews (X-Beitrag)
    und Digg AI. Aendert news_list in place. Gibt eine Zaehlung zurueck."""
    pfad = Path(base_dir) / SPEICHER
    speicher = _lade(pfad)
    heute = date.today().isoformat()
    stat = {"kandidaten": 0, "gespeichert": 0, "neu_gefunden": 0, "neu_leer": 0,
            "fehler": 0, "ohne_budget": 0, "mit_ursprung": 0}
    offen = []
    for n in news_list:
        if not isinstance(n, dict) or not n.get("link"):
            continue
        if not (_x_post(n.get("link")) or _digg_seite(n)):
            continue
        stat["kandidaten"] += 1
        alt = speicher.get(n["link"])
        if isinstance(alt, dict) and not (alt.get("nochmal") and alt.get("d") != heute):
            stat["gespeichert"] += 1
            _anwenden(n, alt)
        else:
            offen.append(n)
    stat["ohne_budget"] = max(0, len(offen) - MAX_ABRUFE)
    offen = offen[:MAX_ABRUFE]
    start = time.monotonic()
    if offen:
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            auftrag = {pool.submit(_pruefen, n): n for n in offen}
            try:
                for fut in as_completed(auftrag, timeout=ZEIT_S):
                    n = auftrag[fut]
                    try:
                        f = fut.result()
                    except Exception as e:
                        stat["fehler"] += 1
                        _log("[X-URSPRUNG fehler] %s: %s" % (n["link"][:90], e.__class__.__name__))
                        continue
                    f["d"] = heute
                    speicher[n["link"]] = f
                    _anwenden(n, f)
                    if f.get("u"):
                        stat["neu_gefunden"] += 1
                        _log("[X-URSPRUNG] %s -> %s (%s)" % (n["link"][:90], f["u"][:120], f["art"]))
                    else:
                        stat["neu_leer"] += 1
            except Exception:                         # Zeitgrenze: Rest naechster Lauf
                stat["fehler"] += sum(1 for f in auftrag if not f.done())
                for f in auftrag:
                    f.cancel()
    stat["mit_ursprung"] = sum(1 for n in news_list if isinstance(n, dict) and n.get("link_ursprung"))
    grenze = (date.today() - timedelta(days=AUFBEWAHREN_TAGE)).isoformat()
    speicher = {k: v for k, v in speicher.items() if isinstance(v, dict) and (v.get("d") or "") >= grenze}
    if speichern:
        try:
            pfad.write_text(json.dumps({
                "_hinweis": "Ursprungsquelle je Meldungslink, geschrieben von x_ursprung.py. "
                            "u leer = geprueft, nichts gefunden.",
                "eintraege": dict(sorted(speicher.items())),
            }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except Exception as e:
            _log("X-URSPRUNG: Speicher nicht geschrieben (%s)" % e)
    _log("X-URSPRUNG: %s (%.1f s)" % (json.dumps(stat), time.monotonic() - start))
    return stat


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    quelle = Path(sys.argv[1] if len(sys.argv) > 1 else "news.json")
    daten = json.loads(quelle.read_text(encoding="utf-8"))
    liste = daten["news"] if isinstance(daten, dict) else daten
    nachtragen(quelle.parent, liste, speichern=False)
    for n in liste:
        if n.get("link_ursprung"):
            print("-", n.get("source"), "|", (n.get("title") or "")[:70])
            print("   ", n["ursprung_art"], n["ursprung_name"], n["link_ursprung"])
