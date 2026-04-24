import urllib.request
import xml.etree.ElementTree as ET
import json
import webbrowser
import os
from datetime import datetime

# API Key laden
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
if not NVIDIA_API_KEY:
    config_pfad = os.path.join(os.path.expanduser("~"), "Documents", "Projekte", "ki-news", "config.txt")
    with open(config_pfad) as f:
        NVIDIA_API_KEY = f.read().strip()

KI_KEYWORDS = ["ki", "ai", "kunstliche", "model", "llm", "gpt", "claude",
                "chatgpt", "openai", "google", "meta ai", "agent", "nvidia",
                "anthropic", "gemini", "mistral", "deepseek"]

FEEDS = [
    ("The Decoder", "https://the-decoder.de/feed/"),
    ("Heise", "https://www.heise.de/rss/heise-atom.xml"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]

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
        return []

def ask_nvidia(alle_news):
    news_text = chr(10).join([f"- {n['title']} (via {n['source']})" for n in alle_news])
    prompt = f"""Du bist @CScampy, sachlicher KI-Beobachter aus Deutschland.

News von heute:
{news_text}

Schreib 3 X-Posts auf Deutsch. Regeln:
- EXAKT zwischen 180 und 240 Zeichen pro Post
- Zaehle die Zeichen selbst bevor du antwortest
- 1-2 passende Emojis pro Post am Anfang oder mittendrin
- Keine Ausrufezeichen
- Optional eine kurze echte Frage ans Ende
- Kurze eigene Einordnung
- Am Ende Quelle als (via Seitenname)
- NUR die Posts kein Kommentar danach

POST 1: [Text]
POST 2: [Text]
POST 3: [Text]"""

    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    data = json.dumps({
        "model": "mistralai/mistral-large-2-instruct-2512",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def send_telegram(posts):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = "9096438"
    if not token:
        print("Kein Telegram Token gefunden")
        return
    nachricht = "KI News fuer @CScampy\n\n" + posts
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": nachricht
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json"
    })
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Telegram: Nachricht gesendet")
    except Exception as e:
        print(f"Telegram Fehler: {e}")

def create_html(alle_news, posts):
    datum = datetime.now().strftime("%d.%m.%Y %H:%M")

    source_colors = {
        "The Decoder": "#1d9bf0",
        "TechCrunch AI": "#ff6b35",
        "VentureBeat AI": "#7c3aed",
        "Ars Technica": "#16a34a",
        "MIT Tech Review": "#dc2626",
        "Heise": "#ca8a04",
    }

    news_html = ""
    for n in alle_news:
        farbe = source_colors.get(n["source"], "#555")
        news_html += f'''
        <div class="news-item">
            <span class="source" style="background:{farbe}">{n["source"]}</span>
            <a href="{n["link"]}" target="_blank">{n["title"]}</a>
        </div>'''

    post_lines = [l.strip() for l in posts.strip().split("\n")
                  if l.strip().startswith("POST")]
    posts_html = ""
    for i, p in enumerate(post_lines, 1):
        text = p.split(":", 1)[1].strip() if ":" in p else p
        zeichen = len(text)
        farbe = "#16a34a" if zeichen <= 240 else "#dc2626"
        posts_html += f'''
        <div class="post-item">
            <div class="post-header">
                <span class="post-nr">Post {i}</span>
                <span class="zeichenzahl" style="color:{farbe}">{zeichen}/280 Zeichen</span>
            </div>
            <p id="post{i}">{text}</p>
            <div class="post-actions">
                <button class="btn-copy" onclick="copyPost('post{i}', this)">Kopieren</button>
                <a href="https://x.com/intent/tweet?text={{}}"
                   onclick="this.href='https://x.com/intent/tweet?text='+encodeURIComponent(document.getElementById('post{i}').textContent)"
                   target="_blank" class="btn-x">X Direkt posten</a>
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
        body {{ font-family: -apple-system, Arial, sans-serif; background: #000; color: #e7e9ea; min-height: 100vh; }}
        .header {{ background: #000; border-bottom: 1px solid #2f3336; padding: 16px 20px; position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 12px; }}
        .header h1 {{ color: #1d9bf0; font-size: 20px; }}
        .datum {{ color: #536471; font-size: 13px; margin-left: auto; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .section-title {{ color: #536471; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; padding: 16px 0 8px; border-bottom: 1px solid #2f3336; margin-bottom: 4px; }}
        .news-item {{ padding: 12px 0; border-bottom: 1px solid #2f3336; display: flex; align-items: flex-start; gap: 8px; }}
        .news-item a {{ color: #e7e9ea; text-decoration: none; font-size: 15px; line-height: 1.4; }}
        .news-item a:hover {{ color: #1d9bf0; }}
        .source {{ color: white; font-size: 10px; font-weight: bold; padding: 2px 8px; border-radius: 12px; white-space: nowrap; margin-top: 2px; }}
        .post-item {{ background: #16181c; border: 1px solid #2f3336; border-radius: 16px; padding: 16px; margin: 12px 0; transition: border-color 0.2s; }}
        .post-item:hover {{ border-color: #1d9bf0; }}
        .post-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
        .post-nr {{ color: #1d9bf0; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; }}
        .zeichenzahl {{ font-size: 12px; font-weight: bold; }}
        .post-item p {{ font-size: 15px; line-height: 1.5; color: #e7e9ea; margin-bottom: 14px; }}
        .post-actions {{ display: flex; gap: 8px; }}
        .btn-copy, .btn-x {{ padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; transition: opacity 0.2s; }}
        .btn-copy {{ background: #2f3336; color: #e7e9ea; border: none; }}
        .btn-copy:hover {{ opacity: 0.8; }}
        .btn-x {{ background: #1d9bf0; color: white; border: none; }}
        .btn-x:hover {{ opacity: 0.8; }}
        .stats {{ display: flex; gap: 16px; padding: 12px 0; border-bottom: 1px solid #2f3336; margin-bottom: 8px; }}
        .stat {{ text-align: center; }}
        .stat-zahl {{ font-size: 22px; font-weight: bold; color: #1d9bf0; }}
        .stat-label {{ font-size: 11px; color: #536471; }}
        .copied {{ background: #16a34a !important; }}
    </style>
    <script>
        function copyPost(id, btn) {{
            const text = document.getElementById(id).textContent;
            navigator.clipboard.writeText(text);
            btn.textContent = 'Kopiert';
            btn.classList.add('copied');
            setTimeout(() => {{
                btn.textContent = 'Kopieren';
                btn.classList.remove('copied');
            }}, 2000);
        }}
    </script>
</head>
<body>
    <div class="header">
        <h1>KI News</h1>
        <span class="datum">Stand: {datum}</span>
    </div>
    <div class="container">
        <div class="stats">
            <div class="stat"><div class="stat-zahl">{len(alle_news)}</div><div class="stat-label">News gefunden</div></div>
            <div class="stat"><div class="stat-zahl">{len(post_lines)}</div><div class="stat-label">Post-Vorschlaege</div></div>
            <div class="stat"><div class="stat-zahl">{len(set(n['source'] for n in alle_news))}</div><div class="stat-label">Quellen</div></div>
        </div>
        <div class="section-title">Aktuelle KI-News</div>
        {news_html}
        <div class="section-title" style="margin-top:24px">Post-Vorschlaege fuer @CScampy</div>
        {posts_html}
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
print("Post-Vorschlaege werden generiert...")

posts = ask_nvidia(alle_news)
send_telegram(posts)

pfad = create_html(alle_news, posts)
print(f"\nFertig! Oeffne: {pfad}")

if os.path.exists(os.path.join(os.path.expanduser("~"), "Documents")):
    webbrowser.open(f"file://{pfad}")
