# 🤖 KI News Dashboard – @CScampy

Automatisches KI-News-Dashboard das täglich aktuelle KI-News sammelt, Post-Vorschläge für X generiert und per Telegram verschickt.

---

## Was das System macht

1. Holt automatisch KI-relevante News aus 6 Quellen
2. Filtert nur Artikel mit KI-Bezug heraus
3. Generiert 3 fertige X-Post-Vorschläge via NVIDIA API
4. Schickt die Posts per Telegram ans Handy
5. Aktualisiert eine öffentliche HTML-Seite auf GitHub Pages

**Live-Seite:** https://dscampy.github.io/ki_news/ki_news.html

---

## Automatischer Zeitplan

Das System läuft täglich automatisch via GitHub Actions – ohne dass der Rechner an sein muss:

- **7:00 Uhr** (UTC 6:00)
- **12:00 Uhr** (UTC 11:00)
- **17:00 Uhr** (UTC 16:00)

---

## News-Quellen

| Quelle | URL | Sprache |
|--------|-----|---------|
| The Decoder | the-decoder.de/feed/ | Deutsch |
| Heise | heise.de/rss/heise-atom.xml | Deutsch |
| TechCrunch AI | techcrunch.com/category/artificial-intelligence/feed/ | Englisch |
| Ars Technica | feeds.arstechnica.com/arstechnica/technology-lab | Englisch |
| VentureBeat AI | venturebeat.com/category/ai/feed/ | Englisch |
| MIT Tech Review | technologyreview.com/feed/ | Englisch |

---

## Voraussetzungen

- Python 3.11+
- NVIDIA API Key (kostenlos auf build.nvidia.com)
- Telegram Bot Token (@BotFather)
- GitHub Account

---

## Lokale Einrichtung

### 1. Repository klonen

```bash
git clone https://github.com/DScampy/ki_news.git
cd ki_news
```

### 2. Config-Datei anlegen

Erstelle die Datei `Documents/Projekte/ki-news/config.txt` mit deinem NVIDIA API Key:

```
nvapi-DEIN-KEY-HIER
```

Diese Datei wird durch `.gitignore` nie auf GitHub hochgeladen.

### 3. Script lokal ausführen

```bash
python ki_news.py
```

Der Browser öffnet sich automatisch mit dem Dashboard.

---

## GitHub Actions Einrichtung

### Secrets hinterlegen

Geh auf GitHub → Repository → Settings → Secrets and variables → Actions:

| Name | Wert |
|------|------|
| `NVIDIA_API_KEY` | Dein NVIDIA API Key |
| `TELEGRAM_TOKEN` | Dein Telegram Bot Token |

### GitHub Pages aktivieren

Settings → Pages → Branch: main → Save

### Workflow manuell auslösen

Actions → KI-Nachrichten-Update → Run workflow

---

## Telegram Bot Einrichtung

1. Schreib `@BotFather` auf Telegram
2. `/newbot` → Name vergeben → Token kopieren
3. Token als GitHub Secret `TELEGRAM_TOKEN` hinterlegen
4. Dem Bot einmal eine Nachricht schicken (Pflicht damit er dir schreiben kann)
5. Deine Chat-ID über `@userinfobot` herausfinden

Die Chat-ID ist im Script fest eingetragen (`9096438`).

---

## Projektstruktur

```
ki_news/
├── ki_news.py              # Hauptscript
├── ki_news.html            # Generiertes Dashboard (wird automatisch aktualisiert)
├── .gitignore              # config.txt wird nicht hochgeladen
└── .github/
    └── workflows/
        └── ki_news.yml     # GitHub Actions Workflow
```

---

## KI-Modell

Aktuell wird `meta/llama-3.1-8b-instruct` über die kostenlose NVIDIA NIM API verwendet.

Das Modell kann in `ki_news.py` Zeile 67 geändert werden:

```python
"model": "meta/llama-3.1-8b-instruct",
```

Verfügbare kostenlose Modelle: https://build.nvidia.com

---

## Dashboard Features

- Dunkles X-ähnliches Design
- Farbkodierte Quellen-Labels
- Zeichenzähler pro Post (grün = OK, rot = zu lang)
- Kopieren-Button mit Bestätigung
- "X Direkt posten" Button
- Automatischer Timestamp

---

## Nächste geplante Schritte

- [ ] Tuki-Stil Prompts ("Verstehst du was passiert?")
- [ ] Mehr Quellen einbauen (Import AI, Hugging Face Blog)
- [ ] Kurze Einordnung pro News-Artikel
- [ ] Obsidian Integration für persistentes Gedächtnis

---

## Erstellt von

D. Scampy (@CScampy) · April 2026 · erstellt mit Claude
