#!/usr/bin/env python3
"""Woerter synchron zur Stimme (19.10.26, Ideen-Speicher Nr. 6 der Roadmap 26.09.).

Die Karte hob die Einordnung bisher gleichmaessig von 4,4 s bis 2 s vor Schluss hervor, egal wie
lange der vorgelesene Titel davor dauert. Google-TTS-Zeitmarken (<mark>) gehen mit den Studio-
Stimmen nicht (Test 19.10.26: HTTP 400 "`<mark>` tags are not currently supported by Studio
voices"). Deshalb kommen die Zeiten aus dem Audio selbst:
  1. ffmpeg silencedetect findet die Sprechpausen.
  2. Satzgrenzen (Titelende + Satzenden der Einordnung) werden nach Textlaenge geschaetzt und auf
     die passendste echte Pause in der Naehe eingerastet (laengere Pause, kleinerer Abstand).
  3. Innerhalb eines Satzes werden die Woerter nach Laenge verteilt (Komma zaehlt etwas extra).
Ergebnis: Startzeit (Sekunden ab Videobeginn) je Wort der Einordnung, gleiche Wortliste wie die
Karte (einordnung.split()). Jeder Fehler -> None, die Karte bleibt dann beim alten Verhalten.
"""
import re
import subprocess

STILLE_DB = -35        # Schwelle fuer "still" (dB)
STILLE_MIN = 0.12      # kuerzeste Pause (s), die zaehlt
# Satzende, aber nicht nach Ziffer ("3. Oktober") oder Einzelbuchstabe ("z. B.")
SATZ_RE = re.compile(r"(?<=[.!?])(?<!\d\.)(?<!\w\.)\s+")


def pausen(audio_path, ffmpeg="ffmpeg"):
    """[(start, ende), ...] und Gesamtdauer aus ffmpeg silencedetect."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-i", str(audio_path), "-af",
                        f"silencedetect=noise={STILLE_DB}dB:d={STILLE_MIN}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    log = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
    if not m:
        return None, None
    dauer = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    endes = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    endes += [dauer] * (len(starts) - len(endes))
    return [(max(0.0, a), b) for a, b in zip(starts, endes)], dauer


def _gewicht(wort):
    g = len(wort) + 1
    if wort.endswith((",", ";", ":")):
        g += 3
    return g


def wort_zeiten(audio_path, headline, einordnung, ffmpeg="ffmpeg"):
    try:
        worte_e = (einordnung or "").split()
        if not worte_e:
            return None
        p, dauer = pausen(audio_path, ffmpeg)
        if not p or not dauer:
            return None
        # Sprechbereich: nach fuehrender, vor abschliessender Stille
        sp_start = p[0][1] if p[0][0] <= 0.2 else 0.0
        sp_ende = p[-1][0] if p[-1][1] >= dauer - 0.2 else dauer
        innen = [(a, b) for a, b in p if a > sp_start + 0.05 and b < sp_ende - 0.05]
        if sp_ende - sp_start < 2:
            return None

        saetze = [(headline or "").split()] + [s.split() for s in SATZ_RE.split(einordnung.strip()) if s.strip()]
        saetze = [s for s in saetze if s]
        gew = [sum(_gewicht(w) for w in s) for s in saetze]
        gesamt = sum(gew)
        spanne = sp_ende - sp_start

        # Satzgrenzen schaetzen und einrasten
        grenzen = []          # (ende_satz_i, start_satz_i+1)
        frei = list(innen)
        kum, letzte = 0, sp_start
        fenster = max(1.2, 0.12 * spanne)
        for i in range(len(saetze) - 1):
            kum += gew[i]
            erwartet = sp_start + spanne * kum / gesamt
            kand = [(b - a - 0.15 * abs((a + b) / 2 - erwartet), a, b) for a, b in frei
                    if abs((a + b) / 2 - erwartet) <= fenster and a > letzte]
            if kand:
                _, a, b = max(kand)
                frei = [x for x in frei if x != (a, b)]
            else:
                a = b = max(erwartet, letzte + 0.1)
            grenzen.append((a, b))
            letzte = b
        # Woerter je Satz verteilen
        zeiten = []
        anfang = sp_start
        for i, s in enumerate(saetze):
            ende = grenzen[i][0] if i < len(grenzen) else sp_ende
            g = [_gewicht(w) for w in s]
            summe, lauf = sum(g), 0
            for gw in g:
                zeiten.append(round(anfang + (ende - anfang) * lauf / summe, 2))
                lauf += gw
            if i < len(grenzen):
                anfang = grenzen[i][1]
        n_titel = len(saetze[0])
        z = zeiten[n_titel:]
        if len(z) != len(worte_e) or any(b < a for a, b in zip(z, z[1:])):
            return None      # Satzzerlegung passt nicht zur Wortliste der Karte
        wort_zeiten.letzte_info = {"grenzen": len(grenzen),
                                   "eingerastet": sum(1 for a, b in grenzen if b > a)}
        return z
    except Exception:
        return None


wort_zeiten.letzte_info = {}
