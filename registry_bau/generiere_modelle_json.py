#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modell-Registry Generator  --  ki-news.live
===========================================
Zieht die OpenRouter-Modellliste und erzeugt daraus:

    out/modelle.json              Stammdaten, EINE Datei, immer geladen  (~120 KB)
    out/registry/<anbieter>.json  Artikel-Rueckverweise, lazy beim Klick (waechst)

ARCHITEKTUR-VERTRAG (nicht verhandelbar):
    modelle.json              GENERAT   - genau ein Schreiber (dieses Skript),
                                          niemals von Hand editieren
    modelle_korrekturen.json  KURATIERT - wird nur gelesen, ueberschreibt
                                          einzelne Felder nach Schluessel

Analog zu Invariante I5/I6 fuer graph.json. Wer ins Generat schreibt, verliert
die Aenderung beim naechsten Lauf.

Stand 20.08.2026. Gemessene Grundlage:
  - 414 API-Eintraege -> 12 Aliase (~latest) -> 402 echte -> 331 nach Dedup
    auf canonical_slug (:free / :batch / :thinking sind Abrechnungsvarianten)
  - 52 Anbieter
  - Nur 4,1 % der Artikel nennen ein Modell, 50,7 % nur einen Anbieter.
    Deshalb haengen die News an der Anbieter-Ebene, nicht am Modell.
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

API_URL = "https://openrouter.ai/api/v1/models"

# FALLE, gefunden am 20.08.2026: /api/v1/models liefert OHNE Parameter NUR
# Modelle mit Text-Ausgabe. Video-, Bild- und Audiogeneratoren fehlen
# stillschweigend -- Seedance, Kling, Runway, Veo, FLUX Video, Seedream,
# Grok Imagine, Krea, Qwen Image, alle unsichtbar. Es gibt keine Fehlermeldung
# und keinen Hinweis, die Liste sieht einfach vollstaendig aus.
# Erst der explizite Filter foerdert sie zutage. 57 zusaetzliche Modelle.
ABRUFE = [
    ("text", ""),
    ("video", "?output_modalities=video"),
    ("bild", "?output_modalities=image"),
    ("audio", "?output_modalities=audio"),
]
HIER = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HIER, "out")
CACHE = os.path.join(HIER, "openrouter_cache.json")
KORREKTUREN = os.path.join(HIER, "modelle_korrekturen.json")
ALIASE = os.path.join(HIER, "anbieter_aliase.json")

# Mindestzahl, ab der die Antwort als vollstaendig gilt.
# Hintergrund: web_fetch schneidet bei ~93 KB ab (statt 680 KB) und liefert
# dann halbe Arrays. Auch curl bricht ab, wenn das Zielfilesystem voll ist
# (Exit 23) -- beides sieht ohne diese Pruefung wie ein Erfolg aus.
MIN_MODELLE = 400


# ---------------------------------------------------------------- Namensregeln
# Gemessen ueber alle 414 Eintraege. Nur diese Woerter sind zuverlaessig
# Ausbaustufen. Zahl in Klammern = Vorkommen.
AUSBAUSTUFEN = {
    "pro": 31, "mini": 18, "lite": 10, "nano": 7, "plus": 6, "max": 5,
    "large": 5, "fast": 4, "ultra": 4, "high": 4, "medium": 3, "small": 3,
}

# FALLE: "Flash" (30x) sieht aus wie eine Stufe, ist bei Google aber Teil des
# Modellnamens -- und kann selbst noch "Lite" tragen ("Gemini 3.5 Flash Lite").
# Diese Woerter duerfen NIE als Ausbaustufe geparst werden.
KEINE_STUFE = {
    "flash", "opus", "sonnet", "haiku", "fable", "grok", "kimi", "glm",
    "minimax", "luna", "terra", "sol", "nova", "solar", "ling", "ring",
    "seed", "seedream", "longcat", "nemotron", "hunyuan", "ernie",
}

