# Einbau-Anleitung Hero-Modul (vom bauenden Modell, Runde 4)

Letzte Pruefung: 0 JS-Fehler, DOMContentLoaded 445 ms, Handy 390 px ohne Ueberlauf. Einzige Konsolenmeldung: 404 fuer hersteller.json (erwartet, Datei existiert noch nicht).

- Gebaut: einbaureifes, responsives Hero-Modul mit Carousel, Kartenabgleich, Release-Kachel, Canvas-Feld und vollständigen Fehlerzuständen.
- In `index.html` den kompletten alten Block `<main class="px-page">...</main>` einschließlich Canvas, Statuszeile und Hero entfernen.
- Den Inhalt von `<style id="px-hero-css">` in den vorhandenen `<head>` übernehmen und das Modul direkt hinter dem von `ki-layout.js` erzeugten Header einsetzen.
- `assets/ki-fonts.css`, `assets/ki-tw.css`, `assets/ki-icons.js` und `assets/ki-layout.js` jeweils nur einmal laden; den Inhalt von `<script id="px-hero-js">` vor `</body>` platzieren.
- End-Schema für `hersteller.json`: `{"stand":"YYYY-MM-DD HH:mm","releases":[{"hersteller":"string","modell":"string","datum":"YYYY-MM-DD","titel":"string","text":"string","url":"https://...","x_url":"https://...","video_url":"https://... oder assets/...","poster":"https://... oder assets/..."}]}`.
- Gültiges Beispiel: `{"stand":"2026-09-16 07:11","releases":[{"hersteller":"Anthropic","modell":"Claude Opus 5.5","datum":"2026-09-16","titel":"Claude Opus 5.5","text":"Anthropic stellt eine neue Modellgeneration vor.","url":"https://www.anthropic.com/news","x_url":"https://x.com/claudeai","video_url":"","poster":""}]}`.
- Ohne oder mit leerer `hersteller.json` bleibt die Release-Kachel live vollständig verborgen; Story 2 und 3 füllen dann die komplette Seitenspalte. Beispieldaten erscheinen nur mit `?demo=1`.
