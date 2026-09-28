Du bist Frontend-Designerin fuer die deutsche KI-Nachrichtenseite ki-news.live (Betreiber Daniel, "Scampy").
Liefere EINE vollstaendige Datei `_graph_v2.html` in einem einzigen ```html Codeblock, danach hoechstens 10 Zeilen: was du gebaut
hast und wie man es in die echte Seite einbaut.
Es ist ein PROTOTYP neben der echten Seite, gleiche Handschrift (siehe Screenshot der Startseite: helles und dunkles
Design, Tuerkis #00d4ff, Violett, feines Raster, 'Space Grotesk' fuer Headlines, 'Work Sans' fuer Text, Monospace-Meta,
Tag-Pillen). Einbinden wie die echten Seiten: <link rel="stylesheet" href="assets/ki-fonts.css">,
<link rel="stylesheet" href="assets/ki-tw.css">, <script src="assets/ki-icons.js"></script>,
<script src="assets/ki-layout.js"></script> (liefert Kopfzeile, Navigation, Theme; eigene CSS-Klassen mit Praefix px-).
Daten nur per fetch mit relativem Pfad (news.json, cards.json, archive.json ...; Aufbau siehe DATENPROBEN, pruefe Felder
defensiv). Keine weiteren externen Ressourcen, ausser wo der Auftrag es erlaubt. Texte aus Daten nur per textContent.
Kein Em-Dash (—) im sichtbaren Text. Handy 390px ohne horizontalen Ueberlauf. Nie blockieren, Fehler abfangen, leere
Daten freundlich zeigen. Deutsch, sachlich, kein Hype. Sei mutig: Canvas/SVG-Grafiken, Karten, Mikroanimationen,
ungewoehnliche Layouts sind ausdruecklich erwuenscht, solange es schnell laedt und lesbar bleibt.

AUFTRAG:
graph.html weiterentwickeln (KONTEXT: aktuelle graph.html,
behalte deren Datenlogik). Liefere eine komplette, deutlich bessere Fassung: Zeitregler (letzte 1/7/30 Tage),
Knotengroesse = Erwaehnungen, Farbe nach Typ/Thema, Suche mit Hervorhebung, Detail-Panel beim Klick mit den
zugehoerigen Meldungen, Ansicht "Heute neu", fluessig auf Handy (Touch, Pinch). Canvas bevorzugt.

=== DATENPROBEN (gekuerzt: Listen auf 2 Eintraege, Texte auf 160 Zeichen) ===

--- news.json ---
{
 "stand": "16.09.2026 07:11",
 "news": [
  {
   "title": "Amazon-Datenverlust im Iran-Krieg und Roboter als sicherer Mitarbeiter.",
   "summary": "Heise berichtet über einen Datenverlust bei Amazon im Zusammenhang mit dem Iran-Konflikt sowie über den Einsatz von Robotern als sichere Mitarbeiter-Alternative",
   "link": "https://www.heise.de/news/Mittwoch-Amazon-Datenverlust-im-Iran-Krieg-Roboter-als-sicherer-Mitarbeiter-11454527.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
   "source": "Heise",
   "color": "#ca8a04",
   "image": "https://heise.cloudimg.io/v7/_www-heise-de_/imgs/18/5/1/6/5/7/7/9/mittwoch-b4d6ef0c91e3813f.webp?func=bound&height=1200&org_if_sml=1&q=85&width=1200",
   "region": "welt",
   "base_score": 20,
   "score": 20,
   "label": "📰 normal",
   "first_seen": "2026-09-16",
   "date": "2026-09-16",
   "story_id": "s028",
   "story_cluster_score": 20,
   "story_article_count": 1,
   "dub_von": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag"
  },
  {
   "title": "Neuer humanoider Roboter soll für sichere Arbeit mit Menschen geeignet sein.",
   "summary": "Ein neu vorgestellter humanoider Roboter wurde speziell für die sichere Zusammenarbeit mit Menschen entwickelt. Er verfügt über Sensoren und Steuerungsmechanism",
   "link": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
   "source": "Heise",
   "color": "#ca8a04",
   "image": "https://heise.cloudimg.io/v7/_www-heise-de_/imgs/18/5/1/6/5/7/7/2/Agility_Digit_5_sit-8b1915ecf232bbf1.webp?func=bound&height=1200&org_if_sml=1&q=85&width=1200",
   "region": "welt",
   "base_score": 56,
   "score": 56,
   "label": "🔥 episch",
   "first_seen": "2026-09-16",
   "date": "2026-09-16",
   "story_id": "s001",
   "story_cluster_score": 56,
   "story_article_count": 2,
   "full_text": "Neuer humanoider Roboter soll für sichere Arbeit mit Menschen geeignet sein | heise online\n heise+ entdecken Suchen Abo Suchen Alle Magazine im Browser lesen An",
   "paywalled": false,
   "dub_quellen": [
    "The Decoder"
   ]
  },
  "... (163 Eintraege)"
 ],
 "posts": [
  {
   "teaser": "Kooperation ist die neue Waffe gegen das eigene Risiko. Die größten Rivalen bündeln ihre Kräfte bei der Sicherheit, was bedeutet, dass sie das Spielfeld der Reg",
   "erklaerung": "Die größten KI-Firmen arbeiten jetzt zusammen, um Regeln für die Sicherheit zu finden. Das ist so, als würden die drei größten Automobilhersteller gemeinsam ent",
   "thread": [
    "Die größten Giganten der Branche hören plötzlich auf, sich nur gegenseitig zu bekämpfen, und bilden ein unsichtbares Bündnis. Es geht nicht um freundschaftliche",
    "OpenAI, Anthropic und Google arbeiten bisher in einem gnadenlosen Wettrüsten um die Vorherrschaft. Jetzt verschieben sie den Fokus auf gemeinsame Sicherheitssta",
    "... (6 Eintraege)"
   ],
   "link": "https://siliconangle.com/2026/09/15/openai-anthropic-and-google-secretly-joined-forces-to-collaborate-on-ai-safety/",
   "story_id": "s000"
  },
  {
   "teaser": "Maschinen lernen gerade, unsere physische Welt ohne Angst zu berühren. Ein neuer humanoider Roboter wird so gebaut, dass er nicht nur Aufgaben erledigt, sondern",
   "erklaerung": "Es gibt neue Roboter, die wie Menschen aussehen und sich sicher im Raum bewegen können. Das heißt, sie könnten bald direkt neben dir in der Halle oder im Lager ",
   "thread": [
    "Die Grenze zwischen Werkstatt und menschlichem Lebensraum verschwimmt durch eine neue Generation von Robotern. Es geht nicht mehr um starre Maschinen hinter Git",
    "Früher waren Industrieroboter schwere, unkontrollierbare Stahlklötze in isolierten Bereichen. Diese neuen humanoiden Modelle nutzen Sensoren und KI, um jede kle",
    "... (6 Eintraege)"
   ],
   "link": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
   "story_id": "s001"
  },
  "... (7 Eintraege)"
 ],
 "roundups": [
  {
   "title": "AI Agents, Foldables, Cyberthreats, and Chip Deals Define This Week in Tech - techrepublic.com",
   "link": "https://news.google.com/rss/articles/CBMirwFBVV95cUxOQV9mdllWQzRkV2hGazd6ek1tdHd3bkh2UXBJTzVXeTNGd0FGQ3FCUk9nRER5WmdvOFlXVzNndXRkRHJpZXl3OF9wcU1QUzBkQzNkMEhZRE9",
   "source": "TechRepublic",
   "date": "2026-09-16",
   "first_seen": "2026-09-16"
  }
 ],
 "feed_uebernahme": {},
 "gn_aufloesung": {
  "neu": 3,
  "archiv": 19,
  "fehler": 0,
  "premium": 39,
  "budget": 0
 },
 "belegarchiv": {
  "aktiv": true,
  "eingereicht": 2,
  "gesichert": 0,
  "fehler": 3,
  "offen": 9,
  "uebersprungen": 0
 },
 "briefing": {
  "datum": "2026-09-16",
  "stand": "16.09.2026 07:11",
  "stories": [
   {
    "title": "OpenAI, Anthropic und Google haben sich heimlich zusammengeschlossen, um an KI-Sicherheit zu kooperieren",
    "link": "https://siliconangle.com/2026/09/15/openai-anthropic-and-google-secretly-joined-forces-to-collaborate-on-ai-safety/",
    "source": "SiliconAngle",
    "label": "🔥 episch",
    "score": 67,
    "story_id": "s000"
   },
   {
    "title": "Neuer humanoider Roboter soll für sichere Arbeit mit Menschen geeignet sein.",
    "link": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
    "source": "Heise",
    "label": "🔥 episch",
    "score": 56,
    "story_id": "s001"
   },
   "... (5 Eintraege)"
  ]
 }
}

--- cards.json ---
[
 {
  "id": "2026-09-16-nvidias-huang-zerreit-anthropics-vorschlag-fr-ki-s",
  "headline": "Nvidias Huang zerreißt Anthropics Vorschlag für KI-Sicherheits-Kartellausnahme als völlig unnötig",
  "mp4_url": "assets/cards/2026-09-16-nvidias-huang-zerreit-anthropics-vorschlag-fr-ki-s.mp4",
  "date": "2026-09-16",
  "source": "CNBC",
  "duration": 22,
  "llm_used": "openrouter:google/gemini-2.5-flash-lite",
  "voice_used": "de-DE-Studio-B"
 },
 {
  "id": "2026-09-16-zwei-lager-haben-sich-in-der-debatte-ber-ki-sicher",
  "headline": "Zwei Lager haben sich in der Debatte über KI-Sicherheit und Regulierung herausgebildet",
  "mp4_url": "assets/cards/2026-09-16-zwei-lager-haben-sich-in-der-debatte-ber-ki-sicher.mp4",
  "date": "2026-09-16",
  "source": "CNBC",
  "duration": 27,
  "llm_used": "groq:openai/gpt-oss-120b",
  "voice_used": "de-DE-Studio-C"
 },
 "... (150 Eintraege)"
]

--- archive.json ---
[
 {
  "title": "Amazon-Datenverlust im Iran-Krieg und Roboter als sicherer Mitarbeiter.",
  "summary": "Heise berichtet über einen Datenverlust bei Amazon im Zusammenhang mit dem Iran-Konflikt sowie über den Einsatz von Robotern als sichere Mitarbeiter-Alternative",
  "link": "https://www.heise.de/news/Mittwoch-Amazon-Datenverlust-im-Iran-Krieg-Roboter-als-sicherer-Mitarbeiter-11454527.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
  "source": "Heise",
  "color": "#ca8a04",
  "image": "https://heise.cloudimg.io/v7/_www-heise-de_/imgs/18/5/1/6/5/7/7/9/mittwoch-b4d6ef0c91e3813f.webp?func=bound&height=1200&org_if_sml=1&q=85&width=1200",
  "region": "welt",
  "base_score": 20,
  "score": 20,
  "label": "📰 normal",
  "first_seen": "2026-09-16",
  "date": "2026-09-16",
  "story_id": "s028",
  "story_cluster_score": 20,
  "story_article_count": 1,
  "dub_von": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag"
 },
 {
  "title": "Neuer humanoider Roboter soll für sichere Arbeit mit Menschen geeignet sein.",
  "summary": "Ein neu vorgestellter humanoider Roboter wurde speziell für die sichere Zusammenarbeit mit Menschen entwickelt. Er verfügt über Sensoren und Steuerungsmechanism",
  "link": "https://www.heise.de/news/Neuer-humanoider-Roboter-soll-fuer-sichere-Arbeit-mit-Menschen-geeignet-sein-11454513.html?wt_mc=rss.red.ho.ho.rdf.beitrag.beitrag",
  "source": "Heise",
  "color": "#ca8a04",
  "image": "https://heise.cloudimg.io/v7/_www-heise-de_/imgs/18/5/1/6/5/7/7/2/Agility_Digit_5_sit-8b1915ecf232bbf1.webp?func=bound&height=1200&org_if_sml=1&q=85&width=1200",
  "region": "welt",
  "base_score": 56,
  "score": 56,
  "label": "🔥 episch",
  "first_seen": "2026-09-16",
  "date": "2026-09-16",
  "story_id": "s001",
  "story_cluster_score": 56,
  "story_article_count": 2,
  "full_text": "Neuer humanoider Roboter soll für sichere Arbeit mit Menschen geeignet sein | heise online\n heise+ entdecken Suchen Abo Suchen Alle Magazine im Browser lesen An",
  "paywalled": false,
  "dub_quellen": [
   "The Decoder"
  ]
 },
 "... (1103 Eintraege)"
]

--- media.json ---
{
 "podcasts": [
  {
   "id": "005",
   "title": "Scampys Podcast #005 - Milliardenverluste machen Elon Musk zum Billionär",
   "description": "Elon Musk wird nicht durch Gewinne reich, sondern durch Geschichten, an die Investoren glauben. Wir schauen, wie er von Zip2 und PayPal über Fast-Pleite 2008 zu",
   "date": "2026-06-23",
   "soundcloud_url": "https://soundcloud.com/dscampy/scampyspodcast005?si=84520765b1a148029fea50c5eab4e1a9&utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing",
   "track_id": "2344913468",
   "duration": ""
  },
  {
   "id": "004",
   "title": "Scampys Podcast #004 - NVIDIAs RTX Spark macht PCs zu KI-Agenten by D.Scampy",
   "description": "Was steckt wirklich hinter dem NVIDIA RTX Spark? In dieser Episode zerlegen wir den neuen KI-Chip für Laptops ohne Marketingfilter. Von der 1-Petaflop-Zahl die ",
   "date": "2026-06-10",
   "soundcloud_url": "https://soundcloud.com/dscampy/scampys-podcast-004-nvidias?si=70eb6983751842f1bd182ee3dcc9b5b4&utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing",
   "track_id": "2336564411",
   "duration": "25:32"
  },
  "... (6 Eintraege)"
 ],
 "videos": [
  {
   "id": "v006",
   "title": "Elon Musks Roboter Versprechen 05 / 2026",
   "date": "2026-05-21",
   "type": "youtube",
   "src": "https://youtu.be/u9vrwKeqEoQ",
   "label": "VIDEO"
  },
  {
   "id": "v005",
   "title": "SpaceX Schlachtplan zum Mars",
   "date": "2026-05-16",
   "type": "youtube",
   "src": "https://youtu.be/WwCcND2oqBQ",
   "label": "VIDEO"
  },
  "... (6 Eintraege)"
 ],
 "xposts": [
  {
   "id": "x006",
   "date": "2026-08-31",
   "url": "https://x.com/ScampyKI/status/2094153411679682638?s=20",
   "note": "Mini Max H3 Max 5 Kostenlose Bilder",
   "image": "https://pbs.twimg.com/amplify_video_thumb/2094153395519029248/img/da2T447qvKXapOsB.jpg"
  },
  {
   "id": "x005",
   "date": "2026-06-16",
   "url": "https://x.com/ScampyKI/status/2066936288431771697?s=20",
   "note": "SpaceX kauft Cursor",
   "image": "https://pbs.twimg.com/profile_images/2052685241978916867/Mkdlq0C8_200x200.png"
  },
  "... (6 Eintraege)"
 ]
}

--- entities.json ---
{
 "_hinweis": "Entity-Registry fuer den Entity-Graph. Kuratiert 16.07.2026 aus phase0-Messung (28 Entitaeten mit >=3 Artikeln in 1276 Artikeln, plus xAI als Parent von Grok). ",
 "version": 2,
 "stand": "2026-08-23",
 "entities": [
  {
   "id": "OpenAI",
   "typ": "anbieter",
   "gehoert_zu": null,
   "aliasse": [
    "open\\s?ai"
   ]
  },
  {
   "id": "Google",
   "typ": "anbieter",
   "gehoert_zu": null,
   "aliasse": [
    "google",
    "deepmind"
   ]
  },
  "... (71 Eintraege)"
 ]
}

--- graph.json ---
{
 "_hinweis": "GENERIERT von ki_news.py (update_entity_graph) - NICHT manuell editieren. Kuratierung laeuft ueber entities.json.",
 "stand": "2026-09-16 07:16",
 "nodes": [
  {
   "id": "Google",
   "count": 682,
   "first_seen": "2026-07-16",
   "typ": "anbieter",
   "gehoert_zu": null,
   "last_seen": "2026-09-16"
  },
  {
   "id": "OpenAI",
   "count": 628,
   "first_seen": "2026-07-16",
   "typ": "anbieter",
   "gehoert_zu": null,
   "last_seen": "2026-09-16"
  },
  "... (68 Eintraege)"
 ],
 "edges": [
  {
   "source": "Chips/GPUs",
   "target": "Nvidia",
   "count": 127,
   "first_seen": "2026-07-16",
   "last_seen": "2026-09-16"
  },
  {
   "source": "Gemini",
   "target": "Google",
   "count": 118,
   "first_seen": "2026-07-16",
   "last_seen": "2026-09-15"
  },
  "... (346 Eintraege)"
 ],
 "seen": {
  "https://news.google.com/rss/articles/CBMicEFVX3lxTE5aRWJTNzZuZk5NeHA0cktrakUySmdQRVhCc1RTQUh4QWxNYjI3djRKTk55TmFzZ3pxckY1bDlYWXRXb1lOZnU0SWdscGtlN3lsOGhiUFdpUzVZWDJWM1JRc3d2WjVVQi0zdDFOU1ZJSUQ?oc=5": "2026-08-17",
  "https://news.google.com/rss/articles/CBMicEFVX3lxTFBWQ05ZZ1N3RENEQXc4eFAzWlF6R0tTSjB1V0RfWjNrbnNTcVdKM25VdlFQdmVsSUt1S1RyV243WWFpYXpHWTBZcE12R2dOdU1Cd0o0eU9DWGloN2pWbVJSNVNubGhUMHlUX1M5UmpzT1c?oc=5": "2026-08-17",
  "https://neurips.cc/Conferences/2026": "2026-08-17",
  "...": "(3465 Schluessel)"
 },
 "seen_stories": {
  "st-03106": "2026-08-17",
  "st-03107": "2026-08-17",
  "st-03108": "2026-08-17",
  "...": "(2856 Schluessel)"
 }
}

--- dashboard_config.json ---
{
 "featured_links": [],
 "blocked_links": [],
 "last_updated": "2026-09-07T07:11:02.383Z",
 "force_cards": []
}
