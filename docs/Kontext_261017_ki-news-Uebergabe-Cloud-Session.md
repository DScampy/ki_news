# Kontext 17.10.2026: ki-news, Cloud-Session (vom Handy gestartet)

Zweck: Einstieg für den nächsten Chat (lokal oder Cloud), ohne die alten Chats lesen zu müssen.
Quelle: `docs/offen.md` (Stand 17.10.), eigene Messungen in dieser Session, Git-Stand. Nicht gelesen wurden die Kontext-Dateien unter `KIVault\06 Archiv\Chat-Kontext\` und der Skill `modell-werkstatt` (liegen nur lokal auf dem PC).

## Umgebung (wichtig)
- Diese Session lief in einer **Cloud-Umgebung (Linux-Container)**, nicht auf dem PC. Kein Zugriff auf `C:\...`, den lokalen KI-News-Ordner, den Skill `modell-werkstatt` oder KIVault-Dateien, die nicht auf GitHub liegen.
- Repo: `DScampy/ki_news`. Arbeits-Branch: `daniel/youthful-wozniak-tyzceg`, am 17.10. per force-with-lease auf `main` (4d66f1c) neu aufgesetzt. Der lokale Ordner kann davon abweichen (manuell aktualisiert). Vor dem Weiterarbeiten `git fetch` und den Stand abgleichen.
- `DScampy/kivault` (GitHub) enthält nur `00 Inbox`, `02 System`, `copilot`, `git` (Stand April). Der Ordner `04 Ressourcen/Tools/bunny-werkstatt` ist dort nicht vorhanden.

## Stand der Arbeit
- **PR #48 (Draft):** https://github.com/DScampy/ki_news/pull/48
  - `artikel.html`: Titelbilder (Dossier-Visual Index 0, Longform-Lead) laden die 1600-px-Variante aus dem Bilder-Spiegel, Rückfall auf 640 px (die 1600er werden nach 60 Tagen gelöscht), danach ausblenden.
  - `docs/offen.md`: Übergabe-Stand und Befunde.
  - Geprüft nur im Headless-Chromium (keine JS-Fehler, erstes Dossier-Bild aus `/bilder/1600/`). **Nicht geprüft:** Schärfe und Ladezeit im echten Chrome.
- Kill-Switch PR #48: Wenn die großen Bilder nicht sichtbar schärfer sind oder die Ladezeit spürbar leidet, verwerfen.

## Befunde dieser Session
1. **„Auf X" (`x_quelle`) im Hero: nicht gebaut, lohnt nicht.**
   - Von 204 Meldungen in `news.json` hat keine `x_quelle`. Nur 2 passen zu den 32 Funden in `x_quellen.json` (Rang 132 und 152 nach Score). In den Tages-Top-30 der letzten 10 Tage 0 bis 2 Treffer.
   - Ursache ist nicht die Handle-Liste (71 von 100 Top-Meldungen seit 03.10. kommen von Quellen mit Handle), sondern die HuggingNews-Zuordnung: 22 von 30 aktuellen Top-Meldungen haben keinen Eintrag in `themenketten.json` (`zuordnung`), bei den übrigen fehlt meist der Post der Quelle in `selectedTweets`.
   - Releases funktionieren (4 von 5 haben `x_url`, `index.html` zeigt ihn schon). Wieder aufnehmen nur, wenn die Zuordnung deutlich besser wird (Ziel: mindestens 1 von 5 Hero-Meldungen).
2. **`image_local` auf Artikel-/Archiv-/Dossier-Seiten: im Kern erledigt.** `assets/ki-bilder.js` (Fetch-Shim, setzt `image` auf `image_local`) ist in artikel, Archiv, dossiers, index, belege, landkarte, linie, modelle, suche und woche eingebunden. 983 von 1012 Archiv-Einträgen mit Bild haben einen Spiegel. Die `*-neu.html`-Vorschauseiten haben den Shim nicht.
3. `offen.md` war veraltet. Listen vor dem Übergeben gegen `main` prüfen.

## Hintergrund (aus offen.md, Kurzfassung)
- Pipeline: `ki_news.py` im Workflow `.github/workflows/ki_news.yml`; `x_quellen.py` läuft nach `hersteller_feed` (Key `HUGGINGNEWS_API_KEY` aus Secret `HUGGINGNEWS_API`), Funde in `x_quellen.json` (Feed reicht nur 3 Tage zurück, Aufbewahrung 21 Tage).
- PR #46 gemergt: Wächter meldet per Telegram, wenn die Übersetzung ausfällt; Platz-Warnung zählt Bilder und Karten-Videos (rund 540 von 1024 MB). Die Telegram-Zustellung ist noch an keinem echten Alarm bestätigt.
- Auswertung 28.09. bis 17.10.: 112 Pipeline-Läufe, keiner rot, Live = main, keine Geheimnisse im Repo, nichts ohne Freigabe veröffentlicht.
- Übersetzer: Fast alle Batches über `meta-llama/llama-3.3-70b-instruct` (kein `:free`, vermutlich bezahlt). Gratis-Modelle scheitern oft.

## Noch offen (priorisiert)
1. PR #48 im echten Chrome ansehen, dann mergen oder verwerfen.
2. **Übersetzer-Kosten prüfen:** Wie viele Batches laufen über `llama-3.3-70b-instruct`, was kostet das pro Monat? Reine Messung.
3. **Story-Clustering in `ki_news.py`** (Nvidia Bloomberg/Reuters als zwei Storys). Zuerst messen. Kill-Switch: unter etwa 3 Doppel-Storys pro Woche in den letzten 14 Tagen lassen.
4. **Prompt-Ursache** für erfundene Rollen und Wertungen („ehemaliger/designierter Präsident …"). In den letzten 120 Meldungen trat nichts mehr auf. Nur untersuchen.
5. Bilder, die sich nie spiegeln lassen (rund 30 von 40 je Lauf), werden bei jedem Lauf erneut versucht.
6. Kleinere Befunde: `tools/neuer-artikel.py` abgeschnitten (`main()` wird nie aufgerufen), `_prototypen/` nicht in `.gitignore`, `index-neu.html` zeigt ohne JS dauerhaft „wird geladen", 14 von 50 Meldungen ohne Quelltext (Google-News-Links).

## Arbeitsweise (Wünsche von Daniel)
- Kleine, klar umrissene Aufgaben (Schwachstellen suchen, kleine Reparaturen) sollen über die **Werkstatt** (`modell-werkstatt`, kostenlose LLMs, lokal) laufen, damit der Hauptchat keinen Kontext verbraucht. Aufträge als fertigen Text formulieren, Funde zurückbringen. Kill-Switch: Wenn ein Gratis-Modell in den ersten drei Aufträgen mehr falsche als echte Funde liefert, lohnt sie nicht.
- Vorher machte alles Opus. Aufteilung: Kleinkram Haiku/Werkstatt, Pipeline-Logik (Clustering) Opus oder Sonnet mit vorheriger Messung.
- Antwortstil: ehrlich, kritisch, ohne Lob und Floskeln; Auswahlmöglichkeiten und Kill-Switch zu jedem Plan.

## Einstieg für den nächsten Chat
„Lies docs/Kontext_261017_ki-news-Uebergabe-Cloud-Session.md und docs/offen.md auf daniel/youthful-wozniak-tyzceg. Prüfe zuerst, ob dein lokaler Stand von GitHub abweicht, und mach dann bei Punkt X der offenen Liste weiter."
