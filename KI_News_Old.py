import urllib.request
import xml.etree.ElementTree as ET
import json

NVIDIA_API_KEY = "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"

FEEDS = [
    ("The Decoder", "https://the-decoder.de/feed/"),
    ("Heise", "https://www.heise.de/rss/heise-atom.xml"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]

KI_KEYWORDS = ["ki", "ai", "künstliche", "model", "llm", "gpt", "claude", 
                "chatgpt", "openai", "google", "meta ai", "agent"]

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
                items.append(f"- {title} ({link})")
        return items[:3]
    except Exception as e:
        return [f"Fehler: {e}"]

def ask_nvidia(prompt):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    data = json.dumps({
        "model": "mistralai/mixtral-8x7b-instruct-v0.1",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

print("KI-News werden geladen...\n")
alle_news = []
for name, url in FEEDS:
    items = fetch_feed(name, url)
    print(f"[{name}]")
    for i in items:
        print(i)
        alle_news.append(i)
    print()

prompt = f"""Du bist @CScampy, sachlicher KI-Beobachter aus Deutschland.

News von heute:
{chr(10).join(alle_news)}

Wähle NUR News die direkt mit KI/AI zu tun haben. Security-News, Fundraising ohne KI-Bezug und allgemeine Tech-News ignorieren.

Schreib exakt 2 X-Posts auf Deutsch:
- Maximal 220 Zeichen
- Keine Ausrufezeichen
- Keine Fragen ans Publikum
- Kurze eigene Einordnung
- Am Ende Quelle als (via Seitenname)
- Kein erklärender Kommentar nach den Posts

POST 1: [Text]
POST 2: [Text]"""

print("\nPost-Vorschläge werden generiert...\n")
print(ask_nvidia(prompt))

"Schreib NUR die zwei Posts. Keine Einordnung, kein Kommentar danach. Nichts außer POST 1 und POST 2."