# Auftrag 9: Startseite nachbessern (Restbudget ~20 $, NUR das hier)

Daniels Befund 28.09. abends, live auf ki-news.live. Reihenfolge = Priorität, nach jedem Punkt pushen.

1. **Genesis zurück.** Der animierte Genesis-Hintergrund (das Allererste auf der Seite) ist weg, samt Farbwahl über
   Profil („alle Farben selbst einstellen“, `ki_genesis_theme`, `setGenesisTheme` in ki-layout.js, `prototype-genesis.html`).
   Stand vor `c54637c` ansehen (git show c54637c^:index.html) und exakt so wiederherstellen, dass er flüssig läuft und hinter dem Hero sichtbar ist.
   Darf entschlackt werden, aber Farbwahl im Profil muss wirken.
2. **Vorschaubilder:** Hero und Seitenkacheln zeigen das Bild der Meldung (Quellbild / image-Feld, wie im alten Karussell vor c54637c),
   NICHT das Poster der MP4-Karte. Fehlt ein Bild, neutraler Platzhalter. Die Karte (MP4) nur nach Klick.
3. **Keine doppelte Karte:** Seitenkacheln dürfen nie dieselbe Meldung wie die große Karte zeigen (Screenshot: Top-Story Nvidia, Kachel 02 Nvidia).
4. **Ton:** Klick auf eine Top-5-Karte startet das Video, aber stumm. Klick = Nutzergeste → mit Ton starten (`muted=false` vor `play()` im Klick-Handler);
   wenn der Browser ablehnt, deutlicher „Ton an“-Knopf auf dem Video.
5. **„Frisch auf dem Markt“:** Das eingebettete Video lässt sich nicht anklicken. Gewünscht: nur das Video des Hersteller-Posts einbetten
   (ohne Post-Text), wie es in den Artikeln schon geht; Klick lädt und spielt es.
6. **Englische Werbung im Nachrichtenstrom** („ACEMAGIC Launches World's First Ryzen AI Max+ PRO 495…“, WCCFTECH, kein Teaser):
   Wie ist das im letzten Workflow durchgerutscht (Übersetzung/Filter für Produktwerbung)? Befund + minimaler Fix in ki_news.py als eigener PR, nicht direkt main.

Tests: Desktop + Handy, hell/dunkel, 0 JS-Fehler, Screenshots. Punkte 1 bis 5 als EIN PR „Startseite Nachbesserung“, Punkt 6 eigener PR.
Budget knapp: bei Budget-Ende sofort pushen und in docs/offen.md notieren, was fehlt.

Nicht mehr für die Cloud (macht Bunny/nächste Session): Seitenleiste, Artikelseite neu, Dossier-Leseansicht, Registry-Karte, Archiv-Logos.
