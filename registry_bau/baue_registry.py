#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registry-Dateien fuer die Website bauen
=======================================
Wandelt die Arbeitsdateien aus out/ in die drei Dateien um, die das
Registry-Panel in Archiv.html liest:

    registry/registry.json      Modelle, Anbieter, Zuordnung Link -> Modell/Anbieter
    registry/facetten.json      Link -> Ressort/Ereignistyp/Themenfelder/Region
    registry/registry-data.js   dieselben Daten fuer file://, auf dem Server ungenutzt

Warum es diesen Schritt ueberhaupt gibt: die Arbeitsdateien in out/ sind
ausfuehrlich und fuer Menschen lesbar (volle Feldnamen, Titel, Quellen,
Scores). Die Website braucht davon nur einen Bruchteil und laedt die Dateien
bei jedem Seitenaufruf -- deshalb Kurzschluessel und keine Artikelkopien.
Titel, Bild und Zusammenfassung kommen im Panel aus window.allNews.

Bis 21.08.2026 wurde diese Umwandlung von Hand gemacht. Das war der Grund,
warum die Live-Daten staendig veralteten.

    python3 baue_registry.py
    python3 baue_registry.py --out out --ziel ../../../Projekte/ki-news/registry
    python3 baue_registry.py --trocken      # nur rechnen, nichts schreiben