# Modus-Suffixe: sagen etwas ueber den Betriebsmodus, nicht ueber die Groesse.
MODI = {
    "instruct", "preview", "latest", "turbo", "thinking", "image", "video",
    "chat", "code", "coder", "reasoning", "vision", "audio", "exp", "it",
}

# Zweistufige Varianten. Stand heute NUR bei OpenAI GPT-5.6:
#   gpt-5.6-sol / -sol-pro / -luna / -luna-pro / -terra / -terra-pro
# Es gibt kein "Sol Mini" und kein "Luna Max". Kommt ein weiterer Anbieter
# dazu, hier ergaenzen -- nicht die Heuristik aufbohren.
VARIANTEN = {"sol", "luna", "terra"}

# Abrechnungs-Suffixe hinter dem Doppelpunkt in der id.
ABRECHNUNG = {"free", "batch", "thinking", "extended", "nitro", "floor"}


def log(msg):
    print(msg, file=sys.stderr)


def _hol(pfad):
    req = urllib.request.Request(
        API_URL + pfad, headers={"User-Agent": "ki-news-registry/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8")).get("data", [])


def kategorie(eintrag):
    """Was das Modell ausgibt. Bestimmt die Kachel-Kategorie."""
    o = (eintrag.get("architecture") or {}).get("output_modalities") or []
    for k in ("video", "image", "audio"):
        if k in o:
            return {"image": "bild"}.get(k, k)
    return "text"


def hole_liste(offline=False):
    """
    Holt ALLE vier Teillisten und fuehrt sie zusammen. Prueft Vollstaendigkeit,
    faellt auf Cache zurueck.
    """
    if not offline:
        try:
            zusammen = {}
            bericht = []
            for name, pfad in ABRUFE:
                teil = _hol(pfad)
                neu = sum(1 for x in teil if x["id"] not in zusammen)
                for x in teil:
                    zusammen.setdefault(x["id"], x)
                bericht.append("%s %d(+%d)" % (name, len(teil), neu))
            daten = {"data": list(zusammen.values())}
            n = len(daten["data"])
            if n < MIN_MODELLE:
                raise ValueError(
                    "Antwort unvollstaendig: %d Eintraege, erwartet >= %d. "
                    "Vermutlich abgeschnitten." % (n, MIN_MODELLE))
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(daten, f)
            log("  API: %s -> %d Eintraege, Cache aktualisiert"
                % (" · ".join(bericht), n))
            return daten["data"]
        except Exception as e:
            log("  API fehlgeschlagen (%s) -- versuche Cache" % e)

    if not os.path.exists(CACHE):
        raise SystemExit("FEHLER: Kein Netz und kein Cache unter %s" % CACHE)
    with open(CACHE, encoding="utf-8") as f:
        daten = json.load(f)
    n = len(daten.get("data", []))
    if n < MIN_MODELLE:
        raise SystemExit("FEHLER: Cache ist unvollstaendig (%d Eintraege)" % n)
    log("  Cache: %d Eintraege" % n)
    return daten["data"]


def norm_wort(s):
    return re.sub(r"[^a-z0-9.]", "", s.lower())


def zerlege_namen(klarname):
    """
    'GPT-5.6 Sol Pro'      -> familie 'GPT-5.6', variante 'Sol',   stufe 'Pro'
    'Gemini 3.5 Flash Lite'-> familie 'Gemini 3.5 Flash', variante None, stufe 'Lite'
    'Claude Opus 5'        -> familie 'Claude Opus 5',    variante None, stufe None
    """
    # Geklammerte Zusaetze sind IMMER Modus, nie Groesse.
    # 'Claude Opus 5 (Fast)' -> Stufe None, Modus 'Fast'
    # 'Nano Banana 2 Lite (Gemini 3.1 Flash Lite Image)' -> Klammer komplett raus,
    # sonst zerreisst die Zerlegung den Namen an der Klammer.
    klammer = re.findall(r"\(([^)]*)\)", klarname)
    klarname = re.sub(r"\s*\([^)]*\)", "", klarname).strip()

    teile = klarname.replace("\u2011", "-").split()
    stufe = None
    variante = None
    modi = list(klammer)

    # Von hinten abtragen. Nur eine Stufe, nur eine Variante.
    while teile:
        w = norm_wort(teile[-1])
        if w in KEINE_STUFE:
            break
        if w in AUSBAUSTUFEN and stufe is None:
            stufe = teile.pop()
            continue
        if w in MODI:
            modi.insert(0, teile.pop())
            continue
        if re.fullmatch(r"\(?\d{4,8}\)?", w):  # nackte Datums-/Versionsnummer
            teile.pop()
            continue
        break

    if teile and norm_wort(teile[-1]) in VARIANTEN:
        variante = teile.pop()

    familie = " ".join(teile).strip() or klarname
    return familie, variante, stufe, (" ".join(modi) or None)


