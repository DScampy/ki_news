#!/usr/bin/env python3
"""X-Posts zu Releases und Top-Meldungen, ausschliesslich ueber die HuggingNews-API (28.09.26).

Daniel: X-Links nur ueber HuggingNews (Secret HUGGINGNEWS_API, wie Themenkette), keine X-API.
HuggingNews liefert je Story "selectedTweets" (role source/support/commentary/analysis/signal,
authorHandle, url, bestBit). Dieses Skript nimmt daraus NUR Posts von fest gepflegten,
offiziellen Konten, nichts wird geraten:

- hersteller.json: je Release der Post des Herstellers (HERSTELLER_HANDLES) aus einer Story,
  deren Titel das Modell nennt -> x_url. Analysen bekannter Benchmark-Konten
  (ANALYSE_HANDLES, z.B. @ArtificialAnlys) -> x_analysen.
- news.json: Top-Meldungen (TOP_N nach Score), die themenketten.json derselben HuggingNews-Story
  zuordnet (rolle "ereignis"), bekommen den Post ihrer eigenen Quelle (QUELLEN_HANDLES,
  z.B. Bloomberg -> @business) -> x_quelle {url, handle, text}.

Der HuggingNews-Feed reicht nur drei Tage zurueck. Funde stehen darum in x_quellen.json
und werden bei jedem Lauf wieder angewendet (Release-URL bzw. Meldungs-Link als Schluessel;
story_id wechselt je Lauf). Ohne Netz/Key oder bei Fehlern: Dateien bleiben unveraendert.

Aufruf: python3 x_quellen.py [--dry-run]     Key optional: HUGGINGNEWS_API_KEY
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
HN_API = "https://api.huggingnews.com/api/stories"
SPEICHER = BASE / "x_quellen.json"
TOP_N = 30
AUFBEWAHREN_TAGE = 21

# Offizielle Konten, kleingeschrieben. Nur hier gelistete Konten werden verlinkt.
HERSTELLER_HANDLES = {
    "OpenAI": {"openai", "openaidevs", "chatgptapp"},
    "Anthropic": {"anthropicai", "claudeai"},
    "Google": {"google", "googledeepmind", "googleai", "geminiapp", "googlefordevs"},
    "Meta": {"aiatmeta"},
    "xAI": {"xai"},
    "Mistral": {"mistralai"},
    "Alibaba Qwen": {"alibaba_qwen"},
    "DeepSeek": {"deepseek_ai"},
    "ElevenLabs": {"elevenlabs", "elevenlabsio"},
    "Nvidia": {"nvidia", "nvidianewsroom", "nvidiaai"},
}
ANALYSE_HANDLES = {"artificialanlys", "epochairesearch", "lmarena_ai", "semianalysis_"}
QUELLEN_HANDLES = {
    "Bloomberg AI": {"business", "technology", "bloomberg"},
    "TechCrunch AI": {"techcrunch"},
    "CNBC": {"cnbc", "cnbctech"},
    "The Verge": {"verge"},
    "Wired": {"wired"},
    "WSJ AI": {"wsj", "wsjtech"},
    "Reuters AI": {"reuters", "reutersbiz", "reuterstech"},
    "FT AI": {"ft"},
    "NYT Technology": {"nytimes", "nytimestech"},
    "Economist AI": {"theeconomist"},
    "Ars Technica": {"arstechnica"},
    "Heise": {"heiseonline"},
    "Golem": {"golem"},
    "SiliconAngle": {"siliconangle"},
    "TechRepublic": {"techrepublic"},
    "CNet": {"cnet"},
    "OpenAI": {"openai", "openaidevs"},
    "Google AI Blog": {"google", "googleai", "googledeepmind"},
    "Anthropic News": {"anthropicai"},
    "Anthropic Research": {"anthropicai"},
}


def log(msg):
    print(msg, flush=True)


def _lade(pfad, default):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return default


def _schreibe(pfad, daten):
    Path(pfad).write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hn(url, key, versuche=2):
    kopf = {"User-Agent": "ki-news.live"}
    if key:
        kopf["Authorization"] = "Bearer " + key
    for i in range(versuche):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < versuche - 1:
                time.sleep(3)
                continue
            raise


def _https_x(url):
    return url if isinstance(url, str) and re.match(r"^https://(x|twitter)\.com/[A-Za-z0-9_]+/status/\d+$", url) else ""


def _tweet(t):
    url = _https_x(t.get("url"))
    if not url:
        return None
    return {"url": url, "handle": str(t.get("authorHandle") or "").strip(),
            "text": re.sub(r"\s+", " ", str(t.get("bestBit") or "")).strip()[:280],
            "rolle": t.get("role") or "", "zeit": t.get("tweetedAt")}


def _norm(s):
    return re.sub(r"[^a-z0-9.]+", " ", str(s or "").lower()).strip()


def _tage_abstand(ereignis, datum):
    """Tage von Release-Datum (YYYY-MM-DD) bis HuggingNews-Ereigniszeit (ISO), oder None."""
    try:
        from datetime import date
        return (date.fromisoformat(str(ereignis)[:10]) - date.fromisoformat(str(datum)[:10])).days
    except Exception:
        return None


def modell_kern(modell):
    """Kern des Modellnamens fuer den Titelabgleich: 'GPT-6 Sol' -> 'gpt 6', 'Claude Opus 5.5'
    -> 'opus 5.5', 'Gemini 3.8 text-to-speech' -> 'gemini 3.8'."""
    toks = str(modell or "").replace("-", " ").split()
    for i, t in enumerate(toks):
        if re.search(r"\d", t):
            if re.search(r"[A-Za-z]", t):
                return _norm(t)
            return _norm((toks[i - 1] + " " + t) if i else t)
    return _norm(modell)


def hole_storys(key):
    feed = _hn(HN_API, key)
    slugs = [s["slug"] for g in feed.get("dayGroups", []) for s in g.get("stories", []) if s.get("slug")]
    return {slug: d for slug, d in details(slugs, key).items() if d}


def details(slugs, key):
    def eins(slug):
        try:
            return slug, _hn(HN_API + "/" + urllib.parse.quote(slug), key)
        except Exception:
            return slug, None
    with ThreadPoolExecutor(4) as pool:
        return dict(pool.map(eins, list(dict.fromkeys(slugs))))


def release_posts(releases, storys, speicher):
    geaendert = 0
    for r in releases:
        eintrag = speicher.setdefault(r.get("url") or r.get("modell"), {})
        kern = modell_kern(r.get("modell"))
        offiziell = HERSTELLER_HANDLES.get(r.get("hersteller"), set())
        for slug, d in storys.items():
            if not kern or kern not in _norm(d.get("title")):
                continue
            # Zeitfenster: Hersteller-Post nur aus der Story zur Ankuendigung (+-2 Tage), sonst
            # traefe z.B. "OpenAI fixes GPT-6 vision bug" (Tage spaeter) als "Release-Post".
            abstand = _tage_abstand(d.get("eventTimeApprox"), r.get("datum"))
            if abstand is None or abstand < -2 or abstand > 7:
                continue
            tweets = [x for x in (_tweet(t) for t in d.get("selectedTweets") or []) if x]
            if not eintrag.get("x_url") and abs(abstand) <= 2:
                eigen = [t for t in tweets if t["handle"].lower() in offiziell]
                eigen.sort(key=lambda t: (t["rolle"] != "source", t["zeit"] or 0))
                if eigen:
                    eintrag.update({"x_url": eigen[0]["url"], "x_handle": eigen[0]["handle"], "hn_slug": slug})
            # Video des Hersteller-Posts (Auftrag 10 Punkt 7): HuggingNews liefert es als Story-Bild
            # (image.mediaType video, videoUrl, credit.tweetUrl) - nur von offiziellen Konten
            bild = d.get("image") or {}
            credit = bild.get("credit") or {}
            if (not eintrag.get("video_url") and abs(abstand) <= 2 and bild.get("mediaType") == "video"
                    and str(credit.get("handle") or "").lower() in offiziell
                    and re.match(r"^https://video\.twimg\.com/", str(bild.get("videoUrl") or ""))):
                eintrag["video_url"] = bild["videoUrl"]
                if bild.get("url"):
                    eintrag["poster"] = bild["url"]
                if not eintrag.get("x_url") and _https_x(credit.get("tweetUrl")):
                    eintrag.update({"x_url": credit["tweetUrl"], "x_handle": credit.get("handle", ""), "hn_slug": slug})
            analysen = eintrag.setdefault("x_analysen", [])
            for t in tweets:
                if t["handle"].lower() in ANALYSE_HANDLES and t["url"] not in [a["url"] for a in analysen]:
                    analysen.append({"url": t["url"], "handle": t["handle"], "text": t["text"]})
        eintrag["gesehen"] = time.strftime("%Y-%m-%d")
        vorher = (r.get("x_url"), r.get("video_url"), json.dumps(r.get("x_analysen") or []))
        if eintrag.get("x_url"):
            r["x_url"] = eintrag["x_url"]
        if eintrag.get("video_url") and not r.get("video_url"):
            r["video_url"] = eintrag["video_url"]
            if eintrag.get("poster") and not r.get("poster"):
                r["poster"] = eintrag["poster"]
        if eintrag.get("x_analysen"):
            r["x_analysen"] = eintrag["x_analysen"][:3]
        geaendert += vorher != (r.get("x_url"), r.get("video_url"), json.dumps(r.get("x_analysen") or []))
    return geaendert


def quellen_posts(news, zuordnung, storys, speicher, key):
    top = sorted((a for a in news if isinstance(a, dict) and a.get("link")),
                 key=lambda a: -float(a.get("score") or 0))[:TOP_N]
    fehlt = [z["hn_slug"] for a in top for z in [zuordnung.get(a["link"]) or {}]
             if z.get("rolle") == "ereignis" and z.get("hn_slug") and z["hn_slug"] not in storys
             and a["link"] not in speicher]
    if fehlt:
        storys.update({s: d for s, d in details(fehlt, key).items() if d})
    geaendert = 0
    for a in top:
        eintrag = speicher.get(a["link"])
        z = zuordnung.get(a["link"]) or {}
        if not eintrag and z.get("rolle") == "ereignis" and z.get("hn_slug") in storys:
            eigene = QUELLEN_HANDLES.get(a.get("source"), set())
            tweets = [x for x in (_tweet(t) for t in storys[z["hn_slug"]].get("selectedTweets") or []) if x]
            passend = [t for t in tweets if t["handle"].lower() in eigene]
            passend.sort(key=lambda t: (t["rolle"] != "source", t["zeit"] or 0))
            if passend:
                t = passend[0]
                eintrag = speicher[a["link"]] = {"url": t["url"], "handle": t["handle"], "text": t["text"],
                                                 "hn_slug": z["hn_slug"]}
        if eintrag:
            eintrag["gesehen"] = time.strftime("%Y-%m-%d")
            neu = {"url": eintrag["url"], "handle": eintrag["handle"], "text": eintrag.get("text", "")}
            if a.get("x_quelle") != neu:
                a["x_quelle"] = neu
                geaendert += 1
    return geaendert


def aufraeumen(speicher):
    grenze = time.strftime("%Y-%m-%d", time.localtime(time.time() - AUFBEWAHREN_TAGE * 86400))
    for teil in ("releases", "meldungen"):
        speicher[teil] = {k: v for k, v in speicher.get(teil, {}).items() if (v.get("gesehen") or "") >= grenze}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("HUGGINGNEWS_API_KEY", "").strip()
    speicher = _lade(SPEICHER, {})
    speicher.setdefault("releases", {})
    speicher.setdefault("meldungen", {})
    try:
        storys = hole_storys(key)
    except Exception as e:
        log(f"x_quellen: HuggingNews nicht erreichbar ({type(e).__name__}) - nur gespeicherte Funde")
        storys = {}
    log(f"x_quellen: {len(storys)} HuggingNews-Storys")

    hersteller = _lade(BASE / "hersteller.json", None)
    n_rel = 0
    if isinstance(hersteller, dict) and isinstance(hersteller.get("releases"), list):
        n_rel = release_posts(hersteller["releases"], storys, speicher["releases"])
        for r in hersteller["releases"]:
            log(f"  Release {r.get('modell', ''):<28} x_url={r.get('x_url') or '-'}  "
                f"Analysen={len(r.get('x_analysen') or [])}")

    news = _lade(BASE / "news.json", None)
    n_news = 0
    if isinstance(news, dict) and isinstance(news.get("news"), list):
        zuordnung = (_lade(BASE / "themenketten.json", {}) or {}).get("zuordnung") or {}
        n_news = quellen_posts(news["news"], zuordnung, storys, speicher["meldungen"], key)
        for m in news["news"]:
            if m.get("x_quelle"):
                log(f"  Meldung {m.get('source', ''):<14} @{m['x_quelle']['handle']:<14} {m.get('title', '')[:60]}")

    aufraeumen(speicher)
    log(f"x_quellen: {n_rel} Release(s) und {n_news} Meldung(en) geaendert")
    if a.dry_run:
        return 0
    if n_rel:
        _schreibe(BASE / "hersteller.json", hersteller)
    if n_news:
        _schreibe_news(news)
    _schreibe(SPEICHER, speicher)
    return 0


def _schreibe_news(news):
    # gleiches Format wie ki_news.py (indent=2, ohne Zeilenumbruch am Ende) -> kleiner Diff
    roh = (BASE / "news.json").read_text(encoding="utf-8")
    einrueckung = 2 if roh.startswith("{\n  ") else None
    (BASE / "news.json").write_text(json.dumps(news, ensure_ascii=False, indent=einrueckung)
                                    + ("\n" if roh.endswith("\n") else ""), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
