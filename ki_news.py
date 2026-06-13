import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os
import logging
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from time import sleep
from urllib.error import URLError, HTTPError
import html as _html

# ──────────────────────────────────────────────────────────────────────────
# SSR / Pre-Rendering für index.html
# ──────────────────────────────────────────────────────────────────────────
# Crawler & KI-Bots (GPTBot, ClaudeBot, PerplexityBot …) führen kein JavaScript
# aus. Diese Funktion schreibt die aktuellen News bei jedem Lauf als ECHTES HTML
# in index.html – in zwei markierte Bereiche. Das JS-Frontend bleibt unverändert;
# es ersetzt diese Bereiche im Browser wie bisher.
#   <!-- SSR:HERO:START --> … <!-- SSR:HERO:END -->
#   <!-- SSR:NEWS:START --> … <!-- SSR:NEWS:END -->
SSR_MAX = 24  # max. News-Karten im vorgerenderten HTML


def _ssr_fmt_date(d):
    """'2026-05-28' -> '28.05.2026'"""
    if not d:
        return ""
    p = str(d)[:10].split("-")
    return f"{p[2]}.{p[1]}.{p[0]}" if len(p) == 3 else _html.escape(str(d))


def _ssr_card(n):
    c = _html.escape(n.get("color") or "#1d9bf0", quote=True)
    src = _html.escape(n.get("source") or "")
    date = _ssr_fmt_date(n.get("date") or n.get("first_seen") or "")
    date_html = (
        f'<span class="text-[11px] font-mono ki-faint">· {date}</span>' if date else ""
    )
    score = n.get("score")
    score_html = (
        f'<span class="text-[10px] font-mono ki-faint" title="Score">{round(score)}</span>'
        if score else ""
    )
    return (
        f'<a href="{_html.escape(n.get("link") or "#", quote=True)}" target="_blank" rel="noopener" '
        f'class="ki-card ki-border border p-4 flex flex-col h-full transition-all">'
        f'<div class="flex items-center justify-between mb-4">'
        f'<span class="text-white px-2 py-0.5 font-source-tag text-source-tag rounded-sm uppercase" '
        f'style="background:{c}">{src}</span>'
        f'</div>'
        f'<h4 class="font-headline-md ki-main mb-2 leading-snug" '
        f"style=\"font-family:'Space Grotesk',sans-serif\">{_html.escape(n.get('title') or '')}</h4>"
        f'<p class="text-on-surface-variant font-body-sm text-body-sm mb-6 flex-grow">'
        f"{_html.escape(n.get('summary') or '')}</p>"
        f'<div class="pt-4 ki-border border-t flex items-center justify-between">'
        f'<span class="text-[11px] font-mono uppercase" style="color:{c}">{src}</span>'
        f'<div style="display:flex;align-items:center;gap:6px">{date_html}{score_html}</div>'
        f'</div>'
        f'</a>'
    )


def inject_ssr(base_dir, news_json_data):
    """Schreibt Hero + News-Grid + JSON-LD als statisches HTML in index.html."""
    base_dir = Path(base_dir)
    index_path = base_dir / "index.html"
    if not index_path.exists():
        return  # Kein index.html in diesem Verzeichnis (z.B. lokal) – nichts zu tun.

    news = sorted(
        list(news_json_data.get("news") or []),
        key=lambda n: n.get("score", 0),
        reverse=True,
    )[:SSR_MAX]
    if not news:
        return

    stand = news_json_data.get("stand", "")

    # ── Hero (Top-Story) ──
    top = news[0]
    hero = (
        "<!-- SSR:HERO:START -->\n"
        '            <div class="c-text">\n'
        f'              <h2 id="c-title">{_html.escape(top.get("title") or "")}</h2>\n'
        f'              <p id="c-desc">{_html.escape(top.get("summary") or "")}</p>\n'
        "            </div>\n"
        "            <!-- SSR:HERO:END -->"
    )

    # ── JSON-LD ItemList ──
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Aktuelle KI-News",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": n.get("link") or "https://ki-news.live/",
                "name": n.get("title") or "",
            }
            for i, n in enumerate(news)
        ],
    }
    json_ld = json.dumps(item_list, ensure_ascii=False, indent=2)

    # ── News-Grid ──
    cards = "\n".join("        " + _ssr_card(n) for n in news)
    news_block = (
        "<!-- SSR:NEWS:START -->\n"
        '      <script type="application/ld+json" id="ssr-newslist">\n'
        f"{json_ld}\n"
        "      </script>\n"
        '      <div id="news-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">\n'
        f"{cards}\n"
        "      </div>\n"
        "      <!-- SSR:NEWS:END -->"
    )

    html_txt = index_path.read_text(encoding="utf-8")
    html_txt, n_hero = re.subn(
        r"<!-- SSR:HERO:START -->.*?<!-- SSR:HERO:END -->",
        lambda _m: hero, html_txt, flags=re.DOTALL,
    )
    html_txt, n_news = re.subn(
        r"<!-- SSR:NEWS:START -->.*?<!-- SSR:NEWS:END -->",
        lambda _m: news_block, html_txt, flags=re.DOTALL,
    )
    # Stand-Label-Default (vor JS-Hydration)
    html_txt = re.sub(
        r'(<span id="stand-label"[^>]*>)[^<]*(</span>)',
        lambda m: f"{m.group(1)}Stand: {_html.escape(stand)}{m.group(2)}",
        html_txt,
    )

    if n_hero and n_news:
        index_path.write_text(html_txt, encoding="utf-8")
        logger.info("SSR: index.html aktualisiert (%d News, Stand %s)", len(news), stand)
    else:
        logger.warning("SSR: Marker fehlen (hero=%d, news=%d) – index.html unveraendert", n_hero, n_news)

def inject_admin_posts(base_dir, news_json_data):
    """Aktualisiert den eingebetteten #news-data Block in admin-posts.html."""
    base_dir = Path(base_dir)
    admin_path = base_dir / "admin-posts.html"
    if not admin_path.exists():
        return
    payload = json.dumps(news_json_data, ensure_ascii=False, indent=2)
    html_txt = admin_path.read_text(encoding="utf-8")
    html_txt, n = re.subn(
        r'(<script type="application/json" id="news-data">).*?(</script>)',
        lambda m: f"{m.group(1)}\n{payload}\n{m.group(2)}",
        html_txt, flags=re.DOTALL,
    )
    if n:
        admin_path.write_text(html_txt, encoding="utf-8")
        logger.info("SSR: admin-posts.html aktualisiert (Stand %s)", news_json_data.get("stand",""))
    else:
        logger.warning("SSR: #news-data Marker in admin-posts.html fehlt – unveraendert")

# -------------------------
# Dashboard-Config + Post-Cache
# -------------------------
def load_dashboard_config(base_dir):
    """Lädt dashboard_config.json (featured_links + blocked_links)."""
    path = Path(base_dir) / "dashboard_config.json"
    if not path.exists():
        return {"featured_links": [], "blocked_links": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"featured_links": [], "blocked_links": []}

