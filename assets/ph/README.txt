Platzhalterbilder fuer News-Kacheln ohne og:image (03.09.2026)
===============================================================
ph-01.jpg ... ph-24.jpg = Standbilder aus den 8 Fallback-Clips in assets/
(fallback-artikel/schrifthell/space/drache/eule/weltraum/wasserwellen/
buchaufschlagen.mp4), je 3 Zeitpunkte, mit KI-NEWS-Schriftzug unten links.

Verwendet von phFor()/cardThumb() in index.html. Die Auswahl haengt am
Link-Hash der Meldung -> gleiche Meldung, gleiches Bild (kein Flackern).

Neu erzeugen (Git Bash, im Repo-Ordner, ffmpeg noetig):

  mkdir -p assets/ph
  FONT="assets/fonts/SpaceGrotesk-Variable.ttf"; i=0
  for v in artikel schrifthell space drache eule weltraum wasserwellen buchaufschlagen; do
    for t in 0.7 2.6 4.4; do
      i=$((i+1)); n=$(printf "%02d" $i)
      ffmpeg -v error -ss $t -i "assets/fallback-$v.mp4" -frames:v 1 \
        -vf "scale=640:-1,crop=640:333,drawtext=fontfile=$FONT:text='KI NEWS':fontcolor=0x9df7d2:fontsize=19:x=20:y=333-38:box=1:boxcolor=0x06120c@0.72:boxborderw=9" \
        -q:v 4 -y "assets/ph/ph-$n.jpg"
    done
  done

Andere Anzahl? PH_COUNT in index.html mit anpassen (muss zur Dateizahl passen).
