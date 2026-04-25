import urllib.request
import xml.etree.ElementTree as ET
import json
import os
import logging
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from time import sleep
from urllib.error import URLError, HTTPError

# -------------------------
# Logging
# -------------------------
LOG_PATH = Path("ki_news.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ki_news")

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

# -------------------------
# Konfiguration
# -------------------------
KI_KEYWORDS = [
    "ki", "ai", "kunstliche", "model", "llm", "gpt", "claude",
    "chatgpt", "openai", "google", "meta ai", "agent", "nvidia",
    "anthropic", "gemini", "mistral", "deepseek"
]

FEEDS = [
    ("The Decoder", "https://the-decoder.de/feed/"),
    ("Heise", "https://www.heise.de/rss/heise-Rubrik-IT-atom.xml"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]

MODELLE = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "meta-llama/llama-3.1-8b-instruct",
]

SOURCE_COLORS = {
    "The Decoder": "#1d9bf0",
    "TechCrunch AI": "#ff6b35",
    "VentureBeat AI": "#7c3aed",
    "Ars Technica": "#16a34a",
    "MIT Tech Review": "#dc2626",
    "Heise": "#ca8a04",
}

# -------------------------
# Feeds
# -------------------------
def http_get_with_retry(url, headers=None, timeout=10, retries=3, backoff=2):
    headers = headers or {"User-Agent": "Mozilla/5.0"}
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (HTTPError, URLError) as e:
            logger.warning("HTTP Fehler %s: %s (Versuch %d/%d)", url, e, attempt, retries)
            sleep(backoff * attempt)
        except Exception as e:
            logger.exception("Unerwarteter Fehler %s: %s", url, e)
            break
    return None

def fetch_feed(name, url):
    raw = http_get_with_retry(url, timeout=15, retries=3, backoff=3)
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
        if title and any(k in title.lower() for k in KI_KEYWORDS):
            items.append({"title": title, "link": link, "source": name})
    return items[:3]

