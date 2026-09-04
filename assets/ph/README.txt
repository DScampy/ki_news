Platzhalterbilder fuer News-Kacheln ohne og:image
Stand 04.09.2026 — 29 Bilder (ph-01 .. ph-29), 640x333, ca. 556 KB gesamt
=========================================================================
Standbilder aus den 10 Fallback-Clips in assets/, je mit KI-NEWS-Schriftzug
unten links. Verwendet von phFor()/cardThumb() in index.html; die Auswahl
haengt am Link-Hash der Meldung -> gleiche Meldung, gleiches Bild.

WICHTIG: Die Zeitpunkte sind einzeln gewaehlt, NICHT gleichmaessig verteilt.
Die Clips animieren den Schriftzug ein; zu frueh gegriffene Frames zeigen
abgeschnittene Buchstaben oder halbe Zeichnungen (Daniel hat am 04.09. genau
solche aussortiert). Wer neu erzeugt, nimmt die Liste unten oder prueft die
neuen Frames vorher als Kontaktbogen.

Zuordnung Bild -> Clip : Sekunde
  01 artikel:1.4         11 drache:4.0          21 wasserwellen:4.4
  02 artikel:3.4         12 drache:4.5          22 buchaufschlagen:0.7
  03 artikel:4.4         13 eule:0.7            23 buchaufschlagen:2.6
  04 schrifthell:0.7     14 eule:3.4            24 buchaufschlagen:4.4
  05 schrifthell:2.6     15 eule:4.4            25 schriftzug:3.9
  06 schrifthell:4.4     16 weltraum:0.7        26 schriftzug:4.4
  07 space:0.7           17 weltraum:3.2        27 leinwand:0.5
  08 space:2.6           18 weltraum:4.4        28 leinwand:2.5
  09 space:4.4           19 wasserwellen:0.7    29 leinwand:3.2
  10 drache:2.0          20 wasserwellen:2.6

Neu erzeugen (Git Bash, im Repo-Ordner, ffmpeg noetig):

  FONT="assets/fonts/SpaceGrotesk-Variable.ttf"
  gen(){ ffmpeg -v error -ss $2 -i "assets/fallback-$1.mp4" -frames:v 1 \
    -vf "scale=640:-1,crop=640:333,drawtext=fontfile=$FONT:text='KI NEWS':fontcolor=0x9df7d2:fontsize=19:x=20:y=333-38:box=1:boxcolor=0x06120c@0.72:boxborderw=9" \
    -q:v 4 -y "assets/ph/ph-$3.jpg"; }
  # dann je Zeile aus der Tabelle:  gen artikel 1.4 01   usw.

Kontaktbogen zum Pruefen (alle 29 auf einem Bild):

  ffmpeg -v error -framerate 1 -i "assets/ph/ph-%02d.jpg" \
    -vf "scale=190:-1,tile=5x6:margin=3:padding=3" -frames:v 1 -y kontaktbogen.jpg

Andere Anzahl? PH_COUNT in index.html mit anpassen (muss zur Dateizahl passen).
