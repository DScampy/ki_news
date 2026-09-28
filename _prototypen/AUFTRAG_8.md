# Auftrag 8: Startseite kürzer (Daniel, 28.09.)

Unter dem Hero stehen alle restlichen Meldungen als volle Karten, die Seite ist dadurch "5 km lang".
Ziel: Die Startseite ist auf dem Handy höchstens ca. 4 Bildschirmhöhen lang, und keine Meldung geht verloren.

Vorlagen in `_prototypen/start_kompakt/`:
- `ref_start_themen.html`: Themen-Navigation, Zähler, Umschalter Karten/Kompakt
- `ref_artikel_c.html`: Bento-Kacheln je Thema mit Live-Zähler, aufklappbar
- `entwurf.html`: kommt automatisch nach, sobald das bauende Modell den Bereich komplett entworfen hat

Richtung:
1. Themen-Kacheln/Reiter mit Anzahl und den 2 bis 3 wichtigsten Titeln, ein Klick klappt die komplette Liste auf.
2. Die übrigen Meldungen als dichte Liste (Zeit, Quelle, Titel, eine Zeile) mit „Mehr zeigen“.
3. Morgenlage/Laufband, Dossiers/Linien und Neueste Analysen als schmale Streifen.

Dabei erhalten bleiben: Deep-Links auf einzelne Meldungen, Vorlese-/Video-Player, SEO (Meldungen im HTML oder
per JS nachgeladen, prüfen, was heute der Fall ist). Den Laufband-Überlappungsfix gleich mitnehmen.
Eigener Commit, main nur mit Daniels OK. Screenshots vorher/nachher mit der Seitenhöhe in px.
