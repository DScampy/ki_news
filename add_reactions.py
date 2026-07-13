#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_reactions.py — reichert news.json mit Community-Reaktionen an.

Zwei unabhaengige Quellen, beide unattended-sicher fuer GitHub Actions:

1. X/Twitter (manuell kuratiert, siehe reactions.json)
   Die 4x-taegliche Pipeline soll NICHT automatisiert auf X suchen
   (Account-Risiko fuer @ScampyKI, siehe Session-Notiz 12.07.26). Reaktions-
   Tweets werden stattdessen manuell/halbautomatisch kuratiert (z.B. per
   Claude-in-Chrome-Session mit eingeloggtem Browser) und in reactions.json
   eingetragen. Dieses Script holt sich dann NUR die Tweet-Metadaten
   (Text/Autor/Likes) ueber die freie fxtwitter-API - kein Login, kein
   X-Scraping, kein Risiko.

2. Hacker News (vollautomatisch, neu 13.07.26)
   Offene, unauthentifizierte JSON-API (Algolia) - kein Login, kein Konto-
   Risiko, unattended-sicher. Nur fuer die Top-N-Storys (dieselbe Auswahl
   wie das Hero-Carousel auf der Website, siehe top_n_stories()).

Reddit bewusst NICHT dabei (entfernt 13.07.26): Reddits unauthentifizierte
JSON-API (search.json, r/<sub>/.json) blockt Cloud-/Datacenter-IP-Ranges mit
HTTP 403 - bestaetigt sowohl aus einer Sandbox-IP als auch live aus einem
echten GitHub-Actions-Lauf (Run #670, 13.07.26: 403 auf jeder Subreddit-
Anfrage, jede Story). Kein Header- oder Query-Problem, sondern IP-basiertes
Blocking. Fix waere OAuth (eigene Reddit-"Script"-App, oauth.reddit.com statt
www.reddit.com), aber der Mehrwert gegenueber HN allein ist gering genug,
dass sich ein weiteres Credential + eine weitere Fehlerquelle nicht lohnt.
Falls das nochmal aufgegriffen wird: OAuth ist der einzige Weg, der
tatsaechlich funktionieren wuerde - reines Retry/UA-Tuning behebt das
IP-Blocking nicht.

Matching der manuellen X-Eintraege per Stichwort im Titel, NICHT per
Artikel-Link: Der repraesentative Link eines Story-Clusters verschiebt sich
zwischen Pipeline-Laeufen (beobachtet 12.07.26 - "Apple vs OpenAI" zeigte
erst the-decoder.de, einen Lauf spaeter techcrunch.com als Top-Link). Ein
Keyword-Match auf den Titel uebersteht das, ein exakter Link-Match nicht.

Expiry fuer manuelle Eintraege (neu 13.07.26): jeder reactions.json-Eintrag
hat ein "created"-Datum. Eintraege aelter als REACTIONS_TTL_DAYS werden beim
Matching ignoriert. Grund: ohne Ablauf koennte ein alter Eintrag (z.B. "apple"
+ "openai" + "eigentum") Monate spaeter einer voellig anderen, neuen Story
mit denselben Stichworten faelschlich zugeordnet werden - niemand wuerde es
merken, die Pipeline bliebe gruen. Gefunden bei Review 13.07.26, vorher nicht
abgedeckt.

Ablauf:
1. reactions.json lesen (manuelle X-Eintraege, mit Ablaufpruefung)
2. news.json + dashboard_config.json lesen
3. Top-N-Storys bestimmen (gleiche Logik wie index.html: blockierte Links
   raus, pro story_id nur staerkster Artikel, gepinnte zuerst, Rest nach
   Score, erste N)
4. Fuer jede Top-Story: erst passenden manuellen X-Eintrag anwenden (falls
   vorhanden + nicht abgelaufen), dann - falls noch Platz (< 2 Reaktionen) -
   Hacker News abfragen
5. news.json zurueckschreiben

Aufruf: python add_reactions.py [--in pfad] [--out pfad] [--no-auto]
(Standard: news.json im selben Ordner, in-place, HN-Autofetch aktiv)
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).parent
REACTIONS_JSON = BASE_DIR / "reactions.json"
DASHBOARD_CONFIG = BASE_DIR / "dashboard_config.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REACTIONS_TTL_DAYS = 21
AUTO_TOP_N = 5
MAX_REACTIONS_PER_STORY = 2

