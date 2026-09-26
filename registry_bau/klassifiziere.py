#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Facetten-Klassifikation  --  die vier Stichpunkte pro Nachricht
===============================================================
Vergibt pro Artikel vier Facetten aus taxonomie.json:

    ressort        genau eines    in welchem Teil der Zeitung stuende das
    ereignistyp    genau einer    was ist passiert
    themenfelder   ein bis vier   worum geht es wirklich
    region         genau eine     wo

Die Trennung von Ereignistyp und Themenfeld ist Daniels Punkt vom 20.08.:
"Veeda AI sammelt 90 Mio Seed" ist ereignistyp=finanzierung, aber
themenfelder=[weltmodelle, robotik] -- das Geld ist nur der Anlass.

ZWEI ACHSEN, unabhaengig voneinander:
    WER    Anbieter/Modell  -> ordne_artikel_zu.py, deterministisch
    WORUEBER  Facetten      -> dieses Skript, LLM-Judge
Ein Artikel ueber OpenAI-Regulierung haengt an beiden. Deshalb laeuft die
Klassifikation ueber ALLE Artikel, nicht nur ueber die ohne Anbieterbezug.

SCHLUESSEL: Der Judge darf nichts erfinden. Jeder Wert wird gegen
taxonomie.json geprueft; was nicht in der Liste steht, wird zu null und
landet in der Nachbearbeitung. Lieber eine Luecke als ein falsches Fach.

Aufruf:
    OPENROUTER_KEY=... python3 klassifiziere.py --limit 60
    python3 klassifiziere.py --trocken     # zeigt den Prompt, ruft nichts auf
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

HIER = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HIER, "out")
TAXONOMIE = os.path.join(HIER, "taxonomie.json")

# Die Ablage ist das Herzstueck der Sparsamkeit: was hier drinsteht, wird
# nicht noch einmal an ein Modell geschickt. Ein Lauf kostet dadurch vier
# Aufrufe statt hundertfuenfzig.
#
# Der Pfad ist ueberschreibbar, weil die Datei an zwei Orten leben muss:
# lokal unter out/, in GitHub Actions im ausgecheckten Repo -- dort ist der
# Ordner nach jedem Lauf wieder weg, wenn die Datei nicht mitgepusht wird.
# Zeigt der Pfad ins Leere, faengt der Judge bei null an und klassifiziert
# stumm und teuer den gesamten Bestand neu.
FACETTEN = os.environ.get("FACETTEN_ABLAGE", "").strip() or os.path.join(
    OUT, "facetten.json")

# Wo die Keys liegen. .secrets.env hat GROQ_API_KEY und GEMINI_API_KEY --
# beide Provider haben brauchbare kostenlose Kontingente. OpenRouter steht
# nur als Fallback drin, weil sein Key ausschliesslich als GitHub-Secret
# existiert und lokal nicht verfuegbar ist.
SECRETS = os.path.join(os.path.expanduser("~"), "Documents", "KIVault",
                       "04 Ressourcen", "Tools", ".secrets.env")

