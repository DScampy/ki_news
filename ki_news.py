import urllib.request
import xml.etree.ElementTree as ET
import json
import webbrowser
import os
from datetime import datetime, timezone, timedelta
BERLIN = timezone(timedelta(hours=2))  # Sommer: +2, Winter: +1
datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

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
    ("Heise", "https://www.heise.de/rss/heise-Rubrik-IT-atom.xml"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]

MODELLE = [
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "google/gemma-3-27b-it",
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

def ask_nvidia(alle_news):
    news_text = chr(10).join([f"- {n['title']} (via {n['source']})" for n in alle_news])
    prompt = f"""Du bist @CScampy, sachlicher KI-Beobachter aus Deutschland.

News:
{news_text}

WICHTIG zur Laenge: Ein Post muss MINDESTENS so lang sein wie dieser Beispielsatz hier - 
"Meta kauft ARM-Chips statt Intel - das klingt technisch, bedeutet aber: weniger Abhaengigkeit von US-Lieferketten und mehr Kontrolle ueber eigene KI-Hardware. (via The Decoder)" 
Das sind 188 Zeichen. Deine Posts muessen LAENGER sein als dieser Satz.

Regeln:
- Zwischen 180 und 240 Zeichen (zaehle selbst)
- 1-2 Emojis
- Kein "Sie" - direkte Ansprache, schreib wie ein Mensch
- Keine Ausrufezeichen  
- Schreib IMMER auf Deutsch, auch wenn die Quelle englisch ist
- wähle einen sachlichen Ton, einfache Sprache, nicht belehrend, freundlich und neugierig
- Eigene Einordnung: Was bedeutet das wirklich?
- Quelle am Ende als (via Seitenname)
- Keine erfundenen Fakten

POST 1: [Text]
ERKLAERUNG 1: [max 80 Zeichen, einfache Sprache]
POST 2: [Text]
ERKLAERUNG 2: [max 80 Zeichen, einfache Sprache]
POST 3: [Text]
ERKLAERUNG 3: [max 80 Zeichen, einfache Sprache]"""

    url = "https://integrate.api.nvidia.com/v1/chat/completions"

    for modell in MODELLE:
        try:
            print(f"Versuche Modell: {modell}")
            data = json.dumps({
                "model": modell,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800
            }).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json"
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

def create_html(alle_news, posts_raw):
    datum = datetime.now().strftime("%d.%m.%Y %H:%M")
    parsed = parse_posts(posts_raw)

    news_html = ""
    for n in alle_news:
        farbe = SOURCE_COLORS.get(n["source"], "#555")
        news_html += f'''
        <div class="news-item">
            <span class="source" style="background:{farbe}">{n["source"]}</span>
            <a href="{n["link"]}" target="_blank">{n["title"]}</a>
        </div>'''

    posts_html = ""
    for i, p in enumerate(parsed, 1):
        text = p["post"]
        erklaerung = p["erklaerung"] or "Keine Erklaerung verfuegbar."
        zeichen = len(text)
        zahl_farbe = "#16a34a" if zeichen <= 240 else "#dc2626"

        # Quelle aus Post-Text extrahieren
        quelle_name = ""
        quelle_farbe = "#555"
        if "(via " in text:
            quelle_name = text.split("(via ")[-1].rstrip(")").strip()
            quelle_farbe = next(
                (v for k, v in SOURCE_COLORS.items() if k.lower() in quelle_name.lower()),
                "#555"
            )

        quelle_html = ""
        if quelle_name:
            quelle_html = f'''
            <details class="quelle-details">
                <summary style="color:{quelle_farbe}">Quelle anzeigen</summary>
                <span class="quelle-badge" style="background:{quelle_farbe}">{quelle_name}</span>
            </details>'''

        posts_html += f'''
        <div class="post-item">
            <div class="post-header">
                <span class="post-nr">Post {i}</span>
                <span class="zeichenzahl" style="color:{zahl_farbe}">{zeichen}/280</span>
            </div>
            <p id="post{i}">{text}</p>
            <div class="erklaerung-box">
                <span class="erklaerung-icon">💡</span>
                <span class="erklaerung-text">{erklaerung}</span>
                {quelle_html}
            </div>
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
        .post-item p {{ font-size: 15px; line-height: 1.5; color: #e7e9ea; margin-bottom: 12px; }}
        .erklaerung-box {{ background: #0d1117; border: 1px solid #2f3336; border-radius: 10px; padding: 10px 12px; margin-bottom: 12px; display: flex; flex-wrap: wrap; align-items: flex-start; gap: 6px; }}
        .erklaerung-icon {{ font-size: 14px; flex-shrink: 0; margin-top: 1px; }}
        .erklaerung-text {{ font-size: 13px; color: #8b949e; flex: 1; line-height: 1.4; min-width: 0; }}
        .quelle-details {{ width: 100%; margin-top: 6px; }}
        .quelle-details summary {{ font-size: 11px; cursor: pointer; user-select: none; list-style: none; display: inline-flex; align-items: center; gap: 4px; }}
        .quelle-details summary::-webkit-details-marker {{ display: none; }}
        .quelle-details summary::before {{ content: '▶'; font-size: 9px; transition: transform 0.2s; }}
        .quelle-details[open] summary::before {{ transform: rotate(90deg); }}
        .quelle-details summary:hover {{ opacity: 0.8; }}
        .quelle-badge {{ display: inline-block; margin-top: 6px; color: white; font-size: 11px; font-weight: bold; padding: 2px 10px; border-radius: 10px; }}
        .post-actions {{ display: flex; gap: 8px; }}
        .btn-copy, .btn-x {{ padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; transition: opacity 0.2s; border: none; }}
        .btn-copy {{ background: #2f3336; color: #e7e9ea; }}
        .btn-copy:hover {{ opacity: 0.8; }}
        .btn-x {{ background: #1d9bf0; color: white; }}
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
            setTimeout(() => {{ btn.textContent = 'Kopieren'; btn.classList.remove('copied'); }}, 2000);
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
            <div class="stat"><div class="stat-zahl">{len(parsed)}</div><div class="stat-label">Post-Vorschlaege</div></div>
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

posts_raw = ask_nvidia(alle_news)
send_telegram(posts_raw)

pfad = create_html(alle_news, posts_raw)
print(f"\nFertig! Oeffne: {pfad}")

if os.path.exists(os.path.join(os.path.expanduser("~"), "Documents")):
    webbrowser.open(f"file://{pfad}")
