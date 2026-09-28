# Auftrag für die Cloud-Session: Start-Hero in index.html einbauen

Stand 28.09.2026. Zum Einfügen in die Cloud-Session (Repo DScampy/ki_news, GitHub main = Live-Stand der Website).

---

Aufgabe: Das neue Hero-Modul auf der Startseite einbauen. Daniel hat es freigegeben, gebaut hat es ein anderes Modell.

**Quellen** (im Repo auf Branch `prototypen/bunny`, Ordner `_prototypen/start_hero/`):
- `hero_modul.html`: fertiges Modul. Nur diese drei Teile übernehmen: `<style id="px-hero-css">`, `<section id="px-hero">`, `<script id="px-hero-js">` (eine IIFE). Der Rest der Datei ist Testgerüst.
- `EINBAU.md`: Einbau-Anleitung des Modells und das Schema von `hersteller.json`.

**Vorgehen**
1. Zuerst klären, ob `index.html` von der Pipeline (Workflows, `ki_news.py` o. ä.) erzeugt oder überschrieben wird. Wenn ja, den Einbau dort vornehmen, wo er den nächsten Lauf übersteht (Template/Generator), nicht nur in der fertigen Datei.
2. Laut Anleitung wird der alte Kopfbereich `<main class="px-page">…</main>` ersetzt. Vorher prüfen, ob darin etwas steckt, das andere Teile brauchen (IDs, auf die JS zugreift, Statuszeile). Nichts stillschweigend entfernen, das anderswo genutzt wird.
3. `ki-fonts.css`, `ki-tw.css`, `ki-icons.js` und `ki-layout.js` jeweils nur einmal laden. `body`/`html`-Styles nicht anfassen, nur `px-`-Klassen.
4. `hersteller.json` gibt es noch nicht. Die Kachel „Frisch auf dem Markt“ muss sich dann ausblenden. Die 404-Meldung in der Konsole ist erwartet. Beispieldaten erscheinen nur mit `?demo=1`.
5. Lokal testen, z. B. mit `python -m http.server`: 0 JS-Fehler (außer der hersteller.json-404), Handy 390 px ohne horizontalen Überlauf, Hell- und Dunkelmodus. Screenshots Desktop + Handy.

**Regeln**
- Nur auf deinem Arbeits-Branch committen. **Kein Merge und kein Push auf main** ohne Daniels ausdrückliches OK, denn main geht sofort live.
- Keine Secrets in Dateien. Kein Em-Dash (—) im sichtbaren Text.
- Am Ende an Daniel: Diff-Zusammenfassung, Screenshots, was vom alten Kopfbereich entfernt wurde und ob der Pipeline-Lauf den Einbau überschreiben könnte.