def release_datum(eintrag):
    """
    canonical_slug traegt bei 151 von 331 Modellen ein exaktes Datum
    ('z-ai/glm-5.3-20260816'). Das ist der echte Release. 'created' ist nur
    der Zeitpunkt, zu dem OpenRouter das Modell gelistet hat.
    """
    slug = eintrag.get("canonical_slug") or ""
    m = re.search(r"-(\d{4})(\d{2})(\d{2})$", slug)
    if m:
        return "%s-%s-%s" % m.groups(), "slug"
    ts = eintrag.get("created")
    if ts:
        return time.strftime("%Y-%m-%d", time.gmtime(ts)), "created"
    return None, None


def preis(p):
    """OpenRouter liefert Preis pro Token als String. Wir rechnen auf 1M hoch."""
    def f(k):
        try:
            v = float(p.get(k) or 0)
        except (TypeError, ValueError):
            return None
        return round(v * 1_000_000, 4) if v else 0.0
    return {"prompt_pro_1m": f("prompt"), "completion_pro_1m": f("completion")}


def lade_zusammenfuehrung():
    """
    OpenRouter fuehrt denselben Anbieter unter mehreren Praefixen. Ohne
    Zusammenfuehrung steht er zweimal in der Registry -- und beide Kacheln
    zeigen ein falsches "neuestes Release". Meta ist der Musterfall: unter
    meta-llama endet die Zeitrechnung im April 2025, unter meta laeuft Muse
    Spark im August 2026 weiter.
    """
    if not os.path.exists(ALIASE):
        return {}
    with open(ALIASE, encoding="utf-8") as f:
        z = json.load(f).get("_zusammenfuehren", {})
    return {k: v for k, v in z.items() if not k.startswith("_")}


def anbieter_klarnamen(echt):
    """
    Der Klarname steht als 'Anbieter: Modell' im name-Feld -- aber nicht
    zuverlaessig: bei einzelnen Modellen fehlt das Praefix, und manche
    Anbieter fuehren einen Produktnamen davor ('Venice: ...' unter dem
    Praefix cognitivecomputations). Deshalb Mehrheitsentscheid pro Praefix
    plus Plausibilitaetspruefung gegen das Praefix selbst.
    """
    kandidaten = defaultdict(Counter)
    for x in echt:
        praefix = x["id"].split("/")[0]
        name = x.get("name") or ""
        if ": " in name:
            kandidaten[praefix][name.split(": ", 1)[0]] += 1

    ergebnis = {}
    for praefix, zaehler in kandidaten.items():
        bester, _ = zaehler.most_common(1)[0]
        a = re.sub(r"[^a-z0-9]", "", bester.lower())
        b = re.sub(r"[^a-z0-9]", "", praefix.lower())
        # Passt der Klarname zum Praefix? Sonst ist es ein Produktname.
        if a and b and (a in b or b in a or a[:5] == b[:5]):
            ergebnis[praefix] = bester
        else:
            ergebnis[praefix] = praefix.replace("-", " ").title()
            log("  Klarname unplausibel: %s -> '%s', nutze '%s'"
                % (praefix, bester, ergebnis[praefix]))
    return ergebnis


