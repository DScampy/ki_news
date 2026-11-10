#!/usr/bin/env python3
"""Recherche-Artikel (29.10.26, Daniel): aus mehreren Quellen zur selben Story ein eigener
Hintergrundartikel, inklusive offizieller Herstellerseite und deren Video/X-Post.

Unterschied zu dossier_automat/release_automat: Hier schreibt ein Sprachmodell Fliesstext
(Daniels Entscheidung B, 29.10.). Dafuer gelten harte Pruefungen, und nur was ALLE besteht,
geht automatisch raus ("wenn nach der Pruefung, dann raus damit"):

  1. Nur Quellenmaterial: Der Prompt verbietet Vorwissen. Jede Zahl, jedes Datum, jede Rolle
     und jede Person mit Kontext-Label muss im Material stehen (tools/deckungspruefung.pruefe,
     dieselbe Pruefung wie fuer die Einordnungen), dazu Produkt-/Firmennamen mit Ziffer oder
     Binnen-Grossbuchstabe (GPT-6, DeepMind) und jede Entitaet aus entities.json.
  2. Stil: kein Gedanken-/Halbgeviertstrich, kein Semikolon, kein Ausrufezeichen, keine
     Wir-Perspektive, keine Verbotswoerter, hoechstens ein Weichmacher, Laengen-Rahmen.
  3. Belege: jeder Absatz nennt mindestens eine Quellennummer.
  4. Pruefer-Modell (PRUEFER_MODELLE, seit 30.10.): je Absatz gegen die Fundstellen seiner Quellen,
     Antwort = Liste nicht gedeckter Aussagen, leer = bestanden. Alle Modelle ausgefallen = nicht
     bestanden. Jev (TypeSafe) laeuft nur noch im Schatten mit (Werte im Register, kein Einfluss).

Bestanden -> recherche/<slug>.html (indexierbar, recherche/sitemap.xml), meldungsseiten.py
verlinkt den Artikel als "Hintergrund" auf der Meldungsseite (ab dem naechsten Lauf).
Nicht bestanden -> artikel/entwurf/recherche-<slug>.html (noindex) mit Pruefbericht, damit
Daniel sieht, woran es lag. Eine Story wird nur einmal versucht (keine Kostenschleife).

Erweiterung (01.11.26, Daniel: "wie im Dossier"): Berichten zu einem veroeffentlichten Artikel
UPDATE_MIN_NEUE_MEDIEN weitere Medien, schreibt das Modell ihn mit alten und neuen Quellen neu.
Dieselben Pruefungen; bestanden -> gleiche Adresse, Vermerk "Aktualisiert am ...", alte Fassung
im Register (versionen). Nicht bestanden -> die alte Fassung bleibt online, der Versuch landet als
artikel/entwurf/recherche-<slug>-update.html. Hoechstens ein Versuch je Artikel und Tag, zaehlt
ins Tageslimit; nach einem Fehlversuch erst wieder, wenn noch weitere Medien dazukommen.

Laufende Faelle (10.11.26, Daniel, Plan R3): Ein Fall, der sich ueber Tage hinzieht, bekommt EINEN
Artikel, der fortgeschrieben wird. Anker ist die Linie (n["linie"] in news.json, dazu Thema-Zuordnungen
aus themenketten.json), nicht die story_id, die jeden Lauf neu vergeben wird. Auch ein Entwurf wird
fortgeschrieben. Nach KETTE_MAX_TAGE beginnt ein neuer Teil, der auf
den alten verweist. Dazu eine Zeitleiste aus den Ereignissen der Linie.
Schalter KETTEN ("schatten" = nur ins Log, "an", "aus").

Format (10.11.26, Daniel, Plan R4): kleine Quellennummern statt dauernd "laut X", Quellen unten kompakt,
immer ein Bild mit "Bild: Quelle", Kasten "Auf einen Blick" mit den harten Zahlen. Schalter FORMAT_R4.

Anker (10.11.26, Digg-Fund): Ein veroeffentlichter Artikel haengt an den Quellen, die er zitiert, nicht an
allen Links seines Clusters. Eine heutige Story braucht 2 gemeinsame Links. Schalter ANKER_ZITIERT.

Einziger Schreiber von recherche/ und artikel/entwurf/recherche-*.html (I5).
Laeuft als eigener Workflow-Schritt nach hersteller_feed.py, continue-on-error (I8).
Kill-Switch: RECHERCHE_AKTIV = False.

Aufruf: python3 recherche_artikel.py [--story SID] [--nur-entwurf] [--dry-run]
"""
import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meldungsseiten as ms

RECHERCHE_AKTIV = True
BASE = Path(__file__).resolve().parent
ORDNER = BASE / "recherche"
REGISTER = ORDNER / "index.json"
ENTWURF_DIR = BASE / "artikel" / "entwurf"
SITE = "https://ki-news.live"
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # Windows ohne tzdata (lokaler Test)
    BERLIN = timezone(timedelta(hours=1))

MIN_QUELLEN = 3                  # verschiedene Medien je Story
MIN_QUELLEN_MIT_HERSTELLER = 2   # ... oder 2, wenn die Herstellerseite dazukommt
MIN_TEXTQUELLEN = 2              # davon mit lesbarem Text (>= 600 Zeichen)
MAX_PRO_TAG = 4                  # zaehlt auch Entwuerfe und Erweiterungen; 01.11. von 2 auf 4 (Daniel)
MAX_PRO_LAUF = 1
# X-Belege (10.11.26, Daniel, Plan R1): X-Posts der HuggingNews-Kette (themenketten.json, Rolle
# source/support) plus darin verlinkte Originalseiten als weitere Belege, Modul x_belege.py.
# "schatten" = nur messen und ins Log schreiben, kein Artikel aendert sich. "aus" = Kill-Switch.
# "an" kommt erst mit R2, nach 3 Tagen Schatten-Auswertung. MIN_QUELLEN gilt weiter: X-Posts
# ersetzen keine Medien (Daniel: "mindestens drei oder vier Quellen").
X_BELEGE = "schatten"
X_SCHATTEN_ZEIT_S = 45           # Zeitgrenze fuer alle Kandidaten eines Laufs zusammen (Test 10.11.: 6 in 19 s)
# Laufende Faelle (10.11.26, Daniel, Plan R3): "ich möchte gerne, dass es endlich zusammenhängende
# Recherche-Artikel gibt, auch wenn die sich über Tage hinziehen". Anlass: Der Huang-Fall lag am 10.11.
# mit 39 Meldungen in 13 Storys, die story_id wechselt jeden Lauf, und es gab 3 Entwuerfe (08., 09.,
# 10.11.), weil nur veroeffentlichte Artikel erweitert wurden. Anker ist jetzt die Linie aus
# themenkette_shadow.linien_fuer_anzeige (HuggingNews-Kettenfamilie ab 3 Ereignissen, Zuordnungen mit
# Zwei-Modell-Votum), siehe linien_zuordnung. Meldungen ohne Linie laufen wie bisher ueber die story_id.
# "schatten" = nur ins Log, was R3 taete, sonst alles wie vorher. "an" = ein Artikel je Linie.
# "aus" = Kill-Switch, auch keine Log-Zeile.
KETTEN = "schatten"
KETTE_MAX_TAGE = 7               # so lange wird ein Artikel fortgeschrieben, dann beginnt ein neuer Teil.
                                 # Daniel 10.11.: Meldungen bleiben etwa eine Woche in der Pipeline, Dauer-
                                 # themen wie Rechenzentren bringen aber jeden Tag etwas Neues.
ZEITLEISTE_MAX = 10              # Ereignisse in der Zeitleiste (das erste bleibt immer drin)
KETTE_NEUE_QUELLEN = 3           # so viele Plaetze im Prompt bleiben bei langen Faellen fuer neue Medien frei
# Format (10.11.26, Daniel, Plan R4). Gemessen 10.11.: "laut X" 2 bis 12 Mal je Artikel, 7 von 13
# veroeffentlichten Artikeln ohne Bild, obwohl jeder davon eine Quelle mit gespiegeltem Bild hatte.
# - Medien nur noch im Satz, wenn sich Quellen widersprechen oder nur ein Medium etwas meldet.
# - Quellen unten als eine Zeile mit Nummern (Vorbild Notebookcheck), Pruefhinweis kleiner.
# - Bild: Karte, sonst Bild der Hauptmeldung, sonst Bild einer anderen Meldung desselben Falls, sonst
#   Herstellerbild. Nur gespiegelte Bilder (ki_news_media), darunter "Bild: <Medium>".
# - Kasten "Auf einen Blick": 3 bis 5 Zeilen mit harten Zahlen, je mit Quellennummer. Code und Pruefer
#   pruefen jede Zeile. Ein Fehler darin haelt den Artikel nicht an, dann faellt nur der Kasten weg.
# False = Kill-Switch, Prompt und Seite wie vor R4.
FORMAT_R4 = True
BLICK_MIN, BLICK_MAX = 3, 5      # Zeilen im Kasten, sonst kein Kasten
BLICK_ZEICHEN = 140              # hoechstens je Zeile
# Feeds ohne eigenen Verlag, wie SAMMEL_FEEDS in insta_caption.py. Ihr Bild nur, wenn kein Medium eins hat.
BILD_SAMMEL = {"AlignedNews", "Digg AI", "China AI Labs"}
# Anker (10.11.26, Digg-Fund). Das Register haelt unter "links" alle Links des Clusters beim Schreiben, nicht
# nur die zitierten Quellen. Am 10.11. mischte der Cluster Fable 5.2 mit Meta Muse Ember (WCCFtech schreibt
# ueber beide): 16 Links, 8 zitiert. Die Erweiterung am 11.11. haette 3 von 7 Quellen zu Meta genommen, und
# Digg und TechCrunch zaehlten als neu, obwohl sie schon im Cluster waren. Darum, nur fuer veroeffentlichte
# Artikel: Anker = zitierte Quellen ("quellen_links", bei aelteren Artikeln aus der Quellenliste der Seite),
# eine heutige Story braucht ANKER_MIN_LINKS gemeinsame Links (wie R3 in _eintrag_zur_linie), und ein Medium
# aus dem alten Cluster zaehlt nicht als neu. Entwuerfe bleiben bei allen Links.
# False = Kill-Switch, Verhalten wie vorher ("quellen_links" wird trotzdem gespeichert, liest dann keiner).
ANKER_ZITIERT = True
ANKER_MIN_LINKS = 2
UPDATE_MIN_NEUE_MEDIEN = 2       # so viele weitere Medien, dann wird ein Artikel erweitert
MAX_MEDIEN_JE_ARTIKEL = 7        # passt zu JEV_MAX_QUELLTEXT (7 Quellen a TEXT_JE_QUELLE)
TEXT_JE_QUELLE = 3000            # Zeichen Quelltext je Quelle im Prompt
JEV_SCHWELLE = 0.8
JEV_MAX_AUFRUFE = 60             # Saetze je Artikel (Titel/Anriss + 4-6 Absaetze, real ~25-30)
JEV_MAX_QUELLTEXT = 24000        # 7 Quellen a TEXT_JE_QUELLE + Kopfzeilen, nichts kappen
# Bumpen, wenn sich die Jev-Pruefung aendert: Entwuerfe, die NUR an Jev gescheitert sind und
# mit einer aelteren Fassung geprueft wurden, bekommen einmal einen neuen Versuch.
PRUEFUNG_VERSION = 7             # 3: Fundstelle (29.10.), 4: Pruefer statt Jev, 5: Gemini-Pruefer (30.10.),
                                 # 6: Pruefer-Belege mit Quellentiteln und ganzen Saetzen (31.10.),
                                 # 7: Entitaeten-Aliasse als Wortanfang (01.11.)
                                 # R4 (10.11.) prueft zusaetzlich den Kasten "Auf einen Blick", bleibt aber
                                 # bei 7: Eine hoehere Zahl holte alte Entwuerfe wieder in die Kandidaten
                                 # (siehe kandidaten), und fuer den Artikeltext aendert sich nichts.
# 29.10.26 im OpenRouter-Katalog geprueft. Sonnet zuerst (Deutsch, haelt Regeln), ~0,03 $ je
# Artikel bei <= 2 Artikeln am Tag. Hoechstens MAX_SCHREIBVERSUCHE Modelle je Story.
# 09.11.26 (Daniel): DeepSeek zuerst, Sonnet als Ersatz. Sonnet war seit 29.10. der groesste
# Posten bei OpenRouter (2 $/10 $ je Mio. Tokens, DeepSeek v4.1 Flash 0,05 $/0,57 $). Bis dahin
# 32 Versuche, 10 veroeffentlicht, alle von Sonnet. Gemini als zweites Modell hat in 8 Faellen
# keinen Artikel gerettet und fliegt deshalb raus. DeepSeek stand vorher an dritter Stelle und
# kam wegen MAX_SCHREIBVERSUCHE = 2 nie dran. Welches Modell schrieb, steht im Register (modell).
# Rueckweg: alte Liste ["anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash"]
MODELLE = ["deepseek/deepseek-v4.1-flash", "anthropic/claude-sonnet-5.5"]
MAX_SCHREIBVERSUCHE = 2

VERBOTEN = ["revolutionär", "bahnbrechend", "game-changer", "gamechanger", "disruptiv",
            "paradigmenwechsel", "nie dagewesen", "synergie", "nahtlos", "tiefgreifend",
            "vielschichtig", "facettenreich", "ganzheitlich", "richtungsweisend", "wegweisend",
            "zukunftsweisend", "spannend", "bleibt abzuwarten", "in einer welt", "zusammenfassend",
            "es ist wichtig zu beachten", "ehrlich gesagt", "offen gesagt", "verändert alles",
            "verändert die welt"]
WEICHMACHER = r"\b(?:möglicherweise|könnte\w*|eventuell|wirft die frage auf)\b"
WIR = r"\b(?:wir|uns|unser\w*)\b"

