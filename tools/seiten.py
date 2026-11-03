# -*- coding: utf-8 -*-
"""
seiten.py: Welche Seiten müssen obere Leiste und Seitenleiste aus assets/ki-layout.js tragen?

Jede HTML-Datei im Hauptordner, außer sie steht auf noindex oder in OHNE_LEISTE. Eine neue Seite
fällt also von selbst unter die Prüfung, statt wie früher still herauszufallen.

meldung/ und recherche/ werden erzeugt und teilen sich je eine Vorlage. Dort genügt eine Stichprobe.
"""
import glob, io, re

OHNE_LEISTE = {
    "score-formel-diagramm.html": "läuft als iframe in stats.html",
    "die5_hoch.html": "Vorlage für die5_video.py",
    "breaking_news_card_template.html": "Vorlage für generate_news_cards.py",
    "breaking_news_card_v2.html": "Vorlage für generate_news_cards.py",
    "breaking_player.html": "Vorlage für generate_news_cards.py",
    "ki_news.html": "wird von ki_news.py erzeugt",
    "creature-lab.html": "Prototyp, nirgends verlinkt",
    "background-creature-ambient.html": "Prototyp, nirgends verlinkt",
    "prototype-genesis.html": "Prototyp, Vollbild-Demo aus profil.html",
}

_NOINDEX = re.compile(r'name="robots"[^>]*noindex', re.I)

# Je eine Seite mit diesem Baustein, damit die Stichprobe jeden Aufbau der Vorlage abdeckt.
_BAUSTEINE = ("<video", "<figure><img", "Teil einer Entwicklung", ">Hintergrund", "Weitere Meldungen", "Einordnung</h2>")


def oeffentliche_seiten():
    """Liefert die Seiten relativ zum Repo-Ordner. Erwartet, dass dieser das Arbeitsverzeichnis ist."""
    seiten = []
    for pfad in sorted(glob.glob("*.html")):
        if pfad in OHNE_LEISTE:
            continue
        if _NOINDEX.search(io.open(pfad, encoding="utf-8").read()):
            continue
        seiten.append(pfad)
    return seiten


def _pfade(muster):
    return sorted(p.replace("\\", "/") for p in glob.glob(muster))


def erzeugte_seiten():
    return _pfade("meldung/*/*.html") + _pfade("recherche/*.html")


def erzeugte_stichprobe():
    """Die ältesten passenden Seiten. Seiten werden nie gelöscht, die Auswahl bleibt also stabil und
    eine neue Meldung macht keinen fremden PR rot. Dazu der längste Titel als Belastungsprobe."""
    stichprobe = ["recherche/"] + [p for p in _pfade("recherche/*.html") if p != "recherche/index.html"][:5]
    meldungen = {p: io.open(p, encoding="utf-8").read() for p in _pfade("meldung/*/*.html")}
    for baustein in _BAUSTEINE:
        treffer = next((p for p, text in meldungen.items() if baustein in text), None)
        if treffer and treffer not in stichprobe:
            stichprobe.append(treffer)
    if meldungen:
        laengster = max(meldungen, key=lambda p: len(re.search(r"<h1>(.*?)</h1>", meldungen[p], re.S).group(1)))
        if laengster not in stichprobe:
            stichprobe.append(laengster)
    return stichprobe
