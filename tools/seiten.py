# -*- coding: utf-8 -*-
"""
seiten.py: Welche Seiten müssen obere Leiste und Seitenleiste aus assets/ki-layout.js tragen?

Jede HTML-Datei im Hauptordner, außer sie steht auf noindex oder in OHNE_LEISTE. Eine neue Seite
fällt also von selbst unter die Prüfung, statt wie früher still herauszufallen.

Noch nicht erfasst: meldung/ und recherche/ werden erzeugt und haben einen eigenen Kopf.
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
