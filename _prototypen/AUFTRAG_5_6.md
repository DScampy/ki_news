# Auftrag 5: Artikel-Automat (Hersteller-Releases + Linien-Dossiers)

Ziel: Aus vorhandenen Daten entstehen automatisch ausführliche Artikel-Seiten, im Stil von Daniels Hand-Artikel
`_prototypen/referenz/opus-5-5-was-es-kann.html` (Aufbau, Tiefe, Look ansehen; Inhalte nicht übernehmen).

Zwei Auslöser:
1. **Hersteller-Release:** neuer Eintrag in `hersteller.json` (Auftrag 3) → Artikel „<Modell>: was es kann“ (Eckdaten, was neu ist,
   Benchmarks/Preise NUR wenn in der offiziellen Quelle, Quellen-Links, X-Post/Video als Klick-Vorschau).
2. **Linien-Dossier:** die Linien aus `ki_news.py _linien_dossiers()` (Stufe 1 ist live, `linie.html#l=<id>`) →
   Dossier-Artikel mit Zeitleiste, je Ereignis Zusammenfassung + alle Quellen + eingebettete Karte (MP4).

**Harte Regeln (Daniels Redaktion)**
- **Nur Aussagen, die in den Quellen/Zusammenfassungen stehen.** Keine neuen Zahlen, Namen, Daten. Jede Zahl mit Quellen-Link.
- Sichtbar gekennzeichnet als „Automatische Zusammenstellung“. Artikel erscheinen als **Entwurf** (z. B. `articles/entwurf/`,
  nicht in Navigation/Sitemap/Feeds), bis Daniel freigibt. Freigabe-Weg vorschlagen (z. B. Flag in einer JSON, die Daniel ändert).
- Stil: Deutsch, sachlich, kein Hype. Verboten: revolutionär, bahnbrechend, Game-Changer, disruptiv, Paradigmenwechsel,
  nahtlos, tiefgreifend, wegweisend. Kein Em-Dash (—). Personen immer mit Kontext-Label: „Dario Amodei (Chef Anthropic)“.
- Textmodell: nur was der Workflow schon an Keys hat. Neue Secrets als Bedarf melden, nicht anlegen.
- Gate vor Aktivierung im Zeitplan: 3 erzeugte Artikel, Daniel prüft sie gegen die Quellen, 0 erfundene Aussagen.

Lieferung: Generator im Repo + 3 Beispiel-Entwürfe + kurze Doku. Nicht auf main ohne Daniels OK.

---

# Auftrag 6: News-Cards grafisch aufwerten (austoben erlaubt)

Die Karten (cards.json, MP4 + Poster, Renderer `generate_news_cards.py` und Card-Templates wie
`breaking_news_card_v2.html`) sollen richtig schön werden. Aktueller Stand: Motive + Stile per Titel-Hash
(Tusche, Kreide, Zeitung …), Daniels Kritik 26.09.: Motive zu gleichförmig.

- Entwirf neue Motive/Stile/Animationen: Canvas/SVG, Partikel, Typo-Animation, Datengrafik aus der Meldung (Zahlen, Firmen-Logos-freie
  Symbolik), Hersteller-Farbwelten. Mutig sein, aber Text lesbar und Hochformat-tauglich (Reels 1080x1920).
- Deterministisch rendern (gleiche Meldung = gleiches Bild), Renderzeit im Workflow im Rahmen halten.
- Kontaktbogen liefern: dieselben 12 echten Meldungen aus cards.json alt vs. neu (Poster-PNGs + 2-3 MP4) in `_vorschau/`.
- Nichts am Live-Rendering umschalten ohne Daniels OK; neue Stile per Schalter/Liste aktivierbar.
