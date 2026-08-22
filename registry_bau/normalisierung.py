# -*- coding: utf-8 -*-
"""
!!! UEBERHOLT seit 20.08.2026 -- NICHT MEHR VERWENDEN !!!
=========================================================
Diese Datei loeste das Problem "Modellnamen aus News ableiten und
normalisieren". Das Problem gibt es nicht mehr: die OpenRouter-API liefert
die kanonische Liste direkt (331 Modelle, 52 Anbieter), News werden ihr
ZUGEORDNET statt aus ihr abgeleitet.

Ersatz: generiere_modelle_json.py

Zusaetzlich enthaelt diese Datei einen bekannten Fehler: "Flash" steht in
AUSBAUSTUFEN, ist bei Google aber Teil des Modellnamens ("Gemini 3.5 Flash
Lite" = Familie 'Gemini 3.5 Flash' + Stufe 'Lite'). Wer die Regeln hier
uebernimmt, uebernimmt den Fehler mit.

Aufgehoben als Referenz fuer die Zweifelsfall-Logik (LLM-Judge-Anbindung),
die im Zuordnungslauf noch gebraucht wird.
=========================================================

Normalisierung von Modellnamen — Regeln zuerst, LLM nur bei Zweifel.

Aufgabe: aus rohen Fundstellen ("Fable 5", "Claude Fable 5", "Qwen3", "Qwen3.8")
einen kanonischen Eintrag pro echtem Modell machen.

ENTWURF (Daniel, 20.08.): Die Regeln entscheiden die klaren Faelle. Wo sie
unsicher sind, wird der Fall als ZWEIFEL markiert und an einen LLM-Judge
gegeben — dieselbe Architektur wie beim Story-Clustering, wo das Muster
"deterministisches Gate, LLM nur fuer den Rest" schon steht.

DIE VIER REGELN

R1  Kanonische Form = Familie + Basisname + Version
    "Fable 5" -> "Claude Fable 5". Das Familienpraefix wird ERGAENZT, nicht
    entfernt: Hersteller schreiben es mal mit, mal ohne, aber die lange Form
    ist die eindeutige.

R2  Varianten-Suffixe sind ein eigenes Feld, kein Namensteil
    "Gemini 3.7 Flash"      -> basis "Gemini 3.7",  variante "Flash"
    "Nemotron 3.5 Lightning"-> basis "Nemotron 3.5",variante "Lightning"
    "GPT-5.6 Sol"           -> basis "GPT-5.6",     variante "Sol"
    "DeepSeek V4 Pro"       -> basis "DeepSeek V4", variante "Pro"
    Loest die zwei schwierigsten Faelle von selbst: GPT-5.6 und GPT-5.6 Sol
    sind dieselbe Basis mit und ohne Variante, bleiben aber unterscheidbar.

R3  Schreibweise vereinheitlichen
    Bindestriche/Leerzeichen zwischen Name und Zahl, Mehrfach-Leerzeichen,
    Gross-/Kleinschreibung der Version ("v4" = "V4").

R4  Praefix-Versionen sind ZWEIFEL, keine Entscheidung
    "Qwen3" vs "Qwen3.8": 3 ist ein Praefix von 3.8. Das kann eine Kurzform
    desselben Modells sein ODER eine echte Vorgaengerversion. Die Regel
    entscheidet das NICHT — sie markiert und gibt ab.

Aufruf:  python normalisierung.py            (Selbsttest mit echten Fundstellen)
"""
import re
import collections

VARIANTEN = ("Pro", "Max", "Mini", "Flash", "Turbo", "Ultra", "Thinking", "Sol",
             "Lightning", "Coder", "Preview", "Beta", "Instruct", "Reasoner",
             "Air", "Nano", "Plus", "Lite")
_VAR_RE = re.compile(r"\s+(%s)\s*$" % "|".join(VARIANTEN), re.I)
_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)\s*$")


def _r3_schreibweise(name):
    n = re.sub(r"\s+", " ", (name or "").strip())
    n = re.sub(r"\s*-\s*", "-", n)
    # "Qwen3.8" -> "Qwen 3.8", aber "GPT-5.6" und "MAI-Code-1.1" bleiben
    n = re.sub(r"(?<=[a-z])(?=\d)", " ", n)
    n = re.sub(r"\bv(\d)", r"V\1", n)
    return re.sub(r"\s+", " ", n).strip()