Stand 21.08.2026.
"""

import argparse
import glob
import json
import os
import time

HIER = os.path.dirname(os.path.abspath(__file__))

# Die Kategorien, die im Panel als Filter auftauchen. Alles andere faellt
# in der Anbieter-Zaehlung unter den Tisch -- absichtlich, sonst stehen
# Einbett- und Moderationsmodelle als eigene Spalte in der Kachel.
KATEGORIEN = ("text", "bild", "video", "audio")


def jetzt():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def lade(pfad, vorgabe=None):
    if not os.path.exists(pfad):
        return vorgabe
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def baue_modelle(roh):
    """Volle Modelldatensaetze auf die elf Felder kuerzen, die das Panel nutzt.

    Die Reihenfolge bleibt wie in modelle.json -- der Generator sortiert dort
    bereits, und das Panel sortiert ohnehin selbst nach Auswahl.
    """
    aus = []
    for m in roh:
        aus.append({
            "s": m.get("slug"),
            "n": m.get("name"),
            "a": m.get("anbieter"),
            "f": m.get("familie"),
            "v": m.get("variante"),
            "st": m.get("ausbaustufe"),
            "r": m.get("release"),
            "rq": m.get("release_quelle"),
            "c": m.get("context_length"),
            "ex": m.get("expiration_date"),
            "k": m.get("kategorie"),
        })
    return aus


def baue_anbieter(roh, modelle):
    """Anbieterzeilen plus Kategorie-Zaehlung.

    Die Zaehlung steht nicht in modelle.json und wird hier aus den Modellen
    aggregiert. Nur Kategorien mit mindestens einem Modell landen im Ergebnis,
    damit die Kachel keine Nullen anzeigt.
    """
    zaehl = {}
    for m in modelle:
        k = m.get("kategorie")
        if k in KATEGORIEN:
            zaehl.setdefault(m.get("anbieter"), {})
            zaehl[m["anbieter"]][k] = zaehl[m["anbieter"]].get(k, 0) + 1

    aus = []
    for a in roh:
        kuerzel = a.get("anbieter")
        aus.append({
            "a": kuerzel,
            "n": a.get("anbieter_name"),
            "m": a.get("modelle"),
            "f": a.get("familien_anzahl"),
            "r": a.get("neuestes_release"),
            "k": {k: v for k, v in (zaehl.get(kuerzel) or {}).items() if v},
        })
    return aus


def baue_zuordnung(shard_ordner):
    """Aus den Anbieter-Shards zwei flache Link-Listen ziehen.

    Die Shards halten pro Artikel Titel, Quelle, Datum und Score. Davon
    braucht das Panel nichts -- es sucht die Artikel ueber den Link in
    window.allNews. Uebrig bleiben also nur die Links, und genau deshalb
    ist registry.json klein geblieben.

    Deckelung passiert bereits in ordne_artikel_zu.py (25 je Modell,
    200 je Anbieter). Hier wird nicht nachgedeckelt.
    """
    art_anbieter = {}
    art_modell = {}
    if not os.path.isdir(shard_ordner):
        return art_anbieter, art_modell

    for pfad in sorted(glob.glob(os.path.join(shard_ordner, "*.json"))):
        if os.path.basename(pfad).startswith("_"):
            continue          # _ohne.json haelt die Artikel ohne Bezug
        d = lade(pfad) or {}
        kuerzel = d.get("anbieter")

        links = [a["link"] for a in (d.get("artikel_anbieter") or [])
                 if a.get("link")]
        if kuerzel and links:
            art_anbieter[kuerzel] = links

        for slug, artikel in (d.get("artikel_modell") or {}).items():
            links = [a["link"] for a in artikel if a.get("link")]
            if links:
                art_modell[slug] = links

    return art_anbieter, art_modell


def baue_facetten(roh):
    """Facetten auf vier Kurzschluessel eindampfen.

    Weggeworfen werden titel, datum, sicher und verworfen: Titel und Datum
    stehen in allNews, die beiden anderen sind Diagnosewerte fuer den Judge
    und haben auf der Website nichts verloren.
    """
    aus = {}
    for link, f in (roh or {}).items():
        aus[link] = {
            "re": f.get("ressort"),
            "ev": f.get("ereignistyp"),
            "tf": f.get("themenfelder") or [],
            "rg": f.get("region"),
        }
    return aus


def schreibe(pfad, daten):
    """Direkt schreiben, ohne Zwischendatei.

    Bewusst nicht atomar: ki_news.py kennt im ganzen Skript kein
    os.replace-Muster, und ein halb geschriebenes registry.json waere beim
    naechsten Lauf ohnehin ueberschrieben. Konsistenz mit dem Hauptskript
    ist hier mehr wert als Sicherheit gegen einen Absturz im Sekundenfenster.
    """
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(pfad)


def baue(out_ordner, ziel_ordner, trocken=False):
    """Kern der Umwandlung. Gibt eine Statistik zurueck, damit der Aufrufer
    ohne erneutes Einlesen protokollieren kann."""
    modelle_roh = lade(os.path.join(out_ordner, "modelle.json"))
    if not modelle_roh:
        raise SystemExit(
            "FEHLER: %s fehlt. Zuerst generiere_modelle_json.py laufen lassen."
            % os.path.join(out_ordner, "modelle.json"))

    facetten_roh = (lade(os.path.join(out_ordner, "facetten.json")) or {})
    facetten_roh = facetten_roh.get("artikel", {})

    stand = jetzt()
    modelle = baue_modelle(modelle_roh.get("modelle") or [])
    anbieter = baue_anbieter(modelle_roh.get("anbieter") or [],
                             modelle_roh.get("modelle") or [])
    art_anbieter, art_modell = baue_zuordnung(
        os.path.join(out_ordner, "registry"))
    facetten = baue_facetten(facetten_roh)

    registry = {
        "stand": stand,
        "modelle": modelle,
        "anbieter": anbieter,
        "artAnbieter": art_anbieter,
        "artModell": art_modell,
    }
    facetten_datei = {
        "stand": stand,
        "anzahl": len(facetten),
        "artikel": facetten,
    }

    stat = {
        "stand": stand,
        "modelle": len(modelle),
        "anbieter": len(anbieter),
        "anbieter_mit_artikeln": len(art_anbieter),
        "modelle_mit_artikeln": len(art_modell),
        "zuordnungen": (sum(len(v) for v in art_anbieter.values())
                        + sum(len(v) for v in art_modell.values())),
        "facetten": len(facetten),
    }

    if trocken:
        stat["geschrieben"] = False
        return stat

    stat["b_registry"] = schreibe(
        os.path.join(ziel_ordner, "registry.json"), registry)
    stat["b_facetten"] = schreibe(
        os.path.join(ziel_ordner, "facetten.json"), facetten_datei)

    # Die js-Fassung haelt beides in einer Variablen. Sie wird nur gebraucht,
    # wenn jemand Archiv.html per Doppelklick oeffnet -- dann verbietet der
    # Browser jeden fetch und das Panel bliebe sonst leer.
    js = ("/* Nur fuer file://. Auf dem Server gewinnt der fetch. "
          "Erzeugt, nicht editieren. */\n"
          "window.KI_REGISTRY_DATA=%s;\n"
          "window.KI_FACETTEN_DATA=%s;\n"
          % (json.dumps(registry, ensure_ascii=False, separators=(",", ":")),
             json.dumps(facetten_datei, ensure_ascii=False,
                        separators=(",", ":"))))
    pfad_js = os.path.join(ziel_ordner, "registry-data.js")
    os.makedirs(ziel_ordner, exist_ok=True)
    with open(pfad_js, "w", encoding="utf-8") as f:
        f.write(js)
    stat["b_js"] = os.path.getsize(pfad_js)
    stat["geschrieben"] = True
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HIER, "out"),
                    help="Ordner mit modelle.json, facetten.json, registry/")
    ap.add_argument("--ziel", default=None,
                    help="Zielordner (Vorgabe: das registry/ im ki-news-Repo)")
    ap.add_argument("--trocken", action="store_true",
                    help="nur rechnen und berichten, nichts schreiben")
    args = ap.parse_args()

    ziel = args.ziel or os.path.join(
        os.path.expanduser("~"), "Documents", "Projekte", "ki-news", "registry")

    print("Registry bauen")
    print("  Quelle: %s" % args.out)
    print("  Ziel  : %s" % ziel)

    stat = baue(args.out, ziel, trocken=args.trocken)

    print("\n  %d Modelle, %d Anbieter" % (stat["modelle"], stat["anbieter"]))
    print("  %d Zuordnungen (%d Anbieter, %d Modelle haben Artikel)"
          % (stat["zuordnungen"], stat["anbieter_mit_artikeln"],
             stat["modelle_mit_artikeln"]))
    print("  %d Artikel mit Facetten" % stat["facetten"])
    if stat["geschrieben"]:
        print("\n  registry.json     %6.1f KB" % (stat["b_registry"] / 1024))
        print("  facetten.json     %6.1f KB" % (stat["b_facetten"] / 1024))
        print("  registry-data.js  %6.1f KB" % (stat["b_js"] / 1024))
        print("\nStand: %s" % stat["stand"])
    else:
        print("\n--trocken: nichts geschrieben")


if __name__ == "__main__":
    main()
