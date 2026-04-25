import urllib.request
import xml.etree.ElementTree as ET
import json
import webbrowser
import os
from datetime import datetime, timezone, timedelta

BERLIN = timezone(timedelta(hours=2))  # Sommer: UTC+2 | Winter: UTC+1 anpassen

# API Key laden
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    config_pfad = os.path.join(os.path.expanduser("~"), "Documents", "Projekte", "ki-news", "config.txt")
    with open(config_pfad) as f:
        OPENROUTER_KEY = f.read().strip()

KI_KEYWORDS = ["ki", "ai", "kunstliche", "model", "llm", "gpt", "claude",
                "chatgpt", "openai", "google", "meta ai", "agent", "nvidia",
                "anthropic", "gemini", "mistral", "deepseek"]

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

def fetch_feed(name, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in list(root.iter("item"))[:10]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            if title and any(k in title.lower() for k in KI_KEYWORDS):
                items.append({"title": title, "link": link, "source": name})
        return items[:3]
    except Exception as e:
        print(f"[{name}] Fehler: {e}")
        return []

def summarize_news(alle_news):
    """Generiert deutsche 2-3-Satz-Zusammenfassungen für alle News in einem Batch-Call."""
    news_text = "\n".join([f"{i+1}. {n['title']} (via {n['source']})" for i, n in enumerate(alle_news)])

    prompt = f"""Fasse jede der folgenden News auf Deutsch zusammen.
Erkläre sachlich was passiert ist und warum es relevant ist. Kein Marketingsprech.
Antworte NUR mit einem JSON-Array, kein weiterer Text, keine Backticks:
[{{"id": 1, "title_de": "Kurzer deutscher Titel", "summary": "2-3 Sätze..."}}, ...]

News:
{news_text}"""

    url = "https://openrouter.ai/api/v1/chat/completions"

    for modell in MODELLE:
        try:
            data = json.dumps({
                "model": modell,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500
            }).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://dscampy.github.io/ki_news/",
                "X-Title": "KI News Dashboard"
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                antwort = json.loads(r.read())["choices"][0]["message"]["content"].strip()
                # Backticks entfernen falls das Modell sie trotzdem schreibt
                antwort = antwort.replace("```json", "").replace("```", "").strip()
                summaries = json.loads(antwort)
                print(f"Zusammenfassungen: {len(summaries)} generiert")
                return {item["id"] - 1: {"title_de": item.get("title_de", ""), "summary": item.get("summary", "")} for item in summaries}
        except Exception as e:
            print(f"Zusammenfassung mit {modell} fehlgeschlagen: {e}")
            continue

    return {}

def ask_llm(alle_news):
    news_text = chr(10).join([f"- {n['title']} (via {n['source']})" for n in alle_news])

    system = """Du bist @CScampy, ein sachlicher aber neugieriger KI-Beobachter aus Deutschland.
Dein Stil: direkt, menschlich, keine Floskeln, keine Ausrufezeichen, kein "Sie".
Du erklärst kurz was eine News wirklich bedeutet - nicht nur was passiert ist, sondern warum es interessant ist.
Du schreibst immer auf Deutsch, auch wenn die Quelle englisch ist.
Du erfindest keine Fakten."""

    user = f"""Hier sind Beispiele wie deine Posts aussehen sollen:

POST: 🤖 Meta kauft ARM statt Intel-Chips - klingt trocken, bedeutet aber weniger Abhängigkeit von US-Lieferketten und mehr Kontrolle über eigene KI-Hardware. Interessant wohin das noch führt (via The Decoder)
ERKLAERUNG: Meta macht sich unabhängiger von Intel

POST: 📊 DeepSeek V4 ist jetzt das größte offene KI-Modell und deutlich günstiger als die Konkurrenz. Gute Nachricht für alle die KI nutzen wollen ohne ein Vermögen auszugeben (via MIT Tech Review)
ERKLAERUNG: Mächtiges KI-Modell jetzt für weniger Geld verfügbar

POST: 🔍 OpenAI-Chefwissenschaftler sagt KI-Entwicklung ist langsamer als viele denken - interessant wenn man bedenkt wie viel Geld gerade in die Branche fließt. Vielleicht ein Zeichen für mehr Realismus (via The Decoder)
ERKLAERUNG: KI-Fortschritt geht langsamer voran als erwartet

Jetzt schreib 3 Posts über diese News:
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
            print(f"Versuche Modell: {modell}")
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
                print(f"Erfolg mit: {modell}")
                return antwort
        except Exception as e:
            print(f"Modell {modell} fehlgeschlagen: {e}")
            continue

    return "Fehler: Kein Modell verfuegbar"

def parse_posts(posts_raw):
    lines = posts_raw.strip().split("\n")
    result = []
    current = {"post": "", "erklaerung": ""}

    for line in lines:
        line = line.strip()
        upper = line.upper()
        if upper.startswith("POST") and ":" in line:
            if current["post"]:
                result.append(current)
                current = {"post": "", "erklaerung": ""}
            current["post"] = line.split(":", 1)[1].strip()
        elif upper.startswith("ERKLAERUNG") and ":" in line:
            current["erklaerung"] = line.split(":", 1)[1].strip()
        elif current["post"] and not upper.startswith("ERKLAERUNG") and line and not current["erklaerung"]:
            current["post"] += " " + line

    if current["post"]:
        result.append(current)

    return result

def send_telegram(posts_raw):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = "9096438"
    if not token:
        print("Kein Telegram Token gefunden")
        return
    nachricht = "KI News fuer @CScampy\n\n" + posts_raw
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": nachricht}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Telegram: Nachricht gesendet")
    except Exception as e:
        print(f"Telegram Fehler: {e}")

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
                <span class="news-arrow">▾</span>
            </div>
            <div class="news-expand">
                {f'<p class="news-summary">{summary_text}</p>' if summary_text else ""}
                <a href="{n["link"]}" target="_blank" onclick="event.stopPropagation()">→ Artikel lesen</a>
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
            quelle_name = text.split("(via ")[-1].rstrip(")").strip()
            quelle_farbe = next(
                (v for k, v in SOURCE_COLORS.items() if k.lower() in quelle_name.lower()),
                "#555"
            )

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
                <button class="btn-copy" onclick="copyPost('post{i}', this)">Kopieren</button>
                <a href="https://x.com/intent/tweet?text={{}}"
                   onclick="this.href='https://x.com/intent/tweet?text='+encodeURIComponent(document.getElementById('post{i}').textContent)"
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

        /* News Items – klappbar */
        .news-item {{ border-bottom: 1px solid #1a1a1a; cursor: pointer; transition: background 0.15s; border-radius: 6px; }}
        .news-item:hover {{ background: #111; }}
        .news-item.open {{ background: #111; border: 1px solid #2f3336; margin: 4px 0; }}
        .news-header {{ padding: 12px 8px; display: flex; align-items: flex-start; gap: 8px; }}
        .news-title {{ color: #e7e9ea; font-size: 14px; line-height: 1.4; flex: 1; }}
        .news-arrow {{ color: #536471; font-size: 12px; margin-top: 2px; flex-shrink: 0; transition: transform 0.2s; }}
        .news-item.open .news-arrow {{ transform: rotate(180deg); color: #1d9bf0; }}
        .source-badge {{ color: white; font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 10px; white-space: nowrap; margin-top: 2px; flex-shrink: 0; }}

        /* Aufklapp-Bereich */
        .news-expand {{ display: none; padding: 0 8px 14px 8px; }}
        .news-item.open .news-expand {{ display: block; }}
        .news-summary {{ font-size: 13px; color: #94a3b8; line-height: 1.5; margin-bottom: 10px; }}
        .news-expand a {{ color: #1d9bf0; font-size: 13px; font-weight: 600; text-decoration: none; }}
        .news-expand a:hover {{ text-decoration: underline; }}

        /* Posts */
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
        function toggleNews(el) {{
            el.classList.toggle('open');
        }}
        function copyPost(id, btn) {{
            const text = document.getElementById(id).textContent;
            navigator.clipboard.writeText(text);
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

    if os.path.exists(os.path.join(os.path.expanduser("~"), "Documents", "Projekte", "ki-news")):
        pfad = os.path.join(os.path.expanduser("~"), "Documents", "Projekte", "ki-news", "ki_news.html")
    else:
        pfad = "ki_news.html"

    with open(pfad, "w", encoding="utf-8") as f:
        f.write(html)
    return pfad

# Hauptprogramm
print("KI-News werden geladen...")
alle_news = []
for name, url in FEEDS:
    items = fetch_feed(name, url)
    alle_news.extend(items)
    print(f"[{name}] {len(items)} relevante News")

print(f"\n{len(alle_news)} KI-News gefunden")
print("Zusammenfassungen werden generiert...")
summaries = summarize_news(alle_news)

print("Post-Vorschlaege werden generiert...")
posts_raw = ask_llm(alle_news)
send_telegram(posts_raw)

pfad = create_html(alle_news, posts_raw, summaries)
print(f"\nFertig! Oeffne: {pfad}")

if os.path.exists(os.path.join(os.path.expanduser("~"), "Documents")):
    webbrowser.open(f"file://{pfad}")
