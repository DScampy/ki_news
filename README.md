# KI News · ki-news.live

Automatisiertes, deutschsprachiges KI-News-Dashboard. Sammelt mehrmals täglich KI-News aus ~25 Quellen, ordnet sie ein, bewertet ihre Wichtigkeit, fasst sie auf Deutsch zusammen und generiert fertige X-Posts im **Scampy-6-Format** — vollautomatisch via GitHub Actions, kein Server nötig.

**Live:** https://ki-news.live/
**Repo:** https://github.com/DScampy/ki_news
**Von:** Scampy · [@ScampyKI](https://x.com/ScampyKI)

---

## Was das System macht

Bei jedem Lauf (`ki_news.py`):

1. **Holen** — KI-relevante News aus ~25 RSS-Feeds (deutsch, international, Primärquellen der Labs).
2. **Filtern & dedupen** — KI-Keyword-Filter, Duplikate per URL/Titel entfernen.
3. **Clustern & bewerten** — verwandte Meldungen gruppieren, Wichtigkeit scoren (Multi-Quellen-Bonus + Quellen-Prestige + Keyword-Signale). Scores **verfallen über die Zeit** (deterministisch aus `base_score` + Erst-Erfassung), damit alte News absinken.
4. **Übersetzen & zusammenfassen** — alle Meldungen auf Deutsch (via LLM).
5. **Posts generieren** — die Top-Storys als fertige X-Posts im **Scampy-6-Format** (Teaser + 6-teiliger Thread + Erklärung).
6. **Verteilen** — Posts per Telegram an [@ScampyNews24_bot](https://t.me/ScampyNews24_bot).
7. **Schreiben** — aktualisiert `news.json`, `archive.json`, `hashtags/hashtags.json`.
8. **Pre-Rendering (SEO)** — bäckt die aktuellen News als echtes HTML + JSON-LD in `index.html` (Hero + News-Grid), damit Crawler & KI-Bots ohne JavaScript den vollen Inhalt sehen.
9. **Committen** — alles automatisch zurück ins Repo via GitHub Actions.

---

## Zeitplan

Läuft **4× täglich** automatisch via GitHub Actions (`workflow_dispatch` erlaubt manuellen Start):

| Berliner Zeit | UTC |
|---|---|
| 07:00 | 05:00 |
| 12:00 | 10:00 |
| 17:00 | 15:00 |
| 20:00 | 18:00 |

Cron: `0 5,10,15,18 * * *`

---

## News-Quellen (~25)

**Deutsch:** The Decoder · Heise · Golem · Caschy Blog

**International:** TechCrunch AI · Ars Technica · VentureBeat AI · Wired · The Verge · CNBC · SiliconAngle · TechRepublic · Bloomberg · CNet · MIT Technology Review · NYT Technology · OpenAI Blog

**Kuratiert:** AlignedNews

**Primärquellen (Lab-Announcements direkt, via Olshansk/rss-feeds):** Anthropic News · Anthropic Research · Google AI · Meta AI · xAI · Mistral · The Batch

> Die volle, gepflegte Liste steht in `FEEDS` in `ki_news.py`. Feeds, die GitHub-Actions-IPs mit 403 blockieren, werden automatisch übersprungen.

---

## LLM-Modelle

Das Script probiert Modelle der Reihe nach durch; bei `429` (Rate Limit) sofort zum nächsten — kein Retry.

**OpenRouter (Zusammenfassungen):** zuerst Free-Modelle (`llama-3.3-70b:free`, `hermes-3-405b:free`, `gemma-4:free`-Varianten), dann kostenpflichtige Anker (`llama-3.3-70b`, `gemma-3-27b`) als Fallback.

**Posts:** eigene Reihenfolge (`MODELLE_POSTS`) — Gemma zuerst für die beste deutsche Scampy-6-Qualität.

**Lokal (optional):** Läuft ein **Ollama**-Server (`OLLAMA_HOST`, Default `localhost:11434`), werden lokale Modelle (`gemma3:27b` u. a.) automatisch erkannt und für die Post-Generierung bevorzugt — kostenlos, kein Rate-Limit.

---

## Frontend

Statisches Dashboard (kein Build-Step, reines HTML/JS), gehostet auf GitHub Pages über die Custom-Domain `ki-news.live`:

- **5 Design-Themes** — Genesis · Karst · Aurora · Meridian · Blanc, plus Dark/Light-Umschalter (Auswahl wird gespeichert).
- **Animierter Hintergrund** — Three.js-Partikelsystem mit Bloom, themenreaktiv.
- **Hero-Karussell** der Top-Storys + Score-/Prioritäts-Anzeige.
- **News-Grid** mit Quellen-Badges, Vorschaubildern und relativem Datum.
- **Vorlese-Funktion** (TTS) für die aktuellen Meldungen.
- **Chat-Assistent** — konfiguriert über `chat-config.js` (Groq).
- **Podcast- & Video-Einbettungen** (SoundCloud / YouTube).

### Seiten

| Datei | Zweck |
|---|---|
| `index.html` | Dashboard / Startseite (News, Hero, Medien) |
| `artikel.html` + `artikel/*.html` | Longform-Artikel (eigene Texte) |
| `Archiv.html` | Kumulatives News-Archiv |
| `stats.html` | Statistiken (Quellen, Scores, Verlauf) |
| `profil.html` | Profil & Design-Einstellungen |
| `Impressum.html` · `Datenschutz.html` | Rechtliches |
| `Admin.html` · `admin-posts.html` | Interne Verwaltung |

---

## SEO & KI-Sichtbarkeit

- **`robots.txt`** — erlaubt explizit Google + alle relevanten KI-Crawler / Answer Engines (GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Applebot, Bingbot u. v. m.).
- **`sitemap.xml`** — alle Seiten, auf `ki-news.live`.
- **Pre-Rendering (SSR)** — `ki_news.py` schreibt die aktuellen News bei jedem Lauf als echtes HTML + `ItemList`-JSON-LD in `index.html` (Marker `<!-- SSR:NEWS:… -->` / `<!-- SSR:HERO:… -->`). So sehen auch JS-lose Crawler sofort die Schlagzeilen — gleiche Seite, kein Cloaking; das JS-Frontend ersetzt den Block im Browser wie gehabt.
- **Schema.org** — `WebSite` + `Person` JSON-LD auf jeder Seite.

---

## GitHub Secrets

| Name | Beschreibung |
|------|-------------|
| `OPENROUTER_KEY` | OpenRouter API Key (LLM-Zusammenfassungen + Posts) |
| `TELEGRAM_TOKEN` | Token des Telegram-Bots (@ScampyNews24_bot) |
| `GROQ_CHAT_KEY` | Groq API Key (Chat-Assistent auf der Website) |

---

## Projektstruktur

```
ki_news/
├── ki_news.py            # Hauptscript (Fetch, Scoring, LLM, Posts, SSR)
├── index.html            # Dashboard – News-Grid & Hero werden per SSR befüllt
├── artikel.html          # Longform-Übersicht
├── artikel/              # Einzelne Longform-Artikel (eigene Texte)
├── Archiv.html           # News-Archiv
├── stats.html            # Statistik-Seite
├── profil.html           # Profil & Design
├── Admin.html
├── admin-posts.html
├── Impressum.html
├── Datenschutz.html
├── news.json             # Aktuelle News + Posts (automatisch)
├── archive.json          # Kumulatives Archiv, max. 2000 Einträge (automatisch)
├── media.json            # Podcasts / Videos / X-Vorschaubilder
├── dashboard_config.json # Angepinnte / gesperrte Artikel
├── hashtags/
│   └── hashtags.json     # Auto-generierte Hashtag-Liste (automatisch)
├── assets/               # CSS, Fonts, Icons, Embed-Helfer
├── robots.txt
├── sitemap.xml
├── CNAME                 # ki-news.live
└── .github/workflows/
    └── ki_news.yml       # GitHub Actions Workflow (4× täglich)
```

---

## Scampy-6 Post-Format

Jeder generierte X-Post besteht aus:

- **Teaser** — max. 265 Zeichen, Hook + Flip, endet mit Quellenangabe
- **Thread 1–6** — je max. 265 Zeichen: Hook → Kontext → Kaskade → Gruselig → Konsequenz → Fazit
- **Erklärung** — kurz, was die News konkret bedeutet

---

## Lokale Einrichtung

```bash
git clone https://github.com/DScampy/ki_news.git
cd ki_news
```

OpenRouter-Key per Umgebungsvariable `OPENROUTER_KEY` setzen, oder in `~/Documents/Projekte/ki-news/config.txt` ablegen (wird nie committet).

```bash
python ki_news.py
```

> Lokal optional: läuft ein Ollama-Server, werden lokale Modelle automatisch für die Post-Generierung genutzt.

---

## Erstellt von

Scampy ([@ScampyKI](https://x.com/ScampyKI)) · 2026 · 
