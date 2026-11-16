#!/usr/bin/env python3
"""Ursprungsquelle fuer Meldungen aus X-Sammlern (15.11.26, Daniel).

Anlass (Daniel 15.11.):
- AlignedNews liefert nur den X-Beitrag. Die eigentliche Quelle steht oft im Beitrag selbst
  oder in der ersten Antwort des Autors. Agile Robots: @roboticomarket schreibt den Text, der
  Link auf robotico.market steht erst in der Antwort darunter.
- Digg AI fasst X-Beitraege zu einer Seite zusammen (unter /ai/, /tech/, /world-business/ und
  weiteren Bereichen, siehe DIGG_ALLE_BEREICHE). Welcher Beitrag die Quelle ist, hebt Digg
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

Plauderei-Pruefung fuer Digg (16.11.26, Daniel: "nicht das Geplauder nehmen, sondern den X-Post
anschauen und auswerten"). Gibt ki_news.py eine Pruef-Funktion mit (pruefer), dann holt dieses
Modul bei Digg-Seiten zusaetzlich die Digg-Zusammenfassung (TLDR) und den vollen Text des
hervorgehobenen X-Beitrags und fragt einmal je Meldung, ob das Nachricht oder Plauderei ist.
Gespeichert wird nur das Ergebnis ("pl", 0..1) und die Adresse des X-Beitrags ("xp"), nie die
Texte (x_ursprung.json liegt im oeffentlichen Repo). An der Meldung steht danach x_beitrag
(Adresse), damit generate_news_cards.py die Einordnung aus dem X-Text schreiben kann.

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
# 16.11.26: nur in news.json, nicht im Archiv (ki_news.py kopiert nur FELDER dorthin)
FELDER_NEWS = FELDER + ("x_beitrag",)
PLAUDEREI_MAX = 8            # neue Jev-Fragen je Lauf
PLAUDEREI_ZEIT_S = 40        # Zeitgrenze fuer alle Jev-Fragen eines Laufs
PLAUDEREI_FEHLER_MAX = 3     # nach so vielen Fehlern in einem Lauf nicht weiter fragen

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
# 16.11.26 (Daniel: Digg zuerst): Digg legt Storys nicht nur unter /ai/ ab, sondern auch unter
# /tech/, /world-business/, /entertainment/, /gaming/. Im Archiv lagen 83 von 146 Digg-Meldungen
# in diesen Bereichen und bekamen nie eine Ursprungsquelle. Die Seiten sind gleich aufgebaut,
# Offline-Probe an 19 Seiten ausserhalb von /ai/: 10 mit hervorgehobener Quelle.
# /entities/ ist eine Themenseite von Digg selbst, keine Story.
# Kill-Switch: DIGG_ALLE_BEREICHE = False, dann wieder nur /ai/.
DIGG_ALLE_BEREICHE = True
_DIGG_RE = re.compile(r"^https?://(?:www\.)?digg\.com/(?!entities/)[a-z0-9-]+/[A-Za-z0-9]+"
                      if DIGG_ALLE_BEREICHE else
                      r"^https?://(?:www\.)?digg\.com/ai/[A-Za-z0-9]+")
_RSC_MARKE = "self.__next_f.push([1,"
_DIGG_MARKE = '"original-post",'
_TLDR_MARKE = '"data-cluster-detail-tldr"'
_KINDER_MARKE = '"children":"'
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


def _tldr(rsc):
    """Digg-Zusammenfassung (TLDR) aus den Seitendaten. Nur Eingabe fuer die Jev-Frage, wird
    nie gespeichert (Digg-Text)."""
    j = rsc.find(_TLDR_MARKE)
    if j < 0:
        return ""
    ende, teile, i = j + 4000, [], j
    dec = json.JSONDecoder()
    while True:
        i = rsc.find(_KINDER_MARKE, i, ende)
        if i < 0:
            break
        try:
            s, i = dec.raw_decode(rsc, i + len(_KINDER_MARKE) - 1)
        except ValueError:
            break
        if isinstance(s, str) and len(s) >= 20:
            teile.append(s)
    return " ".join(teile)[:800]


def _x_text(pid):
    """Voller Text, Autor und Profil eines X-Beitrags. Nur Eingabe fuer die Jev-Frage, wird
    nie gespeichert."""
    d = _abruf(FX_THREAD + pid, UA, True)
    st = d.get("status") if isinstance(d, dict) else None
    if not isinstance(st, dict):
        return {}
    a = st.get("author") if isinstance(st.get("author"), dict) else {}
    q = st.get("quote") if isinstance(st.get("quote"), dict) else {}
    return {"text": (st.get("text") or (st.get("raw_text") or {}).get("text") or "").strip(),
            "handle": a.get("screen_name") or "", "name": a.get("name") or "",
            "bio": (a.get("description") or "").strip(), "zitat": (q.get("text") or "").strip()}


def _aus_digg(seite, mit_text=False):
    """Hervorgehobene Quelle ("Featured Source") einer Digg-AI-Seite.

    Digg legt sie in den Seitendaten als Objekt hinter "original-post" ab:
    {video, embedHtml, source, post: {href: X-Beitrag, linkPreview: {href: Artikel}}, quote}.
    Die ld+json-Liste "citation" ist nur nach Zeit sortiert und taugt nicht als Quelle.
    Messung 15.11.: 27 von 32 Digg-Seiten haben den Eintrag, 3 davon mit verlinktem Artikel.
    Die anderen 5 sind Sammlungen ohne hervorgehobene Quelle. Die werden nicht geraten, sondern
    hoechstens einmal am Tag neu gefragt (Digg kann die Quelle spaeter nachtragen).

    16.11.26: "xp" = Adresse des hervorgehobenen X-Beitrags (auch wenn er auf einen Artikel
    verlinkt). mit_text: dazu fluechtig "_tldr", "_x" und "_link_titel" fuer die Jev-Frage.
    Schluessel mit "_" werden nie gespeichert."""
    rsc = _rsc(_abruf(seite, UA_SEITE, False))
    if not rsc:
        raise ValueError("Digg-Seite ohne Seitendaten")
    zusatz = {"_tldr": _tldr(rsc)} if mit_text else {}

    def _mit(f):
        f.update(zusatz)
        return f

    k = rsc.find(_DIGG_MARKE)
    if k < 0:
        return _mit({"u": "", "nochmal": 1})
    obj, _ = json.JSONDecoder().raw_decode(rsc, k + len(_DIGG_MARKE))
    if not isinstance(obj, dict):
        raise ValueError("Digg original-post ohne Objekt")
    post = obj.get("post") if isinstance(obj.get("post"), dict) else {}
    vorschau = post.get("linkPreview") if isinstance(post.get("linkPreview"), dict) else {}
    p = _x_post(post.get("href"))
    if p:
        zusatz["xp"] = "https://x.com/%s/status/%s" % p
    if mit_text:
        if isinstance(vorschau.get("title"), str):
            zusatz["_link_titel"] = vorschau["title"].strip()[:200]
        if p:
            try:
                x = _x_text(p[1])
            except Exception:                         # geloescht oder FxTwitter gestoert
                x = {}
            if not x.get("text"):                     # Digg-Kopie, wenn sie nicht nur ein Verweis ist
                t = post.get("text")
                if isinstance(t, str) and len(t) > 3 and not t.startswith("$"):
                    x = {"text": t.strip(), "handle": p[0]}
            if x.get("text"):
                zusatz["_x"] = x
    u = vorschau.get("href")
    if isinstance(u, str) and u.startswith("http"):
        u = _aufloesen(u)
        if not _passt(_host(u), _KEINE_QUELLE):
            return _mit(_fund(u, "digg-link"))
    if p:
        return _mit(_fund("https://x.com/%s/status/%s" % p, "digg-x"))
    quelle = obj.get("source")
    u = (quelle.get("href") or quelle.get("url")) if isinstance(quelle, dict) else quelle
    if isinstance(u, str) and u.startswith("http") and not _passt(_host(u), _KEINE_QUELLE):
        return _mit(_fund(_aufloesen(u), "digg"))
    return _mit({"u": "", "nochmal": 1})


def _pruefen(n, mit_text=False):
    if _x_post(n.get("link")):
        return _aus_x(n["link"])
    return _aus_digg(_digg_seite(n), mit_text)


def _anwenden(n, f):
    for feld in FELDER_NEWS:
        n.pop(feld, None)
    if f and f.get("u"):
        n["link_ursprung"] = f["u"]
        n["ursprung_name"] = f.get("name") or _host(f["u"])
        n["ursprung_art"] = f.get("art") or ""
    if f and f.get("xp"):
        n["x_beitrag"] = f["xp"]


def _plauderei_text(n, f):
    """Eingabe fuer die Jev-Frage: Titel, Digg-Zusammenfassung, X-Beitrag mit Autor und Profil,
    Titel des verlinkten Artikels. Leer, wenn es nichts ausser dem Titel gibt."""
    teile = []
    tldr = (f.get("_tldr") or "").strip()
    x = f.get("_x") if isinstance(f.get("_x"), dict) else {}
    if not tldr and not x.get("text"):
        return ""
    teile.append("Titel: " + str(n.get("title") or "").strip())
    if tldr:
        teile.append("Zusammenfassung von Digg: " + tldr[:700])
    if x.get("text"):
        wer = "@" + (x.get("handle") or "?")
        if x.get("name"):
            wer += " (" + x["name"] + ")"
        teile.append("Von Digg hervorgehobener X-Beitrag, Autor: " + wer)
        if x.get("bio"):
            teile.append("Profil des Autors: " + " ".join(x["bio"].split())[:160])
        teile.append("Beitrag: " + x["text"][:900])
        if x.get("zitat"):
            teile.append("Darin zitiert: " + x["zitat"][:400])
    if f.get("_link_titel"):
        teile.append("Verlinkter Artikel: " + f["_link_titel"])
    return "\n".join(teile)


def _lade(pfad):
    try:
        d = json.loads(Path(pfad).read_text(encoding="utf-8"))
        return d.get("eintraege") if isinstance(d.get("eintraege"), dict) else {}
    except Exception:
        return {}


def _jev_offen(n, alt, pruefer, heute):
    """Digg-Meldung, die noch kein Plauderei-Urteil hat und heute noch nicht gefragt wurde."""
    return bool(pruefer and _digg_seite(n) and isinstance(alt, dict)
                and "pl" not in alt and alt.get("pv") != heute)


def nachtragen(base_dir, news_list, speichern=True, pruefer=None):
    """Setzt link_ursprung/ursprung_name/ursprung_art an Meldungen von AlignedNews (X-Beitrag)
    und Digg AI, bei Digg dazu x_beitrag. Aendert news_list in place. Gibt eine Zaehlung zurueck,
    darin "urteile" = {Meldungslink: Plauderei-Wahrscheinlichkeit} fuer Digg-Meldungen.

    pruefer (16.11.26): Funktion Text -> Wahrscheinlichkeit 0..1, dass es Plauderei ist (Jev,
    kommt aus ki_news.py). None = keine Plauderei-Pruefung, alles wie vorher."""
    pfad = Path(base_dir) / SPEICHER
    speicher = _lade(pfad)
    heute = date.today().isoformat()
    stat = {"kandidaten": 0, "gespeichert": 0, "neu_gefunden": 0, "neu_leer": 0,
            "fehler": 0, "ohne_budget": 0, "mit_ursprung": 0,
            "plauderei_gefragt": 0, "plauderei_fehler": 0}
    offen = []
    for n in news_list:
        if not isinstance(n, dict) or not n.get("link"):
            continue
        if not (_x_post(n.get("link")) or _digg_seite(n)):
            continue
        stat["kandidaten"] += 1
        alt = speicher.get(n["link"])
        if (isinstance(alt, dict) and not (alt.get("nochmal") and alt.get("d") != heute)
                and not _jev_offen(n, alt, pruefer, heute)):
            stat["gespeichert"] += 1
            _anwenden(n, alt)
        else:
            if isinstance(alt, dict):
                _anwenden(n, alt)                     # bisheriger Stand, falls der Abruf scheitert
            offen.append(n)
    offen.sort(key=lambda n: n["link"] in speicher)   # neue Meldungen zuerst, Nachfragen danach
    stat["ohne_budget"] = max(0, len(offen) - MAX_ABRUFE)
    offen = offen[:MAX_ABRUFE]
    start = time.monotonic()
    fuer_jev = []
    if offen:
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            auftrag = {}
            for n in offen:
                alt = speicher.get(n["link"])
                mit_text = bool(pruefer and _digg_seite(n)
                                and not (isinstance(alt, dict) and "pl" in alt))
                auftrag[pool.submit(_pruefen, n, mit_text)] = n
            try:
                for fut in as_completed(auftrag, timeout=ZEIT_S):
                    n = auftrag[fut]
                    try:
                        f = fut.result()
                    except Exception as e:
                        stat["fehler"] += 1
                        _log("[X-URSPRUNG fehler] %s: %s" % (n["link"][:90], e.__class__.__name__))
                        continue
                    alt = speicher.get(n["link"])
                    if isinstance(alt, dict) and "pl" in alt:   # Urteil gilt weiter
                        f["pl"] = alt["pl"]
                    f["d"] = heute
                    speicher[n["link"]] = f
                    _anwenden(n, f)
                    if pruefer and _digg_seite(n) and "pl" not in f:
                        fuer_jev.append(n)
                    if f.get("u"):
                        stat["neu_gefunden"] += 1
                        _log("[X-URSPRUNG] %s -> %s (%s)" % (n["link"][:90], f["u"][:120], f["art"]))
                    else:
                        stat["neu_leer"] += 1
            except Exception:                         # Zeitgrenze: Rest naechster Lauf
                stat["fehler"] += sum(1 for f in auftrag if not f.done())
                for f in auftrag:
                    f.cancel()
    # Plauderei-Pruefung: einmal je Digg-Meldung, nacheinander, mit Zeit- und Fehlergrenze
    jev_start = time.monotonic()
    for n in fuer_jev:
        f = speicher[n["link"]]
        if (stat["plauderei_gefragt"] >= PLAUDEREI_MAX
                or stat["plauderei_fehler"] >= PLAUDEREI_FEHLER_MAX
                or time.monotonic() - jev_start > PLAUDEREI_ZEIT_S):
            break                                     # Rest im naechsten Lauf
        text = _plauderei_text(n, f)
        f["pv"] = heute
        if not text:
            continue
        try:
            p = float(pruefer(text))
        except Exception as e:
            stat["plauderei_fehler"] += 1
            _log("[PLAUDEREI-JEV fehler] %s: %s" % (n["link"][:90], e.__class__.__name__))
            continue
        stat["plauderei_gefragt"] += 1
        f["pl"] = round(p, 3)
        x = f.get("_x") or {}
        _log("[PLAUDEREI-JEV p=%.2f] %s | %s | %s" % (
            p, _digg_seite(n)[:70], ("@" + x["handle"]) if x.get("handle") else "ohne X-Beitrag",
            str(n.get("title") or "")[:70]))
    urteile = {}
    for n in news_list:
        if isinstance(n, dict) and _digg_seite(n):
            f = speicher.get(n.get("link"))
            if isinstance(f, dict) and isinstance(f.get("pl"), (int, float)):
                urteile[n["link"]] = f["pl"]
    stat["mit_ursprung"] = sum(1 for n in news_list if isinstance(n, dict) and n.get("link_ursprung"))
    grenze = (date.today() - timedelta(days=AUFBEWAHREN_TAGE)).isoformat()
    speicher = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                for k, v in speicher.items() if isinstance(v, dict) and (v.get("d") or "") >= grenze}
    if speichern:
        try:
            pfad.write_text(json.dumps({
                "_hinweis": "Ursprungsquelle je Meldungslink, geschrieben von x_ursprung.py. "
                            "u leer = geprueft, nichts gefunden. pl = Plauderei-Urteil (Jev).",
                "eintraege": dict(sorted(speicher.items())),
            }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except Exception as e:
            _log("X-URSPRUNG: Speicher nicht geschrieben (%s)" % e)
    _log("X-URSPRUNG: %s (%.1f s)" % (json.dumps(stat), time.monotonic() - start))
    stat["urteile"] = urteile
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
