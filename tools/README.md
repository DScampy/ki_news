# tools/ — Artikel-Pipeline & Design-System

## Das Design-System (seit 10.06.2026)

**Eine Quelle für das komplette Site-Chrome:** `assets/ki-layout.js`
rendert Topbar, Sidebar, Theme-Dots, Dark/Light-Toggle und Mobile-Drawer
auf jeder Seite identisch. Referenz-Design: index.html.

Jede Seite bindet es als erste Zeile nach `<body>` ein:

```html
<script src="assets/ki-layout.js"></script>        <!-- Root-Seiten -->
<script src="../assets/ki-layout.js"></script>     <!-- artikel/ -->
```

- Aktive Seite wird automatisch aus der URL erkannt.
- Neuer Nav-Punkt? NUR in `ki-layout.js` im `NAV`-Array ergänzen — fertig.
- Seitenspezifischer Sidebar-Inhalt (wie Suche im Archiv, Quick-Stats):
  VOR dem Layout-Script `window.KI_SIDEBAR_EXTRA = '<html…>'` setzen.
- **Niemals** wieder Sidebar/Topbar-HTML direkt in eine Seite kopieren.

## Neuen Artikel veröffentlichen

1. Body-HTML schreiben (nur das Innere von `<article>`).
   Verfügbare Klassen: `.skinny-box`, `.benchmark-tbl` (+ `tr.hl`),
   `.art-img` + `.art-img-cap`, `<h2>`, `<p>`, `<blockquote>`, `.source-note`.
   Eigene Extra-Styles im Body via `<style>` sind ok (Theme-Variablen nutzen!).

2. Generator laufen lassen (vom Repo-Root):

```
python tools/neuer-artikel.py \
  --slug mein-artikel \
  --titel "Titel" \
  --untertitel "Standfirst unter der Headline" \
  --desc "Meta-Description (~160 Zeichen)" \
  --tags "Analyse,Hardware,Nvidia" \
  --datum 2026-06-10 \
  --lesezeit 7 \
  --body pfad/zum/body.html \
  [--autor CScampy] [--x-link https://x.com/...] [--og-image URL] [--force]
```

Das Script erzeugt/aktualisiert automatisch:
- `artikel/<slug>.html` (komplette Seite im Site-Design)
- Karte in `artikel.html` (Longform-Liste, neueste zuerst)
- `sitemap.xml`

3. Lokal prüfen, dann deployen.

## Template ändern

`tools/artikel-template.html` — gilt nur für NEUE Artikel.
Chrome-Änderungen (Sidebar/Topbar/Themes) gehören in `assets/ki-layout.js`
und wirken sofort auf ALLE Seiten.