# Ausbaustufen (Pro/Mini/Max...) sind eine EIGENE Ebene unter der Variante.
# Daniels Fund 20.08.: "GPT-5.6 Sol Pro" - Basis GPT-5.6, Variante Sol,
# Ausbaustufe Pro. Daneben "GPT-5.6 Luna", "GPT-5.6 Terra" als Geschwister.
AUSBAUSTUFEN = ("Pro", "Max", "Mini", "Ultra", "Lite", "Nano", "Plus", "Air",
                "Turbo", "Flash", "Preview", "Beta", "Instruct", "Thinking")
_STUFE_RE = re.compile(r"\s+(%s)\s*$" % "|".join(AUSBAUSTUFEN), re.I)


def _r2_variante(name):
    """Schneidet von rechts ab: erst Ausbaustufe, dann Variante.

    Gibt (basis, variante, ausbaustufe) zurueck. Mehrteilige Suffixe wie
    "Sol Pro" werden dadurch korrekt in zwei Ebenen zerlegt statt in eine.
    """
    rest = name
    stufe = None
    m = _STUFE_RE.search(rest)
    if m:
        stufe = m.group(1).capitalize()
        rest = _STUFE_RE.sub("", rest).strip()
    variante = None
    m2 = _VAR_RE.search(rest)
    if m2 and not _VERSION_RE.search(m2.group(1)):
        variante = m2.group(1).capitalize()
        rest = _VAR_RE.sub("", rest).strip()
    return rest, variante, stufe


def _r1_familie(basis, familie):
    """Familienpraefix ergaenzen, falls es fehlt."""
    if not familie:
        return basis
    if basis.lower().startswith(familie.lower()):
        return basis
    # Familie steckt schon drin, nur nicht am Anfang? Dann nichts tun.
    if re.search(r"\b%s\b" % re.escape(familie), basis, re.I):
        return basis
    return "%s %s" % (familie, basis)


def normalisiere(rohname, familie=None):
    """Gibt (kanonisch, basis, variante, version, ausbaustufe) zurueck."""
    n = _r3_schreibweise(rohname)
    basis, variante, stufe = _r2_variante(n)
    basis = _r1_familie(basis, familie)
    m = _VERSION_RE.search(basis)
    version = m.group(1) if m else None
    kanonisch = " ".join(x for x in (basis, variante, stufe) if x)
    return kanonisch, basis, variante, version, stufe


def _ist_praefix_version(a, b):
    """R4: ist Version a ein echtes Praefix von b? ('3' von '3.8')"""
    if not a or not b or a == b:
        return False
    return b.startswith(a + ".")


def gruppiere(fundstellen):
    """fundstellen: Liste von dicts {name, familie, anbieter, n, quellen}

    Liefert (gruppen, zweifel). gruppen: kanonisch -> zusammengefuehrte Eintraege.
    zweifel: Paare, die die Regeln nicht entscheiden — Futter fuer den LLM-Judge.
    """
    norm = []
    for f in fundstellen:
        k, basis, var, ver, stufe = normalisiere(f["name"], f.get("familie"))
        norm.append({**f, "kanonisch": k, "basis": basis, "variante": var,
                     "version": ver, "stufe": stufe})

    gruppen = collections.defaultdict(lambda: {"n": 0, "quellen": set(), "rohnamen": set()})
    for e in norm:
        g = gruppen[e["kanonisch"]]
        g["n"] += e["n"]
        g["quellen"] |= set(e.get("quellen") or [])
        g["rohnamen"].add(e["name"])
        g["anbieter"] = e.get("anbieter")
        g["familie"] = e.get("familie")
        g["basis"] = e["basis"]
        g["variante"] = e["variante"]
        g["version"] = e["version"]
        g["stufe"] = e["stufe"]

    # R4: Praefix-Versionen innerhalb derselben Familie sind unentschieden
    zweifel = []
    keys = list(gruppen)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ga, gb = gruppen[a], gruppen[b]
            if ga.get("familie") != gb.get("familie"):
                continue
            va, vb = ga.get("version"), gb.get("version")
            if _ist_praefix_version(va, vb) or _ist_praefix_version(vb, va):
                zweifel.append((a, b, "Praefix-Version %s / %s" % (va, vb)))
    return gruppen, zweifel


