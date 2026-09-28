# Offene Punkte (Stand 28.09.2026 abends)

Arbeits-Branch: `daniel/youthful-wozniak-tyzceg`. Die Session wurde nach PR 1 wegen Budget angehalten.

## Erledigt heute
- **Hero direkt auf main (a886a2f):** Die rechte Spalte endet bündig mit der großen Karte (die Kante war 2 px), der Genesis-Hintergrund ist hinter dem Hero wieder sichtbar, und das Morgenlage-Laufband hat ein eigenes Fenster. PR #3 ist deshalb ohne Merge geschlossen.
- Seitenkacheln: 47f251a war bereits auf main (als 812d5a9, gleiche patch-id). Live und main sind byte-gleich, und der Test zeigt korrekt mitlaufende Kacheln. Der beobachtete Fehler kam vermutlich aus dem Browser-Cache (max-age 600).
- Genesis ist nicht mit c54637c verschwunden, sondern mit 69e6a17 (deckender Hero-Verlauf).

## PRs zum Mergen (Daniel)
- **#4 Kartenstile** neon + typo + riso, einschließlich des typo-Fixes 330b60d. Achtung: riso wird damit der häufigste Stil (18 von 60), neon fällt auf 4. Gegebenenfalls `NEUE_STILE_JE_MOTIV` umsortieren.
- **#5 Archiv Atlas + neue Artikel-Seite + dossiers.html**, mit „Die aktivsten Entwicklungen“ oben. Offen: Nav-Eintrag „Dossiers“ in `assets/ki-layout.js`?
- **#6 Vorschau-Seiten** (karten/woche/hersteller/og-bilder-neu) + tools + Übersetzungsfix `hersteller_feed.py`.

## Angefangen, nicht fertig
1. **X-Links über HuggingNews** (Branch `daniel/pr5-x-links`, WIP 281765d, `x_quellen.py`):
   - API-Befund: `GET /api/stories/<slug>` liefert `selectedTweets` (role source/support/commentary/analysis/signal, authorHandle, url, bestBit). Das geht auch ohne Key, der Feed reicht nur 3 Tage zurück und ist nicht paginierbar.
   - Logik: Nur fest gepflegte offizielle Handles werden verlinkt, nichts wird geraten. Den Hersteller-Post gibt es nur aus der Story zur Ankündigung (±2 Tage), Analysen (@ArtificialAnlys u.a.) bis 7 Tage danach. Top-Meldungen laufen über die `themenketten.json`-Zuordnung zum Post der eigenen Quelle (z.B. WSJ → @WSJ). Funde werden in `x_quellen.json` gespeichert.
   - Getestet: ElevenLabs Eleven v4 → 2 Analysen von @ArtificialAnlys. „OpenAI fixes GPT-6 vision bug“ wird richtig NICHT als GPT-6-Sol-Release-Post genommen. WSJ-Meldung → @WSJ-Post.
   - Offen: der Workflow-Schritt nach hersteller_feed (env `HUGGINGNEWS_API_KEY: ${{ secrets.HUGGINGNEWS_API }}`, dazu `git add x_quellen.json`), die Anzeige „Auf X“ im Hero (`story.x_quelle`) und ein PR.
   - Die aktuellen 4 Releases (22./23.09.) liegen vor dem Feed-Fenster, deshalb gibt es für sie keinen X-Post. Erst neue Releases werden erfasst.
   - Die Beispiele von Google (2103608768609370118) und ElevenLabs (2104572127617994917) sind nicht mehr im Feed. Laut Beispiel heißt das Konto @ElevenLabs; in `HERSTELLER_HANDLES` steht noch `elevenlabsio`, dort muss `elevenlabs` ergänzt werden.
2. **Prompt-Ursache in ki_news.py:** Rollen und Wertungen nicht erfinden („ehemaliger/designierter Präsident Trump“, „Dieser Preiskampf hat das Potenzial …“). Noch nicht begonnen, nur auf dem Branch.

## Weitere Befunde
- `tools/neuer-artikel.py` ist abgeschnitten, `main()` wird nie aufgerufen.
- `_prototypen/` steht nicht in `.gitignore`.
- og:image aus `tools/og_render.js`: ca. 850 KB je Bild; zeigt `story_id` und Score öffentlich.
- index-neu.html zeigt ohne JS dauerhaft „wird geladen“.
- Deckungsprüfung: 14 von 50 Meldungen ohne Quelltext (Google-News-Links). Die Ämterliste (Stand 28.09.2026) sollte Daniel gegenlesen.

## Auftrag 9 (28.09.26 spät)
- **PR #7 Startseite Nachbesserung** (Punkte 1–5): Genesis ist wieder Bühne hinter dem Hero, Bild der Meldung statt Kartenposter, keine doppelte Meldung, Ton nach Klick im Overlay (sonst Knopf „Ton an“), Release-Video per Klick mit Ton.
  - Den Ton nach dem Klick konnte ich im Test nicht mit echtem Ton belegen, weil das Test-Chromium kein H.264 abspielen kann. Bitte im echten Browser prüfen.
  - Punkt 5, Daten fehlen: Kein Release hat `video_url` oder `x_url`. Das Video des Hersteller-Posts liefert HuggingNews unter `image.videoUrl` mit `credit.tweetUrl`. Das Füllen gehört in `x_quellen.py` (Branch `daniel/pr5-x-links`).
- **PR #8 Sprach-Guard** (Punkt 6): Eine Meldung ohne deutschen Teaser und ohne deutsches Signal wird verworfen. py3langid hielt den ACEMAGIC-Titel für Deutsch (p = 0,61). Einen Filter für reine Produktwerbung gibt es weiterhin nicht, darüber muss Daniel entscheiden.

## Auftrag 10 (28.09.26 abends)
- **PR #11 Startseite Tempo** (Punkte 1, 2, 6): Genesis-Code exakt wie vor c54637c, einzige Ergänzung ist die Pause bei `document.hidden`. Der Hero ist wieder undurchsichtig, die Aurora läuft ohne Live-Blur, der Ton-Knopf hat 52 px Trefferfläche.
  - Gemessen: verdeckter Tab 105 % → 0 % CPU. Bei sichtbarem Tab zeigt Headless ohne GPU keinen Unterschied (etwa 102 %). **Daniel misst im echten Chrome (Shift+Esc).**
- **PR #12 Bilder-Spiegel**: WebP 640 und 1600 ins Medien-Repo, `image_local`. Pages erlaubt 1 GB, deshalb werden die 1600er nach 60 Tagen gelöscht. Artikel-, Archiv- und Dossier-Seiten nutzen `image_local` noch nicht.
- Offen aus Auftrag 10:
  - 3a: Hero und Kacheln eager, Rest lazy (`fetchpriority=high`)
  - 4: `archive.json` auf der Startseite erst bei Leerlauf laden
  - 5: Füllmotiv statt leerer Gitterfläche
  - 7: `video_url` und `x_url` aus HuggingNews (`x_quellen.py`, Branch `daniel/pr5-x-links`)
