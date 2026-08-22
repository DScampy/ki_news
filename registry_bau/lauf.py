#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registry-Schritt fuer den taeglichen Lauf
=========================================
Eine Funktion, die ki_news.py am Ende aufruft. Sie fuehrt die vier Bausteine
in der richtigen Reihenfolge aus und legt die drei Dateien ab, die das
Registry-Panel in Archiv.html liest.

    from registry_bau.lauf import registry_schritt
    registry_schritt(repo_ordner, logger)

Ablauf:

    1. modelle.json   nur wenn es fehlt oder aelter als eine Woche ist.
                      Modelllisten aendern sich in Tagen nicht, und der
                      Generator haengt an OpenRouter -- taeglich waere das
                      eine unnoetige Abhaengigkeit im kritischen Pfad.
    2. Zuordnung      deterministisch, kein Modellaufruf, Sekunden.
    3. Facetten       der Judge. Teuer, deshalb streng inkrementell:
                      was in out/facetten.json steht, wird uebersprungen.
                      Diese Datei MUSS mitgepusht werden, sonst faengt der
                      naechste Lauf bei null an und schickt den gesamten
                      Bestand erneut an ein Modell.
    4. Bauen          die drei Website-Dateien nach registry/.

Grundsatz: dieser Schritt darf den Lauf nie kippen. Jeder Baustein sitzt in
seinem eigenen Auffangnetz, und wenn Schritt 3 scheitert, laeuft Schritt 4
trotzdem -- dann eben mit dem Facettenstand von gestern.

Warum hier ueberall auch SystemExit gefangen wird: die Bausteine sind als
Kommandozeilenwerkzeuge entstanden und melden Fehler mit `raise SystemExit`.
SystemExit erbt von BaseException, nicht von Exception -- ein gewoehnliches
`except Exception` laesst es also durch, und ein fehlender Schluessel wuerde
den kompletten Nachrichtenlauf beenden.