# --------------------------------------------------------------------------
# Selbsttest mit den echten Fundstellen aus dem Phase-0-Scan (09.-19.08.2026)
# --------------------------------------------------------------------------
FUNDSTELLEN = [
    {"name": "Fable 5",               "familie": "Claude",   "anbieter": "Anthropic", "n": 6,  "quellen": ["a", "b"]},
    {"name": "Claude Fable 5",        "familie": "Claude",   "anbieter": "Anthropic", "n": 2,  "quellen": ["a"]},
    {"name": "Claude Opus 5",         "familie": "Claude",   "anbieter": "Anthropic", "n": 4,  "quellen": ["a"]},
    {"name": "Claude Sonnet 5",       "familie": "Claude",   "anbieter": "Anthropic", "n": 1,  "quellen": ["a"]},
    {"name": "GPT-5.6",               "familie": "GPT",      "anbieter": "OpenAI",    "n": 7,  "quellen": ["a", "b"]},
    {"name": "GPT-5.6 Sol",           "familie": "GPT",      "anbieter": "OpenAI",    "n": 7,  "quellen": ["a", "b", "c", "d"]},
    {"name": "GPT-5",                 "familie": "GPT",      "anbieter": "OpenAI",    "n": 2,  "quellen": ["a"]},
    {"name": "GPT-4",                 "familie": "GPT",      "anbieter": "OpenAI",    "n": 2,  "quellen": ["a"]},
    {"name": "Qwen3",                 "familie": "Qwen",     "anbieter": "Alibaba",   "n": 4,  "quellen": ["a"]},
    {"name": "Qwen3.8",               "familie": "Qwen",     "anbieter": "Alibaba",   "n": 3,  "quellen": ["a"]},
    {"name": "Qwen 3.8",              "familie": "Qwen",     "anbieter": "Alibaba",   "n": 2,  "quellen": ["a"]},
    {"name": "DeepSeek V4 Pro",       "familie": "DeepSeek", "anbieter": "DeepSeek",  "n": 10, "quellen": ["a", "b"]},
    {"name": "DeepSeek V4",           "familie": "DeepSeek", "anbieter": "DeepSeek",  "n": 5,  "quellen": ["a", "b"]},
    {"name": "Grok 4.6",              "familie": "Grok",     "anbieter": "xAI",       "n": 10, "quellen": ["a", "b", "c"]},
    {"name": "Gemini 3.7 Flash",      "familie": "Gemini",   "anbieter": "Google",    "n": 6,  "quellen": ["a", "b", "c", "d", "e"]},
    {"name": "Nemotron 3.5 Lightning", "familie": "Nemotron", "anbieter": "Nvidia",   "n": 4,  "quellen": ["a", "b"]},
    {"name": "Nemotron 4",            "familie": "Nemotron", "anbieter": "Nvidia",    "n": 2,  "quellen": ["a"]},
    {"name": "GLM-5.3",               "familie": "GLM",      "anbieter": "Z.ai",      "n": 4,  "quellen": ["a", "b"]},
    {"name": "Kimi K2.6",             "familie": "Kimi",     "anbieter": "Moonshot",  "n": 2,  "quellen": ["a"]},
    {"name": "MAI-Code-1.1",          "familie": "MAI",      "anbieter": "Microsoft", "n": 2,  "quellen": ["a"]},
    {"name": "Mistral Medium 3.5",    "familie": "Mistral",  "anbieter": "Mistral",   "n": 2,  "quellen": ["a"]},
    {"name": "Seedance 2.5",          "familie": "Seedance", "anbieter": "Wizstar",   "n": 3,  "quellen": ["a"]},
]

if __name__ == "__main__":
    gruppen, zweifel = gruppiere(FUNDSTELLEN)
    print("Fundstellen: %d  ->  kanonische Eintraege: %d\n" % (len(FUNDSTELLEN), len(gruppen)))

    nach_anbieter = collections.defaultdict(list)
    for k, g in gruppen.items():
        nach_anbieter[g["anbieter"]].append((k, g))
    for anb in sorted(nach_anbieter):
        print(anb)
        for k, g in sorted(nach_anbieter[anb], key=lambda x: -x[1]["n"]):
            zusammengefuehrt = " <- " + " + ".join(sorted(g["rohnamen"])) if len(g["rohnamen"]) > 1 else ""
            teile = [x for x in (g["variante"], g.get("stufe")) if x]
            var = "  [%s]" % " / ".join(teile) if teile else ""
            print("   %-26s %3dx%s%s" % (k, g["n"], var, zusammengefuehrt))
        print()

    print("=" * 66)
    if zweifel:
        print("ZWEIFEL — Regeln entscheiden nicht, gehen an den LLM-Judge (%d):" % len(zweifel))
        for a, b, grund in zweifel:
            print("   %-22s <-> %-22s  (%s)" % (a, b, grund))
    else:
        print("Keine Zweifelsfaelle — Regeln reichen fuer diesen Datensatz.")
    print("=" * 66)
    quote = 100.0 * (len(gruppen) - len(zweifel)) / len(gruppen)
    print("Regelquote: %.0f%% der Eintraege ohne LLM entschieden" % quote)
