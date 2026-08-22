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
import os
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

# Fuer die deutsche Kurzfassung der Reaktionen (siehe translate_reaction()) -
# dieselbe Free-Modell-Kette wie in ki_news.py (Gemma zuerst, empirisch am
# zuverlaessigsten). Ohne Key: Uebersetzung wird uebersprungen, kein Fehler.
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
TRANSLATE_MODELLE = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    # 22.08.26: meta-llama/llama-3.3-70b-instruct:free entfernt. Die :free-
    # Variante ist seit dem 14.08. nicht mehr im OpenRouter-Katalog - in
    # ki_news.py und story_registry_shadow.py wurde sie damals ausgetauscht,
    # hier blieb sie stehen. Ersetzt durch die beiden am 22.08. live
    # geprueften Modelle; gemini-2.5-flash-lite als bezahlter Notnagel
    # (rund $0.40 je 1M Ausgabe-Token, hier fallen nur wenige Saetze an).
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemini-2.5-flash-lite",
]

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
            tweet_text = t.get("text", "")
            reaction = {
                "source": "x",
                "url": tweet_url,
                "author_name": author.get("name", ""),
                "author_handle": author.get("screen_name", ""),
                "author_avatar": author.get("avatar_url", ""),
                "text": tweet_text,
                "likes": t.get("likes", 0),
                "retweets": t.get("retweets", 0),
                "views": t.get("views", 0),
            }
            text_de = translate_reaction(tweet_text)
            if text_de:
                reaction["text_de"] = text_de
            return reaction
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


# ── Uebersetzung (X-Text/HN-Titel -> kurze deutsche Zusammenfassung) ───────
# Neu 13.07.26 (Daniel-Feedback): Reaktionen kamen bisher 1:1 im Original
# (meist Englisch) auf die Karte - auf einer deutschen Seite abschreckend,
# und lange Tweet-Threads sprengen das Layout. Uebersetzung ist bewusst ein
# Nice-to-have: schlaegt sie fehl oder fehlt OPENROUTER_KEY, faellt das
# Frontend auf den gekuerzten Original-Text zurueck (siehe index.html
# renderReaction()) - kein Blocker fuer den Rest der Pipeline.


# Bug gefunden 17.07.26 (Kimi-K3-Story): HN-Auto-Reaktionen liefern oft nur
# eine blanke Headline (kein Kommentar, keine Meinung - siehe fetch_hn_reaction).
# Der alte "Fasse diese Reaktion zusammen"-Prompt ging aber davon aus, dass
# Substanz zum Zusammenfassen da ist. Bei einer 3-5-Wort-Headline hat das
# Gratis-Modell (Gemma/Llama) stattdessen ehrlich erklaert, dass ihm der Text
# dazu fehlt ("Das ist eine blosse Ueberschrift ohne Inhalt...") - und dieser
# Erklaertext wurde ungeprueft als text_de uebernommen und live auf der Seite
# angezeigt. Fix: (1) kurze Titel bekommen einen Uebersetzungs- statt
# Zusammenfassungs-Prompt, (2) die Antwort wird gegen bekannte Refusal-Marker
# geprueft, bevor sie akzeptiert wird - schlaegt das fehl, bleibt text_de leer
# und das Frontend faellt auf den Original-Titel zurueck (bestehendes Verhalten).
_META_REFUSAL_MARKERS = (
    "keine zusammenfassung", "ohne inhalt", "es fehlt", "fehlt der",
    "kann ich nicht", "blosse ueberschrift", "bloße überschrift",
    "nicht zusammenfassen", "kein kontext", "kein text", "keine reaktion",
    "as an ai", "i cannot", "i can't summarize",
)

# Bug gefunden 20.08.26 (Daniel im Screenshot, Top-Story China-Exportkontrollen):
# text_de enthielt 200x "<pad>" (1000 Zeichen) live auf der Startseite. Der Guard
# oben griff aus ZWEI Gruenden nicht:
#   (1) Der Original-HN-Titel "Nvidia's Arm deal sparks quick backlash in chip
#       industry" hat 9 Woerter - die Grenze stand auf <= 8. Damit fiel er weder
#       in den Uebersetzungs-Prompt (is_headline) noch in den Laengen-Check.
#       Eine harte Grenze, die um genau ein Wort verfehlt wurde.
#   (2) _META_REFUSAL_MARKERS faengt nur SAETZE ab ("keine zusammenfassung",
#       "i cannot"). "<pad>" ist kein Satz, sondern das Padding-Token des
#       Modells - kein Marker traf.
# Fix: Artefakt-Liste (greift vor allem anderen) + Grenze 8 -> 12.
# Kill-Switch: bleiben danach mehr als etwa die Haelfte der Reaktionen
# englisch, ist 12 zu scharf -> auf 10 zurueck, NICHT weiter hochschrauben.
_MODEL_ARTEFAKTE = (
    "<pad>", "<|endoftext|>", "<|im_end|>", "<|eot_id|>",
    "</s>", "<s>", "<unk>", "[PAD]", "[UNK]", "\ufffd",
)

# Ab hier gilt ein Titel als "kurze Headline" (Uebersetzen statt Zusammenfassen
# und Laengen-Plausibilitaet pruefen). War 8, siehe Bug-Notiz oben.
_HEADLINE_MAX_WORDS = 12