# Kaskade: erster Provider mit gueltigem Key und funktionierendem Modell
# gewinnt. Reihenfolge = Praeferenz. Alle drei sprechen dasselbe
# OpenAI-kompatible /chat/completions-Schema, Gemini ueber seine
# Kompatibilitaetsschicht unter /v1beta/openai/ -- das spart eigenes Parsing
# fuer die native generateContent-API.
BACKENDS = [
    # Gemini zuerst: liefert sauberen content. Die gpt-oss-Modelle bei Groq
    # sind Reasoning-Modelle und schreiben ihr Denken in ein separates
    # reasoning-Feld -- bei knappem Budget bleibt content dann LEER, obwohl
    # HTTP 200 und finish_reason=length zurueckkommen. Live geprueft 20.08.
    ("gemini",
     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "GEMINI_API_KEY",
     ["gemini-3-flash-preview", "gemini-flash-latest", "gemma-4-31b-it"]),
    ("groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
     ["qwen/qwen3.6-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]),
    # openai/gpt-oss-20b:free am 22.08.2026 entfernt -- lieferte im Live-Lauf
    # durchgaengig HTTP 404. Das Modell gibt es bei OpenRouter nicht mehr.
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions",
     "OPENROUTER_KEY",
     ["google/gemma-4-31b-it:free"]),
]


# Dieselben Schluessel unter anderem Namen. In GitHub Actions heisst der
# Groq-Schluessel seit jeher GROQ_CHAT_KEY -- ohne diese Zuordnung faende der
# Judge dort nur OpenRouter und liefe unnoetig auf dessen engeren Freikontingent.
ALIASE = {
    "GROQ_API_KEY": ["GROQ_CHAT_KEY"],
    "GEMINI_API_KEY": ["GOOGLE_API_KEY"],
}


def lade_keys():
    """Keys aus der Umgebung, sonst aus .secrets.env."""
    keys = {}
    for _, _, name, _ in BACKENDS:
        v = os.environ.get(name, "").strip()
        if not v:
            for zweitname in ALIASE.get(name, []):
                v = os.environ.get(zweitname, "").strip()
                if v:
                    break
        if v:
            keys[name] = v
    if os.path.exists(SECRETS):
        with open(SECRETS, encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                k, v = zeile.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k not in keys and v:
                    keys[k] = v
    return keys

BATCH = 8          # Artikel pro Aufruf. Groesser spart Tokens, erhoeht aber
                   # das Risiko, dass ein Parse-Fehler den ganzen Batch kippt.
# Grosszuegig: Gemini 3 Flash denkt intern mit und zaehlt das aufs Budget.
# Mit 1400 brach die Antwort live nach anderthalb Eintraegen ab.
MAX_TOKENS = 4000
TIMEOUT = 90


def lade_taxonomie():
    with open(TAXONOMIE, encoding="utf-8") as f:
        t = json.load(f)
    return {
        "ressort": list(t["ressort"]["werte"].keys()),
        "ereignistyp": t["ereignistyp"]["werte"],
        "themenfelder": t["themenfelder"]["werte"],
        "region": t["region"]["werte"],
        "_roh": t,
    }


def baue_system(tax):
    return (
        "Du klassifizierst KI-Nachrichten fuer eine Nachrichten-Registry.\n"
        "Du gibst AUSSCHLIESSLICH ein JSON-Array zurueck. Kein Markdown, kein "
        "Fliesstext, keine Erklaerung.\n\n"
        "Vier Facetten pro Artikel. Verwende NUR Werte aus den Listen. Wenn du "
        "dir nicht sicher bist, setze null -- rate nicht.\n\n"
        "RESSORT (genau eines): " + " | ".join(tax["ressort"]) + "\n\n"
        "EREIGNISTYP (genau einer): " + " | ".join(tax["ereignistyp"]) + "\n\n"
        "THEMENFELDER (ein bis vier, wichtigstes zuerst): "
        + " | ".join(tax["themenfelder"]) + "\n\n"
        "REGION (genau eine, die spezifischste die passt; eine saechsische "
        "Foerdermeldung ist 'sachsen', nicht 'deutschland'): "
        + " | ".join(tax["region"]) + "\n\n"
        "WICHTIG: Ereignistyp und Themenfeld sind verschiedene Fragen. Der "
        "Ereignistyp sagt WAS PASSIERT IST, das Themenfeld WORUM ES WIRKLICH "
        "GEHT. Eine Finanzierungsrunde fuer ein Robotik-Weltmodell ist "
        "ereignistyp=finanzierung, themenfelder=[weltmodelle, robotik] -- das "
        "Geld ist nur der Anlass, nicht das Thema. Wiederhole den Ereignistyp "
        "deshalb NICHT als Themenfeld.\n\n"
        'Format je Artikel: {"nr":1,"ressort":"...","ereignistyp":"...",'
        '"themenfelder":["..."],"region":"...","sicher":true}\n'
        'Setze "sicher":false, wenn Titel und Zusammenfassung nicht ausreichen '
        "und man die verlinkte Seite lesen muesste."
    )


def baue_prompt(batch):
    teile = []
    for i, a in enumerate(batch, 1):
        teile.append(
            "ARTIKEL %d\nTitel: %s\nZusammenfassung: %s\nQuelle: %s"
            % (i, a.get("title", ""), (a.get("summary") or "")[:400],
               a.get("source", ""))
        )
    return "\n\n".join(teile)


def rufe_llm(system, prompt, keys):
    """
    Durch alle Backends und deren Modelle, bis eines antwortet.
    Gibt (text, "provider/modell") oder (None, None).
    """
    erschoepft = []
    for provider, url, keyname, modelle in BACKENDS:
        key = keys.get(keyname)
        if not key:
            continue
        for modell in modelle:
            nutzlast = {
                "model": modell,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
            }
            # Nur Gemini kennt reasoning_effort. Groq quittiert das Feld mit
            # HTTP 400 -- live geprueft 20.08.
            if provider == "gemini" and modell.startswith("gemini"):
                nutzlast["reasoning_effort"] = "none"
            koerper = json.dumps(nutzlast).encode("utf-8")
            kopf = {
                "Authorization": "Bearer %s" % key,
                "Content-Type": "application/json",
                # Ohne User-Agent antwortet Groq mit 403; urllib schickt sonst
                # "Python-urllib/3.x", das wird geblockt.
                "User-Agent": "ki-news-registry/1.0",
            }
            if provider == "openrouter":
                kopf["HTTP-Referer"] = "https://ki-news.live"
            req = urllib.request.Request(url, data=koerper, headers=kopf)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    d = json.loads(r.read().decode("utf-8"))
                # HTTP 200 heisst nicht, dass eine Antwort drin ist -- manche
                # Provider liefern Rate-Limit-Fehler mit Status 200.
                if "choices" not in d:
                    print("  %s/%s: ohne choices (%s)"
                          % (provider, modell, str(d.get("error", d))[:100]))
                    continue
                inhalt = (d["choices"][0]["message"].get("content") or "").strip()
                if not inhalt:
                    # Reasoning-Modelle schreiben ihr Denken in ein eigenes Feld
                    # und liefern dann leeren content trotz HTTP 200.
                    print("  %s/%s: leerer content (finish_reason=%s)"
                          % (provider, modell, d["choices"][0].get("finish_reason")))
                    continue
                return inhalt, "%s/%s" % (provider, modell)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    erschoepft.append("%s/%s" % (provider, modell))
                else:
                    print("  %s/%s: HTTP %d" % (provider, modell, e.code))
                continue
            except Exception as e:
                print("  %s/%s: %s" % (provider, modell, str(e)[:100]))
                continue

    if erschoepft:
        print("  Kontingent erschoepft bei: %s" % ", ".join(erschoepft))
    return None, None


def hole_json(text):
    """
    Das Array aus der Antwort schaelen. Zwei Eigenheiten der Modelle:
    sie packen gern Markdown drum, und bei erschoepftem Token-Budget bricht
    die Antwort mitten im Array ab. Statt dann alles zu verwerfen, sammeln
    wir die vollstaendigen Objekte einzeln ein -- ein halber Batch ist mehr
    wert als keiner.
    """
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a = text.find("[")
    if a == -1:
        return None
    b = text.rfind("]")
    if b > a:
        try:
            return json.loads(text[a:b + 1])
        except json.JSONDecodeError:
            pass
    # Rettung: jedes vollstaendige {...} einzeln parsen.
    raus = []
    for treffer in re.finditer(r"\{[^{}]*\}", text[a:]):
        try:
            raus.append(json.loads(treffer.group(0)))
        except json.JSONDecodeError:
            continue
    return raus or None


def pruefe(eintrag, tax):
    """
    Jeder Wert muss in der Taxonomie stehen. Was nicht passt, wird null.
    Das ist bewusst streng: eine Luecke ist reparierbar, ein falsches Fach
    faellt niemandem auf.
    """
    raus = {"ressort": None, "ereignistyp": None, "themenfelder": [],
            "region": None, "sicher": bool(eintrag.get("sicher", True)),
            "verworfen": []}
    for feld in ("ressort", "ereignistyp", "region"):
        v = eintrag.get(feld)
        if isinstance(v, str) and v in tax[feld]:
            raus[feld] = v
        elif v:
            raus["verworfen"].append("%s=%s" % (feld, v))
    tf = eintrag.get("themenfelder") or []
    if isinstance(tf, str):
        tf = [tf]
    for v in tf[:4]:
        if isinstance(v, str) and v in tax["themenfelder"]:
            raus["themenfelder"].append(v)
        elif v:
            raus["verworfen"].append("themenfeld=%s" % v)
    return raus


def sichere(ergebnis, tax):
    """
    Nach JEDEM Batch schreiben. Ein Lauf ueber 1220 Artikel dauert laenger als
    jedes Zeitlimit, das man ihm setzt -- ohne Zwischenstand waere die Arbeit
    bei jedem Abbruch weg. Beim naechsten Start ueberspringt das Skript alles,
    was schon drinsteht.
    """
    os.makedirs(os.path.dirname(FACETTEN) or ".", exist_ok=True)
    tmp = FACETTEN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "hinweis": "GENERAT. Facetten pro Artikel-Link. Handkorrekturen "
                       "gehoeren in facetten_korrekturen.json.",
            "aktualisiert": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "taxonomie_stand": tax["_roh"].get("_stand"),
            "anzahl": len(ergebnis),
            "artikel": ergebnis,
        }, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FACETTEN)


