# Auftrag 10: Startseite schneller + 3 Fehler (Daniel 28.09. 20 Uhr, Rechner „röchelt“)

Messung Claude lokal (Playwright, Desktop 1440x900, live ki-news.live):
- Leerlauf-CPU ~100-125 % eines Kerns. Genesis-Canvas (1440x900, Vollbild) ausgeblendet → 40 %. Skriptzeit klein, Kosten = Zeichnen.
- `.px-hero-aurora` mit `filter: blur(36px)` auf ~326k px Fläche.
- 9,3 MB beim Laden, davon 7,7 MB Bilder: Originalbilder der Quellen in voller Größe (siliconangle PNG 1,9 MB + 1,8 MB,
  Google 950 KB, CNBC 685 KB …). `archive.json` (414 KB) wird auf der Startseite mitgeladen. 36 Long Tasks, zusammen 14 s beim Laden.

## Aufgaben (ein PR „Startseite Tempo“)
1. **Genesis sparsam:** max. 30 fps, `devicePixelRatio` höchstens 1, Pause bei `document.hidden` und wenn nicht im Bild
   (IntersectionObserver), Partikelzahl halbieren, `prefers-reduced-motion` respektieren. Aussehen soll gleich bleiben.
2. **Aurora ohne Live-Blur:** `filter: blur(36px)` durch weiche radial-gradients ersetzen (gleiches Aussehen, keine Filterkosten).
3. **Bilder:** Nur Hero + 2 Seitenkacheln eager (`fetchpriority=high` für das Hero-Bild), alle anderen `loading=lazy decoding=async`.
   Vorschlag (eigener PR, Pipeline): Vorschaubilder beim Lauf als WebP 640 px ins Media-Repo (`ki_news_media`) spiegeln und diese statt der Originale nutzen.
4. **archive.json** auf der Startseite nur laden, wenn wirklich gebraucht (später/idle).
5. **Fehlendes Bild = Füller:** Statt leerer Gitterfläche mit Ring die bisherigen Füllmotive (prozedurale Motive der Seite) nutzen.
6. **Bug:** Der Ton-/Knopf rechts in der Ecke des Hero-Videos pausiert das Video sofort (Klick geht wohl zusätzlich an den Video-Container → `stopPropagation`).
7. **„Frisch auf dem Markt“ Video/X-Post:** `video_url` und `x_url` aus HuggingNews (`image.videoUrl`, Post-Link) in hersteller.json füllen
   (x_quellen.py fertig machen). Keine X-API.

Messen vorher/nachher: Leerlauf-CPU (CDP Performance.TaskDuration über 5 s), MB beim Laden, Long Tasks. Zahlen in den PR.
