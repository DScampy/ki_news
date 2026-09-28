# Auftrag 2: Archiv, Artikel und Statistik neu (nach dem Start-Hero)

Daniel hat entschieden:
- **Archiv** → Variante B (Kartei/Atlas). Ersetzt `Archiv.html`.
- **Artikel** → `artikel_neu`, Stand Runde 3. Ersetzt `artikel.html`.
- **Statistik** → `stats_v2`. Ersetzt `stats.html`.

**Dateien** auf Branch `prototypen/bunny` unter `_prototypen/<name>/`:
- `entwurf.html` + `vorschau_desktop.png`: der ausgewählte Entwurf. Daniel findet ihn gut, aber zu kantig und fremd neben dem Rest der Seite.
- `site.html`: angepasste Fassung mit den Ecken, Rahmen und Farben der echten Seite. **Die kommt später automatisch dazu**, sobald das bauende Modell fertig ist (ca. 28.09. vormittags). Mit `git fetch origin prototypen/bunny` nachsehen. Fehlt sie noch, zuerst Auftrag 3 machen.

**Vorgehen je Seite**
1. Die Basis ist `site.html`. Die heutige Seite im Repo ist die Referenz für alles, was erhalten bleiben muss: Datenquellen (fetch-Pfade), Suche, Filter, Hashtags, Deep-Links/URL-Parameter, Links von anderen Seiten (z. B. `artikel.html?id=…`), SEO/OG-Meta-Tags, Tracking/Consent.
2. Vergleiche Alt gegen Neu: Jede Funktion der alten Seite muss es in der neuen geben oder bewusst gestrichen sein, und dann steht sie im Bericht an Daniel.
3. Prüfen, ob Workflows oder Python-Skripte diese Seiten erzeugen oder beschreiben. Wenn ja, den Einbau dort machen.
4. Optik angleichen, falls `site.html` noch ausreißt: Karten 12 px Radius, Pillen 999 px, 1-px-Neon-Rahmen `rgba(var(--neon-rgb),.1–.22)` mit weichem Glow, CSS-Variablen und Hell-/Dunkelmodus wie `index.html`.
5. Testen: 0 JS-Fehler, 390 px ohne Überlauf, Hell und Dunkel, echte Daten aus dem Repo. Screenshots.

Regeln wie bei Auftrag 1: eigener Branch, **kein main ohne Daniels OK**, `_prototypen/` nicht mitcommitten, kein Em-Dash im sichtbaren Text. Eine Seite pro Commit, damit Daniel einzeln freigeben kann.

---

# Auftrag 3: hersteller.json-Feed (Pipeline)

Das Hero-Modul zeigt eine Kachel „Frisch auf dem Markt“, sobald `hersteller.json` existiert (Schema in `_prototypen/start_hero/EINBAU.md`).
- Baue in die Pipeline einen Schritt, der die Datei erzeugt: neue Modelle und Releases der großen Hersteller (Anthropic, OpenAI, Google, Meta, Mistral, xAI, DeepSeek …) aus deren **offiziellen Blogs/RSS**. Wo vorhanden, kommen X-Post-Link und Video-URL dazu. Nutze nur Quellen und Keys, die der Workflow schon hat. Neue Secrets nicht selbst anlegen, sondern als Bedarf melden.
- Nur echte Releases der letzten ca. 14 Tage, keine erfundenen Einträge. Leere Liste ist erlaubt, dann blendet sich die Kachel aus.
- Wenn möglich mit bestehenden News-Clustern abgleichen, damit dieselbe Meldung nicht doppelt erscheint.
- Trocken testen (lokal ausführen, Beispiel-Ausgabe zeigen). Nicht auf main.

# Auftrag 4 (optional): Wochenfilm als MP4

`_prototypen/canvas_woche_b/entwurf.html` stellt `window.__film = {dauer, render(t)}` bereit (1080×1920, 45 s, deterministisch).
Schreibe ein Playwright-Skript, das Bild für Bild rendert (30 fps) und per ffmpeg ein MP4 für Reels baut. Das Skript kommt ins Repo. Automatisch posten gehört noch nicht zum Auftrag, zuerst ein Test-MP4 für Daniel.
