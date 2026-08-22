#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zuordnungslauf  --  Artikel an die Modell-Registry heften
=========================================================
Liest Artikel (archive.json / news.json) und schreibt Rueckverweise in die
Anbieter-Shards. Kumulativ: bestehende Eintraege werden nie geloescht, nur
ergaenzt. Damit ueberlebt die Registry das 10-Tage-Fenster von archive.json.

ZWEI EBENEN, wie von Daniel festgelegt:
    Modell    nur bei EXPLIZITER Nennung des Modellnamens
    Anbieter  sonst -- und mehrfach, wenn mehrere genannt sind (11 % der Faelle)

Was weder Modell noch Anbieter trifft, landet in out/registry/_ohne.json.
Das ist bewusst KEIN Muellhaufen: die Datei ist die Arbeitsgrundlage fuer die
Themen-Achse (siehe KONZEPT.md). Gemessen sind das 47,3 % aller Artikel.

Aufruf:
    python3 ordne_artikel_zu.py                 # gegen den Live-Klon
    python3 ordne_artikel_zu.py --quelle X.json # gegen eine Datei
    python3 ordne_artikel_zu.py --trocken       # nur messen, nichts schreiben
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HIER = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HIER, "out")
SHARDS = os.path.join(OUT, "registry")
MODELLE = os.path.join(OUT, "modelle.json")
ALIASE = os.path.join(HIER, "anbieter_aliase.json")

# Pro Modell/Anbieter aufbewahrte Artikel. Nicht die Historie begrenzen,
# sondern die Menge, die eine Kachel beim Aufklappen laedt.
MAX_JE_MODELL = 25
MAX_JE_ANBIETER = 200

# Modellnamen, die als Wort zu haeufig unabsichtlich vorkommen. Ohne diese
# Sperre matcht "Forge" jede Meldung ueber Werkzeuge und "Sol" jede spanische.
ZU_GENERISCH = {
    "forge", "muse", "chat", "code", "coder", "base", "image", "video",
    "nova", "solar", "seed", "dots", "command", "sol", "luna", "terra",
    "flash", "pro", "max", "mini", "nano", "plus", "lite", "turbo",
    "ling", "ring", "step", "reka", "mercury", "venice", "writer",
}


