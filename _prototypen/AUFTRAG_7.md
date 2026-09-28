# Auftrag 7: Prototypen, die Daniel ausgewählt hat (28.09.)

Alle Vorlagen liegen auf Branch `prototypen/bunny` unter `_prototypen/<name>/`, jeweils `entwurf.html`, `spec.md`
(ursprünglicher Auftrag) und `vorschau_desktop.png`. Gebaut hat sie ein anderes Modell mit Beispieldaten. Du baust
die echte Fassung ins Repo: echte Daten, Formensprache der Seite (Karten 12 px Radius, 1-px-Neon-Rahmen, CSS-Variablen,
Hell/Dunkel, `ki-layout.js`), 0 JS-Fehler, 390 px ohne Überlauf. Jede Nummer ein eigener Commit, main nur mit Daniels OK.

1. **Dossier-Vorlage Chronoskop** (`idee_story_dossier_chronoskop`): Das ist die Vorlage für die Dossier-Artikel aus Auftrag 5.
   Sie hat Vorrang vor meinen dortigen Layout-Angaben.
2. **Voxel-KI-Welt** (`voxel_ki_welt`): Die Idee ist eine isometrische Stadt, jeder Hersteller ein Viertel, Aktivität aus den News.
   Baue **eine eigene Version mit eigenen Grafiken** und kopiere den Entwurf nicht, er ist nur die Idee. Austoben erlaubt, gerne Three.js/Canvas.
3. **Sims-Redaktion**: Das ist unsere Redaktion als isometrisches Pixel-Managementspiel. Figuren (Scampy, Recherche-Bot,
   Faktenprüfer, Karten-Renderer, Sprecherin) laufen zwischen den Räumen hin und her (Newsdesk, Recherche-Labor, Schnittraum,
   Chefbüro, Lounge), sobald eine **echte** Meldung reinkommt. Vorbild ist ein Video von einem Trading-Büro. Die Beschreibung steht in
   `_prototypen/sims_redaktion/video_beschreibung.md`. Ein Prototyp des anderen Modells kommt als `entwurf.html` automatisch nach.
   Eigene Grafiken, humorvoll, aber nur echte Meldungen als Auslöser.
4. **Neueste Analysen im Reportage-Look** (`idee_start_neueste_analysen_reporta`): als Abschnitt der Startseite einbauen,
   unter dem neuen Hero.
5. **Redaktions-Wahnsinn** (`idee_redaktions_wahnsinn`): als eigene Seite umsetzen.
6. **Profil/Admin-Upgrade** (`idee_profil_admin_upgrade`): **Das wird wirklich gebraucht, deshalb hier hohe Priorität.**
   Die alten `profil.html`/`Admin.html` sind die Referenz für alle Funktionen, die bleiben müssen. Keine Secrets ins Frontend.
7. **graph.html + Neural Atlas** (`graph_v2`, `idee_news_neural_atlas`): Verbinde beide zu einer neuen graph.html. Der Atlas bringt
   das Aussehen und die Interaktion, graph.html bleibt die Datenbasis (graph.json).
8. **Erzähler-Labor** (`idee_erzaehler_labor`): **nur als Idee aufnehmen**. Bitte noch nicht bauen, sondern in einer Ideen-Liste im Repo
   notieren (z. B. `docs/ideen.md`) mit 3 Sätzen, was es wäre und was es bräuchte.

**Reihenfolge (Daniel, 28.09.):**
1. **Chronoskop-Dossier** (Punkt 1 + Auftrag 5, Dossier-Teil) zuerst.
2. **Sobald das Dossier läuft: der Hersteller-Feed (Auftrag 3).** Die Startseite (Hero-Kachel „Frisch auf dem Markt“) soll immer die
   neuesten Modelle mit Links zeigen: offizielle Seite, X-Post, Video. Die Links kommen aus den News, die die Pipeline ohnehin
   einsammelt (Quellen-URLs der Meldungen, die ein Release betreffen), dazu die offiziellen Hersteller-Blogs.
3. Danach 6, 4, 7, 5, 3 (Sims), 2, 8.