def baue(roh):
    # 1) Aliase raus. Die 12 '~anbieter/x-latest' sind Zeiger, keine Modelle.
    aliase = {}
    echt = []
    for x in roh:
        if x.get("alias_target"):
            aliase[x["id"]] = x["alias_target"].get("slug")
        else:
            echt.append(x)

    # 2) Dedup auf canonical_slug. Der laengere id-lose Eintrag gewinnt,
    #    Abrechnungsvarianten werden als Liste angehaengt.
    gruppen = defaultdict(list)
    for x in echt:
        gruppen[x["canonical_slug"]].append(x)

    klarnamen = anbieter_klarnamen(echt)
    zusammen = lade_zusammenfuehrung()
    if zusammen:
        log("  Anbieter zusammengefuehrt: %s"
            % ", ".join("%s->%s" % kv for kv in sorted(zusammen.items())))

    modelle = []
    for slug, gruppe in gruppen.items():
        # Basiseintrag = der ohne Doppelpunkt-Suffix, sonst der erste
        basis = next((g for g in gruppe if ":" not in g["id"]), gruppe[0])
        varianten_ids = sorted(g["id"] for g in gruppe)
        abrechnung = sorted({
            g["id"].split(":", 1)[1] for g in gruppe if ":" in g["id"]
        })

        praefix = basis["id"].split("/")[0]
        praefix = zusammen.get(praefix, praefix)
        name = basis.get("name") or basis["id"]
        klarname = name.split(": ", 1)[1] if ": " in name else name
        anbieter_klar = klarnamen.get(praefix) or praefix.replace("-", " ").title()

        familie, variante, stufe, modus = zerlege_namen(klarname)
        rel, rel_quelle = release_datum(basis)
        arch = basis.get("architecture") or {}

        modelle.append({
            "slug": slug,
            "id": basis["id"],
            "anbieter": praefix,
            "kategorie": kategorie(basis),
            "anbieter_name": anbieter_klar,
            "name": klarname,
            "familie": familie,
            "variante": variante,
            "ausbaustufe": stufe,
            "modus": modus,
            "release": rel,
            "release_quelle": rel_quelle,
            "knowledge_cutoff": basis.get("knowledge_cutoff"),
            "expiration_date": basis.get("expiration_date"),
            "context_length": basis.get("context_length"),
            "modalitaeten": {
                "input": arch.get("input_modalities"),
                "output": arch.get("output_modalities"),
            },
            "reasoning": bool(basis.get("reasoning")),
            "preis": preis(basis.get("pricing") or {}),
            "hugging_face_id": basis.get("hugging_face_id"),
            "abrechnung": abrechnung,
            "ids": varianten_ids,
            # wird vom Zuordnungslauf gefuellt, hier bewusst leer:
            "artikel_anzahl": 0,
        })

    # Anbieter alphabetisch, darin neuestes Modell zuerst
    modelle.sort(key=lambda m: (m["anbieter"], _neg(m["release"])))
    return modelle, aliase


def _neg(d):
    """Sortierschluessel: neuestes Datum zuerst, Modelle ohne Datum ans Ende."""
    return (1, "") if not d else (0, "".join(chr(255 - ord(c)) for c in d))


def anbieter_index(modelle):
    idx = defaultdict(lambda: {
        "anbieter": None, "anbieter_name": None, "modelle": 0,
        "familien": set(), "neuestes_release": None,
    })
    for m in modelle:
        e = idx[m["anbieter"]]
        e["anbieter"] = m["anbieter"]
        e["anbieter_name"] = e["anbieter_name"] or m["anbieter_name"]
        e["modelle"] += 1
        e["familien"].add(m["familie"])
        if m["release"] and (not e["neuestes_release"] or m["release"] > e["neuestes_release"]):
            e["neuestes_release"] = m["release"]
    out = []
    for k, e in idx.items():
        e = dict(e)
        e["familien"] = sorted(e.pop("familien"))
        e["familien_anzahl"] = len(e["familien"])
        out.append(e)
    out.sort(key=lambda e: (-e["modelle"], e["anbieter"]))
    return out