_FRAGE_SATZ = {
    "type": "noul",
    "instructions": "Ist jede Tatsachenbehauptung im Satz `satz` (Zahlen, Namen, Rollen, Daten, Ereignisse, "
                    "Zuschreibungen) durch `quellen` gedeckt? `kontext` ist der umgebende Absatz und dient "
                    "nur dem Verständnis (worauf sich \"er\", \"dagegen\" usw. beziehen), geprüft wird nur "
                    "`satz`. Übersetzung ins Deutsche und eigene Formulierung sind erlaubt. Ein Satz, der "
                    "nur einordnet, was die Quellen sagen oder nicht sagen (z. B. ein benannter Widerspruch), "
                    "ist gedeckt, wenn die Quellen das so hergeben.",
    "criteria": {
        "true": "Ja: alles steht so oder sinngemäß in den Quellen, Herstellerangaben sind als solche "
                "erkennbar.",
        "false": "Nein: mindestens eine Behauptung fehlt in den Quellen, ist verfälscht, übertrieben, "
                 "als Tatsache statt als Herstellerangabe dargestellt oder der falschen Quelle/Person "
                 "zugeschrieben.",
    },
}


def _deckung():
    spec = importlib.util.spec_from_file_location("deckungspruefung", BASE / "tools" / "deckungspruefung.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lade(pfad, leer):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return leer


def _zahl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sauber(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ── Auswahl ──────────────────────────────────────────────────────────────────

def kandidaten(news, releases, register, nur_story=None):
    # Entwuerfe, die nur an einer aelteren Jev-/Pruefer-/Entitaeten-Pruefung scheiterten, zaehlen nicht als erledigt
    erledigt = {l for e in register.values() for l in e.get("links", [])
                if not (e.get("status") == "entwurf" and e.get("pruefung", 1) < PRUEFUNG_VERSION
                        and e.get("gruende") and all(g.startswith(("Jev", "Prüfer", "Entität")) for g in e["gruende"]))}
    storys = {}
    for n in news:
        if n.get("link") and n.get("story_id"):
            storys.setdefault(n["story_id"], []).append(n)
    out = []
    for sid, glieder in storys.items():
        if nur_story and sid != nur_story:
            continue
        links = {l for g in glieder for l in ms._links(g)}
        if links & erledigt:
            continue
        medien = {(g.get("source") or "").strip().lower() for g in glieder} - {""}
        rel = _release_zu(releases, {sid}, links)
        if not (len(medien) >= MIN_QUELLEN or (rel and len(medien) >= MIN_QUELLEN_MIT_HERSTELLER)):
            continue
        rep = max(glieder, key=lambda x: _zahl(x.get("score")))
        out.append({"sid": sid, "rep": rep, "glieder": glieder, "links": sorted(links), "release": rel})
    out.sort(key=lambda k: _zahl(k["rep"].get("score")), reverse=True)
    return out


def _release_zu(releases, sids, links):
    return next((r for r in releases if r.get("story_id") in sids or r.get("news_link") in links), None)


def _medien(glieder):
    return {(g.get("source") or "").strip() for g in glieder} - {""}


def zitierte_links(slug, e):
    """Woran ein Registereintrag haengt. Veroeffentlicht und ANKER_ZITIERT: die Links der zitierten Quellen,
    aus dem Register ("quellen_links") oder aus der Quellenliste der Seite. Sonst alle Links des Clusters."""
    alle = set(e.get("links") or [])
    if not ANKER_ZITIERT or e.get("status") != "veroeffentlicht":
        return alle
    if e.get("quellen_links"):
        return set(e["quellen_links"])
    try:
        seite = (ORDNER / f"{slug}.html").read_text(encoding="utf-8")
    except OSError:
        return alle
    ol = re.search(r'<ol class="quellen[^"]*">(.*?)</ol>', seite, re.S)
    zitiert = {html.unescape(h) for h in re.findall(r'href="([^"]+)"', ol.group(1))} if ol else set()
    return zitiert or alle


def _mind_links(alt):
    """Gemeinsame Links, ab denen eine heutige Story zu einem Artikel gehoert (vorher: einer)."""
    return max(1, min(ANKER_MIN_LINKS, len(alt))) if ANKER_ZITIERT else 1


def _cluster_medien(e, nach_link):
    """Medien, die beim Schreiben schon im Cluster waren, auch nicht zitierte. Sie zaehlen nicht als neu."""
    if not ANKER_ZITIERT or e.get("status") != "veroeffentlicht":
        return set()
    return {m.lower() for m in _medien(nach_link[l] for l in e.get("links") or [] if l in nach_link)}


def erweiterungen(news, archiv, releases, register, heute):
    """Veroeffentlichte Artikel, zu deren Story inzwischen weitere Medien berichten. Die Story wird
    ueber die Links im Register gefunden: Das Clustering teilt sie spaeter oft anders auf (01.11.:
    die Cursor-Quellen lagen in s058 und s109, Golem nur noch im Archiv). Seit 10.11. ueber die
    zitierten Quellen, je Story ANKER_MIN_LINKS gemeinsame Links (siehe ANKER_ZITIERT)."""
    nach_link = {}
    for n in archiv + news:              # news zuletzt: aktuellere Felder gewinnen
        for l in ms._links(n):
            nach_link[l] = n
    storys = {}
    for n in news:
        if n.get("story_id"):
            storys.setdefault(n["story_id"], []).append(n)
    out = []
    for slug, e in register.items():
        fv = e.get("fehlversuch") or {}
        if e.get("status") != "veroeffentlicht" or heute in (e.get("datum"), e.get("aktualisiert"), fv.get("datum")):
            continue
        alt = zitierte_links(slug, e)
        mind = _mind_links(alt)
        glieder, ids, sids = [], set(), set()
        treffer = [nach_link[l] for l in sorted(alt) if l in nach_link]
        for sid, g in storys.items():
            if len({l for n in g for l in ms._links(n)} & alt) >= mind:
                treffer += g
                sids.add(sid)
        for n in treffer:
            if id(n) not in ids:
                ids.add(id(n))
                glieder.append(n)
        medien_alt = {m.lower() for m in (e.get("medien") or
                                          _medien(g for g in glieder if set(ms._links(g)) & alt))}
        medien_alt |= _cluster_medien(e, nach_link)
        neu = sorted(m for m in _medien(glieder) if m.lower() not in medien_alt)
        versucht = {m.lower() for m in fv.get("medien") or []}   # nach Fehlversuch: weitere Medien noetig
        if sum(m.lower() not in versucht for m in neu) < UPDATE_MIN_NEUE_MEDIEN:
            continue
        links = {l for g in glieder for l in ms._links(g)}
        rep = max((g for g in glieder if g.get("story_id") in sids) or glieder, key=lambda x: _zahl(x.get("score")))
        out.append({"sid": rep.get("story_id") or e.get("story_id"), "rep": rep, "glieder": glieder,
                    "links": sorted(links), "release": _release_zu(releases, sids, links),
                    "update": slug, "alt_links": alt, "neu": neu})
    out.sort(key=lambda k: -len(k["neu"]))
    return out


def heute_verbraucht(register, heute):
    """Neue Artikel, Entwuerfe, Erweiterungen und gescheiterte Erweiterungen von heute."""
    return sum((e.get("datum") == heute) + (e.get("aktualisiert") == heute)
               + ((e.get("fehlversuch") or {}).get("datum") == heute) for e in register.values())


# ── Laufende Faelle (Plan R3) ────────────────────────────────────────────────

def _tage(von, bis):
    try:
        return (datetime.strptime(str(bis)[:10], "%Y-%m-%d") - datetime.strptime(str(von)[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return 0


def zeitleiste(linie):
    """Ereignisse der Linie von alt nach neu, ohne die, die das Dossier als abseits markiert hat.
    Hoechstens ZEITLEISTE_MAX, das erste Ereignis bleibt immer drin. Nur unsere eigenen Titel."""
    weg = set((linie.get("dossier") or {}).get("abseits") or [])
    liste = sorted((e for e in linie.get("e") or [] if e.get("k") not in weg and e.get("t") and e.get("d")),
                   key=lambda e: e["d"])
    if len(liste) > ZEITLEISTE_MAX:
        liste = liste[:1] + liste[-(ZEITLEISTE_MAX - 1):]
    return [{"d": e["d"][:10], "t": _sauber(e["t"]), "q": _sauber(e.get("q")), "l": e.get("l") or ""} for e in liste]


def _eintrag_zur_linie(register, lid, links, vergeben):
    """Registereintrag, der die Linie fortsetzt. Zuerst einer mit derselben Linie (der neueste Teil).
    Sonst einer von vor R3 mit gemeinsamen Links, mindestens 2 (bei Eintraegen mit 1 Link dieser),
    damit ein einzelner geerbter Link keinen fremden Artikel kapert. Dabei veroeffentlichte vor
    Entwuerfen, dann die meisten gemeinsamen Links, dann der neueste."""
    eigene = [(s, e) for s, e in register.items() if e.get("linie") == lid and s not in vergeben]
    if eigene:
        return max(eigene, key=lambda x: x[1].get("datum") or "")[0]
    alte = []
    for s, e in register.items():
        alt = zitierte_links(s, e)
        if s in vergeben or e.get("linie") or not alt:
            continue
        gemeinsam = len(alt & links)
        if gemeinsam >= min(2, len(alt)):
            alte.append(((e.get("status") == "veroeffentlicht", gemeinsam, e.get("datum") or ""), s))
    return max(alte)[1] if alte else None


def linien_zuordnung(news, linien, themen):
    """Welche Meldung gehoert zu welcher Linie: {link: lid} und je Linie alle Links ihrer Kettenfamilie.
    n["linie"] kennt nur Ereignis-Zuordnungen und deren Cluster-Geschwister. Am 10.11. fehlte so die
    Huang-Story s017 (Reuters, FT, Economist), obwohl themenketten.json sie derselben Familie als
    "thema" zuordnet (auch Zwei-Modell-Votum). Darum zaehlt hier auch die eigene Thema-Zuordnung, und
    Cluster-Geschwister ohne eigene Zuordnung erben sie, wie in themenkette_shadow.linien_fuer_anzeige.
    Die Familien-Links finden ausserdem alte Artikel, deren Quellen schon im Archiv liegen."""
    zu = themen.get("zuordnung") or {}
    fv = themen.get("familie_von") or {}
    fam = {l: hashlib.md5(fv.get(z["kette"], z["kette"]).encode("utf-8")).hexdigest()[:8]
           for l, z in zu.items() if z.get("kette")}
    familie = {}
    for l, lid in fam.items():
        if lid in linien:
            familie.setdefault(lid, set()).add(l)
    zug, storys = {}, {}
    for n in news:
        if not n.get("link"):
            continue
        storys.setdefault(n.get("story_id"), []).append(n)
        if n.get("linie") in linien:
            zug[n["link"]] = n["linie"]
            continue
        eigene = {fam[l] for l in ms._links(n) if l in fam}
        if len(eigene) == 1 and next(iter(eigene)) in linien:
            zug[n["link"]] = next(iter(eigene))
    for sid, glieder in storys.items():
        lids = {zug[g["link"]] for g in glieder if g["link"] in zug}
        if sid and len(lids) == 1:
            for g in glieder:
                if g["link"] not in zug and not any(l in fam for l in ms._links(g)):
                    zug[g["link"]] = next(iter(lids))
    return zug, familie


def linien_plan(news, linien, releases, register, heute, zug, familie, archiv=()):
    """Plan R3: ein Eintrag je Linie mit Meldungen in news.json. "kandidat" ist der Kandidat fuer
    die Schreibschleife (neu oder Fortschreibung) oder None, dann sagt "grund" warum nicht.
    zug, familie: aus linien_zuordnung. archiv nur fuer _cluster_medien. Liest nichts aus dem Netz."""
    nach_link = {l: n for n in list(archiv) + list(news) for l in ms._links(n)}
    gruppen = {}
    for n in news:
        if n.get("link") in zug:
            gruppen.setdefault(zug[n["link"]], []).append(n)
    plan, vergeben = [], set()
    for lid, glieder in sorted(gruppen.items(), key=lambda x: (-len(x[1]), x[0])):
        linie = linien[lid]
        links = {l for g in glieder for l in ms._links(g)}
        bekannte = links | familie.get(lid, set()) | {e.get("l") for e in linie.get("e") or [] if e.get("l")}
        medien = _medien(glieder)
        sids = sorted({g.get("story_id") for g in glieder if g.get("story_id")})
        rel = _release_zu(releases, set(sids), links)
        rep = max(glieder, key=lambda x: _zahl(x.get("score")))
        p = {"lid": lid, "titel": (linie.get("dossier") or {}).get("titel") or ms._titel(rep),
             "ereignisse": linie.get("n") or len(linie.get("e") or []), "seit": linie.get("seit") or "",
             "sids": sids, "meldungen": len(glieder), "medien": sorted(medien), "slug": None,
             "aktion": "", "grund": "", "neu": [], "kandidat": None}
        plan.append(p)
        k = {"sid": "Linie " + lid, "rep": rep, "glieder": glieder, "links": sorted(links), "release": rel,
             "linie": lid, "zeitleiste": zeitleiste(linie), "medien_linie": sorted(medien)}
        slug = _eintrag_zur_linie(register, lid, bekannte, vergeben)
        e = register.get(slug) if slug else None
        if e and _tage(e.get("datum"), heute) > KETTE_MAX_TAGE:
            vergeben.add(slug)
            k["vorgaenger"] = slug
            if e.get("status") == "veroeffentlicht":
                k["vorgaenger_info"] = {"pfad": e.get("pfad"), "titel": e.get("titel")}
            p["slug"], p["aktion"] = slug, "neuer Teil"
            e = None
        if e:
            vergeben.add(slug)
            p["slug"] = slug
            fv = e.get("fehlversuch") or {}
            if heute in (e.get("datum"), e.get("aktualisiert"), fv.get("datum")):
                p["grund"] = "heute schon geschrieben"
                continue
            bekannt = {m.lower() for m in (e.get("medien") or []) + (e.get("medien_linie") or [])}
            bekannt |= _cluster_medien(e, nach_link)
            neu = sorted(m for m in medien if m.lower() not in bekannt)
            versucht = {m.lower() for m in fv.get("medien") or []}
            p["neu"] = neu
            if sum(m.lower() not in versucht for m in neu) < UPDATE_MIN_NEUE_MEDIEN:
                p["grund"] = f"nur {len(neu)} neue Medien"
                continue
            if e.get("status") == "veroeffentlicht":
                k.update(update=slug, alt_links=zitierte_links(slug, e), neu=neu)
            else:
                # Entwurf: wird frisch geschrieben, ohne "neu"-Marken und ohne Vorrang fuer alte Quellen
                k.update(update=slug, alt_links=set(), neu=neu, entwurf=True)
            p["aktion"], p["kandidat"] = "fortschreiben", k
            continue
        if not (len(medien) >= MIN_QUELLEN or (rel and len(medien) >= MIN_QUELLEN_MIT_HERSTELLER)):
            p["grund"] = f"nur {len(medien)} Medien"
            continue
        p["aktion"], p["kandidat"] = p["aktion"] or "neu", k
    return plan


def _in_linie(k, zug):
    return any(g.get("link") in zug for g in k["glieder"])


def ketten_logzeilen(plan, kand, erw, register, zug):
    """Was R3 taete, fuer den Schattenbetrieb. Je Linie eine Zeile."""
    zeilen = []
    for p in plan:
        einzel = [k["update"][:40] if k.get("update") else k["sid"]
                  for k in kand + erw if any(zug.get(g.get("link")) == p["lid"] for g in k["glieder"])]
        kopf = (f"[RECHERCHE] Ketten-Schatten {p['lid']} ({p['titel'][:60]}): {p['ereignisse']} Ereignisse seit "
                f"{ms._datum_de(p['seit'])}, {p['meldungen']} Meldungen in {len(p['sids'])} Storys, "
                f"{len(p['medien'])} Medien -> ")
        e = register.get(p["slug"]) if p["slug"] else {}
        wer = (f"{p['slug'][:50]} ({'Entwurf' if e.get('status') == 'entwurf' else 'Artikel'} vom "
               f"{ms._datum_de(e.get('datum') or '')})") if p["slug"] else ""
        if p["aktion"] == "fortschreiben":
            was = f"wuerde fortschreiben: {wer}, +{len(p['neu'])} Medien ({', '.join(p['neu'][:6])})"
        elif p["aktion"] == "neuer Teil" and p["kandidat"]:
            was = f"wuerde neuen Teil schreiben, {wer} ist aelter als {KETTE_MAX_TAGE} Tage"
        elif p["aktion"] == "neu":
            was = "wuerde neuen Artikel schreiben"
        else:
            was = f"nichts zu tun, {p['grund']}" + (f" ({wer})" if wer else "")
        was += f", statt {len(einzel)} Einzelkandidaten ({', '.join(einzel)})" if einzel else ""
        zeilen.append(kopf + was)
    return zeilen


def _absaetze(seite):
    """Nur Fliesstext-Absaetze (<p> ab 60 Zeichen, ohne Dubletten), keine Menues/Listen."""
    s = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", seite)
    out, gesehen = [], set()
    for roh in re.findall(r"(?is)<p[^>]*>(.*?)</p>", s):
        t = _sauber(html.unescape(re.sub(r"<[^>]+>", " ", roh)))
        if len(t) >= 60 and t not in gesehen:
            gesehen.add(t)
            out.append(t)
    return " ".join(out)


def _quelltext(m, dp):
    """Artikeltext. Zuerst frisch von der Seite (nur Absaetze, ohne Navigation): full_text in
    news.json ist der Seitenanfang und besteht oft nur aus Menues ("heise+ entdecken Suchen Abo")."""
    for url in (m.get("link_verlag"), m.get("link")):
        if not url or "news.google.com" in url:
            continue
        try:
            seite = dp._get(url)
        except Exception:
            seite = ""
        t = _absaetze(seite) if seite else ""
        if len(t) < dp.MIN_QUELLTEXT and seite:
            t = dp.text_aus_html(seite)
        if len(t) >= dp.MIN_QUELLTEXT and not _zustimmseite(t):
            return t
        break
    ft = m.get("full_text")
    return ft if isinstance(ft, str) and len(ft) >= dp.MIN_QUELLTEXT and not _zustimmseite(ft) else ""


def _zustimmseite(t):
    """Cookie-/Zustimm-Wand statt Artikel (30.10.: Golem lieferte nur "... der Nutzung aller Cookies
    zustimmen ..."; der Pruefer bemaengelte zu Recht, dass die "Quelle" nichts belegt)."""
    kopf = t[:1500].lower()
    return sum(kopf.count(w) for w in ("cookie", "zustimm", "einwillig", "tracking", "consent", "privacy center")) >= 4


def _lesbar(g):
    """Hat die Meldung eine Adresse, von der _quelltext lesen kann (nicht nur news.google.com)?"""
    return any(u and "news.google.com" not in u for u in (g.get("link_verlag"), g.get("link")))


def _reihe_linie(k, reihe, alt, neu):
    """R3: je Medium eine Meldung (die bisherige Quelle, sonst die neueste lesbare). Gibt
    es mehr Medien als MAX_MEDIEN_JE_ARTIKEL, behalten die bisherigen Quellen ihre Plaetze bis auf
    KETTE_NEUE_QUELLEN, die fuer neue Medien frei bleiben. Sonst kamen neue Medien bei langen Faellen
    nie in den Prompt. Lesbare Medien vor solchen, die nur ueber news.google.com kommen (Test 10.11.:
    Huang-Linie mit 15 Medien, 5 der 7 gewaehlten ohne Text), dann die neueren Meldungen. Ergebnis nach
    Datum, damit die Quellennummern dem Verlauf folgen."""
    def zeit(g):
        return g.get("first_seen") or g.get("date") or ""
    beste = {}
    neueste = sorted(reihe, key=zeit, reverse=True)
    for g in sorted(neueste, key=lambda x: (not set(ms._links(x)) & alt, not _lesbar(x))):
        m = (g.get("source") or "").strip().lower()
        if m and m not in beste:
            beste[m] = g
    def vorne(medien):                   # lesbar zuerst, darin die neueste Meldung zuerst
        medien = sorted(medien, key=lambda m: zeit(beste[m]), reverse=True)
        return sorted(medien, key=lambda m: not _lesbar(beste[m]))
    bisher = [m for m, g in beste.items() if set(ms._links(g)) & alt]
    neue = vorne(m for m in beste if m in neu and m not in bisher)
    frei = min(len(neue), KETTE_NEUE_QUELLEN)
    wahl = bisher[:MAX_MEDIEN_JE_ARTIKEL - frei] + neue[:frei]
    wahl += vorne(m for m in beste if m not in wahl)[:MAX_MEDIEN_JE_ARTIKEL - len(wahl)]
    return sorted((beste[m] for m in wahl),
                  key=lambda g: (g.get("first_seen") or g.get("date") or "", -_zahl(g.get("score"))))


def material(k, dp):
    """Nummerierte Quellen: je Medium die Meldung mit dem laengsten Text, dazu die Herstellerseite.
    Bei einer Erweiterung zuerst die Meldungen der bisherigen Fassung (alt_links)."""
    quellen, gesehen = [], set()
    alt = k.get("alt_links") or set()
    neu = {m.lower() for m in k.get("neu") or []}
    reihe = sorted(k["glieder"], key=lambda x: (not set(ms._links(x)) & alt, -len(x.get("full_text") or "")))
    if k.get("linie"):
        reihe = _reihe_linie(k, reihe, alt, neu)
    for g in reihe:
        medium = (g.get("source") or "").strip()
        if not medium or medium.lower() in gesehen or len(gesehen) >= MAX_MEDIEN_JE_ARTIKEL:
            continue
        gesehen.add(medium.lower())
        text = _quelltext(g, dp)
        quellen.append({"medium": medium, "titel": _sauber(g.get("title")), "link": g.get("link_verlag") or g.get("link"),
                        "text": _sauber(" ".join(x for x in (g.get("summary"), text) if x))[:TEXT_JE_QUELLE],
                        "hat_text": len(text) >= dp.MIN_QUELLTEXT, "hersteller": False,
                        "neu": medium.lower() in neu and not k.get("entwurf")})   # R3: Entwurf ohne Marke
    r = k["release"]
    if r and r.get("url"):
        text = _quelltext({"link": r["url"]}, dp)
        quellen.append({"medium": f"{r.get('hersteller') or 'Hersteller'} (offizielle Seite)",
                        "titel": _sauber(r.get("titel_en") or r.get("titel")), "link": r["url"],
                        "text": _sauber(" ".join(x for x in (r.get("text_en") or r.get("text"), text) if x))[:TEXT_JE_QUELLE],
                        "hat_text": len(text) >= dp.MIN_QUELLTEXT, "hersteller": True})
    for i, q in enumerate(quellen, 1):
        q["nr"] = i
    return quellen


def karte_zur_story(k, base=BASE):
    """Karte nur, wenn ihr HAUPTlink zur Story gehoert und sie nicht aelter als die Story ist.
    Ueber Zusatz-Links haengen alte Karten an neuen Storys (29.10.: Chrome-Karte vom 25.10. am
    Gemini-4-Carbon-Link), darum nicht ms._karten_nach_link."""
    roh = _lade(base / "cards.json", [])
    karten = roh if isinstance(roh, list) else roh.get("cards", [])
    ab = min((g.get("first_seen") or g.get("date") or "9999")[:10] for g in k["glieder"])
    for c in karten:
        links = c.get("links") or []
        links = [links] if isinstance(links, str) else links
        if links and links[0] in k["links"] and (c.get("date") or "")[:10] >= ab:
            return c
    return None


def bild_zur_story(k, quellen):
    """R4: (gross, klein, Medium) des Bildes. Zuerst die Hauptmeldung, dann andere Meldungen desselben Falls,
    deren Medium als Quelle im Artikel steht (in Quellenreihenfolge), dann die uebrigen, zuletzt das Bild der
    Herstellerseite. Nur gespiegelte Bilder, keine fremden Adressen. 640er bleiben dauerhaft liegen, 1600er
    loescht bilder_spiegel.py nach BILDER_GROSS_TAGE.
    Sammel-Feeds (BILD_SAMMEL) kommen zuletzt: Ihr Bild stammt von einem fremden Verlag, den wir nicht kennen
    (Digg: link_verlag ist wieder digg.com). Darum dort "Bild: via Digg AI"."""
    nr = {q["medium"].strip().lower(): q["nr"] for q in quellen if not q["hersteller"]}
    sammel = {s.lower() for s in BILD_SAMMEL}
    kandidaten = [k["rep"]] + [g for g in k["glieder"] if g is not k["rep"]]
    def rang(g):
        s = (g.get("source") or "").strip().lower()
        return (s in sammel, g is not k["rep"], nr.get(s, 99))
    for g in sorted(kandidaten, key=rang):
        klein, gross = g.get("image_local") or "", g.get("image_local_gross") or ""
        if klein.startswith("https://") or gross.startswith("https://"):
            von = (g.get("source") or "").strip()
            return gross or klein, klein or gross, ("via " + von) if von.lower() in sammel else von
    r = k["release"] or {}
    if (r.get("poster") or "").startswith("https://"):
        return r["poster"], r["poster"], r.get("hersteller") or ""
    return "", "", ""


# ── Schreiben ────────────────────────────────────────────────────────────────

def prompt(quellen, alt=None, fall=False):
    """alt: die veroeffentlichte Fassung (Register "artikel"), wenn der Artikel erweitert wird.
    fall: Quellen einer Linie (Plan R3), nach Datum geordnet."""
    teile = []
    for q in quellen:
        # 01.11.: Bei "Medienbericht" schrieb Sonnet "Ein Medienbericht zitiert ..." statt des Mediums
        art = "Offizielle Herstellerseite" if q["hersteller"] else "Medium"
        if q.get("neu"):
            art += ", neu"
        teile.append(f"[{q['nr']}] {q['medium']} ({art})\nTitel: {q['titel']}\nText: {q['text']}")
    erweiterung = ""
    if alt:
        erweiterung = (
            "Es gibt schon eine veröffentlichte Fassung dieses Artikels (unten). Inzwischen berichten weitere "
            "Medien, ihre Quellen sind mit „neu“ markiert. Schreibe den Artikel neu: Ergänze, was die neuen "
            "Quellen hinzufügen, korrigiere, was sie überholen, und behalte, was weiterhin in den Quellen steht. "
            "Hat sich die Hauptnachricht geändert, darf sich auch der Titel ändern. Für die bisherige Fassung "
            "gelten dieselben Regeln: Nichts daraus übernehmen, was nicht in den Quellen steht. Die "
            "Quellennummern beziehen sich nur auf die Liste unten.\n\nBisherige Fassung:\n"
            f"Titel: {alt.get('titel', '')}\nAnriss: {alt.get('anriss', '')}\n"
            + "\n".join(x.get("text", "") for x in alt.get("absaetze") or []) + "\n\n")
    if fall:
        # R3: Fall ueber mehrere Tage. Daten stehen bewusst nicht im Quellenkopf, denn die Pruefung
        # sucht jede Zahl im Quelltext, ein Datum aus dem Kopf galte dort als nicht belegt.
        erweiterung = (
            "Die Quellen gehören zu einem Fall, der sich über mehrere Tage entwickelt hat. Sie sind nach "
            "Datum geordnet, die letzte ist die neueste. Der erste Absatz nennt die neueste Entwicklung. "
            "Danach erzählst du der Reihe nach, wie es dazu kam. Ein Datum nur, wenn es in einer Quelle "
            "steht.\n\n") + erweiterung
    medium_regel = "- Das Medium immer beim Namen nennen (\"laut TechRepublic\"), nie \"ein Medienbericht\" oder \"ein Bericht\".\n"
    blick_feld, blick_regel = "}\n", ""
    if FORMAT_R4:
        # R4: Die Nummern hinter dem Absatz zeigen die Herkunft. Namen nur, wo der Leser sie braucht.
        medium_regel = (
            "- Medien nicht im Satz nennen, die Quellennummern hinter dem Absatz zeigen die Herkunft. Den Namen nur, "
            "wenn sich Quellen widersprechen (\"Heise nennt 5 Dollar, Golem 4,99 Dollar\") oder wenn nur ein Medium "
            "etwas meldet, das die anderen nicht bestätigen, zum Beispiel mit eigenen Informanten (\"laut Reuters\"). "
            "Nie \"ein Medienbericht\" oder \"ein Bericht\".\n")
        blick_feld = (', "blick": [{"text": "kurze Zeile mit einer harten Zahl, höchstens 120 Zeichen", '
                      '"quellen": [1]}]}\n')
        blick_regel = (f" \"blick\": {BLICK_MIN} bis {BLICK_MAX} Zeilen mit den wichtigsten Zahlen (Preis, Betrag, "
                       "Datum, Anzahl), kein ganzer Satz nötig, zum Beispiel „Preis: 8 Dollar je Million Tokens“. "
                       "Jede Zahl genau wie in der Quelle, jede Zeile mit ihrer Quellennummer. Gibt es keine "
                       f"{BLICK_MIN} solchen Zahlen, eine leere Liste.")
    return (
        "Du schreibst für ki-news.live einen deutschen Hintergrundartikel zu einer KI-Meldung. "
        "Grundlage sind AUSSCHLIESSLICH die nummerierten Quellen unten.\n\n"
        "Regeln:\n"
        "- Nur Fakten, die in mindestens einer Quelle stehen. Kein Vorwissen, keine Vermutung. Keine Zahl, "
        "kein Datum, kein Name, keine Rolle, die nicht in den Quellen steht.\n"
        "- Zahlen als Ziffern, der Wert genau wie in der Quelle, nicht umrechnen, nicht runden. Aber deutsch "
        "geschrieben: Komma statt Dezimalpunkt, \"88,2 Prozent\" statt \"88.2%\", \"2 Dollar\" statt \"$2\", "
        "\"doppelt so hoch\" statt \"2x\", \"89 Punkte mehr\" statt \"+89\".\n"
        + medium_regel +
        "- Keine englischen Zitate. Englische Aussagen sinngemäß auf Deutsch wiedergeben, ohne Anführungszeichen.\n"
        "- Jede Person beim ersten Auftauchen mit Rolle in Klammern, z. B. \"Sundar Pichai (Chef Google)\", "
        "aber nur mit einer Rolle, die in einer Quelle steht. Zusätze wie \"ehemalig\", \"früher\", "
        "\"bisherig\", \"designiert\" nur, wenn die Quelle sie nennt.\n"
        "- Angaben des Herstellers (Benchmarks, Versprechen) als seine Angaben kennzeichnen (\"laut Google\"), "
        "nicht als Tatsache.\n"
        "- Widersprechen sich Quellen (andere Zahl, anderes Datum), das offen benennen.\n"
        "- Erster Absatz: der wichtigste konkrete Fakt, mit Zahl, wenn eine da ist. Letzter Absatz: was offen "
        "bleibt oder was das konkret bedeutet, ohne Beruhigungsfloskel.\n"
        "- Ton: nüchtern, konkret, skeptisch gegenüber Hype. Satzlänge variieren, auch mal ein kurzer Satz.\n"
        "- Verboten: Gedankenstrich, Semikolon, Ausrufezeichen, \"wir\"/\"uns\", Hashtags, Emojis, die Wörter "
        "revolutionär, bahnbrechend, Game-Changer, disruptiv, Paradigmenwechsel, nahtlos, tiefgreifend, "
        "wegweisend, spannend, und Floskeln wie \"es bleibt abzuwarten\", \"in einer Welt\", \"nicht nur ... "
        "sondern auch\". \"könnte\", \"möglicherweise\", \"eventuell\" höchstens einmal im ganzen Text.\n"
        "- Jeder Absatz nennt die Nummern der Quellen, auf denen er beruht.\n\n"
        "Antworte NUR mit gültigem JSON, ohne Erklärung. Anführungszeichen im Text nur als „ “, "
        "nie als gerades Anführungszeichen:\n"
        '{"titel": "ein Aussagesatz, höchstens 90 Zeichen, ohne Schlusspunkt", '
        '"anriss": "1 bis 2 Sätze, höchstens 260 Zeichen", '
        '"absaetze": [{"text": "250 bis 700 Zeichen", "quellen": [1, 2]}], '
        '"tags": ["höchstens 3 Schlagwörter"]'
        + blick_feld + "4 bis 6 Absätze." + blick_regel + "\n\n" + erweiterung + "Quellen:\n\n" + "\n\n".join(teile)
    )


def _anfrage(p, modell, key, reasoning, system="", temperature=0.3):
    nachrichten = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": p}]
    nutzlast = {"model": modell, "max_tokens": 8000, "temperature": temperature,
                "messages": nachrichten, "usage": {"include": True}}
    if reasoning:
        nutzlast["reasoning"] = reasoning
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(nutzlast).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://ki-news.live/", "X-Title": "KI News Recherche-Artikel"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def _fehlertext(e):
    """Haengt die Begruendung aus der Fehlerantwort an (e.text). 29.10. 16 UTC: Sonnet und Gemini
    lieferten beide HTTP 429, im Log stand nur der Code - nicht, ob Rate-Limit, Schluessel-Limit
    oder Anbieter. OpenRouter schickt {"error": {"message": ..., "metadata": ...}}, keine Geheimnisse."""
    try:
        roh = e.read().decode("utf-8", "replace")
        try:
            f = json.loads(roh).get("error") or {}
            text = " ".join(str(x) for x in (f.get("message"), f.get("metadata")) if x) or roh
        except ValueError:
            text = roh
    except Exception:
        text = ""
    e.text = _sauber(text)[:300]
    return e.text


def _schreib_reasoning(modell):
    # 10.11.26: DeepSeek v4.1 Flash haelt sich nicht an effort "low". Am 09.11. hat es zweimal alle
    # 8000 Tokens zum Denken verbraucht (reasoning_tokens 8000, finish_reason=length, 0 Zeichen Text),
    # dann musste Sonnet ran. Im OpenRouter-Katalog steht fuer DeepSeek reasoning.mandatory False,
    # fuer Sonnet True. Darum nur bei DeepSeek Denken aus, mit demselben Schalter wie Nemotron im
    # Pruefer. Rueckweg: hier wieder fuer alle {"effort": "low", "exclude": True} zurueckgeben.
    return {"enabled": False} if modell.startswith("deepseek/") else {"effort": "low", "exclude": True}


def schreibe(p, modell, key):
    # 29.10.26, erster Live-Lauf: Sonnet und Gemini lieferten keinen auswertbaren Text (0 Zeichen
    # Titel). Wie bei Nemotron/gpt-oss in ki_news.py: denkende Modelle verbrauchen das Budget fuers
    # Denken. Darum Denken drosseln und mehr Budget; lehnt ein Endpunkt den Parameter ab (HTTP 400),
    # einmal ohne. Leere/kaputte Antworten werden mit Grund protokolliert statt still verworfen.
    try:
        roh = _anfrage(p, modell, key, _schreib_reasoning(modell))
    except urllib.error.HTTPError as e:
        _fehlertext(e)
        if e.code != 400:
            raise
        print(f"[RECHERCHE] {modell}: HTTP 400 mit reasoning-Parameter ({e.text}), zweiter Versuch ohne")
        try:
            roh = _anfrage(p, modell, key, None)
        except urllib.error.HTTPError as e2:
            _fehlertext(e2)
            raise
    wahl = (roh.get("choices") or [{}])[0]
    antwort = (wahl.get("message") or {}).get("content") or ""
    if isinstance(antwort, list):          # manche Anbieter liefern Inhaltsbloecke
        antwort = "".join(b.get("text", "") for b in antwort if isinstance(b, dict))
    antwort = re.sub(r"^```(?:json)?\s*|\s*```$", "", antwort.strip())
    a = {}
    if "{" in antwort and "}" in antwort:
        try:
            a = json.loads(antwort[antwort.index("{"): antwort.rindex("}") + 1])
        except ValueError as e:
            print(f"[RECHERCHE] {modell}: JSON kaputt ({e}), Anfang: {antwort[:160]!r}")
    if not a:
        print(f"[RECHERCHE] {modell}: kein JSON. finish_reason={wahl.get('finish_reason')}, "
              f"{len(antwort)} Zeichen, usage={roh.get('usage')}, Anfang: {antwort[:160]!r}")
    else:
        # 10.11.26: Auch bei Erfolg Verbrauch zeigen. Bisher stand er nur im Fehlerfall im Log, so war
        # nicht zu sehen, wie knapp ein Artikel am 8000er-Budget lag und was der Schreiber kostet.
        u = roh.get("usage") or {}
        print(f"[RECHERCHE] {modell}: {u.get('completion_tokens')} Tokens Ausgabe, davon "
              f"{(u.get('completion_tokens_details') or {}).get('reasoning_tokens')} Denken, {u.get('cost')} $")
    absaetze = [{"text": _zahlformat(_sauber(x.get("text"))), "quellen": [int(q) for q in x.get("quellen") or []
                                                                          if str(q).isdigit()]}
                for x in a.get("absaetze") or [] if isinstance(x, dict)]
    blick = [{"text": _zahlformat(_sauber(x.get("text"))).rstrip("."),
              "quellen": [int(q) for q in x.get("quellen") or [] if str(q).isdigit()]}
             for x in (a.get("blick") or [] if FORMAT_R4 else []) if isinstance(x, dict)]
    return {"titel": _zahlformat(_sauber(a.get("titel"))).rstrip("."), "anriss": _zahlformat(_sauber(a.get("anriss"))),
            "absaetze": absaetze, "tags": [_sauber(t) for t in (a.get("tags") or [])][:3], "blick": blick}


_ZAHL = r"\d+(?:[.,]\d+)*"
_GROESSE = r"(?:\s+(?:Millionen|Milliarden|Billionen|Mio\.|Mrd\.))?"


def _de_zahl(z):
    """88.2 -> 88,2 und 1,000 -> 1.000. Mehrdeutiges wie 1.500 bleibt stehen."""
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", z):
        return z.replace(",", ".")
    if re.fullmatch(r"\d+\.\d+", z) and not re.fullmatch(r"\d{1,3}\.\d{3}", z):
        return z.replace(".", ",")
    return z


def _zahlformat(t):
    """Prozent und Dollar deutsch schreiben, bevor geprueft wird (01.11.: Sonnet uebernahm "88.2%" und
    "$2" aus den Quellen). Die Deckungspruefung findet "88,2" auch als "88.2" in der Quelle.
    Versionen ("v5.0", "GPT-5.5") bleiben, weil kein % oder $ daran haengt."""
    t = re.sub(r"(?<![\w.,])(" + _ZAHL + r")\s?%", lambda m: _de_zahl(m.group(1)) + " Prozent", t)
    t = re.sub(r"(?<![\w$])(?:US)?\$\s?(" + _ZAHL + r")(" + _GROESSE + ")",
               lambda m: _de_zahl(m.group(1)) + m.group(2) + " Dollar", t)
    t = re.sub(r"(?<![\w.,])(" + _ZAHL + r")(" + _GROESSE + r")\s?\$",
               lambda m: _de_zahl(m.group(1)) + m.group(2) + " Dollar", t)
    return t


# ── Pruefen ──────────────────────────────────────────────────────────────────

def _volltext(a):
    return " ".join([a["titel"] + ".", a["anriss"]] + [x["text"] for x in a["absaetze"]])


def pruefe_text(a, quellen, dp, entities):
    """Harte Code-Pruefungen. Liefert die Liste der Verstoesse (leer = bestanden)."""
    fehler = []
    voll = _volltext(a)
    mat = " ".join(f"{q['medium']} {q['titel']} {q['text']}" for q in quellen)
    mat_l = mat.lower()

    if not a["titel"] or len(a["titel"]) > 100:
        fehler.append(f"Titel fehlt oder zu lang ({len(a['titel'])} Zeichen)")
    if not a["anriss"] or len(a["anriss"]) > 300:
        fehler.append(f"Anriss fehlt oder zu lang ({len(a['anriss'])} Zeichen)")
    if not 4 <= len(a["absaetze"]) <= 6:
        fehler.append(f"{len(a['absaetze'])} Absätze statt 4 bis 6")
    gueltig = {q["nr"] for q in quellen}
    for i, x in enumerate(a["absaetze"], 1):
        if not 120 <= len(x["text"]) <= 900:
            fehler.append(f"Absatz {i}: {len(x['text'])} Zeichen")
        if not x["quellen"] or not set(x["quellen"]) <= gueltig:
            fehler.append(f"Absatz {i}: Quellenangabe fehlt oder ungültig ({x['quellen']})")
    return fehler + _inhalt_fehler(voll, a["titel"], " ".join([a["anriss"]] + [x["text"] for x in a["absaetze"]]),
                                   mat, dp, entities)


def _inhalt_fehler(voll, titel, rest, mat, dp, entities):
    """Zeichen, Woerter, Zahlen, Namen, Personen und Entitaeten gegen das Material (aus pruefe_text, R4)."""
    fehler = []
    mat_l = mat.lower()
    for zeichen, name in (("—", "Gedankenstrich"), ("–", "Halbgeviertstrich"), (";", "Semikolon"),
                          ("!", "Ausrufezeichen"), ("#", "Hashtag")):
        if zeichen in voll:
            fehler.append(f"{name} im Text")
    vl = voll.lower()
    fehler += [f'Verbotswort "{w}"' for w in VERBOTEN if w in vl]
    if len(re.findall(WEICHMACHER, vl)) > 1:
        fehler.append("mehr als ein Weichmacher")
    if re.search(WIR, vl):
        fehler.append("Wir-Perspektive")

    # Zahlen, Daten, Rollen, Personen: dieselbe Pruefung wie fuer die Einordnungen
    for t in dp.pruefe({"title": titel, "summary": rest}, mat):
        fehler.append(f"{t['art']}: {t['befund']}")
    # Produkt-/Firmennamen mit Ziffer oder Binnen-Grossbuchstabe (GPT-6, DeepMind, H100). Deutsche
    # Kompositum-Endungen ("GPT-6-Modell", "H100-Chips") werden abgeschnitten, Bindestrich = Leerzeichen.
    mat_n = re.sub(r"[-\s]+", " ", mat_l)
    for tok in sorted(set(re.findall(r"[A-Za-zÄÖÜäöü0-9]+(?:[-.][A-Za-zÄÖÜäöü0-9]+)*", voll))):
        teile = tok.split("-")
        while len(teile) > 1 and re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]{2,}", teile[-1]):
            teile.pop()
        tok = "-".join(teile).rstrip(".")
        if not re.search(r"[A-Za-z]", tok) or not (re.search(r"\d", tok) or re.search(r"[a-z][A-Z]", tok)):
            continue
        if re.sub(r"[-\s]+", " ", tok.lower()) not in mat_n:
            fehler.append(f'Name "{tok}" nicht in den Quellen')
    # Personen mit Kontext-Label: "Vorname Nachname (Rolle)"
    for name in re.findall(r"\b([A-ZÄÖÜ][\w'-]+(?:\s+[A-ZÄÖÜ][\w'-]+){1,2})\s+\(", voll):
        if name.split()[-1].lower() not in mat_l:
            fehler.append(f'Person "{name}" nicht in den Quellen')
    for e in entities:
        # Aliasse sind Wortanfaenge ("rechenzentr|data cent"). 01.11.: Mit \b am Ende fand "data cent"
        # kein "data centers", der OpenAI-Entwurf scheiterte an "Rechenzentren".
        muster = [re.compile(r"(?i)\b(?:" + al + r")") for al in e.get("aliasse") or []]
        if any(m.search(voll) for m in muster) and not any(m.search(mat) for m in muster):
            fehler.append(f'Entität "{e.get("id")}" nicht in den Quellen')
    return fehler


def pruefe_blick(a, quellen, dp, entities):
    """R4: Kasten "Auf einen Blick" mit denselben Code-Pruefungen wie der Text. Liefert die Verstoesse.
    Der Kasten ist eine Zugabe: Ein Verstoss haelt nicht den Artikel an, der Aufrufer laesst den Kasten weg."""
    blick = a.get("blick") or []
    if not blick:
        return []
    fehler = []
    if not BLICK_MIN <= len(blick) <= BLICK_MAX:
        fehler.append(f"{len(blick)} Zeilen statt {BLICK_MIN} bis {BLICK_MAX}")
    gueltig = {q["nr"] for q in quellen}
    for i, x in enumerate(blick, 1):
        if not x["text"] or len(x["text"]) > BLICK_ZEICHEN:
            fehler.append(f"Zeile {i}: {len(x['text'])} Zeichen")
        if not re.search(r"\d", x["text"]):
            fehler.append(f"Zeile {i}: keine Zahl")
        if not x["quellen"] or not set(x["quellen"]) <= gueltig:
            fehler.append(f"Zeile {i}: Quellenangabe fehlt oder ungültig ({x['quellen']})")
    text = ". ".join(x["text"] for x in blick)
    mat = " ".join(f"{q['medium']} {q['titel']} {q['text']}" for q in quellen)
    # Die Deckungspruefung laesst einstellige Zahlen aus (im Fliesstext meist Aufzaehlung). Im Kasten ist
    # jede Zahl die Aussage ("Preis: 8 Dollar"), darum hier auch die einstelligen gegen das Material.
    for i, x in enumerate(blick, 1):
        for m in re.finditer(r"(?<![\w.,-])\d(?![\w-]|[.,]\d)", x["text"]):
            if not re.search(r"(?<![\d.,])" + m.group(0) + r"(?![\d]|[.,]\d)", mat):
                fehler.append(f"Zeile {i}: {m.group(0)} nicht im Quelltext")
    return fehler + _inhalt_fehler(text, "", text, mat, dp, entities)


def _jev(text, kontext, quellen_text, key):
    body = json.dumps({"model": "jev-latest",
                       "state": {"satz": text[:1500], "kontext": kontext[:2500], "quellen": quellen_text[:JEV_MAX_QUELLTEXT]},
                       "questions": {"gedeckt": _FRAGE_SATZ}}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.loads(r.read())["answers"]["gedeckt"]["noul"])


def _saetze(text):
    """Saetze; Kurzstuecke (z. B. nach "z. B.") haengen am vorigen Satz. Kein Schnitt nach
    Ziffer+Punkt: "bis zum 4. November 2026" wurde am 29.10. in zwei Saetze zerlegt."""
    out = []
    for s in re.split(r"(?<=[^\d\s][.!?])\s+(?=[A-ZÄÖÜ0-9„])", text.strip()):
        if out and len(s) < 25:
            out[-1] += " " + s
        elif s:
            out.append(s)
    return out


_STOPP = set("aber alle auch beim bereits damit dann dass dabei denn deren diese dieser dieses doch eine einem "
             "einen einer eines etwa gegen hatte haben jedoch kann laut mehr nach noch nicht nur oder rund sein "
             "seine seit sich sind soll sowie über unter viel vom von vor wird wurde zwei drei weil wenn wie "
             "zum zur zwischen dort hier dies diesem erst".split())


def _anker(satz, dp):
    """Was ein Beleg enthalten muss: Zahlen (mit Schreibvarianten), Namen, Inhaltswoerter."""
    zahlen = [dp._zahl_varianten(z) for z in dp._zahlen(satz)]
    namen = {w.lower() for w in re.findall(r"\b[A-Za-z][\w-]*(?:\d|[a-z][A-Z])[\w.-]*", satz)}
    # gross geschriebene Woerter ausser dem Satzanfang (Firmen, Produkte, Personen, Benchmarks)
    namen |= {w.lower() for w in re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]+\b", satz.split(" ", 1)[-1])
              if len(w) > 3 and w.lower() not in _STOPP}
    # Wortstamm (6 Zeichen): "Verfuegbarkeit" soll "verfuegbar" finden (30.10.: Heise-Satz "bald" verpasst)
    woerter = {w[:6] for w in re.findall(r"[a-zäöüß]{5,}", satz.lower()) if w not in _STOPP}
    # Woertliche Zitate zaehlen wie Zahlen (30.10.: „unsupported claims“ stand nur bei The Verge, die
    # Suche nahm wegen der vielen deutschen Woerter trotzdem Heise-Stellen)
    zahlen += [{z.strip().lower()} for z in re.findall(r"[„\"“]([^“”\"„]{3,60})[“”\"]", satz)]
    return zahlen, namen, woerter


def fundstelle(satz, quellen_liste, dp, vorher="", fenster=700, schritt=250, anzahl=3, bereiche=False):
    """Die Ausschnitte der genannten Quellen, die am meisten Zahlen/Namen/Woerter des Satzes
    enthalten (29.10.26, Daniels Entscheidung A). Jev fand wortgleiche Belege in 6.000 Zeichen
    Quelltext nicht zuverlaessig (Mistral: "62 Punkten" stand fast woertlich bei The Decoder,
    p=0,73). Mit dem passenden Ausschnitt muss es nur noch vergleichen, nicht suchen.
    vorher: der Satz davor, schwach gewichtet ("Das Modell liegt ... vorn" meint das Modell von
    eben). Liefert "" wenn kein Ausschnitt genug Treffer hat."""
    zahlen, namen, woerter = _anker(satz, dp)
    v_zahlen, v_namen, _ = _anker(vorher, dp) if vorher else ([], set(), set())
    kandidaten = []
    for q in quellen_liste:
        t = q["text"]
        for start in range(0, max(1, len(t) - fenster // 2), schritt):
            # Rand je 200 Zeichen: 30.10. endete der Ausschnitt kurz vor "in its European data centers"
            stueck = t[max(0, start - 200):start + fenster + 200]
            sl = stueck.lower()
            punkte = (3 * sum(any(v in stueck or v in sl for v in vs) for vs in zahlen)
                      + 2 * sum(n in sl for n in namen) + sum(w in sl for w in woerter)
                      + sum(any(v in stueck for v in vs) for vs in v_zahlen) + sum(n in sl for n in v_namen - namen))
            kandidaten.append((punkte, q["nr"], start, stueck))
    kandidaten.sort(key=lambda x: -x[0])
    if not kandidaten or kandidaten[0][0] < 4:
        return ""
    gewaehlt = []
    # Zwei Durchgaenge: erst der beste Ausschnitt JE QUELLE, dann weitere. 30.10.: Heise (16 Punkte)
    # belegte zwei der drei Plaetze, die Verge-Stelle mit dem woertlichen Zitat (12) fiel raus.
    for durchgang in (1, 2):
        for punkte, nr, start, stueck in kandidaten:
            if len(gewaehlt) >= anzahl or punkte < max(4, kandidaten[0][0] // 2):
                break
            if durchgang == 1 and any(nr == g[0] for g in gewaehlt):
                continue
            if any(nr == g[0] and abs(start - g[1]) < fenster for g in gewaehlt):
                continue                  # keine fast gleichen Ausschnitte doppelt
            gewaehlt.append((nr, start, stueck))
    if bereiche:                          # fuer pruefer_material: (Quelle, von, bis) zum Zusammenlegen
        return [(nr, max(0, start - 200), start + fenster + 200) for nr, start, _ in gewaehlt]
    nach_nr = {q["nr"]: q for q in quellen_liste}
    return "\n\n".join(f"[{nr}] {nach_nr[nr]['medium']}: …{stueck}…" for nr, start, stueck in gewaehlt)


# ── Pruefer-Modell (30.10.26, Daniels Entscheidung 1) ──────────────────────────
# Jev gab satzweise auch dann 0,1-0,6, wenn der Beleg fast woertlich im kurzen Ausschnitt stand
# (Gemini 30.10.: Exploitgym 0,62, "tagelang" 0,11). Jetzt entscheidet ein Sprachmodell: ein Aufruf
# je Artikel, je Absatz die Fundstellen, Antwort = Liste der NICHT gedeckten Aussagen. Leer = raus.
# Kette nur fuer Ausfaelle (Fehler, leer, kaputtes/unvollstaendiges JSON). Ein echtes Urteil
# "nicht gedeckt" ist endgueltig, es wird nicht beim naechsten Modell nachgefragt.
# Nemotron Ultra free (Daniels Wunsch) traegt laut ki_news.log die Uebersetzung (107 OK, 0x 429 im
# Log-Fenster 30.10.), als Pruefer aber ungemessen. Backup gemini-3.8-flash: Sieger der Oberklasse im
# Richter-Vergleich 02.10. (KIVault ox-analyse/MESSUNG_021026_Richter-Stabilitaet.md: 39/38 von 41,
# 0 Fehlurteile, 3 s). Reihenfolge nach tools/pruefer_vergleich.py (Workflow "Pruefer-Vergleich").
# 30.10. gemessen (Workflow "Pruefer-Vergleich", 2 echte Entwuerfe, 5 eingebaute Fehler x 2 Runden):
#   gemini-3.8-flash 10/10 (6 s, ~0,5 Cent/Artikel), claude-haiku-5.5 10/10 (13 s), gpt-6-luna 9/10,
#   qwen3.7-plus 9/10 (84 s), nemotron-3-ultra:free 7/10 - uebersah die vertauschte Zuordnung in beiden
#   Runden und hielt im Pipeline-Lauf 30.10. einen sauberen Artikel an ("halbiert" sei nicht dasselbe
#   wie "um das Zweifache reduziert"). Darum Gemini vorn, Haiku als Backup, Nemotron nicht.
PRUEFER_MODELLE = ["google/gemini-3.8-flash", "anthropic/claude-haiku-5.5"]
PRUEFER_BELEG_JE_ABSATZ = 8000            # 30.10.: 5000 schnitt den Verge-Beleg ab
_PRUEFER_SYSTEM = ("Du bist Faktenprüfer für eine deutsche Nachrichtenseite. Du prüfst Absätze ausschließlich gegen "
                   "die mitgelieferten Belegstellen (deutsch oder englisch). Kein Vorwissen benutzen.")


def _pruefer_reasoning(modell):
    # wie ki_news.py: Nemotron denkt sonst das Budget leer und liefert kaputtes JSON
    return {"enabled": False} if modell.startswith("nvidia/") else {"effort": "low", "exclude": True}


_SATZENDE = r"(?<=[^\d\s])[.!?][\"“”’)]?"   # wie _saetze: "4. November" ist kein Satzende


def _satzgrenzen(t, von, bis, rand=400):
    """Bereich auf ganze Saetze erweitern (je hoechstens rand Zeichen). 31.10.: Der Beleg endete bei
    TechCrunch mitten im Satz ("And Anthropic's planned…", "reached out to …"), Gemini meldete beide
    Aussagen als nicht gedeckt, obwohl sie im Quelltext standen."""
    von, bis = max(0, von), min(len(t), bis)
    if von:
        enden = [m.end() for m in re.finditer(_SATZENDE + r"\s", t[max(0, von - rand):von])]
        if enden:
            von = max(0, von - rand) + enden[-1]
    m = re.search(_SATZENDE + r"(?=\s|$)", t[bis:bis + rand])
    if m:
        bis += m.end()
    return von, bis


def pruefer_material(a, quellen, dp):
    """[(id, text, belege)] - P0 = Titel+Anriss (alle Quellen), P1.. = Absaetze (ihre Quellen)."""
    nach_nr = {q["nr"]: q for q in quellen}

    def belege(text, nrs, grenze=PRUEFER_BELEG_JE_ABSATZ):
        """Fundstellen aller Saetze, je Quelle ueberlappende Bereiche zusammengelegt. 30.10.: Ohne das
        belegten doppelte Ausschnitte den Platz, "European data centers" fiel hinter die Grenze."""
        liste = [nach_nr[n] for n in nrs if n in nach_nr]
        saetze = _saetze(text)
        roh = []
        for satz, vorher in zip(saetze, [""] + saetze[:-1]):
            roh += (fundstelle(satz, liste, dp, vorher, bereiche=True)
                    or fundstelle(text, liste, dp, anzahl=4, bereiche=True) or [])
        gemerged = []
        for nr, von, bis in sorted({(nr, *_satzgrenzen(nach_nr[nr]["text"], von, bis)) for nr, von, bis in roh}):
            if gemerged and gemerged[-1][0] == nr and von <= gemerged[-1][2]:
                gemerged[-1][2] = max(gemerged[-1][2], bis)
            else:
                gemerged.append([nr, von, bis])
        # Titel der Quellen: der Schreiber sieht sie im Prompt, der Pruefer sah sie nicht. 31.10.: "fast
        # 12 Stunden" stand bei Ars Technica nur in der Ueberschrift, Gemini hielt den Artikel an.
        titel = [f"[{q['nr']}] {q['medium']}, Titel: {q['titel']}" for q in liste if q.get("titel")]
        stellen = [f"[{nr}] {nach_nr[nr]['medium']}: {'…' if von else ''}{nach_nr[nr]['text'][von:bis]}"
                   f"{'…' if bis < len(nach_nr[nr]['text']) else ''}" for nr, von, bis in gemerged]
        return "\n".join(titel + stellen)[:grenze]

    kopf = f"{a['titel']}. {a['anriss']}"
    absaetze = [(f"P{i}", x["text"], belege(x["text"], x["quellen"])) for i, x in enumerate(a["absaetze"], 1)]
    # Titel/Anriss fassen den Artikel zusammen ("die Preisangaben widersprechen sich"): eigene
    # Fundstellen plus die aller Absaetze. 30.10.: Ohne das fehlten die Preise, Fehlalarm bei 4 Modellen.
    alles = " ".join([kopf] + [x["text"] for x in a["absaetze"]])
    # R4: jede Zeile des Kastens "Auf einen Blick" gegen die Belege ihrer Quellen
    blick = [(f"B{i}", x["text"], belege(x["text"], x["quellen"])) for i, x in enumerate(a.get("blick") or [], 1)]
    return [("P0", kopf, belege(alles, list(nach_nr), 2 * PRUEFER_BELEG_JE_ABSATZ))] + absaetze + blick


def pruefer_prompt(teile):
    return ("Prüfe jeden Absatz: Steht jede Tatsachenbehauptung (Zahl, Name, Rolle, Datum, Ereignis, Zuschreibung "
            "an eine Quelle wie \"laut Heise\") so oder sinngemäß in den Belegen DIESES Absatzes? Übersetzung und eigene "
            "Formulierung sind erlaubt. Einordnende Sätze (\"die Quellen widersprechen sich\") sind gedeckt, wenn die "
            "Belege das hergeben. Antworte NUR mit JSON: {\"<id>\": [\"zitierte nicht gedeckte Aussage: kurzer Grund\"], "
            "...}. Leere Liste, wenn alles gedeckt ist. Jede id muss vorkommen.\n\n"
            + "\n\n".join(f"### {i}\nAbsatz: {t}\nBelege:\n{b or '(keine Belegstelle gefunden)'}" for i, t, b in teile))


def pruefer_urteil(teile, modell, key):
    """{id: [nicht gedeckte Aussagen]} + Nutzungsdaten. ValueError, wenn die Antwort unbrauchbar ist."""
    p = pruefer_prompt(teile)
    try:
        roh = _anfrage(p, modell, key, _pruefer_reasoning(modell), _PRUEFER_SYSTEM, 0)
    except urllib.error.HTTPError as e:
        _fehlertext(e)
        if e.code != 400:
            raise
        roh = _anfrage(p, modell, key, None, _PRUEFER_SYSTEM, 0)
    wahl = (roh.get("choices") or [{}])[0]
    text = (wahl.get("message") or {}).get("content") or ""
    if isinstance(text, list):
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    try:
        urteil = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        raise ValueError(f"kein JSON (finish_reason={wahl.get('finish_reason')}, Anfang {text[:120]!r})")
    # R4: Fehlt eine Kastenzeile (B..), gilt das Urteil trotzdem, nur der Kasten faellt weg
    fehlt = [i for i, _, _ in teile if not isinstance(urteil.get(i), list) and not i.startswith("B")]
    if fehlt:
        raise ValueError(f"unvollständig, fehlt {fehlt}")
    return {i: ([_sauber(x) for x in urteil[i] if _sauber(x)] if isinstance(urteil.get(i), list)
                else ["vom Prüfer nicht beurteilt"]) for i, _, _ in teile}, roh.get("usage") or {}


def pruefe_llm(a, quellen, dp, key, modelle=None):
    """Liefert (fehler, info). Fehler leer = bestanden. Alle Modelle ausgefallen = nicht bestanden."""
    import time
    teile = pruefer_material(a, quellen, dp)
    info = {"ausfaelle": []}
    for modell in modelle or PRUEFER_MODELLE:
        start = time.time()
        try:
            urteil, usage = pruefer_urteil(teile, modell, key)
        except Exception as e:
            grund = f"{modell}: {type(e).__name__} {getattr(e, 'code', '')} {getattr(e, 'text', '') or e}"
            print(f"[RECHERCHE] Prüfer ausgefallen: {grund[:300]}")
            info["ausfaelle"].append(grund[:200])
            continue
        info.update(modell=modell, sekunden=round(time.time() - start, 1), kosten=usage.get("cost"))
        namen = {"P0": "Titel/Anriss"}
        fehler = [f"Prüfer: {namen.get(i, 'Absatz ' + i[1:])}: {x[:200]}" for i, liste in urteil.items()
                  if not i.startswith("B") for x in liste]
        kasten = [f"Zeile {i[1:]}: {x[:200]}" for i, liste in urteil.items() if i.startswith("B") for x in liste]
        if kasten:                       # R4: nur der Kasten faellt weg, der Artikel nicht
            a["blick"] = []
            info["blick_weg"] = kasten
            print(f"[RECHERCHE] Kasten Auf einen Blick faellt weg (Prüfer): {kasten[:3]}")
        return fehler, info
    return ["Prüfer: kein Modell lieferte ein Urteil"], info


def pruefe_jev(a, quellen, key, dp=None):
    """Jev je SATZ gegen die vollstaendigen Quellen seines Absatzes (Titel+Anriss: alle Quellen).
    Liefert (fehler, werte).

    29.10.26, erster echter Artikel (Gemini 4 Carbon): Je Absatz lag Jev bei 0,14-0,73, obwohl
    jede geprueft Aussage in den Quellen stand. Zwei Gruende: Der Quelltext wurde bei 12.000
    Zeichen gekappt (Absatz 1 nannte 6 Quellen a 3.000, Heise mit "vier Wochen" fehlte), und ein
    dichter Absatz mit fuenf Zahlen aus drei Quellen bekommt bei der kleinsten Unsicherheit einen
    niedrigen Wert. Satzweise sieht Jev genau das Material, das auch das Schreibmodell hatte,
    und der Pruefbericht nennt den Satz, der nicht gedeckt ist. Schwelle bleibt JEV_SCHWELLE.
    Ab PRUEFUNG_VERSION 3 (Daniels Entscheidung A): statt ganzer Quellen nur die Fundstelle
    (siehe fundstelle()); satzweise mit ganzen Quellen fand Jev woertliche Belege nicht."""
    if not key:
        return ["Jev: kein TYPESAFE_API_KEY"], []
    nach_nr = {q["nr"]: q for q in quellen}

    def qtext(nrs):
        return "\n\n".join(f"[{n}] {nach_nr[n]['medium']}: {nach_nr[n]['titel']}. {nach_nr[n]['text']}"
                           for n in nrs if n in nach_nr)

    def belege(satz, vorher, absatz, nrs):
        """Fundstelle des Satzes; ohne eigene Zahlen/Namen (reine Einordnung wie "Hier
        widersprechen sich die Quellen") die Fundstellen des ganzen Absatzes; sonst alles."""
        if dp is not None:
            liste = [nach_nr[n] for n in nrs if n in nach_nr]
            fs = fundstelle(satz, liste, dp, vorher) or fundstelle(absatz, liste, dp, anzahl=4)
            if fs:
                return fs
        return qtext(nrs)

    def zerlegt(text):
        s = _saetze(text)
        return zip(s, [""] + s[:-1])

    kopf = f"{a['titel']}. {a['anriss']}"
    teile = [("Titel/Anriss", s, kopf, belege(s, v, kopf, list(nach_nr))) for s, v in zerlegt(kopf)]
    for i, x in enumerate(a["absaetze"], 1):
        teile += [(f"Absatz {i}", s, x["text"], belege(s, v, x["text"], x["quellen"]))
                  for s, v in zerlegt(x["text"])]
    if len(teile) > JEV_MAX_AUFRUFE:
        return [f"Jev: {len(teile)} Sätze, mehr als {JEV_MAX_AUFRUFE} Prüfungen"], []
    fehler, werte = [], []
    for name, satz, kontext, qt in teile:
        try:
            p = _jev(satz, kontext, qt, key)
        except Exception as e:
            return fehler + [f"Jev nicht erreichbar ({type(e).__name__})"], werte
        werte.append(round(p, 2))
        if p < JEV_SCHWELLE:
            fehler.append(f'Jev: {name} nicht gedeckt (p={p:.2f}): "{satz[:140]}"')
    return fehler, werte


# ── Seite ────────────────────────────────────────────────────────────────────

_CSS_EXTRA = """
.kicker{font-size:.8125rem;color:var(--akzent);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
sup a{text-decoration:none;font-size:.75em;margin-left:1px}
ol.quellen{padding-left:1.25rem;font-size:.9375rem}
ol.quellen li{margin:.35rem 0}
.offiziell{border:1px solid var(--linie);border-radius:4px;padding:.9rem 1rem;margin:1.5rem 0}
.offiziell h2{margin-top:0}
.pruefung{background:var(--grund);border:1px solid var(--linie);border-radius:4px;padding:.75rem 1rem;font-size:.875rem}
.entwurf{border:2px solid #b45309;border-radius:4px;padding:.75rem 1rem;margin-bottom:1.25rem;font-size:.9375rem}
.yt{margin:0 0 1rem}
ol.zeitleiste{list-style:none;margin:1rem 0 1.5rem .35rem;padding:0 0 0 1.25rem;border-left:2px solid var(--linie)}
ol.zeitleiste li{position:relative;margin:0 0 1rem;font-size:.9375rem}
ol.zeitleiste li::before{content:"";position:absolute;left:calc(-1.25rem - 6px);top:.3rem;width:10px;height:10px;border-radius:50%;background:var(--akzent)}
ol.zeitleiste time{display:block;font-size:.8125rem;font-weight:600;color:var(--akzent)}
ol.zeitleiste .meta{display:block;margin:0;font-size:.8125rem}
.blick{border-left:3px solid var(--akzent);background:var(--grund);border-radius:0 4px 4px 0;padding:.65rem 1rem;margin:1rem 0 1.25rem}
.blick h2{margin:0 0 .35rem;font-size:1rem}
.blick ul{margin:0;padding-left:1.1rem}
.blick li{margin:.2rem 0;font-size:.9375rem}
figure figcaption{font-size:.75rem;color:var(--grau);margin-top:.3rem}
ol.quellen.kompakt{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:.25rem 1.1rem;font-size:.875rem}
ol.quellen.kompakt li{margin:0}
ol.quellen.kompakt .nr{color:var(--grau)}
.pruefung.klein{font-size:.8125rem;padding:.5rem .75rem}
""".strip()


_CSS_LISTE = """
ul.recherchen{list-style:none;padding:0;margin:1.5rem 0}
ul.recherchen li{border-top:1px solid var(--linie);padding:1rem 0}
ul.recherchen .meta{margin:0}
ul.recherchen h2{margin:.25rem 0 .35rem}
ul.recherchen h2 a{color:var(--tinte);text-decoration:none}
ul.recherchen h2 a:hover{color:var(--akzent)}
ul.recherchen p.text{margin:0}
""".strip()


def _youtube_id(u):
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})", u or "")
    return m.group(1) if m else ""


def rendere(a, k, quellen, karte, slug, stand, entwurf, bericht, erschienen=None, vermerk=""):
    """erschienen: Zeitpunkt der ersten Fassung (bei einer Erweiterung), vermerk: "Aktualisiert ..."."""
    esc = html.escape
    rep, r = k["rep"], k["release"]
    pfad = f"/recherche/{slug}.html"
    url = SITE + pfad
    bild = rep.get("image_local_gross") or rep.get("image_local") or (r or {}).get("poster") or ""
    bild_klein, bild_von = bild, ""
    if FORMAT_R4:
        bild, bild_klein, bild_von = bild_zur_story(k, quellen)
    robots = "noindex, nofollow" if entwurf else "index, follow, max-image-preview:large"
    n_medien = sum(1 for q in quellen if not q["hersteller"])
    erschienen = erschienen or stand
    datum = erschienen[:10]
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": a["titel"][:110],
          "description": a["anriss"][:200], "inLanguage": "de", "datePublished": erschienen, "dateModified": stand,
          "mainEntityOfPage": url, "isBasedOn": [q["link"] for q in quellen if q.get("link")],
          "author": {"@type": "Organization", "name": "KI News", "url": SITE + "/"},
          "publisher": {"@type": "Organization", "name": "KI News", "url": SITE + "/",
                        "logo": {"@type": "ImageObject", "url": SITE + "/s-logo.png"}}}
    if bild:
        ld["image"] = [bild]
    ld_txt = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    teile = [
        "<!DOCTYPE html>", '<html lang="de">', "<head>", '<meta charset="utf-8"/>',
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
        f"<title>{esc(a['titel'])} · KI News</title>",
        f'<meta name="description" content="{esc(a["anriss"][:200])}"/>',
        f'<meta name="robots" content="{robots}"/>',
    ]
    if not entwurf:
        teile.append(f'<link rel="canonical" href="{url}"/>')
    teile += [
        '<link rel="icon" type="image/png" href="/s-logo.png"/>',
        '<meta property="og:type" content="article"/>',
        f'<meta property="og:title" content="{esc(a["titel"])}"/>',
        f'<meta property="og:description" content="{esc(a["anriss"][:200])}"/>',
        f'<meta property="og:url" content="{url}"/>', '<meta property="og:locale" content="de_DE"/>',
    ]
    if bild:
        teile += [f'<meta property="og:image" content="{esc(bild)}"/>',
                  '<meta name="twitter:card" content="summary_large_image"/>']
    teile += [
        '<meta name="twitter:site" content="@ScampyKI"/>',
        '<link rel="preload" href="/assets/fonts/Fraunces-Variable.woff2" as="font" type="font/woff2" crossorigin/>',
        '<link rel="preload" href="/assets/fonts/WorkSans-Variable.woff2" as="font" type="font/woff2" crossorigin/>',
        '<link rel="stylesheet" href="/assets/ki-fonts.css"/>',
        ms._ICONS,
        f"<script>{ms._THEME_JS}</script>",
        f"<style>{ms._CSS}\n{_CSS_EXTRA}</style>",
        f'<script type="application/ld+json">{ld_txt}</script>',
        "</head>", "<body>",
        ms._KOPF,
        "<main>", "<article>",
    ]
    if entwurf:
        teile.append('<div class="entwurf"><strong>Entwurf, nicht veröffentlicht.</strong> Die automatische '
                     'Prüfung hat diesen Text angehalten:<ul>' +
                     "".join(f"<li>{esc(b)}</li>" for b in bericht) + "</ul></div>")
    teile += [
        f'<p class="kicker">Recherche · ' + ("Laufender Fall · " if k.get("linie") else "")
        + f'{n_medien} Quellen' + (" + Herstellerseite" if r else "") + "</p>",
        f'<p class="meta"><time datetime="{datum}">{ms._datum_de(datum)}</time>'
        + (f" · {esc(vermerk)}" if vermerk else "") + "</p>",
        f"<h1>{esc(a['titel'])}</h1>",
        f'<p class="anriss">{esc(a["anriss"])}</p>',
    ]
    vg = k.get("vorgaenger_info") or {}
    if vg.get("pfad"):
        teile.append(f'<p class="quelle">Vorgeschichte: <a href="{esc(vg["pfad"])}">{esc(vg.get("titel") or "")}</a></p>')
    blick = (a.get("blick") or []) if FORMAT_R4 else []
    if blick:
        # R4: Zahlen und Nummern kommen aus dem geprueften Artikel (pruefe_blick, Pruefer B1..)
        teile.append('<aside class="blick"><h2>Auf einen Blick</h2><ul>' + "".join(
            f"<li>{esc(x['text'])}" + "".join(f'<sup><a href="#q{n}">[{n}]</a></sup>' for n in x["quellen"])
            + "</li>" for x in blick) + "</ul></aside>")
    video = (karte or {}).get("mp4_url") or ""
    if video:
        p = (karte or {}).get("poster_url") or ""
        pp = f' poster="{esc(p)}"' if p else ""
        # Kartenformat: width/height reservieren den Platz, bis das Poster geladen ist. Sonst springt
        # der Text darunter beim ersten Aufruf weg (Layout-Sprung 0,22).
        teile.append(f'<figure><video controls playsinline preload="none" width="840" height="1320"{pp}>'
                     f'<source src="{esc(video)}" type="video/mp4"/></video></figure>')
    elif bild and FORMAT_R4:
        # R4: 640er als src, weil er dauerhaft bleibt. Fehlt der 1600er spaeter, faellt das Bild auf src zurueck.
        ss = (f' srcset="{esc(bild_klein)} 640w, {esc(bild)} 1600w" sizes="(max-width: 46rem) 100vw, 46rem"'
              ' onerror="this.onerror=null;this.removeAttribute(\'srcset\')"') if bild != bild_klein else ""
        cap = f"<figcaption>Bild: {esc(bild_von)}</figcaption>" if bild_von else ""
        teile.append(f'<figure><img src="{esc(bild_klein)}"{ss} alt="" loading="lazy"/>{cap}</figure>')
    elif bild:
        teile.append(f'<figure><img src="{esc(bild)}" alt="" loading="lazy"/></figure>')
    for x in a["absaetze"]:
        belege = "".join(f'<sup><a href="#q{n}">[{n}]</a></sup>' for n in x["quellen"])
        teile.append(f"<p>{esc(x['text'])}{belege}</p>")

    if r and r.get("url"):
        teile.append('<section class="offiziell">')
        teile.append(f"<h2>Offiziell von {esc(r.get('hersteller') or 'Hersteller')}</h2>")
        yt = _youtube_id(r.get("video_url"))
        if yt:
            teile.append(f'<div class="yt" data-yt="{esc(yt)}"></div>')
        elif (r.get("video_url") or "").startswith("https://"):
            pp = f' poster="{esc(r["poster"])}"' if (r.get("poster") or "").startswith("https://") else ""
            teile.append(f'<figure><video controls playsinline preload="none"{pp}>'
                         f'<source src="{esc(r["video_url"])}"/></video></figure>')
        teile.append(f'<p><a href="{esc(r["url"])}" rel="noopener" target="_blank">'
                     f'{esc(r.get("titel") or r.get("titel_en") or r["url"])}</a></p>')
        if (r.get("x_url") or "").startswith("https://x.com/"):
            teile.append(f'<blockquote class="twitter-tweet"><a href="{esc(r["x_url"])}">'
                         f'Beitrag von {esc(r.get("hersteller") or "")} auf X</a></blockquote>')
        teile.append("</section>")

    leiste = k.get("zeitleiste") or []
    if len(leiste) >= 2:
        # R3: Zeitleiste aus den Ereignissen der Linie. Titel, Datum und Medium kommen aus news.json und
        # archive.json (wie im Dossier), nicht vom Sprachmodell.
        teile.append('<section class="verlauf"><h2>So hat sich der Fall entwickelt</h2><ol class="zeitleiste">')
        for e in leiste:
            t = esc(e["t"])
            if e["l"].startswith("https://"):
                t = f'<a href="{esc(e["l"])}" rel="noopener" target="_blank">{t}</a>'
            teile.append(f'<li><time datetime="{esc(e["d"])}">{ms._datum_de(e["d"])}</time>{t}'
                         + (f'<span class="meta">{esc(e["q"])}</span>' if e["q"] else "") + "</li>")
        teile.append("</ol></section>")

    teile.append("<h2>Quellen</h2>")
    if FORMAT_R4:
        # R4: eine Zeile wie bei Notebookcheck, der Titel steht im title-Attribut
        teile.append('<ol class="quellen kompakt">' + "".join(
            f'<li id="q{q["nr"]}"><span class="nr">[{q["nr"]}]</span> <a href="{esc(q["link"] or "")}" '
            f'title="{esc(q["titel"])}" rel="noopener" target="_blank">{esc(q["medium"])}</a></li>'
            for q in quellen) + "</ol>")
    else:
        teile.append('<ol class="quellen">' + "".join(
            f'<li id="q{q["nr"]}">{esc(q["medium"])}: <a href="{esc(q["link"] or "")}" rel="noopener" '
            f'target="_blank">{esc(q["titel"])}</a></li>' for q in quellen) + "</ol>")
    if rep.get("seite"):
        teile.append(f'<p class="quelle">Zur Kurzmeldung: <a href="{esc(rep["seite"])}">{esc(ms._titel(rep))}</a></p>')
    teile.append("</article>")
    if FORMAT_R4:
        teile.append(
            '<p class="pruefung klein">So entsteht dieser Text: Ein Sprachmodell fasst die verlinkten Quellen '
            'zusammen. Vorher prüft die Automatik, dass jede Zahl, jedes Datum und jeder Name in einer Quelle steht '
            'und jeder Absatz von seinen Quellen gedeckt ist. Maßgeblich sind die Originalquellen.</p>')
    else:
        teile.append(
            '<p class="pruefung">So entsteht dieser Text: Ein Sprachmodell hat die oben verlinkten Quellen '
            'zusammengefasst. Vor der Veröffentlichung wurde automatisch geprüft, dass jede Zahl, jedes Datum '
            'und jeder Name in mindestens einer Quelle steht und dass jeder Absatz durch die genannten Quellen '
            'gedeckt ist. Fehler sind trotzdem möglich, maßgeblich sind die Originalquellen.</p>')
    teile += [
        "</main>",
        ms._FUSS,
        '<script src="/assets/ki-embed.js"></script>',
        "<script>(function(){if(!window.KIEmbed)return;document.querySelectorAll('[data-yt]').forEach("
        "function(el){el.innerHTML=KIEmbed.youtube(el.getAttribute('data-yt'),{label:'VIDEO'});});})();</script>",
        "</body>", "</html>", "",
    ]
    return "\n".join(teile)


def sitemap(register):
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    daten = [e.get("aktualisiert") or e["datum"] for e in register.values() if e.get("status") == "veroeffentlicht"]
    if daten:
        zeilen.append(f"  <url><loc>{SITE}/recherche/</loc><lastmod>{max(daten)}</lastmod></url>")
    for e in sorted(register.values(), key=lambda x: x["pfad"]):
        if e.get("status") == "veroeffentlicht":
            zeilen.append(f"  <url><loc>{SITE}{e['pfad']}</loc>"
                          f"<lastmod>{e.get('aktualisiert') or e['datum']}</lastmod></url>")
    zeilen += ["</urlset>", ""]
    ms._schreiben_wenn_neu(ORDNER / "sitemap.xml", "\n".join(zeilen))


def uebersicht(register):
    """recherche/index.html: die veroeffentlichten Artikel, neueste zuerst. Entwuerfe stehen hier nie."""
    esc = html.escape
    fertig = sorted((e for e in register.values() if e.get("status") == "veroeffentlicht"),
                    key=lambda e: e.get("stand_aktualisiert") or e.get("stand") or e.get("datum") or "", reverse=True)
    beschreibung = ("Hintergrundtexte zu Nachrichten, über die mehrere Medien berichtet haben. "
                    "Jeder Text nennt seine Quellen.")
    zeilen = []
    for e in fertig:
        medien = len(e.get("medien") or [])
        quellen = e.get("quellen") or 0
        meta = f'<time datetime="{esc(e["datum"][:10])}">{ms._datum_de(e["datum"])}</time> · '
        meta += f"{medien} Quellen + Herstellerseite" if 0 < medien < quellen else f"{quellen} Quellen"
        if e.get("aktualisiert"):
            meta += f' · aktualisiert am {ms._datum_de(e["aktualisiert"])}'
        zeilen.append(f'<li><p class="meta">{meta}</p><h2><a href="{esc(e["pfad"])}">{esc(e["titel"])}</a></h2>'
                      f'<p class="text">{esc(e.get("anriss") or "")}</p></li>')
    seite = [
        "<!DOCTYPE html>", '<html lang="de">', "<head>", '<meta charset="utf-8"/>',
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
        "<title>Recherche · KI News</title>",
        f'<meta name="description" content="{beschreibung}"/>',
        '<meta name="robots" content="index, follow"/>',
        f'<link rel="canonical" href="{SITE}/recherche/"/>',
        '<link rel="icon" type="image/png" href="/s-logo.png"/>',
        '<meta property="og:type" content="website"/>',
        '<meta property="og:title" content="Recherche · KI News"/>',
        f'<meta property="og:description" content="{beschreibung}"/>',
        f'<meta property="og:url" content="{SITE}/recherche/"/>', '<meta property="og:locale" content="de_DE"/>',
        '<meta name="twitter:site" content="@ScampyKI"/>',
        '<link rel="preload" href="/assets/fonts/Fraunces-Variable.woff2" as="font" type="font/woff2" crossorigin/>',
        '<link rel="preload" href="/assets/fonts/WorkSans-Variable.woff2" as="font" type="font/woff2" crossorigin/>',
        '<link rel="stylesheet" href="/assets/ki-fonts.css"/>',
        ms._ICONS,
        f"<script>{ms._THEME_JS}</script>",
        f"<style>{ms._CSS}\n{_CSS_EXTRA}\n{_CSS_LISTE}</style>",
        "</head>", "<body>", ms._KOPF, "<main>",
        "<h1>Recherche</h1>",
        f'<p class="anriss">{beschreibung}</p>',
        '<ul class="recherchen">' + "".join(zeilen) + "</ul>" if zeilen
        else "<p>Noch keine Recherche veröffentlicht.</p>",
        '<p class="pruefung">So entstehen diese Texte: Ein Sprachmodell fasst die im Artikel verlinkten Quellen '
        'zusammen. Vor der Veröffentlichung wird automatisch geprüft, dass jede Zahl, jedes Datum und jeder Name '
        'in mindestens einer Quelle steht und dass jeder Absatz durch die genannten Quellen gedeckt ist. Fehler '
        'sind trotzdem möglich, maßgeblich sind die Originalquellen.</p>',
        "</main>", ms._FUSS, "</body>", "</html>", "",
    ]
    ms._schreiben_wenn_neu(ORDNER / "index.html", "\n".join(seite))


def oeffentliche_listen(register):
    """Uebersicht und Sitemap. Laeuft auch ohne neuen Artikel, ein Fehler hier kostet keinen Artikel."""
    if not register:
        return
    try:
        sitemap(register)
        uebersicht(register)
    except Exception as e:
        print(f"[RECHERCHE] Uebersicht/Sitemap: {type(e).__name__} {e}")


# ── Ablauf ───────────────────────────────────────────────────────────────────

def erweitere(e, k, artikel, quellen, fehler, bestanden, modell, pinfo, jev_werte, stand, heute, dry_run=False):
    """Erweiterung eines veroeffentlichten Artikels (e = sein Registereintrag, wird geaendert).
    Bestanden: gleiche Adresse, alte Fassung nach e["versionen"]. Sonst bleibt die Seite, wie sie ist."""
    slug = k["update"]
    neu = [q["medium"] for q in quellen if q.get("neu")]
    vermerk = f"Aktualisiert am {ms._datum_de(heute)}, weitere Quellen: {', '.join(neu)}"
    seite = rendere(artikel, k, quellen, karte_zur_story(k), slug, stand, not bestanden,
                    fehler or ["Testlauf mit --nur-entwurf"], erschienen=e.get("stand") or e.get("datum"),
                    vermerk=vermerk)
    ziel = (ORDNER / f"{slug}.html") if bestanden else (ENTWURF_DIR / f"recherche-{slug}-update.html")
    print(f"[RECHERCHE] Erweiterung {'veroeffentlicht' if bestanden else 'entwurf'}: "
          f"{ziel.relative_to(BASE).as_posix()} (+{len(neu)} Medien: {', '.join(neu)}, {len(quellen)} Quellen)")
    if dry_run:
        print(json.dumps(artikel, ensure_ascii=False, indent=1))
        return
    ms._schreiben_wenn_neu(ziel, seite)
    if k.get("linie"):
        e["linie"] = k["linie"]          # R3: ab jetzt haengt der Artikel an der Linie
    if not bestanden:
        e["fehlversuch"] = {"datum": heute, "medien": k["neu"], "gruende": fehler,
                            "pfad": f"/artikel/entwurf/recherche-{slug}-update.html"}
        return
    e["versionen"] = (e.get("versionen") or []) + [
        {f: e.get(f) for f in ("datum", "aktualisiert", "titel", "anriss", "quellen", "modell", "links", "artikel")}]
    e.update(titel=artikel["titel"], anriss=artikel["anriss"], artikel=artikel, aktualisiert=heute,
             quellen=len(quellen), medien=[q["medium"] for q in quellen if not q["hersteller"]],
             links=sorted(set(k["links"]) | set(e.get("links") or [])), modell=modell, pruefer=pinfo,
             jev=jev_werte, gruende=[], pruefung=PRUEFUNG_VERSION, stand_aktualisiert=stand,
             quellen_links=[q["link"] for q in quellen if q.get("link")])
    if k.get("medien_linie"):
        e["medien_linie"] = k["medien_linie"]
    e.pop("fehlversuch", None)


def entwurf_fortschreiben(e, k, artikel, quellen, fehler, bestanden, modell, pinfo, jev_werte, stand, heute,
                          dry_run=False):
    """R3: Ein Entwurf derselben Linie wird mit allen Quellen neu geschrieben, unter derselben Adresse.
    Bestanden: wird veroeffentlicht (recherche/<slug>.html). Sonst ersetzt der neue Entwurf den alten,
    und der naechste Versuch braucht wieder UPDATE_MIN_NEUE_MEDIEN weitere Medien (medien_linie).
    Die alte Fassung kommt nach e["versionen"]."""
    slug = k["update"]
    weitere = {m.lower() for m in k.get("neu") or []}
    neu = [q["medium"] for q in quellen if q["medium"].lower() in weitere]
    seite = rendere(artikel, k, quellen, karte_zur_story(k), slug, stand, not bestanden,
                    fehler or ["Testlauf mit --nur-entwurf"])
    ziel = (ORDNER / f"{slug}.html") if bestanden else (ENTWURF_DIR / f"recherche-{slug}.html")
    print(f"[RECHERCHE] Entwurf fortgeschrieben, {'veroeffentlicht' if bestanden else 'weiter Entwurf'}: "
          f"{ziel.relative_to(BASE).as_posix()} (+{len(neu)} Medien" + (f": {', '.join(neu)}" if neu else "")
          + f", {len(quellen)} Quellen)")
    if dry_run:
        print(json.dumps(artikel, ensure_ascii=False, indent=1))
        return
    ms._schreiben_wenn_neu(ziel, seite)
    e["versionen"] = (e.get("versionen") or []) + [
        {f: e.get(f) for f in ("datum", "aktualisiert", "status", "titel", "anriss", "quellen", "modell",
                               "links", "gruende", "artikel")}]
    e.update(titel=artikel["titel"], anriss=artikel["anriss"], artikel=artikel, aktualisiert=heute,
             quellen=len(quellen), medien=[q["medium"] for q in quellen if not q["hersteller"]],
             medien_linie=k.get("medien_linie") or [], links=sorted(set(k["links"]) | set(e.get("links") or [])),
             modell=modell, pruefer=pinfo, jev=jev_werte, gruende=fehler, pruefung=PRUEFUNG_VERSION, stand=stand,
             quellen_links=[q["link"] for q in quellen if q.get("link")])
    if k.get("linie"):
        e["linie"] = k["linie"]
    if bestanden:
        # Erscheinungsdatum = heute (Uebersicht, Sitemap, KETTE_MAX_TAGE). "aktualisiert" faellt weg,
        # sonst zaehlte der Artikel im Tageslimit doppelt. Das Datum des Entwurfs steht in versionen.
        e.update(status="veroeffentlicht", pfad=f"/recherche/{slug}.html", datum=heute)
        e.pop("aktualisiert", None)
    e.pop("fehlversuch", None)


def _x_schatten(k, mit_text, dp, xs):
    """Plan R1: misst, was X-Belege an den Textquellen aendern wuerden, und schreibt es nur ins Log.
    Fehler und Zeitgrenze blockieren nie (I8)."""
    try:
        import x_belege
        if xs.get("ende") is None:
            xs["ende"] = time.monotonic() + X_SCHATTEN_ZEIT_S
            xs["themen"] = _lade(BASE / "themenketten.json", {})
        if time.monotonic() > xs["ende"]:
            print(f"[RECHERCHE] X-Schatten {k['sid']}: Zeitgrenze {X_SCHATTEN_ZEIT_S} s erreicht")
            return
        erg = x_belege.sammeln(k, xs["themen"], os.environ.get("HUGGINGNEWS_API_KEY", "").strip(),
                               dp, _quelltext, xs["ende"], xs["cache"])
        print(x_belege.logzeile(k["sid"], erg, mit_text,
                                x_belege.bewertung(erg, mit_text, MIN_TEXTQUELLEN, dp.MIN_QUELLTEXT)))
    except Exception as e:
        print(f"[RECHERCHE] X-Schatten {k.get('sid')}: Fehler {type(e).__name__}, weiter ohne")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", help="nur diese story_id (Test)")
    ap.add_argument("--nur-entwurf", action="store_true", help="auch bestandene Texte nur als Entwurf")
    ap.add_argument("--dry-run", action="store_true", help="nichts schreiben, nur berichten")
    args = ap.parse_args()
    if not RECHERCHE_AKTIV:
        print("[RECHERCHE] aus (RECHERCHE_AKTIV = False)")
        return 0
    key = os.environ.get("OPENROUTER_KEY", "").strip()
    jev_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        print("[RECHERCHE] kein OPENROUTER_KEY, nichts zu tun")
        return 0

    news_doc = _lade(BASE / "news.json", {})
    news = news_doc.get("news") or []
    linien = news_doc.get("linien") or {}
    releases = _lade(BASE / "hersteller.json", {}).get("releases") or []
    entities = _lade(BASE / "entities.json", {}).get("entities") or []
    register = _lade(REGISTER, {})
    if not args.dry_run:
        oeffentliche_listen(register)
    jetzt = datetime.now(timezone.utc).replace(microsecond=0)
    heute = jetzt.astimezone(BERLIN).strftime("%Y-%m-%d")
    frei = MAX_PRO_TAG - heute_verbraucht(register, heute)
    if frei <= 0 and not args.story:
        print(f"[RECHERCHE] Tageslimit {MAX_PRO_TAG} erreicht")
        return 0

    dp = _deckung()
    kand = kandidaten(news, releases, register, args.story)
    archiv = _lade(BASE / "archive.json", [])
    erw = [] if args.story else erweiterungen(news, archiv if isinstance(archiv, list) else [],
                                               releases, register, heute)
    if KETTEN in ("schatten", "an") and not args.story:
        try:
            zug, familie = linien_zuordnung(news, linien, _lade(BASE / "themenketten.json", {}))
            plan = linien_plan(news, linien, releases, register, heute, zug, familie,
                               archiv if isinstance(archiv, list) else [])
        except Exception as e:          # I8: R3 darf den Schritt nie aufhalten
            print(f"[RECHERCHE] Ketten: Fehler {type(e).__name__}, weiter ohne")
            plan = None
        if plan is not None and KETTEN == "schatten":
            for zeile in ketten_logzeilen(plan, kand, erw, register, zug):
                print(zeile)
        elif plan is not None:
            # Storys und Erweiterungen, die zu einer Linie gehoeren, laufen nur noch ueber die Linie.
            # Laufende Faelle zuerst (Daniel 10.11.), je Linie hoechstens einmal am Tag.
            vergeben = {p["slug"] for p in plan if p["slug"]}
            lk = [p["kandidat"] for p in plan if p["kandidat"]]
            for zeile in ketten_logzeilen(plan, kand, erw, register, zug):
                print(zeile.replace("Ketten-Schatten", "Kette").replace("wuerde ", ""))
            kand = lk + [k for k in kand if not _in_linie(k, zug)]
            erw = [k for k in erw if not _in_linie(k, zug) and k["update"] not in vergeben]
    print(f"[RECHERCHE] {len(kand)} Kandidaten (>= {MIN_QUELLEN} Medien oder Herstellerseite + "
          f"{MIN_QUELLEN_MIT_HERSTELLER}), {len(erw)} Erweiterungen "
          f"({', '.join(k['update'][:40] + ' +' + '/'.join(k['neu']) for k in erw)}), frei heute: {frei}")
    versucht = 0
    xs = {"ende": None, "cache": {}}   # X-Schatten (Plan R1), ein Zeitbudget je Lauf
    for k in kand + erw:                 # neue Storys zuerst
        if versucht >= (1 if args.story else min(MAX_PRO_LAUF, frei)):
            break
        quellen = material(k, dp)
        mit_text = sum(1 for q in quellen if q["hat_text"])
        if X_BELEGE == "schatten":
            _x_schatten(k, mit_text, dp, xs)
        if mit_text < MIN_TEXTQUELLEN:
            print(f"[RECHERCHE] {k['sid']} uebersprungen: nur {mit_text} Quellen mit Text "
                  f"({ms._titel(k['rep'])[:60]})")
            continue
        versucht += 1
        alt = register[k["update"]] if k.get("update") else None
        # Ein Entwurf (R3) wird frisch geschrieben: Sein Text hat die Pruefung nicht bestanden.
        p = prompt(quellen, alt.get("artikel") if alt and alt.get("status") == "veroeffentlicht" else None,
                   fall=bool(k.get("linie")))
        artikel, fehler, modell, jev_werte, pinfo = None, ["kein Modell lieferte Text"], "", [], {}
        for modell in MODELLE[:MAX_SCHREIBVERSUCHE]:
            try:
                artikel = schreibe(p, modell, key)
            except Exception as e:
                print(f"[RECHERCHE] {modell}: {type(e).__name__} {getattr(e, 'code', '')} {getattr(e, 'text', '')}".rstrip())
                artikel, fehler = None, [f"{modell}: {type(e).__name__}"]
                continue
            fehler = pruefe_text(artikel, quellen, dp, entities)
            print(f"[RECHERCHE] {modell}: {len(fehler)} Verstoesse {fehler[:4]}")
            kasten = pruefe_blick(artikel, quellen, dp, entities)
            if kasten:                   # R4: nur der Kasten faellt weg
                artikel["blick"] = []
                print(f"[RECHERCHE] {modell}: Kasten Auf einen Blick faellt weg {kasten[:4]}")
            if not fehler:
                break
        if artikel and not fehler:
            fehler, pinfo = pruefe_llm(artikel, quellen, dp, key)
            print(f"[RECHERCHE] Prüfer {pinfo.get('modell')} ({pinfo.get('sekunden')} s, {pinfo.get('kosten')} $) -> "
                  f"{'bestanden' if not fehler else fehler}")
            if jev_key:                   # Jev nur noch zum Vergleich, entscheidet nicht (30.10.)
                jev_fehler, jev_werte = pruefe_jev(artikel, quellen, jev_key, dp)
                print(f"[RECHERCHE] Jev (Schatten) {jev_werte}: {len(jev_fehler)} Saetze unter {JEV_SCHWELLE}")
        if not artikel or not artikel["titel"]:
            print(f"[RECHERCHE] {k['sid']}: kein verwertbarer Text, {fehler}")
            if alt and not args.dry_run:
                alt["fehlversuch"] = {"datum": heute, "medien": k["neu"], "gruende": fehler}
            continue

        bestanden = not fehler and not args.nur_entwurf
        stand = jetzt.isoformat()
        if alt:
            weiter = erweitere if alt.get("status") == "veroeffentlicht" else entwurf_fortschreiben
            weiter(alt, k, artikel, quellen, fehler, bestanden, modell, pinfo, jev_werte, stand, heute,
                   args.dry_run)
            continue
        slug = ms._slug(artikel["titel"])
        while slug in register:
            slug += "-2"
        karte = karte_zur_story(k)
        seite = rendere(artikel, k, quellen, karte, slug, stand, not bestanden,
                        fehler or ["Testlauf mit --nur-entwurf"])
        ziel = (ORDNER / f"{slug}.html") if bestanden else (ENTWURF_DIR / f"recherche-{slug}.html")
        eintrag = {"pfad": f"/recherche/{slug}.html" if bestanden else f"/artikel/entwurf/recherche-{slug}.html",
                   "titel": artikel["titel"], "anriss": artikel["anriss"], "datum": heute,
                   "status": "veroeffentlicht" if bestanden else "entwurf", "story_id": k["sid"],
                   "quellen": len(quellen), "modell": modell, "jev": jev_werte, "pruefer": pinfo, "gruende": fehler,
                   "links": k["links"], "pruefung": PRUEFUNG_VERSION, "stand": stand,
                   "medien": [q["medium"] for q in quellen if not q["hersteller"]], "artikel": artikel,
                   "quellen_links": [q["link"] for q in quellen if q.get("link")]}
        if k.get("linie"):              # R3: Anker fuer das Fortschreiben
            eintrag.update(linie=k["linie"], medien_linie=k.get("medien_linie") or [])
            if k.get("vorgaenger"):
                eintrag["vorgaenger"] = k["vorgaenger"]
        print(f"[RECHERCHE] {eintrag['status']}: {eintrag['pfad']} ({len(quellen)} Quellen)")
        if args.dry_run:
            print(json.dumps(artikel, ensure_ascii=False, indent=1))
            continue
        ms._schreiben_wenn_neu(ziel, seite)
        register[slug] = eintrag

    if not args.dry_run and versucht:
        ORDNER.mkdir(exist_ok=True)
        ms._schreiben_wenn_neu(REGISTER, json.dumps(register, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        oeffentliche_listen(register)
    return 0


if __name__ == "__main__":
    sys.exit(main())