KNOWN_PLAYERS = [
    "OpenAI", "Anthropic", "Google", "Gemini", "DeepMind", "xAI", "Grok",
    "Meta", "Microsoft", "Nvidia", "Mistral", "DeepSeek", "Apple",
    "Hugging Face", "Amazon", "Claude", "ChatGPT", "Perplexity",
    "Stability AI", "Midjourney", "Runway", "Qwen", "Alibaba", "Baidu",
    "Cohere", "Groq", "Sam Altman", "Elon Musk", "Dario Amodei",
    "Demis Hassabis", "Fidji Simo",
]
TITLE_STOPWORDS = {
    "Die", "Der", "Das", "Ein", "Eine", "Und", "Mit", "Fuer", "Für", "Von",
    "Bei", "Nach", "Wird", "Werden", "Neue", "Neuer", "Neues", "Wie", "Was",
    "Diese", "Dieser", "Dieses", "Ueber", "Über", "Zwischen", "Gegen",
}


# ── X (manuell kuratiert) ────────────────────────────────────────────────

def tweet_id_from_url(url):
    m = re.search(r"status(?:es)?/(\d+)", url or "")
    return m.group(1) if m else ""


def fetch_tweet_data(tweet_url, retries=2, timeout=10):
    tweet_id = tweet_id_from_url(tweet_url)
    if not tweet_id:
        return {}
    req = urllib.request.Request(
        f"https://api.fxtwitter.com/status/{tweet_id}",
        headers={"User-Agent": UA, "Accept": "application/json"},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            d = json.loads(raw)
            t = (d or {}).get("tweet") or {}
            if not t:
                return {}
            author = t.get("author") or {}
            return {
                "source": "x",
                "url": tweet_url,
                "author_name": author.get("name", ""),
                "author_handle": author.get("screen_name", ""),
                "author_avatar": author.get("avatar_url", ""),
                "text": t.get("text", ""),
                "likes": t.get("likes", 0),
                "retweets": t.get("retweets", 0),
                "views": t.get("views", 0),
            }
        except (HTTPError, URLError) as e:
            print(f"  Versuch {attempt}/{retries} fehlgeschlagen fuer {tweet_url}: {e}")
            time.sleep(1.5)
        except Exception as e:
            print(f"  Fehler bei {tweet_url}: {e}")
            return {}
    return {}


def entry_expired(entry):
    created = entry.get("created")
    if not created:
        # Alteintraege ohne Datum (vor 13.07.26 angelegt): einmalig durchlassen,
        # aber im Log sichtbar machen, damit sie nachgepflegt werden.
        print(f"  Hinweis: Eintrag '{entry.get('label','?')}' hat kein 'created'-Datum - "
              f"bitte in reactions.json nachtragen, sonst laeuft er nie ab.")
        return False
    try:
        created_dt = datetime.strptime(created, "%Y-%m-%d")
    except ValueError:
        return False
    return datetime.now() - created_dt > timedelta(days=REACTIONS_TTL_DAYS)


def story_matches(title, entry):
    t = (title or "").lower()
    if not all(kw.lower() in t for kw in entry.get("match_all", [])):
        return False
    any_kws = entry.get("match_any", [])
    if any_kws and not any(kw.lower() in t for kw in any_kws):
        return False
    return True


# ── Hacker News (automatisch) ────────────────────────────────────────────
# Reddit-Aequivalent bewusst entfernt (13.07.26) - siehe Modul-Docstring:
# unauthentifizierte Reddit-JSON-API blockt GitHub-Actions-IPs mit 403,
# bestaetigt in Produktion (Run #670). OAuth waere der einzige Fix, lohnt
# sich aber nicht fuer den Mehrwert gegenueber HN allein.

def _http_json(url, headers, timeout=10):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def fetch_hn_reaction(keywords):
    # HN Algolia-API liefert keine verlaesslichen Kommentar-Scores -> statt
    # (frei erfundener) "bester Kommentar" ehrlich nur Story + Diskussion
    # zeigen, keine Kommentar-Qualitaet vortaeuschen, die die API nicht hat.
    query = " ".join(keywords)
    url = ("https://hn.algolia.com/api/v1/search?"
           + urllib.parse.urlencode({"query": query, "tags": "story", "numericFilters": "points>15"}))
    try:
        data = _http_json(url, {"User-Agent": UA})
        hits = data.get("hits", [])
        if not hits:
            return None
        hit = hits[0]
        return {
            "source": "hn",
            "text": hit.get("title", ""),
            "score": hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
        }
    except Exception as e:
        print(f"  HN-Suche fehlgeschlagen fuer '{query}': {e}")
        return None


def title_keywords(title, max_n=3):
    found = [p for p in KNOWN_PLAYERS if p.lower() in (title or "").lower()]
    tokens = re.findall(r"[A-ZÄÖÜ][\wÄÖÜäöüß\-]{3,}", title or "")
    tokens = [t for t in tokens if t not in TITLE_STOPWORDS and t not in found]
    combined = found + tokens
    return combined[:max_n] if combined else [(title or "").split(" ")[0]]


# ── Top-N-Auswahl (repliziert die Hero-Carousel-Logik aus index.html) ──────

def top_n_stories(news_list, config_path=DASHBOARD_CONFIG, n=AUTO_TOP_N):
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except Exception:
        cfg = {}
    blocked = set(cfg.get("blocked_links", []))
    featured_links = cfg.get("featured_links", [])
    featured_set = set(featured_links)

    all_news = [s for s in news_list if s.get("link") not in blocked]

    best_by_story = {}
    for s in all_news:
        sid = s.get("story_id")
        if not sid or s.get("link") in featured_set:
            continue
        if sid not in best_by_story or (s.get("score", 0) or 0) > (best_by_story[sid].get("score", 0) or 0):
            best_by_story[sid] = s
    all_news = [s for s in all_news if not s.get("story_id") or s.get("link") in featured_set or best_by_story.get(s.get("story_id")) is s]

    by_link = {s.get("link"): s for s in all_news if s.get("link")}
    featured = [by_link[l] for l in featured_links if l in by_link]
    non_featured = [s for s in all_news if s.get("link") not in featured_set]
    non_featured.sort(key=lambda s: s.get("score", 0) or 0, reverse=True)

    return (featured + non_featured)[:n]


# ── Orchestrierung ───────────────────────────────────────────────────────

def apply_manual_reactions(news_list, entries):
    matched_stories = 0
    enriched_tweets = 0
    tweet_cache = {}
    active_entries = [e for e in entries if not entry_expired(e)]
    skipped = len(entries) - len(active_entries)
    if skipped:
        print(f"{skipped} reactions.json-Eintrag(e) abgelaufen (> {REACTIONS_TTL_DAYS} Tage) - uebersprungen.")

    for story in news_list:
        title = story.get("title", "")
        for entry in active_entries:
            if not story_matches(title, entry):
                continue
            matched_stories += 1
            reactions = []
            for tu in entry.get("tweets", []):
                if tu not in tweet_cache:
                    print(f"Hole Tweet-Daten: {tu}")
                    tweet_cache[tu] = fetch_tweet_data(tu)
                data = tweet_cache[tu]
                if data:
                    reactions.append(data)
                    enriched_tweets += 1
                else:
                    print(f"  -> keine Daten erhalten fuer {tu} (geloescht/privat/API-Fehler?)")
            if reactions:
                story["reactions"] = reactions
            break  # erster passender Eintrag gewinnt, Story nicht doppelt matchen
    return matched_stories, enriched_tweets


def apply_auto_reactions(news_list, config_path):
    targets = top_n_stories(news_list, config_path=config_path, n=AUTO_TOP_N)
    enriched = 0
    for story in targets:
        existing = story.get("reactions", [])
        if len(existing) >= MAX_REACTIONS_PER_STORY:
            continue
        title = story.get("title", "")
        kws = title_keywords(title)

        r = fetch_hn_reaction(kws)
        if r:
            existing.append(r)
            enriched += 1
            print(f"Auto-Reaktion fuer '{title[:60]}...': HN, {r['score']} Punkte, {r['num_comments']} Kommentare")

        if existing:
            story["reactions"] = existing
    return len(targets), enriched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=str(BASE_DIR / "news.json"))
    ap.add_argument("--out", dest="out_path", default=None,
                     help="Standard: gleiche Datei wie --in (in-place)")
    ap.add_argument("--no-auto", action="store_true",
                     help="Nur manuelle X-Reaktionen anwenden, kein HN-Autofetch")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path) if args.out_path else in_path

    if not in_path.exists():
        print(f"Keine {in_path} gefunden - Pfad pruefen.")
        sys.exit(1)

    news_data = json.loads(in_path.read_text(encoding="utf-8"))
    news_list = news_data.get("news", [])

    matched_stories = enriched_tweets = 0
    if REACTIONS_JSON.exists():
        reactions_cfg = json.loads(REACTIONS_JSON.read_text(encoding="utf-8"))
        matched_stories, enriched_tweets = apply_manual_reactions(news_list, reactions_cfg.get("entries", []))
    else:
        print(f"Keine {REACTIONS_JSON.name} gefunden - ueberspringe manuelle X-Reaktionen.")

    auto_targets = auto_enriched = 0
    if not args.no_auto:
        auto_targets, auto_enriched = apply_auto_reactions(news_list, DASHBOARD_CONFIG)
    else:
        print("--no-auto gesetzt - ueberspringe HN.")

    out_path.write_text(
        json.dumps(news_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nFertig: {matched_stories} Story(s) per manuellem X-Match, {enriched_tweets} Tweet-Abrufe. "
          f"{auto_targets} Top-Storys fuer Auto-Reaktionen geprueft, {auto_enriched} HN-Treffer. "
          f"Geschrieben nach {out_path}")


if __name__ == "__main__":
    main()
