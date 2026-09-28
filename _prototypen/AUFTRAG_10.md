# Auftrag 10: Startseite schneller + 3 Fehler (Daniel 28.09. 20 Uhr, Rechner „röchelt“)

Messung Claude lokal (Playwright, Desktop 1440x900, live ki-news.live):
- Leerlauf-CPU ~100-125 % eines Kerns. Genesis-Canvas (1440x900, Vollbild) ausgeblendet → 40 %. Skriptzeit klein, Kosten = Zeichnen.
- `.px-hero-aurora` mit `filter: blur(36px)` auf ~326k px Fläche.
- 9,3 MB beim Laden, davon 7,7 MB Bilder: Originalbilder der Quellen in voller Größe (siliconangle PNG 1,9 MB + 1,8 MB,
  Google 950 KB, CNBC 685 KB …). `archive.json` (414 KB) wird auf der Startseite mitgeladen. 36 Long Tasks, zusammen 14 s beim Laden.

## Aufgaben (ein PR „Startseite Tempo“)
1. **Genesis NICHT neu bauen (Daniel):** Die alte Version lief wunderbar. Genesis-Code exakt wie vor `c54637c` lassen.
   Stattdessen den Hero-Teil zurück auf das Verhalten vor Auftrag 9: Hero-Fläche NICHT durchsichtig über dem animierten Canvas.
   Verdacht (Claude): Durchsichtiger Hero + `blur(36px)`-Aurora über dem laufenden Canvas zwingt den Browser, die ganze
   Hero-Fläche samt Unschärfe in jedem Frame neu zu zeichnen. Genesis bleibt ringsum sichtbar wie früher.
   Einzige erlaubte Ergänzung am Genesis: Pause bei `document.hidden` (Tab im Hintergrund).
2. **Aurora ohne Live-Blur:** `filter: blur(36px)` durch weiche radial-gradients ersetzen (gleiches Aussehen, keine Filterkosten).
3. **Bilder:** Nur Hero + 2 Seitenkacheln eager (`fetchpriority=high` für das Hero-Bild), alle anderen `loading=lazy decoding=async`.
   **Bilder ablegen (Daniel, eigener PR, Pipeline):** Beim Lauf jedes Meldungsbild einmal ins Media-Repo (`ki_news_media/bilder/`)
   spiegeln: WebP 640 px für Startseite/Karten + WebP 1600 px für Dossiers/Artikel-Hintergründe, Dateiname = stabiler Hash der
   Original-URL, Feld `image_local` in news.json/archive.json. Die Seiten nutzen `image_local`, sonst Original. So bleiben die
   Bilder auch fürs Archiv und die Dossiers erhalten, wenn die Quelle sie löscht.
4. **archive.json** auf der Startseite nur laden, wenn wirklich gebraucht (später/idle).
5. **Fehlendes Bild = Füller:** Statt leerer Gitterfläche mit Ring die bisherigen Füllmotive (prozedurale Motive der Seite) nutzen.
6. **Bug:** Der Ton-/Knopf rechts in der Ecke des Hero-Videos pausiert das Video sofort (Klick geht wohl zusätzlich an den Video-Container → `stopPropagation`).
7. **„Frisch auf dem Markt“ Video/X-Post:** `video_url` und `x_url` aus HuggingNews (`image.videoUrl`, Post-Link) in hersteller.json füllen
   (x_quellen.py fertig machen). Keine X-API.

Hinweis: Headless-Messung ohne GPU zeigte alt und neu gleich (~108 %), also im echten Browser mit GPU messen oder Daniel testen lassen.
Messen vorher/nachher: Leerlauf-CPU (CDP Performance.TaskDuration über 5 s), MB beim Laden, Long Tasks. Zahlen in den PR.
