#!/usr/bin/env python3
"""X-Belege fuer Recherche-Artikel (10.11.26, Daniel, Plan R1): Schattenbetrieb.

Anlass (Messung 10.11.): Der Nvidia/Huang-Fall wurde im 09-UTC-Lauf zweimal uebersprungen
(s008: 0, s009: 1 Quelle mit Text). Genug Medien berichteten, aber alle nur ueber news.google.com
oder hinter Bezahlschranke (Reuters, FT, Economist, WSJ). HuggingNews fuehrt denselben Fall als
Kette (themenketten.json, 33 Storys seit 29.10.) und waehlt je Story X-Posts mit Rolle aus.

Dieses Modul sammelt zu einem Recherche-Kandidaten die X-Posts seiner HuggingNews-Kette und
holt ihren Text ueber FxTwitter (ohne Login, wie add_reactions.py). Links in den Posts zu
Originalseiten werden wie jede andere Quelle gelesen.

Regeln:
- Nur Rolle source und support (ROLLEN). analysis, commentary und signal sind Meinung.
- HuggingNews ist nur Wegweiser (robots.txt use=reference): von dort kommt nur, WELCHE Posts zur
  Story gehoeren. Der Text kommt vom Post selbst. Es wird nichts gespeichert.
- Daniels Bedingung (10.11.): Mindestens 3 Medien muessen berichten. Das prueft weiter
  recherche_artikel.kandidaten() (MIN_QUELLEN). X-Posts ersetzen keine Medien, sie fuellen nur
  die Luecke bei MIN_TEXTQUELLEN.
- Nie blockieren: harte Zeitgrenze, jeder Fehler ergibt ein leeres Ergebnis.

R1 = Schatten: recherche_artikel.py schreibt das Ergebnis nur ins Log, kein Artikel aendert sich.
Kill-Switch dort: X_BELEGE = "aus".

Test ohne Pipeline:  python3 x_belege.py s008      (liest news.json und themenketten.json)
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
HN_API = "https://api.huggingnews.com/api/stories"
FX_API = "https://api.fxtwitter.com/status/"
UA = "ki-news.live (+https://ki-news.live)"

ROLLEN = ("source", "support")
MAX_HN_STORYS = 6       # je Kandidat: direkt zugeordnete HN-Storys zuerst, dann die neuesten Glieder
MAX_POSTS = 8           # je Kandidat
MAX_ORIGINALE = 2       # verlinkte Originalseiten je Kandidat, die gelesen werden
TIMEOUT_S = 10
_NICHT_ORIGINAL = ("x.com", "twitter.com", "t.co", "pbs.twimg.com", "video.twimg.com")


def _json(url, key=""):
    kopf = {"User-Agent": UA, "Accept": "application/json"}
    if key:
        kopf["Authorization"] = "Bearer " + key
    with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=TIMEOUT_S) as r:
        return json.loads(r.read())


def _post_id(url):
    m = re.match(r"^https://(?:x|twitter)\.com/[A-Za-z0-9_]+/status/(\d+)", str(url or ""))
    return m.group(1) if m else ""


def _domain(url):
    try:
        d = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return d[4:] if d.startswith("www.") else d


def _ist_x(url):
    d = _domain(url)
    return any(d == x or d.endswith("." + x) for x in _NICHT_ORIGINAL)


def kette_zu(links, themen):
    """(kette_id, direkte HN-Slugs) fuer die Links eines Kandidaten. Die Kette, der die meisten
    Links zugeordnet sind, gewinnt (s008: 3 von 4 Links in der Huang-Kette). Direkte Slugs nur
    aus dieser Kette und nur mit Rolle "ereignis": Test 10.11. hatte in der Meta-Story (s000)
    einen WCCFtech-Link der Fable-Kette, ohne diese Regel kamen @claudeai-Posts in die Meta-Belege."""
    zuordnung = themen.get("zuordnung") or {}
    treffer = [zuordnung.get(link) or {} for link in links]
    ketten = Counter(z["kette"] for z in treffer if z.get("kette"))
    if not ketten:
        return "", []
    kette = ketten.most_common(1)[0][0]
    direkt = []
    for z in treffer:
        if z.get("kette") == kette and z.get("rolle") == "ereignis" and z.get("hn_slug") \
                and z["hn_slug"] not in direkt:
            direkt.append(z["hn_slug"])
    return kette, direkt


def hn_slugs(kette, direkt, themen, max_n=MAX_HN_STORYS):
    glieder = ((themen.get("ketten") or {}).get(kette) or {}).get("glieder") or []
    out = []
    for s in list(direkt) + list(reversed(glieder)):      # Glieder sind alt -> neu
        if s and s not in out:
            out.append(s)
    return out[:max_n]


def hn_posts(slugs, key, ende, cache):
    """Ausgewaehlte Posts (Rolle source/support) der HN-Storys, ohne Doppel. Nur URL, Handle,
    Rolle, Zeit und Slug, kein HN-Text."""
    posts, gesehen = [], set()
    for slug in slugs:
        if time.monotonic() > ende:
            break
        if slug not in cache:
            try:
                cache[slug] = _json(HN_API + "/" + urllib.parse.quote(slug), key)
            except (urllib.error.URLError, OSError, ValueError):
                cache[slug] = None
        story = cache[slug] or {}
        for t in story.get("selectedTweets") or []:
            pid = _post_id(t.get("url"))
            if not pid or pid in gesehen or t.get("role") not in ROLLEN:
                continue
            gesehen.add(pid)
            posts.append({"id": pid, "url": t["url"], "handle": str(t.get("authorHandle") or ""),
                          "rolle": t["role"], "zeit": t.get("tweetedAt"), "hn_slug": slug})
    posts.sort(key=lambda p: (p["rolle"] != "source", str(p["zeit"] or "")))
    return posts


def fx_post(pid, cache):
    """Text eines Posts ueber FxTwitter: eigener Text plus zitierter Post, dazu die Links."""
    if pid in cache:
        return cache[pid]
    try:
        t = (_json(FX_API + pid) or {}).get("tweet") or {}
    except (urllib.error.URLError, OSError, ValueError):
        t = {}
    if not t:
        cache[pid] = None
        return None
    teile = [t.get("text") or ""]
    q = t.get("quote") or {}
    if q.get("text"):
        teile.append("Zitierter Post von @%s: %s" % ((q.get("author") or {}).get("screen_name", ""), q["text"]))
    links = []
    for f in (t.get("raw_text") or {}).get("facets") or []:
        u = f.get("replacement") or ""
        if f.get("type") == "url" and u.startswith("https://") and not _ist_x(u):
            links.append(u)
    a = t.get("author") or {}
    cache[pid] = {"name": a.get("name") or "", "handle": a.get("screen_name") or "",
                  "text": re.sub(r"\s+", " ", " ".join(teile)).strip(), "lang": t.get("lang") or "",
                  "zeit": t.get("created_timestamp"), "links": list(dict.fromkeys(links)),
                  "medien": len((t.get("media") or {}).get("all") or [])}
    return cache[pid]


def sammeln(k, themen, key="", dp=None, quelltext=None, ende=None, cache=None):
    """Ergebnis fuer einen Kandidaten k (recherche_artikel.kandidaten). quelltext(m, dp) liest
    Originalseiten (recherche_artikel._quelltext). Ohne dp/quelltext werden keine Seiten gelesen."""
    ende = ende or time.monotonic() + 45
    cache = cache if cache is not None else {}
    erg = {"kette": "", "hn": 0, "posts": [], "leer": 0, "originale": [], "zeichen": 0}
    kette, direkt = kette_zu(k.get("links") or [], themen)
    erg["kette"] = kette
    slugs = hn_slugs(kette, direkt, themen)
    erg["hn"] = len(slugs)
    if not slugs:
        return erg
    hn = cache.setdefault("hn", {})
    fx = cache.setdefault("fx", {})
    for p in hn_posts(slugs, key, ende, hn)[:MAX_POSTS]:
        if time.monotonic() > ende:
            break
        d = fx_post(p["id"], fx)
        if not d or not d["text"]:
            erg["leer"] += 1
            continue
        erg["posts"].append({**p, **{x: d[x] for x in ("name", "text", "lang", "links", "medien")},
                             "handle": d["handle"] or p["handle"]})
    erg["zeichen"] = sum(len(p["text"]) for p in erg["posts"])
    if quelltext and dp is not None:
        bekannt = {_domain(u) for g in k.get("glieder") or [] for u in (g.get("link_verlag"), g.get("link")) if u}
        kandidat = []
        for p in erg["posts"]:
            for u in p["links"]:
                if _domain(u) not in bekannt and u not in kandidat:
                    kandidat.append(u)
        for u in kandidat[:MAX_ORIGINALE]:
            if time.monotonic() > ende:
                break
            try:
                t = quelltext({"link": u}, dp)
            except Exception:
                t = ""
            erg["originale"].append({"link": u, "zeichen": len(t or ""), "hat_text": bool(t)})
    return erg


def bewertung(erg, mit_text, min_textquellen, min_zeichen):
    """Was die Zaehlregel aus R2 ergaebe. Regel A: X-Posts zusammen hoechstens 1 Textquelle,
    mindestens 1 klassische Textquelle (Medium oder verlinkte Originalseite) bleibt Pflicht.
    Regel B: wie A, aber ohne die Pflicht."""
    originale = sum(1 for o in erg["originale"] if o["hat_text"])
    x = 1 if erg["zeichen"] >= min_zeichen else 0
    klassisch = mit_text + originale
    neu = klassisch + x
    return {"neu": neu, "a": neu >= min_textquellen and klassisch >= 1, "b": neu >= min_textquellen,
            "originale": originale, "x": x}


def logzeile(sid, erg, mit_text, bew):
    if not erg["kette"] and not erg["hn"]:
        return f"[RECHERCHE] X-Schatten {sid}: keine HuggingNews-Kette"
    rollen = Counter(p["rolle"] for p in erg["posts"])
    konten = ", ".join("@" + p["handle"] for p in erg["posts"][:5])
    ja = lambda b: "ja" if b else "nein"
    return (f"[RECHERCHE] X-Schatten {sid}: Kette {erg['kette'][:40] or '-'} ({erg['hn']} HN-Storys), "
            f"{len(erg['posts'])} Posts ({rollen.get('source', 0)} source, {rollen.get('support', 0)} support, "
            f"{erg['leer']} leer, {erg['zeichen']} Zeichen) [{konten}], "
            f"Originalseiten {bew['originale']}/{len(erg['originale'])} mit Text, "
            f"Textquellen {mit_text} -> {bew['neu']}, wuerde schreiben: Regel A {ja(bew['a'])}, Regel B {ja(bew['b'])}")


def _test(sid):
    news = json.loads((BASE / "news.json").read_text(encoding="utf-8")).get("news") or []
    themen = json.loads((BASE / "themenketten.json").read_text(encoding="utf-8"))
    glieder = [n for n in news if str(n.get("story_id", "")) == sid or str(n.get("story_id", "")).endswith(sid)]
    links = sorted({u for g in glieder for u in (g.get("link"), g.get("link_verlag")) if u})
    erg = sammeln({"sid": sid, "links": links, "glieder": glieder}, themen)
    print(logzeile(sid, erg, 0, bewertung(erg, 0, 2, 600)))
    for p in erg["posts"]:
        print(f"  {p['rolle']:<7} @{p['handle']:<16} {p['lang']:<3} {len(p['text']):>5} Z. Links {len(p['links'])}  {p['url']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(_test(sys.argv[1]) if len(sys.argv) > 1 else 0)
