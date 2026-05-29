# KI News Dashboard · @CScampy

Automatisches KI-News-Dashboard. Sammelt täglich News aus 10 Quellen, generiert fertige X-Posts im Scampy-6-Stil und schickt sie per Telegram.

**Live:** https://dscampy.github.io/ki\_news/

\---

## Was das System macht

1. Holt KI-relevante News aus 10 Quellen (4 deutsch, 6 englisch)
2. Filtert nach KI-Keywords, dedupliziert per URL
3. Übersetzt \& fasst alle News auf Deutsch zusammen (via LLM)
4. Generiert 3 fertige X-Posts im **Scampy-6-Format** (Teaser + 6-teiliger Thread + Erklärung)
5. Schickt die Posts per Telegram an [@ScampyNews24\_bot](https://t.me/ScampyNews24_bot)
6. Aktualisiert `news.json`, `archive.json`, `hashtags/hashtags.json` und `index.html`
7. Committet alles automatisch zurück ins Repo via GitHub Actions

\---

## Zeitplan

Läuft 4× täglich automatisch via GitHub Actions – kein Rechner nötig:

|Berliner Zeit|UTC|
|-|-|
|07:00|05:00|
|12:00|10:00|
|17:00|15:00|
|20:00|18:00|

\---

## News-Quellen

|Quelle|Feed|Sprache|
|-|-|-|
|The Decoder|the-decoder.de/feed/|Deutsch|
|Heise|heise.de/rss/heise-Rubrik-IT-atom.xml|Deutsch|
|Golem|rss.golem.de/rss.php?feed=RSS2.0|Deutsch|
|Caschy Blog|stadt-bremerhaven.de/feed/|Deutsch|
|TechCrunch AI|techcrunch.com/category/artificial-intelligence/feed/|Englisch|
|Ars Technica|feeds.arstechnica.com/arstechnica/technology-lab|Englisch|
|VentureBeat AI|venturebeat.com/category/ai/feed/|Englisch|
|MIT Tech Review|technologyreview.com/feed/|Englisch|
|The Verge|theverge.com/rss/index.xml|Englisch|
|Wired AI|wired.com/feed/tag/artificial-intelligence/rss|Englisch|

\---

## LLM-Modelle (OpenRouter)

Das Script probiert Modelle der Reihe nach. Bei 429 (Rate Limit) sofort weiter zum nächsten.

|Priorität|Modell|Kosten|
|-|-|-|
|1|meta-llama/llama-3.3-70b-instruct:free|kostenlos|
|2|nousresearch/hermes-3-llama-3.1-405b:free|kostenlos|
|3|google/gemma-4-31b-it:free|kostenlos|
|4|tencent/hy3-preview:free|kostenlos|
|5|google/gemma-4-26b-a4b-it:free|kostenlos|
|6|meta-llama/llama-3.3-70b-instruct|\~$0.008/Lauf|
|7|google/gemma-3-27b-it|Fallback|

\---

## GitHub Secrets

|Name|Beschreibung|
|-|-|
|`OPENROUTER\\\_KEY`|OpenRouter API Key (LLM + Zusammenfassungen)|
|`TELEGRAM\\\_TOKEN`|Token des Telegram-Bots (@ScampyNews24\_bot)|
|`GROQ\\\_CHAT\\\_KEY`|Groq API Key (Frontend-Chat auf der Website)|

\---

## Projektstruktur

```
ki\\\_news/
├── ki\\\_news.py                  # Hauptscript
├── index.html                  # Dashboard (automatisch generiert)
├── Archiv.html                 # Archiv-Seite (statisch, manuell gepflegt)
├── news.json                   # Aktuelle News + Posts (automatisch)
├── archive.json                # Kumulatives Archiv, max. 2000 Einträge (automatisch)
├── hashtags/
│   └── hashtags.json           # Auto-generierte Hashtag-Liste (automatisch)
├── .gitignore
└── .github/
    └── workflows/
        └── ki\\\_news.yml         # GitHub Actions Workflow
```

\---

## Scampy-6 Post-Format

Jeder Post besteht aus:

* **Teaser** – max. 265 Zeichen, Hook + Flip, endet mit Quellenangabe
* **Thread 1–6** – je max. 265 Zeichen: Hook → Kontext → Kaskade → Gruselig → Konsequenz → Fazit
* **Erklärung** – max. 60 Zeichen, was die News konkret bedeutet

\---

## Lokale Einrichtung

```bash
git clone https://github.com/DScampy/ki\\\_news.git
cd ki\\\_news
```

OpenRouter-Key in `\\\~/Documents/Projekte/ki-news/config.txt` speichern (wird nie commitet).

```bash
python ki\\\_news.py
```

\---

## Erstellt von

D. Scampy ([@CScampy](https://x.com/CScampy)) · 2026