Stand 21.08.2026.
"""

import io
import os
import sys
import time
import contextlib

HIER = os.path.dirname(os.path.abspath(__file__))
if HIER not in sys.path:
    sys.path.insert(0, HIER)

# Wie alt modelle.json werden darf, bevor der Generator neu laeuft.
MODELLE_MAX_ALTER_TAGE = 7

# Artikel je Lauf fuer den Judge. Bei rund dreissig neuen Artikeln pro Tag
# ist das reichlich; die Grenze greift nur, wenn ein Rueckstand abgearbeitet
# wird, und deckelt dann die Laufzeit statt sie explodieren zu lassen.
JUDGE_LIMIT = 120


class _Sammler:
    """Faengt die print-Ausgabe der Bausteine ein und schiebt sie ins Log.

    Die Bausteine schreiben ihre Fortschrittsmeldungen auf stdout. In Actions
    landet das unstrukturiert zwischen den Zeilen von ki_news.py -- so bekommt
    jede Zeile wenigstens ihr Praefix.
    """

    def __init__(self, logger, praefix):
        self.logger = logger
        self.praefix = praefix

    def __enter__(self):
        self.puffer = io.StringIO()
        self._um = contextlib.redirect_stdout(self.puffer)
        self._um.__enter__()
        return self

    def __exit__(self, *a):
        self._um.__exit__(*a)
        for zeile in self.puffer.getvalue().splitlines():
            if zeile.strip():
                self.logger.info("%s %s", self.praefix, zeile.rstrip())
        return False


def _alter_tage(pfad):
    if not os.path.exists(pfad):
        return None
    return (time.time() - os.path.getmtime(pfad)) / 86400.0


def registry_schritt(repo, logger, judge_limit=JUDGE_LIMIT,
                     modelle_erneuern=None):
    """Registry-Dateien aktualisieren. Wirft nichts nach aussen.

    repo    Wurzel des ausgecheckten Repos (dort liegen archive.json,
            news.json und der Ordner registry/).
    logger  ki_news-Logger.
    judge_limit      Artikel je Lauf fuer den Judge, 0 schaltet ihn ab.
    modelle_erneuern None = nach Alter entscheiden, True/False = erzwingen.

    Rueckgabe: True, wenn die Website-Dateien geschrieben wurden.
    """
    repo = str(repo)          # ki_news.py reicht ein Path herein
    out = os.path.join(HIER, "out")
    ziel = os.path.join(repo, "registry")
    modelle = os.path.join(out, "modelle.json")
    ablage = os.path.join(out, "facetten.json")
    os.makedirs(out, exist_ok=True)
    os.makedirs(ziel, exist_ok=True)

    # ── 1. Modellliste ────────────────────────────────────────────────────
    alter = _alter_tage(modelle)
    if modelle_erneuern is None:
        modelle_erneuern = alter is None or alter > MODELLE_MAX_ALTER_TAGE
    if modelle_erneuern:
        try:
            import generiere_modelle_json
            with _Sammler(logger, "[registry:modelle]"):
                generiere_modelle_json.main([])
            logger.info("Registry: Modellliste erneuert (war %s Tage alt)",
                        "n/a" if alter is None else "%.1f" % alter)
        except (Exception, SystemExit) as e:
            logger.warning("Registry: Modellliste nicht erneuert, alter Stand "
                           "wird weiterbenutzt: %s", e)
    if not os.path.exists(modelle):
        logger.error("Registry: %s fehlt und liess sich nicht erzeugen -- "
                     "Schritt uebersprungen.", modelle)
        return False

    # ── 2. Zuordnung Artikel -> Modell/Anbieter ───────────────────────────
    quellen = [p for p in (os.path.join(repo, "archive.json"),
                           os.path.join(repo, "news.json"))
               if os.path.exists(p)]
    if not quellen:
        logger.error("Registry: weder archive.json noch news.json in %s -- "
                     "Schritt uebersprungen.", repo)
        return False
    try:
        import ordne_artikel_zu
        argv = []
        for q in quellen:
            argv += ["--quelle", q]
        with _Sammler(logger, "[registry:zuordnung]"):
            ordne_artikel_zu.main(argv)
    except (Exception, SystemExit) as e:
        logger.exception("Registry: Zuordnung fehlgeschlagen, alter Stand "
                         "bleibt: %s", e)

    # ── 3. Facetten ───────────────────────────────────────────────────────
    # Bewusst nach der Zuordnung: wenn hier das Kontingent ausgeht, sind die
    # Zuordnungen schon frisch und Schritt 4 hat trotzdem etwas zu tun.
    if judge_limit:
        vorher = _facetten_anzahl(ablage)
        try:
            import klassifiziere
            with _Sammler(logger, "[registry:facetten]"):
                klassifiziere.main(["--quelle", quellen[0],
                                    "--limit", str(judge_limit),
                                    "--ablage", ablage])
            nachher = _facetten_anzahl(ablage)
            logger.info("Registry: Facetten %d -> %d (+%d)",
                        vorher, nachher, nachher - vorher)
        except (Exception, SystemExit) as e:
            logger.warning("Registry: Judge uebersprungen, Facettenstand "
                           "bleibt bei %d: %s", vorher, e)

    # ── 4. Website-Dateien bauen ──────────────────────────────────────────
    try:
        import baue_registry
        stat = baue_registry.baue(out, ziel)
        logger.info("Registry: %d Modelle, %d Anbieter, %d Zuordnungen, "
                    "%d Facetten -> %s",
                    stat["modelle"], stat["anbieter"], stat["zuordnungen"],
                    stat["facetten"], ziel)
        return True
    except (Exception, SystemExit) as e:
        logger.exception("Registry: Bauen fehlgeschlagen: %s", e)
        return False


def _facetten_anzahl(pfad):
    import json
    try:
        with open(pfad, encoding="utf-8") as f:
            return len(json.load(f).get("artikel", {}))
    except (OSError, ValueError):
        return 0


if __name__ == "__main__":
    import argparse
    import logging

    ap = argparse.ArgumentParser(description="Registry-Schritt einzeln laufen "
                                             "lassen, ohne ki_news.py.")
    ap.add_argument("--repo", default=os.path.dirname(HIER))
    ap.add_argument("--limit", type=int, default=JUDGE_LIMIT,
                    help="Artikel fuer den Judge, 0 = Judge aus")
    ap.add_argument("--modelle", choices=("auto", "ja", "nein"), default="auto")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ok = registry_schritt(
        os.path.abspath(a.repo), logging.getLogger("registry"),
        judge_limit=a.limit,
        modelle_erneuern={"auto": None, "ja": True, "nein": False}[a.modelle])
    sys.exit(0 if ok else 1)