def load_post_cache(base_dir):
    """Lädt post-cache.json – gespeicherte LLM-Texte pro Artikel-Link."""
    path = Path(base_dir) / "post-cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_post_cache(base_dir, cache):
    """Speichert post-cache.json, bereinigt Einträge älter als 90 Tage."""
    cutoff = (datetime.now(BERLIN) - timedelta(days=90)).strftime("%Y-%m-%d")
    pruned = {link: data for link, data in cache.items()
              if data.get("generated_at", "9999") >= cutoff}
    path = Path(base_dir) / "post-cache.json"
    try:
        path.write_text(json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("post-cache.json: %d Eintraege gespeichert", len(pruned))
    except Exception as e:
        logger.exception("Fehler beim Schreiben post-cache.json: %s", e)

# -------------------------
# Logging
# -------------------------
LOG_PATH = Path("ki_news.log")
_fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
_fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
_fh.setFormatter(_fmt)
logger = logging.getLogger("ki_news")
logger.setLevel(logging.INFO)
logger.addHandler(_fh)
logger.propagate = False  # Kein Doppel-Logging durch Root-Logger

# -------------------------
# Zeitzone
# -------------------------
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = timezone(timedelta(hours=2))

# -------------------------
# Keys
# -------------------------
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
if not OPENROUTER_KEY:
    cfg = Path.home() / "Documents" / "Projekte" / "ki-news" / "config.txt"
    if cfg.exists():
        try:
            OPENROUTER_KEY = cfg.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Fehler beim Lesen config.txt: %s", e)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "9096438").strip()
GROQ_CHAT_KEY = os.environ.get("GROQ_CHAT_KEY", "").strip()

# -------------------------
# Konfiguration
# -------------------------
# Kurzwörter (ki, ai, llm, gpt) brauchen Wort-Grenzen – sonst matched "Kinostart", "marketing" etc.
# Längere Begriffe (openai, chatgpt, anthropic...) sind sicher als Substring.
KI_KEYWORDS_WORD = {
    # Nur als ganzes Wort matchen (Regex \b...\b)
    "ki", "ai", "llm", "gpt",
}
KI_KEYWORDS_SUBSTR = {
    # Substring-Match ok – lang genug um keine Fehlalarme zu erzeugen
    "kunstliche", "künstliche", "intelligenz", "model", "claude",
    "chatgpt", "openai", "google", "meta ai", "agent", "nvidia",
    "anthropic", "gemini", "mistral", "deepseek", "roboter", "automation",
    "sprachmodell", "chatbot", "machine learning", "neural", "generativ",
}

def _is_ki_relevant(title: str) -> bool:
    """Prüft ob ein Titel KI-relevant ist – mit Wortgrenzen für Kurzkürzel."""
    t = title.lower()
    # Substr-Check (unkritische, lange Keywords)
    if any(k in t for k in KI_KEYWORDS_SUBSTR):
        return True
    # Wort-Grenze-Check für ki / ai / llm / gpt
    if any(re.search(r'\b' + re.escape(k) + r'\b', t) for k in KI_KEYWORDS_WORD):
        return True
    return False

FEEDS = [
    # Deutsch
    ("The Decoder", "https://the-decoder.de/feed/"),
    ("Heise",       "https://www.heise.de/newsticker/heise.rdf"),
    ("Golem",       "https://rss.golem.de/rss.php?feed=RSS2.0"),
    ("Caschy Blog", "https://stadt-bremerhaven.de/feed/"),
    # Englisch – AI-spezifische Feeds bevorzugt
    ("TechCrunch AI",  "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica",   "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("Wired",          "https://wired.com/feed/rss"),
    ("The Verge",      "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("CNBC", 		"https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("SiliconAngle",   "https://siliconangle.com/feed"),
    ("TechRepublic",   "https://www.techrepublic.com/rssfeeds/articles/"),
    # Paywall-Quellen via Google News RSS
    ("Reuters AI",   "https://news.google.com/rss/search?q=site:reuters.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("Bloomberg AI", "https://news.google.com/rss/search?q=site:bloomberg.com+AI&hl=en&gl=US&ceid=US:en"),
    ("WSJ AI",       "https://news.google.com/rss/search?q=site:wsj.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("FT AI",        "https://news.google.com/rss/search?q=site:ft.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("Economist AI", "https://news.google.com/rss/search?q=site:economist.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("CNet", 		"https://www.cnet.com/rss/all/"),
    ("MIT", 		"https://www.technologyreview.com/feed/"),
    ("NYT Technology",  "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("OpenAI",         "https://openai.com/blog/rss.xml"),
    # Kuratiert – bereits AI-spezifisch, kein KI-Filter nötig
    ("AlignedNews",    "https://alignednews.com/feed"),
    # Primärquellen – Lab-Announcements direkt (via Olshansk/rss-feeds, stündlich aktualisiert)
    ("Anthropic News",     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml"),
    ("Anthropic Research", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml"),
    ("Meta AI Blog",       "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml"),
    ("Google AI Blog",     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_google_ai.xml"),
    ("xAI News",           "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_xainews.xml"),
    ("Mistral News",       "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_mistral.xml"),
    ("The Batch",          "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_the_batch.xml"),
    # Hardware / AI-Hardware (Computex, AI-Laptops, Server)
    ("WCCFtech",           "https://wccftech.com/feed/"),
]

# Nur diese 3 News gehen an den LLM fuer Posts
# Mehr = generischer Fuelltext weil das Modell ueberfordert ist
MAX_LLM_NEWS = 3

MODELLE = [
    # Free-Modelle – Gemma zuerst (empirisch: llama/hermes dauerhaft auf 429)
    "google/gemma-4-31b-it:free",                      # Gemma 4 31B – zuverlässigster Free-Slot
    "google/gemma-4-26b-a4b-it:free",                  # Gemma 4 26B Fallback
    "meta-llama/llama-3.3-70b-instruct:free",         # Llama 3.3 70B – oft 429
    "nousresearch/hermes-3-llama-3.1-405b:free",      # 405B – oft 429
    # Kostenpflichtige Fallbacks (~$0.008/Lauf) – nur wenn alle Free-Modelle 429
    "meta-llama/llama-3.3-70b-instruct",               # Anker – immer verfügbar
    "google/gemma-3-27b-it",                            # Letzter Fallback
]

# NEU: Separate Modellliste für Post-Generierung
# Gemma-4-31b schreibt bessere deutsche Posts als Llama – empirisch aus Logs bestätigt.
# Reihenfolge bewusst anders als MODELLE: Gemma zuerst, Llama als Fallback.
MODELLE_POSTS = [
    "google/gemma-4-31b-it:free",                      # Beste Posts-Qualität (DE-Format, Scampy-6)
    "google/gemma-4-26b-a4b-it:free",                  # Gemma-Fallback
    "meta-llama/llama-3.3-70b-instruct:free",          # Llama Free
    "nousresearch/hermes-3-llama-3.1-405b:free",       # Hermes Free
    "meta-llama/llama-3.3-70b-instruct",               # Paid-Anker
    "google/gemma-3-27b-it",                            # Letzter Fallback
]

# NEU: Ollama – lokaler Provider (wird automatisch erkannt, GitHub Actions ignoriert das)
# Setup: https://ollama.ai → `ollama pull gemma3:27b` oder `ollama pull gemma2:27b`
# Wenn OLLAMA_HOST gesetzt ist UND ein Server antwortet, werden Ollama-Modelle
# an ERSTER Stelle in MODELLE_POSTS eingefügt (kein Rate-Limit, kostenlos).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODELS_POSTS = [
    "ollama/gemma3:27b",    # Beste Qualität lokal
    "ollama/gemma2:27b",    # Fallback
    "ollama/llama3.3:70b",  # Llama lokal
]

def _detect_ollama_models():
    """Prüft welche Ollama-Modelle lokal verfügbar sind. Gibt [] zurück wenn kein Server."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
            available = {m["name"].split(":")[0] for m in data.get("models", [])}
            matched = []
            for om in OLLAMA_MODELS_POSTS:
                name = om.replace("ollama/", "").split(":")[0]
                if name in available:
                    matched.append(om)
            if matched:
                logger.info("Ollama verfügbar – %d Modelle: %s", len(matched), matched)
            return matched
    except Exception:
        return []  # Kein Ollama-Server – kein Problem

SOURCE_COLORS = {
    "The Decoder": "#1d9bf0",
    "TechCrunch AI": "#ff6b35",
    "VentureBeat AI": "#7c3aed",
    "Ars Technica": "#16a34a",
    "MIT Tech Review": "#dc2626",
    "Heise": "#ca8a04",
}

THREAD_LABELS = ["Hook", "Kontext", "Kaskade", "Gruselig", "Konsequenz", "Fazit"]

# -------------------------
# NEU: Story-Scoring & Clustering
# -------------------------

# Quellen-Prestige: höhere Zahl = glaubwürdiger / reichweitenstärker
SOURCE_PRESTIGE = {
    "Bloomberg":      5,
    "The Decoder":    5,
    "TechCrunch AI":  5,
    "Heise":          5,
    "VentureBeat AI": 5,
    "Ars Technica":   5,
    "Wired":          5,
    "The Verge":      5,
    "Golem":          5,
    "SiliconAngle":   5,
    "TechRepublic":   5,
    "Caschy Blog":    5,
    "CNet":	      5,
    "CNBC":           5,
    "NYT Technology":  5,
    # Gizmodo entfernt (blockiert GitHub Actions)
    # Primärquellen (direkt vom Hersteller) – höher gewichtet als Media
    "Anthropic News":     10,
    "Anthropic Research": 10,
    "Meta AI Blog":       10,
    "Google AI Blog":     10,
    "xAI News":           10,
    "Mistral News":       10,
    "OpenAI":             10,
    "The Batch":          5,
}

# Wichtigkeits-Keywords → Punktebonus
# Tuple: (keyword, punkte)
IMPORTANCE_KEYWORDS = [
    # Mega-Events (15 Punkte) – echte Nachricht, nicht nur ein Update
    ("ban", 15), ("banned", 15), ("verboten", 15), ("lawsuit", 15), ("klage", 15),
    ("billion", 15), ("milliard", 15), ("fired", 15), ("entlassen", 15),
    ("merger", 15), ("acqui", 15), ("übernimmt", 15), ("shutdown", 15),
    ("regulation", 15), ("gesetz", 15), ("verbot", 15),
    ("valuation", 15), ("bewertung", 15), ("funding round", 15), ("raises $", 15),
    # Wichtige Ereignisse (10 Punkte)
    ("launch", 10), ("release", 10), ("veröffentlicht", 10),
    ("breakthrough", 10), ("durchbruch", 10), ("funding", 10), ("investment", 10),
    ("raises", 10), ("million", 10), ("opens", 10), ("patent", 10),
    # Interessante Entwicklungen (5 Punkte)
    ("study", 5), ("studie", 5), ("research", 5), ("warnt", 5),
    ("kritik", 5), ("beats", 5), ("übertrifft", 5), ("first", 5), ("erstmals", 5),
    ("open source", 5), ("open-source", 5), ("kostenlos", 5),
]


# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)
# Tuple: (keyword, punkte)
PENALTY_KEYWORDS = [
    # Heise-Selbstvermarktung
    ("webinar", -30), ("academy", -30), ("online-kurs", -25), ("anmeldung", -20),
    ("schulung", -25), ("zertifikat", -20), ("workshop", -15),
    # Gaming / Hardware ohne KI-Relevanz
    ("gaming", -20), ("esports", -30), ("playstation", -30), ("xbox", -30),
    ("nintendo", -30), ("benchmark", -15), (" fps", -20), ("game pass", -30),
    ("grafikkarte test", -20), ("monitor test", -20),
    # Deals / Commerce
    (" sale", -20), ("deal:", -20), ("discount", -20), ("angebot:", -20),
    ("best buy", -25), ("preis fällt", -15),
    # Gerüchte ohne Substanz
    ("rumor:", -10), ("leak:", -10), ("leaked:", -10), ("könnte kommen", -10),
]

# Score-Labels für Telegram-Log und news.json
SCORE_LABELS = [
    (40, "🔥 episch"),
    (25, "⚡ wichtig"),
    (0,  "📰 normal"),
]

def _title_keywords(title):
    """Extrahiert bedeutsame Wörter aus einem Titel (min. 4 Zeichen, keine Stopwörter)."""
    STOPWORDS = {
        "die", "der", "das", "ein", "eine", "und", "oder", "mit", "von", "für",
        "auf", "in", "an", "bei", "zu", "ist", "sind", "hat", "wird", "nach",
        "the", "a", "an", "of", "in", "to", "for", "on", "with", "and", "or",
        "is", "are", "new", "its", "their", "by", "as", "at", "from", "that",
        "this", "was", "has", "have", "will", "über", "nach", "beim", "auch",
    }
    words = re.findall(r'\b\w{4,}\b', title.lower())
    return {w for w in words if w not in STOPWORDS}

def cluster_news(alle_news):
    """
    Gruppiert ähnliche Artikel: 2+ gemeinsame Schlüsselwörter im Titel = gleiche Story.
    Gibt Liste von Clusters zurück (jeder Cluster = Liste von Artikeln).
    """
    clusters = []
    for item in alle_news:
        kw = _title_keywords(item["title"])
        merged = False
        for cluster in clusters:
            cluster_kw = _title_keywords(cluster[0]["title"])
            if len(kw & cluster_kw) >= 2:
                cluster.append(item)
                merged = True
                break
        if not merged:
            clusters.append([item])
    return clusters

def score_cluster(cluster):
    """
    Berechnet Relevanz-Score für einen Story-Cluster.
    Formel: Multi-Quellen-Bonus + Prestige-Bonus + Wichtigkeits-Keywords
    """
    unique_sources = len({item["source"] for item in cluster})
    # Mehrere Quellen = wichtige Story (Kern-Signal) – max. 4 gewertet (Deckel gegen Google-Dominanz)
    source_score = min(unique_sources, 4) * 15

    # Höchstes Prestige im Cluster zählt
    prestige_score = max(SOURCE_PRESTIGE.get(item["source"], 3) for item in cluster)

    # Keywords aus allen Titeln im Cluster prüfen
    all_titles = " ".join(item["title"].lower() for item in cluster)
    kw_score = sum(pts for kw, pts in IMPORTANCE_KEYWORDS if kw in all_titles)
    penalty_score = sum(pts for kw, pts in PENALTY_KEYWORDS if kw in all_titles)

    total = source_score + prestige_score + kw_score + penalty_score
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label

def pick_top_news(alle_news, n=3, history=None, featured_links=None):
    """
    Wählt die n wichtigsten Artikel nach Clustering + Scoring.
    Statt blindem [:3] aus der Feed-Reihenfolge.
    Gibt je einen repräsentativen Artikel pro Top-Cluster zurück.

    history (link -> {first_seen, base_score}) optional: wenn gesetzt, wird nach
    dem ZEIT-VERFALLENEN Score sortiert – identisch zur Dashboard-Sortierung,
    damit Telegram und Dashboard dieselben Top-Storys zeigen.
    """
    history = history or {}
    featured_links = set(featured_links or [])
    clusters = cluster_news(alle_news)

    # Jeden Cluster bewerten
    scored = []
    for cluster in clusters:
        score, label = score_cluster(cluster)
        # Repräsentant = Artikel aus der prestigiösten Quelle im Cluster
        rep = max(cluster, key=lambda x: SOURCE_PRESTIGE.get(x["source"], 0))
        # Effektiver Score: ältesten first_seen im ganzen Cluster verwenden.
        # Verhindert dass neue Artikel über alte Storys den Cluster "verjüngen".
        cluster_histories = [history[item["link"]] for item in cluster if item.get("link") in history]
        if cluster_histories:
            oldest_first_seen = min(h["first_seen"] for h in cluster_histories)
            best_base = max(h.get("base_score", score) for h in cluster_histories)
            eff_score = decay_score(best_base, oldest_first_seen)
        else:
            eff_score = score  # komplett neue Story: heute erfasst, kein Verfall
        # Featured-Boost aus dashboard_config.json (mit Zeitverfall)
        if featured_links:
            cluster_links = {item.get("link", "") for item in cluster}
            if rep.get("link", "") in featured_links or cluster_links & featured_links:
                fs = history.get(rep.get("link", ""), {}).get("first_seen", _today_iso())
                days_old = _days_since(fs)
                boost = 60 if days_old == 0 else 30 if days_old == 1 else 15 if days_old == 2 else 0
                eff_score += boost
        scored.append({
            "rep": rep,
            "score": score,
            "eff_score": eff_score,
            "label": label,
            "sources_count": len({i["source"] for i in cluster}),
        })

    # Nach verfallenem Score absteigend sortieren (bei Gleichstand: roher Score)
    scored.sort(key=lambda x: (x["eff_score"], x["score"]), reverse=True)

    top = scored[:n]
    for item in top:
        logger.info(
            "[Scoring] %s | %s | Score: %d (akt. %d) | Quellen: %d",
            item["label"], item["rep"]["title"][:60], item["score"], item["eff_score"], item["sources_count"]
        )

    return [item["rep"] for item in top], {
        item["rep"]["link"]: {"score": item["score"], "label": item["label"]}
        for item in scored
    }

# -------------------------
# Score-Verfall (Zeit-Decay)
# -------------------------
# Jeder Artikel verliert pro Tag seit Erst-Erfassung Punkte, Untergrenze 0.
# So sinken alte Stories automatisch nach unten und machen Platz für Neues.
SCORE_DECAY_PER_DAY = 5
SCORE_FLOOR = 0
MAX_AGE_DAYS = 7  # Artikel älter als 7 Tage werden aus news.json entfernt

def _today_iso():
    return datetime.now(BERLIN).strftime("%Y-%m-%d")

def _days_since(date_str):
    """Volle Tage zwischen date_str (YYYY-MM-DD) und heute. Robust gegen Müll."""
    if not date_str:
        return 0
    try:
        d0 = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0
    today = datetime.now(BERLIN).date()
    return max(0, (today - d0).days)

def decay_score(base_score, first_seen):
    """
    Deterministischer Verfall: score = max(0, base_score - 5 * Tage_seit_Erfassung).

    Bewusst NICHT kumulativ (kein „-5 pro Lauf“): der GitHub-Action-Cron kann
    mehrmals täglich laufen – ein Abzug pro Lauf würde Artikel je nach Laufzahl
    unterschiedlich stark bestrafen. Aus base_score + first_seen neu zu rechnen
    ist idempotent und liefert bei jedem Lauf denselben, korrekten Wert.
    """
    try:
        base = int(base_score)
    except (ValueError, TypeError):
        base = 0
    decayed = base - SCORE_DECAY_PER_DAY * _days_since(first_seen)
    return max(SCORE_FLOOR, decayed)

def build_history_map(*archive_lists):
    """
    Baut link -> {first_seen, base_score} aus vorhandenen Archiv-Einträgen.
    Quelle der Wahrheit für „wann zum ersten Mal gesehen“ + „Ausgangs-Score“.
    Ältere Archive ohne diese Felder werden tolerant migriert (Fallback auf date/score).
    """
    hist = {}
    for lst in archive_lists:
        for n in (lst or []):
            link = n.get("link")
            if not link:
                continue
            first_seen = n.get("first_seen") or n.get("date") or _today_iso()
            base_score = n.get("base_score")
            if base_score is None:
                base_score = n.get("score", 0)
            prev = hist.get(link)
            entry = {"first_seen": first_seen, "base_score": base_score}
            if "image" in n:
                entry["image"] = n.get("image") or ""
            # Frühestes Datum gewinnt (echtes Erst-Sichten)
            if prev is None or str(first_seen) < str(prev["first_seen"]):
                # Bild aus dem vorherigen Eintrag retten, falls neuer keins hat
                if prev and "image" in prev and "image" not in entry:
                    entry["image"] = prev["image"]
                hist[link] = entry
            else:
                if base_score and not prev.get("base_score"):
                    prev["base_score"] = base_score
                if "image" in entry and "image" not in prev:
                    prev["image"] = entry["image"]
    return hist

def apply_decay_to_entries(entries):
    """Rechnet score für eine Liste von Einträgen neu (in-place) aus base_score+first_seen."""
    for n in entries:
        if not isinstance(n, dict):
            continue
        fs = n.get("first_seen") or n.get("date")
        bs = n.get("base_score")
        if bs is None:
            bs = n.get("score", 0)
            n["base_score"] = bs
        if not n.get("first_seen"):
            n["first_seen"] = fs or _today_iso()
        n["score"] = decay_score(bs, n["first_seen"])
    return entries


# -------------------------
# Feeds
# -------------------------
def http_get_with_retry(url, headers=None, timeout=10, retries=3, backoff=2):
    # Realistischer Browser-UA – reduziert 403/Throttling bei Medien-Seiten
    default_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    headers = headers or {
        "User-Agent": default_ua,
        "Accept": "application/rss+xml,application/xml,*/*"
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (HTTPError, URLError) as e:
            if hasattr(e, 'code') and e.code == 403:
                # 403 = Feed blockiert GitHub Actions IPs → kein Retry, sofort aufgeben
                logger.warning("HTTP Fehler %s: %s (Versuch %d/%d) – Feed blockiert, überspringe", url, e, attempt, retries)
                break
            logger.warning("HTTP Fehler %s: %s (Versuch %d/%d)", url, e, attempt, retries)
            sleep(backoff * attempt)
        except Exception as e:
            logger.exception("Unerwarteter Fehler %s: %s", url, e)
            break
    return None

def fetch_feed(name, url):
    # The Decoder braucht mehr Zeit – Server langsam für GitHub Actions IPs
    timeout = 20 if "the-decoder" in url else 12
    raw = http_get_with_retry(url, timeout=timeout, retries=2, backoff=3)
    if not raw:
        logger.error("[%s] Kein Inhalt erhalten.", name)
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning("[%s] XML ParseError: %s", name, e)
        return []

    items = []
    candidates = list(root.iter("item")) or list(root.iter("entry"))
    for item in candidates[:10]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not link:
            link_elem = item.find("link")
            if link_elem is not None:
                link = link_elem.get("href", "").strip()
        if title and _is_ki_relevant(title):
            items.append({"title": title, "link": link, "source": name})
    return items[:3]

# -------------------------
# Vorschaubilder (og:image) – serverseitig für externe Links / X-Posts
# -------------------------
# X-Posts (und andere externe Links) liefern kein eigenes Vorschaubild im RSS.
# Wir holen das og:image / twitter:image einmalig beim Lauf und speichern es in
# news.json + archive.json, damit die Karten im Frontend ein Standbild zeigen –
# ganz ohne dass der Browser des Besuchers das Drittanbieter-HTML laden muss.
_OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']', re.I),
]

def fetch_og_image(url):
    """Holt das og:image / twitter:image einer URL. Gibt absolute URL oder '' zurück."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        raw = http_get_with_retry(url, timeout=10, retries=1, backoff=2)
        if not raw:
            return ""
        # Nur den <head> durchsuchen reicht und ist schnell.
        head = raw[:200000]
        for pat in _OG_PATTERNS:
            m = pat.search(head)
            if m:
                img = (m.group(1) or "").strip()
                if not img:
                    continue
                # Schema-relative oder Pfad-relative URLs absolut machen
                if img.startswith("//"):
                    img = "https:" + img
                elif img.startswith("/"):
                    from urllib.parse import urlparse
                    p = urlparse(url)
                    img = f"{p.scheme}://{p.netloc}{img}"
                if img.startswith(("http://", "https://")):
                    return img
    except Exception as e:
        logger.debug("og:image-Abruf fehlgeschlagen für %s: %s", url, e)
    return ""

def resolve_preview_image(link, history_entry):
    """
    Liefert das Vorschaubild für einen Link. Nutzt den Cache (history_entry aus
    archive.json) und holt nur dann neu, wenn noch keins gespeichert ist – das
    spart HTTP-Abrufe bei jedem Lauf. Leerer String = kein Bild gefunden.
    """
    if history_entry and "image" in history_entry:
        # Schon einmal versucht (auch wenn Ergebnis leer war) → nicht erneut abrufen
        return history_entry.get("image") or ""
    return fetch_og_image(link)

# -------------------------
# X-Beiträge: Vorschaubild serverseitig holen (kein CORS-Problem)
# -------------------------
def _tweet_id_from_url(url):
    m = re.search(r"status(?:es)?/(\d+)", url or "")
    return m.group(1) if m else ""

def fetch_tweet_image(tweet_id):
    """
    Holt das Vorschaubild eines X-Beitrags über die CORS-freie fxtwitter-API.
    Serverseitig (GitHub-Action) – im Gegensatz zum Browser kein CORS-Block.
    Gibt eine pbs.twimg.com-Bild-URL zurück oder '' wenn keins gefunden.
    """
    if not tweet_id:
        return ""
    try:
        raw = http_get_with_retry(f"https://api.fxtwitter.com/status/{tweet_id}", timeout=10, retries=1)
        if not raw:
            return ""
        d = json.loads(raw)
        t = (d or {}).get("tweet") or {}
        m = t.get("media") or {}
        photos = m.get("photos") or []
        if photos and photos[0].get("url"):
            return photos[0]["url"]
        videos = m.get("videos") or []
        if videos and videos[0].get("thumbnail_url"):
            return videos[0]["thumbnail_url"]
        allm = m.get("all") or []
        if allm:
            return allm[0].get("thumbnail_url") or allm[0].get("url") or ""
        author = t.get("author") or {}
        if author.get("avatar_url"):
            return author["avatar_url"]
    except Exception as e:
        logger.debug("Tweet-Bild (fx) fehlgeschlagen %s: %s", tweet_id, e)
    return ""

def update_media_xpost_images(base_dir):
    """Ergänzt fehlende Vorschaubilder der X-Beiträge in media.json (serverseitig)."""
    path = base_dir / "media.json"
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    xposts = data.get("xposts") or []
    changed = False
    for x in xposts:
        if not isinstance(x, dict) or x.get("image"):
            continue
        img = fetch_tweet_image(_tweet_id_from_url(x.get("url", "")))
        if img:
            x["image"] = img
            changed = True
            logger.info("X-Vorschaubild ergänzt: %s", x.get("url", ""))
    if changed:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("media.json: X-Vorschaubilder aktualisiert")
        except Exception as e:
            logger.exception("Fehler beim Schreiben media.json: %s", e)

# -------------------------
# LLM – Zusammenfassungen (alle News, fuer Dashboard links)
# -------------------------
def summarize_news(alle_news):
    result = {i: {"title_de": n["title"], "summary": ""} for i, n in enumerate(alle_news)}
    if not OPENROUTER_KEY:
        logger.info("Kein OPENROUTER_KEY: Ueberspringe Zusammenfassungen.")
        return result

    batch_size = 6
    url = "https://openrouter.ai/api/v1/chat/completions"

    # Placeholder-Erkennung: LLMs kopieren manchmal den Beispieltext aus dem Prompt
    PLACEHOLDER_PATTERNS = {
        "kurzer deutscher titel", "kurznews", "kurze meldung", "titel auf deutsch",
        "deutsche zusammenfassung", "news zusammenfassung", "hier der titel",
        "zusammenfassung hier", "titel hier", "schlagzeile", "beispieltitel",
    }
    def _is_placeholder(title: str) -> bool:
        t = title.lower().strip()
        return len(t) < 8 or any(p in t for p in PLACEHOLDER_PATTERNS)

    for batch_start in range(0, len(alle_news), batch_size):
        batch = alle_news[batch_start:batch_start + batch_size]
        news_text = "\n".join([f"{i+1}. {n['title']} (via {n['source']})" for i, n in enumerate(batch)])
        prompt = f"""Du bist ein deutschsprachiger KI-News-Redakteur.
Uebersetze und fasse JEDE der folgenden News auf Deutsch zusammen.
Antworte AUSSCHLIESSLICH mit einem JSON-Array – kein Text davor oder danach, keine Backticks, kein Markdown.

Format (ersetze Inhalt mit echten Werten fuer jede News):
[{{"id": 1, "title_de": "Echter deutscher Titel der News", "summary": "2-3 Saetze: was ist passiert und warum relevant fuer KI-Interessierte."}}, ...]

Wichtig:
- title_de MUSS eine echte Uebersetzung des Originaltitels sein
- Jede id muss vorkommen (1 bis {len(batch)})
- Nur das JSON-Array zurueckgeben, sonst nichts

News:
{news_text}"""

        for modell in MODELLE:
            try:
                data = json.dumps({
                    "model": modell,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 900
                }).encode()
                req = urllib.request.Request(url, data=data, headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://ki-news.live/",
                    "X-Title": "KI News Dashboard"
                })
                with urllib.request.urlopen(req, timeout=60) as r:
                    antwort = json.loads(r.read())["choices"][0]["message"]["content"].strip()
                    antwort = antwort.replace("```json", "").replace("```", "").strip()
                    summaries = json.loads(antwort)
                    for item in summaries:
                        global_index = batch_start + item["id"] - 1
                        if 0 <= global_index < len(alle_news):
                            raw_title = item.get("title_de", "")
                            # Placeholder-Schutz: falls LLM Beispieltext zurückgibt → Original behalten
                            title_de = raw_title if raw_title and not _is_placeholder(raw_title) \
                                       else alle_news[global_index]["title"]
                            result[global_index] = {
                                "title_de": title_de,
                                "summary": item.get("summary", "")
                            }
                    logger.info("Zusammenfassungen Batch %d OK mit %s", batch_start // batch_size + 1, modell)
                    break
            except HTTPError as e:
                if e.code == 429:
                    logger.warning("Batch %d: %s Rate-Limit (429) – naechstes Modell",
                                   batch_start // batch_size + 1, modell)
                else:
                    logger.warning("Batch %d mit %s fehlgeschlagen: HTTP %s",
                                   batch_start // batch_size + 1, modell, e.code)
                continue
            except Exception as e:
                logger.warning("Batch %d mit %s fehlgeschlagen: %s",
                               batch_start // batch_size + 1, modell, e)
                continue
    return result

# -------------------------
# NEU: Einheitlicher LLM-Aufruf (OpenRouter + Ollama)
# -------------------------
def _call_llm_api(model, messages, max_tokens, timeout=90):
    """
    Ruft OpenRouter oder einen lokalen Ollama-Server auf.
    Modell-Prefix 'ollama/' → Ollama, alles andere → OpenRouter.
    Wirft HTTPError(429) bei Rate-Limit, Exception bei anderen Fehlern.
    """
    if model.startswith("ollama/"):
        ollama_model = model[7:]  # "ollama/gemma3:27b" → "gemma3:27b"
        url = f"{OLLAMA_HOST}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
    else:
        if not OPENROUTER_KEY:
            raise ValueError("Kein OPENROUTER_KEY gesetzt")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ki-news.live/",
            "X-Title": "KI News Dashboard",
        }
        ollama_model = model

    data = json.dumps({
        "model": ollama_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

# -------------------------
# LLM – Posts Scampy-6
# Bekommt nur MAX_LLM_NEWS Items – mehr = Fuelltext
# -------------------------
def ask_llm(top_news, n=None):
    if not OPENROUTER_KEY:
        fallback = ""
        for i in range(1, 4):
            fallback += f"TEASER {i}: Keine LLM-Verbindung – kein OPENROUTER_KEY.\n"
            for j in range(1, 7):
                fallback += f"THREAD {i}-{j}: Kein Key.\n"
            fallback += f"ERKLAERUNG {i}: Kein Key.\n"
        return fallback

    news_text = "\n".join([f"- {n['title']} (via {n['source']})" for n in top_news])

    system = """Du bist @ScampyKI, ein sachlicher aber neugieriger KI-Beobachter aus Deutschland.
Dein Stil: direkt, menschlich, keine Floskeln, keine Ausrufezeichen, kein "Sie".
Du ziehst den Leser rein – jeder Satz endet mit einer kleinen Spannung die zum naechsten zieht.
Du erklaerst was eine News WIRKLICH bedeutet – die Erkenntnis, nicht das Ereignis.
Du schreibst immer auf Deutsch, auch wenn die Quelle englisch ist.
Du erfindest keine Fakten."""

    n = n or len(top_news)
    user = f"""Schreibe GENAU {n} Posts – einen pro News. Nicht mehr, nicht weniger.

TEASER-Regeln:
- Beginne mit der Erkenntnis, nicht mit dem Ereignis
- Hook + Flip: erst die ueberraschende Wahrheit, dann die Konsequenz
- Maximal 265 Zeichen (Emojis zaehlen als 2)
- Kein Ausrufezeichen, kein Promotional Content
- Ende: (via Quellenname)

THREAD-Regeln – Scampy-6-Struktur:
THREAD X-1 Hook: Sofort rein, kein Anlauf, die Erkenntnis als erster Satz
THREAD X-2 Kontext: Historischer Rahmen + konkrete Zahlen
THREAD X-3 Kaskade: Was das Schritt fuer Schritt konkret bedeutet
THREAD X-4 Gruselig: Was daran beunruhigend oder faszinierend ist
THREAD X-5 Konsequenz: Was das fuer echte Menschen heute bedeutet
THREAD X-6 Fazit: Ein Gedanke der nachhallt – endet mit einer persoenlichen Frage an den Leser
Jeder Thread-Teil: mindestens 180, maximal 265 Zeichen. Kurze Antworten sind Fehler.

ERKLAERUNG: max 60 Zeichen, was die News konkret bedeutet.

Format – EXAKT so, keine Abweichungen:
TEASER 1: [Text]
THREAD 1-1: [Text]
THREAD 1-2: [Text]
THREAD 1-3: [Text]
THREAD 1-4: [Text]
THREAD 1-5: [Text]
THREAD 1-6: [Text]
ERKLAERUNG 1: [Text]
TEASER 2: [Text]
THREAD 2-1: [Text]
THREAD 2-2: [Text]
THREAD 2-3: [Text]
THREAD 2-4: [Text]
THREAD 2-5: [Text]
THREAD 2-6: [Text]
ERKLAERUNG 2: [Text]
TEASER 3: [Text]
THREAD 3-1: [Text]
THREAD 3-2: [Text]
THREAD 3-3: [Text]
THREAD 3-4: [Text]
THREAD 3-5: [Text]
THREAD 3-6: [Text]
ERKLAERUNG 3: [Text]

News (genau diese 3, je eine pro Post):
{news_text}"""

    # NEU: Ollama-Modelle an erster Stelle wenn lokal verfügbar
    ollama_available = _detect_ollama_models()
    modell_liste = ollama_available + MODELLE_POSTS

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    for modell in modell_liste:
        try:
            antwort = _call_llm_api(modell, messages, max_tokens=3600, timeout=90)
            if not antwort:
                logger.warning("Posts: %s liefert leeren Content – naechstes Modell", modell)
                continue
            logger.info("Posts OK mit Modell: %s", modell)
            return antwort
        except HTTPError as e:
            if e.code == 429:
                logger.warning("Posts: %s Rate-Limit (429) – naechstes Modell", modell)
            else:
                logger.warning("Posts: %s fehlgeschlagen: HTTP %s", modell, e.code)
            continue
        except Exception as e:
            logger.warning("Posts: %s fehlgeschlagen: %s", modell, e)
            continue
    logger.error("Posts: Kein Modell verfuegbar – alle Fallbacks erschoepft")
    return "Fehler: Kein Modell verfuegbar"

# -------------------------
# Parsing
# -------------------------
def parse_posts(posts_raw):
    lines = posts_raw.strip().splitlines()
    result = []
    current = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        upper = line.upper()

        if re.match(r'TEASER\s+\d+\s*:', upper):
            if current is not None:
                result.append(current)
            current = {"teaser": line.split(":", 1)[1].strip(), "thread": [], "erklaerung": ""}
        elif re.match(r'THREAD\s+\d+-\d+\s*:', upper):
            if current is not None:
                current["thread"].append(line.split(":", 1)[1].strip())
        elif re.match(r'ERKLAERUNG\s+\d+\s*:', upper):
            if current is not None:
                current["erklaerung"] = line.split(":", 1)[1].strip()

    if current is not None:
        result.append(current)

    return result

# -------------------------
# Telegram – plain text, keine Labels
# Du teilst den Thread selbst ein beim Posten auf X
# -------------------------
def _sanitize_for_telegram(text):
    """Entfernt Zeichen die Telegram HTTP 400 verursachen."""
    # Telegram mag keine ungepaarten < > & Zeichen ohne parse_mode
    # Einfachste Loesung: plain text ohne parse_mode, aber < > & ersetzen
    text = text.replace("&", "und").replace("<", "(").replace(">", ")")
    return text

def _telegram_send_chunk(text, max_retries=3, delay=5):
    text = _sanitize_for_telegram(text)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    logger.info("Telegram: Chunk gesendet (Versuch %d)", attempt)
                    return True
                logger.warning("Telegram API ok=false: %s", resp)
        except Exception as e:
            logger.warning("Telegram Fehler (Versuch %d): %s", attempt, e)
        sleep(delay)
    return False

def _x_intent_url(text):
    """X mit vorbefuelltem Post-Text oeffnen (ein Tap vom Ticker zum Posting)."""
    return "https://x.com/intent/post?text=" + urllib.parse.quote(text or "", safe="")

def _telegram_send_message(text, buttons=None, max_retries=3, delay=5):
    """Einzelnachricht mit HTML-Formatierung + optionalen Inline-Buttons.
    Faellt bei HTML-Parse-Fehlern automatisch auf plain text zurueck."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(1, max_retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    return True
                logger.warning("Telegram API ok=false: %s", resp)
                if "parse" in str(resp.get("description", "")).lower():
                    # HTML-Problem -> naechster Versuch ohne parse_mode
                    payload.pop("parse_mode", None)
                    payload["text"] = _sanitize_for_telegram(text)[:4000]
        except Exception as e:
            logger.warning("Telegram Fehler (Versuch %d): %s", attempt, e)
        sleep(delay)
    return False

def send_telegram_stories(stories, score_map=None, detailliert=False):
    """Eine Nachricht PRO neuer Story: Label + fetter Titel + Teaser +
    Erklaerung, Buttons 'Auf X posten' (Intent-Link) und 'Artikel'.
    detailliert=True (genau 1 neue Story): Thread-Entwurf komplett anhaengen."""
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False
    score_map = score_map or {}

    def esc(t):
        return _html.escape(t or "", quote=False)

    ok_all = True
    for n, p in stories:
        label = score_map.get(n.get("link", ""), {}).get("label", "")
        teile = [f"{label} <b>{esc(n.get('title', ''))}</b>".strip()]
        if p.get("teaser"):
            teile += ["", esc(p["teaser"])]
        if p.get("erklaerung"):
            teile += ["", f"<i>{esc(p['erklaerung'])}</i>"]
        if detailliert and p.get("thread"):
            teile += ["", "<b>Thread-Entwurf:</b>"]
            teile += [f"{i}/ {esc(tweet)}" for i, tweet in enumerate(p["thread"], 1)]
        buttons_row = []
        if p.get("teaser"):
            buttons_row.append({"text": "Auf X posten", "url": _x_intent_url(p["teaser"])})
        if n.get("link"):
            buttons_row.append({"text": "Artikel", "url": n["link"]})
        ok = _telegram_send_message("\n".join(teile), [buttons_row] if buttons_row else None)
        ok_all = ok and ok_all
        sleep(1)  # Telegram-Rate-Limit schonen
    return ok_all

def send_telegram(parsed):
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False

    teile = ["KI News fuer @ScampyNews24_bot\n"]
    for i, p in enumerate(parsed, 1):
        teile.append(f"--- Post {i} ---")
        teile.append(p["teaser"])
        if p.get("erklaerung"):
            teile.append(f"({p['erklaerung']})")
        teile.append("")

    nachricht = "\n".join(teile).strip()

    chunks = []
    if len(nachricht) <= 4000:
        chunks = [nachricht]
    else:
        current_chunk = ""
        for zeile in teile:
            candidate = (current_chunk + "\n" + zeile).strip()
            if len(candidate) > 4000:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = zeile
            else:
                current_chunk = candidate
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

    success = all(_telegram_send_chunk(chunk) for chunk in chunks)
    if not success:
        logger.error("Telegram: Mindestens ein Chunk fehlgeschlagen.")
    return success

# -------------------------
# HTML
# -------------------------
def create_html(alle_news, parsed, summaries):
    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

    news_html = ""
    for i, n in enumerate(alle_news):
        farbe = SOURCE_COLORS.get(n["source"], "#555")
        summary = summaries.get(i, {})
        title_de = summary.get("title_de", n["title"])
        summary_text = summary.get("summary", "")
        news_html += f'''
        <div class="news-item" onclick="toggleNews(this)">
            <div class="news-header">
                <span class="source-badge" style="background:{farbe}">{n["source"]}</span>
                <span class="news-title">{title_de}</span>
                <span class="news-arrow">&#9662;</span>
            </div>
            <div class="news-expand">
                {f'<p class="news-summary">{summary_text}</p>' if summary_text else ""}
                <a href="{n["link"]}" target="_blank" onclick="event.stopPropagation()">&#8594; Artikel lesen</a>
            </div>
        </div>'''

    posts_html = ""
    for i, p in enumerate(parsed, 1):
        teaser = p["teaser"]
        erklaerung = p.get("erklaerung", "")
        thread = p.get("thread", [])
        zeichen = len(teaser)
        zahl_farbe = "#16a34a" if zeichen <= 265 else "#dc2626"

        quelle_name = ""
        quelle_farbe = "#555"
        if "(via " in teaser:
            try:
                quelle_name = teaser.split("(via ")[-1].rstrip(")").strip()
                quelle_farbe = next(
                    (v for k, v in SOURCE_COLORS.items() if k.lower() in quelle_name.lower()), "#555"
                )
            except Exception:
                quelle_name = ""

        thread_html = ""
        if thread:
            n_parts = len(thread)
            thread_parts_html = ""
            for j, t in enumerate(thread, 1):
                label = THREAD_LABELS[j - 1] if j - 1 < len(THREAD_LABELS) else str(j)
                t_zeichen = len(t)
                t_farbe = "#16a34a" if t_zeichen <= 265 else "#dc2626"
                thread_parts_html += f'''
                <div class="thread-part">
                    <div class="thread-meta">
                        <span class="thread-nr">{j}/{n_parts} {label}</span>
                        <span class="thread-zeichen" style="color:{t_farbe}">{t_zeichen}/265</span>
                    </div>
                    <p class="thread-text" id="thread{i}-{j}">{t}</p>
                    <button class="btn-copy-sm" onclick="copyPost(\'thread{i}-{j}\', this)">Kopieren</button>
                </div>'''

            thread_html = f'''
            <div class="thread-toggle" onclick="toggleThread(this)">&#9658; Thread anzeigen ({n_parts} Teile)</div>
            <div class="thread-section" style="display:none">
                {thread_parts_html}
            </div>'''

        posts_html += f'''
        <div class="post-card">
            <div class="post-meta">
                <span class="post-nr">Post {i}</span>
                <span class="post-zeichen" style="color:{zahl_farbe}">{zeichen}/265</span>
            </div>
            <p class="post-text" id="teaser{i}">{teaser}</p>
            {f'<p class="post-erklaerung">{erklaerung}</p>' if erklaerung else ""}
            {f'<span class="post-quelle" style="background:{quelle_farbe}">{quelle_name}</span>' if quelle_name else ""}
            <div class="post-actions">
                <button class="btn-copy" onclick="copyPost(\'teaser{i}\', this)">Kopieren</button>
                <a href="https://x.com/intent/tweet?text={{}}"
                   onclick="this.href=\'https://x.com/intent/tweet?text=\'+encodeURIComponent(document.getElementById(\'teaser{i}\').textContent)"
                   target="_blank" class="btn-x">Posten</a>
            </div>
            {thread_html}
        </div>'''

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KI News Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, Arial, sans-serif; background: #0a0a0a; color: #e7e9ea; min-height: 100vh; }}
        .header {{ background: #000; border-bottom: 1px solid #2f3336; padding: 14px 24px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 10; }}
        .header h1 {{ color: #1d9bf0; font-size: 18px; font-weight: 700; }}
        .header-stats {{ margin-left: auto; display: flex; gap: 20px; }}
        .stat {{ text-align: center; }}
        .stat-zahl {{ font-size: 18px; font-weight: 700; color: #1d9bf0; }}
        .stat-label {{ font-size: 10px; color: #536471; text-transform: uppercase; letter-spacing: 0.5px; }}
        .datum {{ color: #536471; font-size: 12px; margin-left: 16px; }}
        .layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; max-width: 1200px; margin: 0 auto; min-height: calc(100vh - 57px); }}
        .panel {{ padding: 20px; }}
        .panel-left {{ border-right: 1px solid #2f3336; }}
        .panel-title {{ color: #536471; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; padding-bottom: 12px; border-bottom: 1px solid #2f3336; margin-bottom: 4px; }}
        .news-item {{ border-bottom: 1px solid #1a1a1a; cursor: pointer; transition: background 0.15s; border-radius: 6px; }}
        .news-item:hover {{ background: #111; }}
        .news-item.open {{ background: #111; border: 1px solid #2f3336; margin: 4px 0; }}
        .news-header {{ padding: 12px 8px; display: flex; align-items: flex-start; gap: 8px; }}
        .news-title {{ color: #e7e9ea; font-size: 14px; line-height: 1.4; flex: 1; }}
        .news-arrow {{ color: #536471; font-size: 12px; margin-top: 2px; flex-shrink: 0; transition: transform 0.2s; }}
        .news-item.open .news-arrow {{ transform: rotate(180deg); color: #1d9bf0; }}
        .source-badge {{ color: white; font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 10px; white-space: nowrap; margin-top: 2px; flex-shrink: 0; }}
        .news-expand {{ display: none; padding: 0 8px 14px 8px; }}
        .news-item.open .news-expand {{ display: block; }}
        .news-summary {{ font-size: 13px; color: #94a3b8; line-height: 1.5; margin-bottom: 10px; }}
        .news-expand a {{ color: #1d9bf0; font-size: 13px; font-weight: 600; text-decoration: none; }}
        .news-expand a:hover {{ text-decoration: underline; }}
        .post-card {{ background: #111; border: 1px solid #2f3336; border-radius: 14px; padding: 16px; margin: 10px 0; transition: border-color 0.2s; }}
        .post-card:hover {{ border-color: #1d9bf0; }}
        .post-meta {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .post-nr {{ color: #1d9bf0; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }}
        .post-zeichen {{ font-size: 11px; font-weight: 700; }}
        .post-text {{ font-size: 15px; line-height: 1.5; color: #e7e9ea; margin-bottom: 6px; }}
        .post-erklaerung {{ font-size: 12px; color: #536471; margin-bottom: 8px; font-style: italic; }}
        .post-quelle {{ display: inline-block; color: white; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; margin-bottom: 10px; }}
        .post-actions {{ display: flex; gap: 8px; margin-top: 10px; }}
        .btn-copy, .btn-x {{ padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; transition: opacity 0.2s; border: none; }}
        .btn-copy {{ background: #2f3336; color: #e7e9ea; }}
        .btn-copy:hover {{ opacity: 0.8; }}
        .btn-x {{ background: #1d9bf0; color: white; }}
        .btn-x:hover {{ opacity: 0.8; }}
        .copied {{ background: #16a34a !important; }}
        .thread-toggle {{ color: #536471; font-size: 12px; cursor: pointer; margin-top: 12px; padding: 8px 0 0 0; border-top: 1px solid #1a1a1a; user-select: none; transition: color 0.2s; }}
        .thread-toggle:hover {{ color: #1d9bf0; }}
        .thread-section {{ margin-top: 8px; }}
        .thread-part {{ background: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 10px; padding: 10px 12px; margin: 6px 0; }}
        .thread-meta {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .thread-nr {{ color: #536471; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }}
        .thread-zeichen {{ font-size: 10px; font-weight: 700; }}
        .thread-text {{ font-size: 14px; line-height: 1.5; color: #e7e9ea; margin-bottom: 8px; }}
        .btn-copy-sm {{ padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 700; cursor: pointer; background: #1a1a1a; color: #94a3b8; border: 1px solid #2f3336; transition: opacity 0.2s; }}
        .btn-copy-sm:hover {{ opacity: 0.8; }}
        @media (max-width: 700px) {{
            .layout {{ grid-template-columns: 1fr; }}
            .panel-left {{ border-right: none; border-bottom: 1px solid #2f3336; }}
        }}
    </style>
    <script>
        function toggleNews(el) {{ el.classList.toggle('open'); }}
        function toggleThread(btn) {{
            const section = btn.nextElementSibling;
            const isOpen = section.style.display !== 'none';
            section.style.display = isOpen ? 'none' : 'block';
            const n = section.querySelectorAll('.thread-part').length;
            btn.innerHTML = isOpen
                ? '&#9658; Thread anzeigen (' + n + ' Teile)'
                : '&#9660; Thread ausblenden';
        }}
        function copyPost(id, btn) {{
            navigator.clipboard.writeText(document.getElementById(id).textContent);
            const orig = btn.textContent;
            btn.textContent = 'Kopiert';
            btn.classList.add('copied');
            setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 2000);
        }}
    </script>
</head>
<body>
    <div class="header">
        <h1>KI News</h1>
        <div class="header-stats">
            <div class="stat"><div class="stat-zahl">{len(alle_news)}</div><div class="stat-label">News</div></div>
            <div class="stat"><div class="stat-zahl">{len(parsed)}</div><div class="stat-label">Posts</div></div>
            <div class="stat"><div class="stat-zahl">{len(set(n['source'] for n in alle_news))}</div><div class="stat-label">Quellen</div></div>
        </div>
        <span class="datum">Stand: {datum}</span>
    </div>
    <div class="layout">
        <div class="panel panel-left">
            <div class="panel-title">Aktuelle KI-News</div>
            {news_html}
        </div>
        <div class="panel panel-right">
            <div class="panel-title">Post-Vorschlaege fuer @ScampyKI</div>
            {posts_html}
        </div>
    </div>
</body>
</html>"""

    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"

    if proj_dir.exists():
        # Lokal: nur ki_news.html schreiben – index.html ist die Tailwind-Seite, nie überschreiben
        pfad_lokal = str(proj_dir / "ki_news.html")
        try:
            Path(pfad_lokal).write_text(html, encoding="utf-8")
            logger.info("HTML geschrieben: ki_news.html")
        except Exception as e:
            logger.exception("Fehler beim Schreiben HTML: %s", e)
        return pfad_lokal
    else:
        # GitHub Actions: Posts-HTML als ki_news.html, index.html (Tailwind-Dashboard) NICHT anfassen
        pfad = "ki_news.html"
        try:
            Path(pfad).write_text(html, encoding="utf-8")
            logger.info("HTML geschrieben: %s", pfad)
        except Exception as e:
            logger.exception("Fehler beim Schreiben HTML: %s", e)
        return pfad

# -------------------------
# Main
# -------------------------
def main():
    logger.info("Starte KI News Lauf")
    alle_news = []
    for name, url in FEEDS:
        try:
            items = fetch_feed(name, url)
            alle_news.extend(items)
            logger.info("[%s] %d relevante News", name, len(items))
        except Exception as e:
            logger.exception("Fehler beim Feed %s: %s", name, e)

    seen = set()
    unique_news = []
    for n in alle_news:
        if n.get("link") and n["link"] not in seen:
            seen.add(n["link"])
            unique_news.append(n)
    alle_news = unique_news

    if not alle_news:
        logger.info("Keine KI-News gefunden.")
        return

    logger.info("%d KI-News gefunden (gesamt)", len(alle_news))

    # Zusammenfassungen fuer alle News (Dashboard links)
    summaries = summarize_news(alle_news)

    # Link->Titel-DE-Map: sofort aufgebaut, bevor blocked_links die alle_news-Indizes verschiebt.
    # Wird fuer Telegram benoetigt (send_telegram_stories nutzt n['title'] direkt).
    _title_de_by_link = {
        alle_news[i].get("link"): summaries.get(i, {}).get("title_de") or alle_news[i]["title"]
        for i in range(len(alle_news))
        if alle_news[i].get("link")
    }

    # ── Score-Verfall-Historie früh laden, damit Telegram-Auswahl UND Dashboard
    #    nach demselben (verfallenen) Score ranken → identische Top-Storys ──────
    heute = _today_iso()
    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"
    _archive_base = proj_dir if proj_dir.exists() else Path(".")
    _existing_archive = []
    try:
        _arch_path = _archive_base / "archive.json"
        if _arch_path.exists():
            _existing_archive = json.loads(_arch_path.read_text(encoding="utf-8"))
    except Exception:
        _existing_archive = []
    history = build_history_map(_existing_archive)

    # Cluster-Membership-Map: link → ältester first_seen im Cluster (Story-Alter-Fix)
    # Verhindert dass neue Artikel über bekannte Storys mit frischem Datum auftauchen.
    _clusters = cluster_news(alle_news)
    link_to_cluster_age = {}
    for cl in _clusters:
        cl_histories = [history[item["link"]] for item in cl if item.get("link") in history]
        if cl_histories:
            oldest = min(h["first_seen"] for h in cl_histories)
            for item in cl:
                if item.get("link"):
                    link_to_cluster_age[item["link"]] = oldest

    # Dashboard-Config laden (featured + blocked links)
    _cfg_base = proj_dir if proj_dir.exists() else Path(".")
    dash_cfg = load_dashboard_config(_cfg_base)
    featured_links = dash_cfg.get("featured_links", [])
    blocked_links  = set(dash_cfg.get("blocked_links", []))
    if blocked_links:
        before = len(alle_news)
        alle_news = [n for n in alle_news if n.get("link") not in blocked_links]
        logger.info("Blocked-Filter: %d News entfernt", before - len(alle_news))

    # NEU: Top-3 nach (verfallenem) Scoring wählen statt blindem [:3]
    top_news, score_map = pick_top_news(
        alle_news, n=MAX_LLM_NEWS, history=history, featured_links=featured_links
    )
    logger.info("%d News an LLM uebergeben (nach Scoring)", len(top_news))

    # Post-Cache laden – LLM nur für noch nicht analysierte Stories aufrufen
    post_cache = load_post_cache(_cfg_base)
    heute_str  = _today_iso()
    uncached   = [n for n in top_news if n.get("link") not in post_cache]
    cached     = [n for n in top_news if n.get("link") in post_cache]
    if uncached:
        posts_raw    = ask_llm(uncached, n=len(uncached))
        parsed_new   = parse_posts(posts_raw)
        logger.info("%d neue Posts geparst, %d aus Cache", len(parsed_new), len(cached))
        for news_item, p in zip(uncached, parsed_new):
            link = news_item.get("link", "")
            if link:
                post_cache[link] = {
                    "teaser":      p.get("teaser", ""),
                    "erklaerung":  p.get("erklaerung", ""),
                    "thread":      p.get("thread", []),
                    "generated_at": heute_str,
                }
        save_post_cache(_cfg_base, post_cache)
    else:
        logger.info("Alle %d Top-Stories aus Post-Cache (keine LLM-Kosten)", len(top_news))

    # Posts in Reihenfolge der Top-News zusammenbauen
    parsed = [
        {
            "teaser":     post_cache.get(n.get("link",""), {}).get("teaser", ""),
            "erklaerung": post_cache.get(n.get("link",""), {}).get("erklaerung", ""),
            "thread":     post_cache.get(n.get("link",""), {}).get("thread", []),
        }
        for n in top_news
    ]
    logger.info("%d Posts bereit", len(parsed))

    # ── Telegram-Delta: nur NEUE Top-Storys senden, 1 Nachricht pro Story ──
    tg_state_file = Path("telegram_state.json")
    tg_sent = {}
    try:
        tg_sent = json.loads(tg_state_file.read_text(encoding="utf-8")).get("sent_links", {})
    except Exception:
        pass
    neue_stories = [
        ({**n, "title": _title_de_by_link.get(n.get("link"), n["title"])}, p)
        for n, p in zip(top_news, parsed)
        if n.get("link") and n["link"] not in tg_sent
    ]
    if not neue_stories:
        logger.info("Telegram: keine neuen Top-Storys – Versand uebersprungen.")
    elif send_telegram_stories(neue_stories, score_map, detailliert=(len(neue_stories) == 1)):
        jetzt = datetime.now(BERLIN).isoformat()
        for n, _ in neue_stories:
            tg_sent[n["link"]] = jetzt
        if len(tg_sent) > 60:  # State begrenzen: nur die 60 juengsten Links
            tg_sent = dict(sorted(tg_sent.items(), key=lambda kv: kv[1])[-60:])
        try:
            tg_state_file.write_text(
                json.dumps({"sent_links": tg_sent, "stand": jetzt}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("telegram_state.json nicht schreibbar: %s", e)

    # ── news.json schreiben (fuer Dashboard + Archiv) ──────────────────────
    def write_json_file(path_obj, data):
        try:
            path_obj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("JSON geschrieben: %s", path_obj)
        except Exception as e:
            logger.exception("Fehler beim Schreiben %s: %s", path_obj, e)

    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

    # News-Liste mit deutschen Titeln + Zusammenfassungen aufbauen
    # NEU: score + label aus score_map ergänzen, dann Zeit-Verfall anwenden
    news_list = []
    for i, n in enumerate(alle_news):
        s = summaries.get(i, {})
        link = n.get("link", "")
        scoring = score_map.get(link, {})
        raw_score = scoring.get("score", 0)
        # Schon mal gesehen? Dann ursprüngliches Datum + Ausgangs-Score behalten.
        # Neuer Artikel einer bekannten Story? Cluster-Alter erben → kein Score-Revival.
        hist = history.get(link)
        first_seen = hist["first_seen"] if hist else link_to_cluster_age.get(link, heute)
        base_score = hist["base_score"] if hist else raw_score
        # Vorschaubild (og:image) – aus Cache oder einmalig serverseitig holen
        preview_img = resolve_preview_image(link, hist)
        entry = {
            "title":      s.get("title_de", n["title"]),
            "summary":    s.get("summary", ""),
            "link":       link,
            "source":     n.get("source", ""),
            "color":      SOURCE_COLORS.get(n.get("source", ""), "#555"),
            "image":      preview_img,                     # NEU: Vorschaubild für die Karte
            "base_score": base_score,                      # NEU: Ausgangs-Score (verfällt nie)
            "score":      decay_score(base_score, first_seen),  # NEU: aktueller, verfallener Score
            "label":      scoring.get("label", "📰 normal"),
            "first_seen": first_seen,                      # NEU: Erst-Erfassung (Basis für Verfall)
            "date":       first_seen,                      # date = Erst-Erfassung (für Sortierung/Anzeige)
        }
        news_list.append(entry)

    # Artikel älter als MAX_AGE_DAYS aus news.json entfernen
    news_list = [
        n for n in news_list
        if _days_since(n.get("first_seen")) <= MAX_AGE_DAYS
    ]

    # Posts (Teasers) den Top-3-News zuordnen (kommt aus post_cache via parsed)
    posts_list = [
        {"teaser": p.get("teaser",""), "erklaerung": p.get("erklaerung",""), "thread": p.get("thread",[])}
        for p in parsed
    ]

    news_json_data = {
        "stand": datum,
        "news":  news_list,
        "posts": posts_list,
    }

    if proj_dir.exists():
        write_json_file(proj_dir / "news.json", news_json_data)
    else:
        write_json_file(Path("news.json"), news_json_data)

    # ── SSR / Pre-Rendering: aktuelle News als echtes HTML in index.html ──
    # (für Crawler & KI-Bots, die kein JavaScript ausführen)
    try:
        inject_ssr(proj_dir if proj_dir.exists() else Path("."), news_json_data)
    except Exception as e:
        logger.exception("SSR-Injektion fehlgeschlagen: %s", e)
    try:
        inject_admin_posts(proj_dir if proj_dir.exists() else Path("."), news_json_data)
    except Exception as e:
        logger.exception("Admin-Posts SSR fehlgeschlagen: %s", e)

    # ── archive.json kumulativ schreiben ──────────────────────────────────
    def update_archive(base_dir):
        archive_path = base_dir / "archive.json"
        try:
            if archive_path.exists():
                existing = json.loads(archive_path.read_text(encoding="utf-8"))
            else:
                existing = []
        except Exception:
            existing = []

        seen_links = {n["link"] for n in existing if n.get("link")}
        new_entries = [n for n in news_list if n.get("link") and n["link"] not in seen_links]
        # Neuestes vorne, max 2000 Eintraege
        merged = new_entries + existing
        merged = merged[:2000]
        # NEU: Score-Verfall auf das GANZE Archiv neu anwenden, damit auch alte
        # Einträge in der Statistik-Seite über die Zeit absinken (idempotent aus
        # base_score + first_seen). Migriert alte Einträge ohne diese Felder.
        apply_decay_to_entries(merged)
        try:
            archive_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("archive.json aktualisiert: %d Eintraege gesamt (Score-Verfall angewandt)", len(merged))
        except Exception as e:
            logger.exception("Fehler beim Schreiben archive.json: %s", e)

    if proj_dir.exists():
        update_archive(proj_dir)
    else:
        update_archive(Path("."))

    # ── X-Beiträge: fehlende Vorschaubilder serverseitig ergänzen ──────────
    update_media_xpost_images(proj_dir if proj_dir.exists() else Path("."))

    # ── hashtags/hashtags.json aktualisieren ──────────────────────────────
    def update_hashtags(base_dir):
        """Extrahiert Hashtags aus Quellen + News-Titeln und mergt in hashtags.json."""
        hashtag_dir = base_dir / "hashtags"
        hashtag_path = hashtag_dir / "hashtags.json"
        try:
            hashtag_dir.mkdir(exist_ok=True)
            if hashtag_path.exists():
                existing_data = json.loads(hashtag_path.read_text(encoding="utf-8"))
                existing_tags = set(existing_data.get("tags", []))
            else:
                existing_tags = set()
        except Exception:
            existing_tags = set()

        # Basis-Tags aus Quellen
        source_tags = {
            "The Decoder": "#TheDecoder",
            "TechCrunch AI": "#TechCrunch",
            "VentureBeat AI": "#VentureBeat",
            "Ars Technica": "#ArsTechnica",
            "MIT Tech Review": "#MITTechReview",
            "Heise": "#Heise",
        }
        # Keyword-Tags aus Nachrichtentiteln generieren
        keyword_map = {
            "openai": "#OpenAI", "chatgpt": "#ChatGPT", "gpt": "#GPT",
            "claude": "#Claude", "anthropic": "#Anthropic",
            "gemini": "#Gemini", "google": "#Google",
            "meta ai": "#MetaAI", "llama": "#Llama",
            "mistral": "#Mistral", "deepseek": "#DeepSeek",
            "nvidia": "#Nvidia", "gemma": "#Gemma",
            "agent": "#AIAgent", "llm": "#LLM",
            "roboter": "#Robotik", "automation": "#Automation",
            "sicherheit": "#AISafety", "datenschutz": "#Datenschutz",
        }
        new_tags = set()
        for n in alle_news:
            title_lower = n["title"].lower()
            # Quellen-Tag
            src_tag = source_tags.get(n.get("source", ""))
            if src_tag:
                new_tags.add(src_tag)
            # Keyword-Tags aus Titel
            for kw, tag in keyword_map.items():
                if kw in title_lower:
                    new_tags.add(tag)

        # Immer vorhandene Basis-Tags
        base_tags = {"#KI", "#AI", "#AINews", "#KünstlicheIntelligenz", "#LLM"}
        merged = sorted(base_tags | existing_tags | new_tags)

        try:
            hashtag_path.write_text(
                json.dumps({"tags": merged}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info("hashtags.json aktualisiert: %d Tags", len(merged))
        except Exception as e:
            logger.exception("Fehler beim Schreiben hashtags.json: %s", e)

    if proj_dir.exists():
        update_hashtags(proj_dir)
    else:
        update_hashtags(Path("."))

    # ── HTML generieren ───────────────────────────────────────────────────────
    pfad = create_html(alle_news, parsed, summaries)

    logger.info("KI News Lauf abgeschlossen.")


# -------------------------
# Entry Point
# -------------------------
if __name__ == "__main__":
    main()