# -------------------------
# LLM
# -------------------------
def summarize_news(alle_news):
    """Deutsche Titel + Zusammenfassungen. Fallback auf Originaltitel wenn noetig."""
    result = {i: {"title_de": n["title"], "summary": ""} for i, n in enumerate(alle_news)}
    if not OPENROUTER_KEY:
        logger.info("Kein OPENROUTER_KEY: Ueberspringe Zusammenfassungen.")
        return result

    batch_size = 6
    url = "https://openrouter.ai/api/v1/chat/completions"

    for batch_start in range(0, len(alle_news), batch_size):
        batch = alle_news[batch_start:batch_start + batch_size]
        news_text = "\n".join([f"{i+1}. {n['title']} (via {n['source']})" for i, n in enumerate(batch)])
        prompt = f"""Fasse jede News auf Deutsch zusammen. Antworte NUR mit JSON, kein weiterer Text, keine Backticks:
[{{"id": 1, "title_de": "Kurzer deutscher Titel", "summary": "2-3 Saetze was passiert ist und warum relevant"}}, ...]

News:
{news_text}"""

        for modell in MODELLE:
            try:
                data = json.dumps({
                    "model": modell,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800
                }).encode()
                req = urllib.request.Request(url, data=data, headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dscampy.github.io/ki_news/",
                    "X-Title": "KI News Dashboard"
                })
                with urllib.request.urlopen(req, timeout=60) as r:
                    antwort = json.loads(r.read())["choices"][0]["message"]["content"].strip()
                    antwort = antwort.replace("```json", "").replace("```", "").strip()
                    summaries = json.loads(antwort)
                    for item in summaries:
                        global_index = batch_start + item["id"] - 1
                        if 0 <= global_index < len(alle_news):
                            result[global_index] = {
                                "title_de": item.get("title_de", alle_news[global_index]["title"]),
                                "summary": item.get("summary", "")
                            }
                    logger.info("Zusammenfassungen Batch %d: OK", batch_start // batch_size + 1)
                    break
            except Exception as e:
                logger.warning("Batch %d mit %s fehlgeschlagen: %s", batch_start // batch_size + 1, modell, e)
                continue
    return result

def ask_llm(alle_news):
    if not OPENROUTER_KEY:
        return ("POST 1: Keine LLM-Verbindung.\nERKLAERUNG 1: Kein Key.\n"
                "POST 2: Keine LLM-Verbindung.\nERKLAERUNG 2: Kein Key.\n"
                "POST 3: Keine LLM-Verbindung.\nERKLAERUNG 3: Kein Key.\n")

    news_text = "\n".join([f"- {n['title']} (via {n['source']})" for n in alle_news])
    system = """Du bist @CScampy, ein sachlicher aber neugieriger KI-Beobachter aus Deutschland.
Dein Stil: direkt, menschlich, keine Floskeln, keine Ausrufezeichen, kein "Sie".
Du erklaerst kurz was eine News wirklich bedeutet - nicht nur was passiert ist, sondern warum es interessant ist.
Du schreibst immer auf Deutsch, auch wenn die Quelle englisch ist.
Du erfindest keine Fakten."""

    user = f"""Hier sind Beispiele wie deine Posts aussehen sollen:

POST: 🤖 Meta kauft ARM statt Intel-Chips - klingt trocken, bedeutet aber weniger Abhaengigkeit von US-Lieferketten und mehr Kontrolle ueber eigene KI-Hardware. Interessant wohin das noch fuehrt (via The Decoder)
ERKLAERUNG: Meta macht sich unabhaengiger von Intel

POST: 📊 DeepSeek V4 ist jetzt das groesste offene KI-Modell und deutlich guenstiger als die Konkurrenz. Gute Nachricht fuer alle die KI nutzen wollen ohne ein Vermoegen auszugeben (via MIT Tech Review)
ERKLAERUNG: Maechtiges KI-Modell jetzt fuer weniger Geld verfuegbar

POST: 🔍 OpenAI-Chefwissenschaftler sagt KI-Entwicklung ist langsamer als viele denken - interessant wenn man bedenkt wie viel Geld gerade in die Branche fliesst. Vielleicht ein Zeichen fuer mehr Realismus (via The Decoder)
ERKLAERUNG: KI-Fortschritt geht langsamer voran als erwartet

Jetzt schreib 3 Posts ueber diese News:
{news_text}

Format - jede Zeile einzeln, nichts vermischen:
POST 1: [Text, zwischen 200 und 240 Zeichen]
ERKLAERUNG 1: [max 60 Zeichen, was bedeutet das konkret]
POST 2: [Text, zwischen 200 und 240 Zeichen]
ERKLAERUNG 2: [max 60 Zeichen]
POST 3: [Text, zwischen 200 und 240 Zeichen]
ERKLAERUNG 3: [max 60 Zeichen]"""

    url = "https://openrouter.ai/api/v1/chat/completions"
    for modell in MODELLE:
        try:
            data = json.dumps({
                "model": modell,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "max_tokens": 800
            }).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://dscampy.github.io/ki_news/",
                "X-Title": "KI News Dashboard"
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                antwort = json.loads(r.read())["choices"][0]["message"]["content"]
                logger.info("Erfolg mit Modell: %s", modell)
                return antwort
        except Exception as e:
            logger.warning("Modell %s fehlgeschlagen: %s", modell, e)
            continue
    return "Fehler: Kein Modell verfuegbar"

# -------------------------
# Parsing
# -------------------------
def parse_posts(posts_raw):
    lines = posts_raw.strip().splitlines()
    result = []
    current = {"post": "", "erklaerung": ""}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("POST") and ":" in line:
            if current["post"]:
                result.append(current)
                current = {"post": "", "erklaerung": ""}
            current["post"] = line.split(":", 1)[1].strip()
        elif upper.startswith("ERKLAERUNG") and ":" in line:
            current["erklaerung"] = line.split(":", 1)[1].strip()
        elif current["post"] and not upper.startswith("ERKLAERUNG") and not current["erklaerung"]:
            current["post"] += " " + line

    if current["post"]:
        result.append(current)
    return result

# -------------------------
# Telegram
# -------------------------
def send_telegram(posts_raw, max_retries=3, delay=5):
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False

    nachricht = "KI News fuer @CScampy\n\n" + posts_raw
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": nachricht}).encode()

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    logger.info("Telegram: Nachricht gesendet (Versuch %d)", attempt)
                    return True
                logger.warning("Telegram API ok=false: %s", resp)
        except Exception as e:
            logger.warning("Telegram Fehler (Versuch %d): %s", attempt, e)
        sleep(delay)
    logger.error("Telegram: Alle Versuche fehlgeschlagen.")
    return False

# -------------------------
# HTML
# -------------------------
def create_html(alle_news, posts_raw, summaries):
    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")
    parsed = parse_posts(posts_raw)

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
        text = p["post"]
        erklaerung = p["erklaerung"] or ""
        zeichen = len(text)
        zahl_farbe = "#16a34a" if 180 <= zeichen <= 240 else ("#f59e0b" if zeichen < 180 else "#dc2626")

        quelle_name = ""
        quelle_farbe = "#555"
        if "(via " in text:
            try:
                quelle_name = text.split("(via ")[-1].rstrip(")").strip()
                quelle_farbe = next(
                    (v for k, v in SOURCE_COLORS.items() if k.lower() in quelle_name.lower()), "#555"
                )
            except Exception:
                quelle_name = ""

        posts_html += f'''
        <div class="post-card">
            <div class="post-meta">
                <span class="post-nr">Post {i}</span>
                <span class="post-zeichen" style="color:{zahl_farbe}">{zeichen}/280</span>
            </div>
            <p class="post-text" id="post{i}">{text}</p>
            {f'<p class="post-erklaerung">{erklaerung}</p>' if erklaerung else ""}
            {f'<span class="post-quelle" style="background:{quelle_farbe}">{quelle_name}</span>' if quelle_name else ""}
            <div class="post-actions">
                <button class="btn-copy" onclick="copyPost(\'post{i}\', this)">Kopieren</button>
                <a href="https://x.com/intent/tweet?text={{}}"
                   onclick="this.href=\'https://x.com/intent/tweet?text=\'+encodeURIComponent(document.getElementById(\'post{i}\').textContent)"
                   target="_blank" class="btn-x">Posten</a>
            </div>
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
        @media (max-width: 700px) {{
            .layout {{ grid-template-columns: 1fr; }}
            .panel-left {{ border-right: none; border-bottom: 1px solid #2f3336; }}
        }}
    </style>
    <script>
        function toggleNews(el) {{ el.classList.toggle('open'); }}
        function copyPost(id, btn) {{
            navigator.clipboard.writeText(document.getElementById(id).textContent);
            btn.textContent = 'Kopiert';
            btn.classList.add('copied');
            setTimeout(() => {{ btn.textContent = 'Kopieren'; btn.classList.remove('copied'); }}, 2000);
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
            <div class="panel-title">Post-Vorschlaege fuer @CScampy</div>
            {posts_html}
        </div>
    </div>
</body>
</html>"""

    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"
    pfad = str(proj_dir / "index.html") if proj_dir.exists() else "index.html"

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

    # Duplikate entfernen
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

    logger.info("%d KI-News gefunden", len(alle_news))
    summaries = summarize_news(alle_news)
    posts_raw = ask_llm(alle_news)
    send_telegram(posts_raw)
    pfad = create_html(alle_news, posts_raw, summaries)
    logger.info("Fertig. HTML: %s", pfad)

    try:
        p = Path(pfad)
        if p.exists():
            webbrowser.open(p.resolve().as_uri())
    except Exception:
        pass

if __name__ == "__main__":
    main()