def _looks_like_valid_translation(antwort, original):
    # Modell-Artefakte zuerst: die ueberleben jede andere Pruefung, weil sie
    # weder Refusal-Satz noch auffaellig kurz/lang sein muessen.
    if any(m in antwort for m in _MODEL_ARTEFAKTE):
        return False
    a = antwort.lower()
    if any(m in a for m in _META_REFUSAL_MARKERS):
        return False
    # Ein echtes Uebersetzungsergebnis fuer eine kurze Headline ist etwa
    # gleich lang wie das Original - ein Vielfaches laenger heisst meist
    # "erklaert" statt "uebersetzt".
    if len(original.split()) <= _HEADLINE_MAX_WORDS and len(antwort) > len(original) * 4:
        return False
    return True


def translate_reaction(text):
    if not OPENROUTER_KEY or not (text or "").strip():
        return None
    is_headline = len(text.split()) <= _HEADLINE_MAX_WORDS
    if is_headline:
        prompt = (
            "Uebersetze den folgenden kurzen Titel woertlich ins Deutsche. "
            "Nur die Uebersetzung ausgeben - keine Erklaerung, kein Hinweis "
            "darauf, dass Kontext oder eine Meinung fehlt, kein Kommentar.\n\n"
            f"Titel: {text[:300]}"
        )
    else:
        prompt = (
            "Fasse die folgende Reaktion (Tweet oder Forenbeitrag, evtl. auf "
            "Englisch) in maximal 2 kurzen deutschen Saetzen zusammen. Erhalte "
            "den Kernpunkt/die Pointe. Nur die Zusammenfassung ausgeben, keine "
            "Anfuehrungszeichen, kein Meta-Kommentar wie \"Der Autor schreibt\".\n\n"
            f"Text: {text[:1500]}"
        )
    url = "https://openrouter.ai/api/v1/chat/completions"
    for modell in TRANSLATE_MODELLE:
        try:
            data = json.dumps({
                "model": modell,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
            }).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ki-news.live/",
                "X-Title": "KI News Reactions",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                antwort = json.loads(r.read())["choices"][0]["message"]["content"].strip()
            antwort = antwort.strip('"').strip()
            if antwort and _looks_like_valid_translation(antwort, text):
                return antwort
            if antwort:
                print(f"  Uebersetzung verworfen (wirkt wie Meta-Kommentar): {antwort[:80]!r}")
        except Exception as e:
            print(f"  Uebersetzung fehlgeschlagen mit {modell}: {e}")
            continue
    return None


# ── Hacker News (automatisch) ────────────────────────────────────────────
# Reddit-Aequivalent bewusst entfernt (13.07.26) - siehe Modul-Docstring:
# unauthentifizierte Reddit-JSON-API blockt GitHub-Actions-IPs mit 403,
# bestaetigt in Produktion (Run #670). OAuth waere der einzige Fix, lohnt
# sich aber nicht fuer den Mehrwert gegenueber HN allein.

def _http_json(url, headers, timeout=10):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# Bug gefunden 20.08.26 (beim Nachrechnen des <pad>-Bugs, gleiche Karte):
# Unter der China-Exportkontrollen-Story vom 19.08.2026 hing HN-Item 24467989 -
# "Nvidia's Arm deal sparks quick backlash in chip industry" vom 14.09.2020.
# Die Zahlen (263 Punkte / 190 Kommentare) waren echt, nur die Zuordnung war
# fast sechs Jahre daneben. Ursache: die Suche hatte KEINEN Zeitfilter und nahm
# hits[0] - Algolia sortiert per Default nach RELEVANZ, nicht nach Datum. Bei
# Keywords wie "Nvidia/Chips/China" gewinnt ein alter, hoch bewerteter Post
# gegen jede frische Diskussion; je bekannter der Akteur, desto wahrscheinlicher
# der Griff ins Archiv.
# Kill-Switch: bekommen danach spuerbar viele Storys GAR KEINE HN-Reaktion mehr,
# Fenster auf 365 Tage oeffnen - aber nicht abschalten. Eine falsche Reaktion
# ist schaedlicher als keine.
HN_MAX_AGE_DAYS = 180


def fetch_hn_reaction(keywords):
    # HN Algolia-API liefert keine verlaesslichen Kommentar-Scores -> statt
    # (frei erfundener) "bester Kommentar" ehrlich nur Story + Diskussion
    # zeigen, keine Kommentar-Qualitaet vortaeuschen, die die API nicht hat.
    query = " ".join(keywords)
    _cutoff = int(time.time()) - HN_MAX_AGE_DAYS * 24 * 60 * 60
    url = ("https://hn.algolia.com/api/v1/search?"
           + urllib.parse.urlencode({
               "query": query,
               "tags": "story",
               "numericFilters": f"points>15,created_at_i>{_cutoff}",
           }))
    try:
        data = _http_json(url, {"User-Agent": UA})
        hits = data.get("hits", [])
        if not hits:
            return None
        hit = hits[0]
        title = hit.get("title", "")
        reaction = {
            "source": "hn",
            "text": title,
            "score": hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
        }
        text_de = translate_reaction(title)
        if text_de:
            reaction["text_de"] = text_de
        return reaction
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
