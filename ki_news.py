import re
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
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "9096438"

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

# Nur diese 3 News gehen an den LLM fuer Posts
# Mehr = generischer Fuelltext weil das Modell ueberfordert ist
MAX_LLM_NEWS = 3

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

THREAD_LABELS = ["Hook", "Kontext", "Kaskade", "Gruselig", "Konsequenz", "Fazit"]

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
# LLM – Zusammenfassungen (alle News, fuer Dashboard links)
# -------------------------
def summarize_news(alle_news):
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

# -------------------------
# LLM – Posts Tuki-6
# Bekommt nur MAX_LLM_NEWS Items – mehr = Fuelltext
# -------------------------
def ask_llm(top_news):
    if not OPENROUTER_KEY:
        fallback = ""
        for i in range(1, 4):
            fallback += f"TEASER {i}: Keine LLM-Verbindung – kein OPENROUTER_KEY.\n"
            for j in range(1, 7):
                fallback += f"THREAD {i}-{j}: Kein Key.\n"
            fallback += f"ERKLAERUNG {i}: Kein Key.\n"
        return fallback

    news_text = "\n".join([f"- {n['title']} (via {n['source']})" for n in top_news])

    system = """Du bist @CScampy, ein sachlicher aber neugieriger KI-Beobachter aus Deutschland.
Dein Stil: direkt, menschlich, keine Floskeln, keine Ausrufezeichen, kein "Sie".
Du ziehst den Leser rein – jeder Satz endet mit einer kleinen Spannung die zum naechsten zieht.
Du erklaerst was eine News WIRKLICH bedeutet – die Erkenntnis, nicht das Ereignis.
Du schreibst immer auf Deutsch, auch wenn die Quelle englisch ist.
Du erfindest keine Fakten."""

    user = f"""Schreibe GENAU 3 Posts – einen pro News. Nicht mehr, nicht weniger.

TEASER-Regeln:
- Beginne mit der Erkenntnis, nicht mit dem Ereignis
- Hook + Flip: erst die ueberraschende Wahrheit, dann die Konsequenz
- Maximal 265 Zeichen (Emojis zaehlen als 2)
- Kein Ausrufezeichen, kein Promotional Content
- Ende: (via Quellenname)

THREAD-Regeln – Tuki-6-Struktur:
THREAD X-1 Hook: Sofort rein, kein Anlauf, die Erkenntnis als erster Satz
THREAD X-2 Kontext: Historischer Rahmen + konkrete Zahlen
THREAD X-3 Kaskade: Was das Schritt fuer Schritt konkret bedeutet
THREAD X-4 Gruselig: Was daran beunruhigend oder faszinierend ist
THREAD X-5 Konsequenz: Was das fuer echte Menschen heute bedeutet
THREAD X-6 Fazit: Ein Gedanke der nachhallt – endet mit einer persoenlichen Frage an den Leser
Jeder Thread-Teil: maximal 265 Zeichen.

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

    url = "https://openrouter.ai/api/v1/chat/completions"
    for modell in MODELLE:
        try:
            data = json.dumps({
                "model": modell,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "max_tokens": 2400
            }).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://dscampy.github.io/ki_news/",
                "X-Title": "KI News Dashboard"
            })
            with urllib.request.urlopen(req, timeout=90) as r:
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

def send_telegram(parsed):
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False

    teile = ["KI News fuer @CScampy\n"]
    for i, p in enumerate(parsed, 1):
        teile.append(f"--- Post {i} ---")
        teile.append(p["teaser"])
        if p.get("erklaerung"):
            teile.append(f"({p['erklaerung']})")
        if p.get("thread"):
            teile.append("")
            for t in p["thread"]:
                teile.append(t)
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
            <div class="panel-title">Post-Vorschlaege fuer @CScampy</div>
            {posts_html}
        </div>
    </div>
</body>
</html>"""

    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"

    if proj_dir.exists():
        # Lokal: nur ki_news.html – index.html ist die oeffentliche Startseite, wird nicht angefasst
        pfad_lokal = proj_dir / "ki_news.html"
    else:
        # GitHub Actions: nur ki_news.html committen
        pfad_lokal = Path("ki_news.html")

    try:
        pfad_lokal.write_text(html, encoding="utf-8")
        logger.info("HTML geschrieben: %s", pfad_lokal)
    except Exception as e:
        logger.exception("Fehler beim Schreiben HTML: %s", e)
    return str(pfad_lokal)

# -------------------------
# JSON Export fuer index.html
# -------------------------
def write_news_json(alle_news, summaries):
    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")
    items = []
    for i, n in enumerate(alle_news):
        summary = summaries.get(i, {})
        items.append({
            "title": summary.get("title_de", n["title"]),
            "summary": summary.get("summary", ""),
            "link": n["link"],
            "source": n["source"],
            "color": SOURCE_COLORS.get(n["source"], "#555")
        })
    payload = {"stand": datum, "news": items}

    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"
    pfad = (proj_dir / "news.json") if proj_dir.exists() else Path("news.json")
    try:
        pfad.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("news.json geschrieben: %d Items", len(items))
    except Exception as e:
        logger.exception("Fehler beim Schreiben news.json: %s", e)


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

    # LLM bekommt nur die 3 besten – verhindert Fuelltext
    top_news = alle_news[:MAX_LLM_NEWS]
    logger.info("%d News an LLM uebergeben", len(top_news))

    posts_raw = ask_llm(top_news)
    parsed = parse_posts(posts_raw)
    logger.info("%d Posts geparst", len(parsed))

    send_telegram(parsed)
    write_news_json(alle_news, summaries)
    pfad = create_html(alle_news, parsed, summaries)
    logger.info("Fertig. HTML: %s", pfad)

    try:
        p = Path(pfad)
        if p.exists():
            webbrowser.open(p.resolve().as_uri())
    except Exception:
        pass

if __name__ == "__main__":
    main()