def norm(s):
    """Kleinschreibung, alle Trenner zu Leerzeichen, mit Randleerzeichen."""
    s = (s or "").lower()
    s = re.sub(r"[‐-―\-_/,;:()\[\]{}\"'`]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return " " + s.strip() + " "


def lade_muster():
    with open(MODELLE, encoding="utf-8") as f:
        reg = json.load(f)
    with open(ALIASE, encoding="utf-8") as f:
        al = json.load(f)

    # Zusammengefuehrte Anbieter teilen sich eine Aliasliste, sonst landen
    # Meta-Artikel je nach Suchbegriff bei zwei verschiedenen Kacheln.
    zus = {k: v for k, v in al.get("_zusammenfuehren", {}).items()
           if not k.startswith("_")}
    anbieter_alias = {}
    for k, v in al.get("aliase", {}).items():
        ziel = zus.get(k, k)
        anbieter_alias.setdefault(ziel, [])
        anbieter_alias[ziel] += [norm(x).strip() for x in v]
    # Anbieter ohne OpenRouter-Modell: erkannt, aber ohne Kachel.
    extern = {}
    for k, v in al.get("_nicht_in_der_api", {}).items():
        if k.startswith("_"):
            continue
        extern[k] = [norm(x).strip() for x in v]

    # ZWEI GETRENNTE MUSTERSAETZE -- der Unterschied ist der ganze Punkt.
    #
    # Modellmuster: NUR der volle Klarname. "GPT-5.6 Sol Pro" ist eine
    # explizite Nennung, "GPT-5.6" ist keine -- die Familie traegt sechs
    # Varianten, und einem Artikel alle sechs anzuhaengen ist schlicht falsch.
    # Genau das passierte in der ersten Fassung: 'Qwen' ist als Familie mit
    # einem Modell hinterlegt, also bekam dieses eine Modell jede beliebige
    # Qwen-Meldung angeheftet.
    muster = []
    for m in reg["modelle"]:
        n = norm(m["name"]).strip()
        if len(n) < 5 or n in ZU_GENERISCH:
            continue
        muster.append((n, m["slug"], m["anbieter"]))
    muster = sorted(set(muster), key=lambda t: -len(t[0]))

    # Familienmuster: eigener Zweig. Ein Familientreffer geht an den ANBIETER
    # und vermerkt die Familie -- nie an ein einzelnes Modell.
    fam = {}
    for m in reg["modelle"]:
        n = norm(m["familie"]).strip()
        if len(n) < 5 or n in ZU_GENERISCH:
            continue
        fam.setdefault(n, (m["familie"], m["anbieter"]))
    familien = sorted(
        ((n, v[0], v[1]) for n, v in fam.items()), key=lambda t: -len(t[0]))

    return reg, muster, familien, anbieter_alias, extern


def treffer_anbieter(txt, tabelle):
    return {p for p, alis in tabelle.items() if any(a in txt for a in alis)}


def kurz(a):
    """Der Rueckverweis. Bewusst schlank -- die Karte zeigt nicht mehr."""
    return {
        "titel": (a.get("title") or "")[:180],
        "link": a.get("link"),
        "quelle": a.get("source"),
        "datum": (a.get("first_seen") or a.get("date") or "")[:10],
        "score": a.get("score"),
    }


def lade_shard(name):
    p = os.path.join(SHARDS, "%s.json" % name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"anbieter": name, "modelle": [], "artikel_anbieter": [], "artikel_modell": {}}


def standard_quellen():
    """Wo archive.json und news.json liegen, wenn nichts angegeben ist.

    Erst der Ordner ueber diesem hier -- so trifft es in GitHub Actions, wo
    das Skript unter registry_bau/ im ausgecheckten Repo liegt. Danach der
    uebliche Ort auf Daniels Rechner. Frueher stand hier ein fester
    Sandbox-Pfad, den es auf keinem der beiden Systeme gab.
    """
    kandidaten = []
    repo = os.path.dirname(HIER)
    heim = os.path.join(os.path.expanduser("~"), "Documents", "Projekte",
                        "ki-news")
    for basis in (repo, heim):
        for name in ("archive.json", "news.json"):
            p = os.path.join(basis, name)
            if os.path.exists(p) and p not in kandidaten:
                kandidaten.append(p)
        if kandidaten:
            break          # nicht zwei Staende mischen
    return kandidaten


def main(argv=None):
    # argv statt sys.argv, damit der Aufruf aus lauf.py nicht die Argumente
    # von ki_news.py mitliest.
    ap = argparse.ArgumentParser()
    ap.add_argument("--quelle", action="append", default=None)
    ap.add_argument("--trocken", action="store_true")
    ap.add_argument("--reset", action="store_true",
                    help="Artikel-Rueckverweise verwerfen und neu aufbauen. "
                         "Noetig, wenn sich die Zuordnungsregel geaendert hat -- "
                         "der Normalfall ergaenzt nur und wuerde alte Fehltreffer "
                         "konservieren.")
    args = ap.parse_args(argv)

    quellen = args.quelle or standard_quellen()

    reg, muster, familien, alias, extern = lade_muster()
    print("Zuordnungslauf")
    print("  %d Modellmuster, %d Familienmuster, %d Anbieter, %d externe"
          % (len(muster), len(familien), len(alias), len(extern)))

    artikel = []
    gesehen = set()
    for q in quellen:
        if not os.path.exists(q):
            print("  Quelle fehlt: %s" % q)
            continue
        with open(q, encoding="utf-8") as f:
            d = json.load(f)
        liste = d if isinstance(d, list) else (d.get("articles") or d.get("news") or [])
        neu = 0
        for a in liste:
            k = a.get("link") or a.get("title")
            if k and k not in gesehen:
                gesehen.add(k)
                artikel.append(a)
                neu += 1
        print("  %s: %d Artikel, %d neu" % (os.path.basename(q), len(liste), neu))

    zweig = Counter()
    je_anbieter = defaultdict(list)
    je_modell = defaultdict(lambda: defaultdict(list))
    ohne = []

    for a in artikel:
        txt = norm((a.get("title") or "") + " " + (a.get("summary") or ""))
        mt = [(n, s, p) for n, s, p in muster if " " + n + " " in txt]
        if mt:
            zweig["1_modell"] += 1
            for n, s, p in mt[:3]:
                je_modell[p][s].append(kurz(a))
                je_anbieter[p].append(kurz(a))
            continue
        ft = [(kl, p) for n, kl, p in familien if " " + n + " " in txt]
        if ft:
            zweig["1b_familie"] += 1
            for kl, p in ft[:2]:
                e = kurz(a)
                e["familie"] = kl
                je_anbieter[p].append(e)
            continue
        pt = treffer_anbieter(txt, alias)
        if pt:
            zweig["2_anbieter"] += 1
            zweig["2b_mehrfach"] += 1 if len(pt) > 1 else 0
            for p in pt:
                je_anbieter[p].append(kurz(a))
            continue
        et = treffer_anbieter(txt, extern)
        if et:
            zweig["3_extern"] += 1
            e = kurz(a)
            e["anbieter_extern"] = sorted(et)
            ohne.append(e)
            continue
        zweig["4_ohne"] += 1
        ohne.append(kurz(a))

    tot = len(artikel)
    print("\n=== Ergebnis ueber %d Artikel ===" % tot)
    for k in sorted(zweig):
        print("  %-14s %5d  %5.1f%%" % (k, zweig[k], zweig[k] / tot * 100))
    belegt = sum(len(v) for v in je_modell.values())
    print("\n  Modelle mit Artikeln  : %d von %d" % (belegt, len(reg["modelle"])))
    print("  Anbieter mit Artikeln : %d von %d" % (len(je_anbieter), len(reg["anbieter"])))

    if args.trocken:
        print("\n  --trocken: nichts geschrieben")
        return

    os.makedirs(SHARDS, exist_ok=True)
    if args.reset:
        for f in os.listdir(SHARDS):
            fp = os.path.join(SHARDS, f)
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
            d["artikel_anbieter"] = []
            d["artikel_modell"] = {}
            d["artikel"] = []
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
        print("  --reset: %d Shards geleert" % len(os.listdir(SHARDS)))

    stempel = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    neu_ges = 0
    for anb in set(list(je_anbieter) + [m["anbieter"] for m in reg["modelle"]]):
        sh = lade_shard(anb)

        def misch(alt, frisch, grenze):
            nonlocal neu_ges
            hab = {x.get("link") for x in alt}
            for x in frisch:
                if x.get("link") not in hab:
                    alt.append(x)
                    hab.add(x.get("link"))
                    neu_ges += 1
            alt.sort(key=lambda x: x.get("datum") or "", reverse=True)
            return alt[:grenze]

        sh["artikel_anbieter"] = misch(
            sh.get("artikel_anbieter", []), je_anbieter.get(anb, []), MAX_JE_ANBIETER)
        am = sh.setdefault("artikel_modell", {})
        for slug, lst in je_modell.get(anb, {}).items():
            am[slug] = misch(am.get(slug, []), lst, MAX_JE_MODELL)
        sh["aktualisiert"] = stempel
        sh["anzahl_anbieter"] = len(sh["artikel_anbieter"])
        sh["anzahl_modell"] = sum(len(v) for v in am.values())

        with open(os.path.join(SHARDS, "%s.json" % anb), "w", encoding="utf-8") as f:
            json.dump(sh, f, ensure_ascii=False, indent=1)

    p_ohne = os.path.join(SHARDS, "_ohne.json")
    alt = []
    if os.path.exists(p_ohne):
        with open(p_ohne, encoding="utf-8") as f:
            alt = json.load(f).get("artikel", [])
    hab = {x.get("link") for x in alt}
    for x in ohne:
        if x.get("link") not in hab:
            alt.append(x)
            hab.add(x.get("link"))
    alt.sort(key=lambda x: x.get("datum") or "", reverse=True)
    with open(p_ohne, "w", encoding="utf-8") as f:
        json.dump({
            "hinweis": "Artikel ohne Anbieter- und Modellbezug. Arbeitsgrundlage "
                       "fuer die Themen-Achse, kein Muellhaufen.",
            "aktualisiert": stempel,
            "anzahl": len(alt),
            "artikel": alt,
        }, f, ensure_ascii=False, indent=1)

    # Trefferzahl in die Stammdaten zurueckschreiben
    zaehler = {}
    for anb, d in je_modell.items():
        for slug, lst in d.items():
            zaehler[slug] = len(lst)
    for m in reg["modelle"]:
        m["artikel_anzahl"] = zaehler.get(m["slug"], m.get("artikel_anzahl", 0))
    with open(MODELLE, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)

    gr = sum(os.path.getsize(os.path.join(SHARDS, f)) for f in os.listdir(SHARDS))
    print("\n  %d neue Rueckverweise geschrieben" % neu_ges)
    print("  Shards: %d Dateien, %.0f KB" % (len(os.listdir(SHARDS)), gr / 1024))
    print("  ohne Zuordnung: %d in _ohne.json" % len(alt))


if __name__ == "__main__":
    main()