def main(argv=None):
    # argv statt sys.argv, damit der Aufruf aus lauf.py nicht die Argumente
    # von ki_news.py mitliest.
    global FACETTEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--quelle", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--trocken", action="store_true")
    ap.add_argument("--ablage", default=None,
                    help="Datei mit den bereits klassifizierten Artikeln. "
                         "Vorgabe: out/facetten.json bzw. FACETTEN_ABLAGE.")
    args = ap.parse_args(argv)

    if args.ablage:
        FACETTEN = os.path.abspath(args.ablage)
    print("  Ablage: %s%s" % (FACETTEN,
                              "" if os.path.exists(FACETTEN) else "  (neu)"))

    tax = lade_taxonomie()
    system = baue_system(tax)

    # Quelle suchen: erst der Wert von --quelle, sonst die ueblichen Orte.
    # Der Sandbox-Pfad taugt nicht als Vorgabe -- unter Windows gibt es ihn nicht.
    quelle = args.quelle
    if not quelle:
        # Erst der Ordner ueber diesem -- so trifft es in GitHub Actions, wo
        # das Skript unter registry_bau/ im ausgecheckten Repo liegt. Dann der
        # uebliche Ort auf Daniels Rechner.
        for k in (os.path.join(os.path.dirname(HIER), "archive.json"),
                  os.path.join(os.path.expanduser("~"), "Documents", "Projekte",
                               "ki-news", "archive.json")):
            if os.path.exists(k):
                quelle = k
                break
    if not quelle or not os.path.exists(quelle):
        raise SystemExit("FEHLER: keine Artikelquelle gefunden. Mit --quelle angeben.")
    print("  Quelle: %s" % quelle)

    with open(quelle, encoding="utf-8") as f:
        d = json.load(f)
    artikel = d if isinstance(d, list) else (d.get("articles") or d.get("news") or [])

    schon = {}
    if os.path.exists(FACETTEN):
        with open(FACETTEN, encoding="utf-8") as f:
            schon = json.load(f).get("artikel", {})
    offen = [a for a in artikel if a.get("link") and a["link"] not in schon]
    if args.limit:
        offen = offen[:args.limit]

    print("Facetten-Klassifikation")
    print("  %d Artikel gesamt, %d bereits klassifiziert, %d offen"
          % (len(artikel), len(schon), len(offen)))

    if args.trocken:
        print("\n--- SYSTEM (%d Zeichen) ---\n%s" % (len(system), system))
        print("\n--- PROMPT, erster Batch ---\n%s" % baue_prompt(offen[:BATCH]))
        print("\n--trocken: nichts aufgerufen")
        return

    keys = lade_keys()
    verfuegbar = [p for p, _, kn, _ in BACKENDS if keys.get(kn)]
    if not verfuegbar:
        raise SystemExit(
            "FEHLER: kein Key gefunden. Erwartet GROQ_API_KEY, GEMINI_API_KEY "
            "oder OPENROUTER_KEY in der Umgebung oder in\n  %s" % SECRETS)
    print("  Backends mit Key: %s" % ", ".join(verfuegbar))

    ergebnis = dict(schon)
    stat = Counter()
    verworfen = Counter()
    modelle_genutzt = Counter()

    for i in range(0, len(offen), BATCH):
        batch = offen[i:i + BATCH]
        text, modell = rufe_llm(system, baue_prompt(batch), keys)
        arr = hole_json(text)
        if not arr:
            stat["batch_fehler"] += 1
            print("  Batch %d: keine verwertbare Antwort" % (i // BATCH + 1))
            continue
        modelle_genutzt[modell] += 1
        nach_nr = {e.get("nr"): e for e in arr if isinstance(e, dict)}
        for j, a in enumerate(batch, 1):
            e = nach_nr.get(j)
            if not e:
                stat["ohne_antwort"] += 1
                continue
            f = pruefe(e, tax)
            f["titel"] = (a.get("title") or "")[:180]
            f["datum"] = (a.get("first_seen") or a.get("date") or "")[:10]
            ergebnis[a["link"]] = f
            stat["ressort_" + (f["ressort"] or "KEINS")] += 1
            if not f["sicher"]:
                stat["unsicher"] += 1
            for v in f["verworfen"]:
                verworfen[v] += 1
        print("  Batch %d/%d ok (%s)"
              % (i // BATCH + 1, (len(offen) + BATCH - 1) // BATCH, modell))
        sichere(ergebnis, tax)
        time.sleep(4)   # Gemini-Freikontingent ist knapp

    n = sum(v for k, v in stat.items() if k.startswith("ressort_"))
    print("\n=== %d Artikel klassifiziert ===" % n)
    for k, v in sorted(((k, v) for k, v in stat.items()
                        if k.startswith("ressort_")), key=lambda kv: -kv[1]):
        print("  %-28s %4d  %5.1f%%" % (k[8:], v, v / max(n, 1) * 100))
    print("\n  unsicher (Seite nachladen): %d" % stat["unsicher"])
    print("  Batch-Fehler              : %d" % stat["batch_fehler"])
    print("  genutzte Modelle          : %s" % dict(modelle_genutzt))
    if verworfen:
        print("\n  Erfundene Werte (Top 10):")
        for k, v in verworfen.most_common(10):
            print("    %3dx %s" % (v, k))

    # Kill-Switch aus taxonomie.json
    keins = stat.get("ressort_KEINS", 0)
    groesstes = max((v for k, v in stat.items()
                     if k.startswith("ressort_") and k != "ressort_KEINS"),
                    default=0)
    if n:
        if keins / n > 0.15:
            print("\n  KILL-SWITCH: %.0f%% ohne Ressort (Grenze 15%%). "
                  "Taxonomie ueberarbeiten, NICHT den Prompt." % (keins / n * 100))
        if groesstes / n > 0.40:
            print("\n  KILL-SWITCH: groesstes Ressort bei %.0f%% (Grenze 40%%). "
                  "Liste zu grob." % (groesstes / n * 100))


if __name__ == "__main__":
    main()