def overlay(modelle):
    """modelle_korrekturen.json ueberschreibt einzelne Felder nach slug."""
    if not os.path.exists(KORREKTUREN):
        return 0
    with open(KORREKTUREN, encoding="utf-8") as f:
        korr = json.load(f)
    eintraege = korr.get("modelle", {})
    n = 0
    fuer_slug = {m["slug"]: m for m in modelle}
    for slug, felder in eintraege.items():
        ziel = fuer_slug.get(slug)
        if not ziel:
            log("  Korrektur zeigt ins Leere: %s" % slug)
            continue
        ziel.update(felder)
        ziel["korrigiert"] = sorted(felder)
        n += 1
    return n


def schreibe(modelle, anbieter, aliase):
    os.makedirs(os.path.join(OUT, "registry"), exist_ok=True)

    stamm = {
        "erzeugt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quelle": API_URL,
        "generator": "generiere_modelle_json.py",
        "hinweis": "GENERAT. Nicht von Hand editieren -- Aenderungen gehoeren "
                   "in modelle_korrekturen.json.",
        "anzahl_modelle": len(modelle),
        "anzahl_anbieter": len(anbieter),
        "aliase": aliase,
        "anbieter": anbieter,
        "modelle": modelle,
    }
    p = os.path.join(OUT, "modelle.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(stamm, f, ensure_ascii=False, indent=1)

    # Shards: pro Anbieter eine Datei fuer die Artikel-Rueckverweise.
    # Jetzt noch leer -- der Zuordnungslauf fuellt sie spaeter kumulativ.
    nach_anbieter = defaultdict(list)
    for m in modelle:
        nach_anbieter[m["anbieter"]].append(m["slug"])
    for anb, slugs in nach_anbieter.items():
        sp = os.path.join(OUT, "registry", "%s.json" % anb)
        alt = {}
        if os.path.exists(sp):          # bestehende Artikel nie wegwerfen
            with open(sp, encoding="utf-8") as f:
                alt = json.load(f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({
                "anbieter": anb,
                "aktualisiert": stamm["erzeugt"],
                "modelle": sorted(slugs),
                "artikel_anbieter": alt.get("artikel_anbieter", []),
                "artikel_modell": alt.get("artikel_modell", {}),
            }, f, ensure_ascii=False, indent=1)

    return p, os.path.getsize(p)


def main(argv=None):
    # argv statt sys.argv, damit der Aufruf aus lauf.py nicht die Argumente
    # von ki_news.py mitliest.
    offline = "--offline" in (sys.argv if argv is None else argv)
    log("Modell-Registry Generator")
    roh = hole_liste(offline=offline)

    modelle, aliase = baue(roh)
    n_korr = overlay(modelle)
    anbieter = anbieter_index(modelle)
    pfad, groesse = schreibe(modelle, anbieter, aliase)

    log("")
    log("  API-Eintraege        : %d" % len(roh))
    log("  davon Aliase         : %d" % len(aliase))
    log("  Modelle nach Dedup   : %d" % len(modelle))
    log("  Anbieter             : %d" % len(anbieter))
    log("  Korrekturen angewandt: %d" % n_korr)
    log("  Release aus Slug     : %d" % sum(1 for m in modelle if m["release_quelle"] == "slug"))
    log("  Release aus created  : %d" % sum(1 for m in modelle if m["release_quelle"] == "created"))
    log("  mit Ausbaustufe      : %d" % sum(1 for m in modelle if m["ausbaustufe"]))
    log("  mit Variante         : %d" % sum(1 for m in modelle if m["variante"]))
    kat = Counter(m["kategorie"] for m in modelle)
    log("  Kategorien           : %s" % dict(kat.most_common()))
    log("")
    log("  -> %s  (%.0f KB)" % (pfad, groesse / 1024))
    log("  -> %s/registry/*.json  (%d Dateien)" % (OUT, len(anbieter)))


if __name__ == "__main__":
    main()
