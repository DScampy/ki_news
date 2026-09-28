# -*- coding: utf-8 -*-
"""
Karten v2 (26.09.2026) — waehlt fuer eine News-Karte Stil, Motiv und Zahlen.

Daniel hat die Probe am 26.09. abgenommen (KIVault/02 Projekte/KI-News/karten-v2/).
Die Vorlage `breaking_news_card_v2.html` zeichnet eine Szene in einem von drei Stilen
(blaupause, tusche, daten); diese Datei liefert nur die Felder dafuer.

Grundsatz "auswaehlen statt erzeugen": kein Modell schreibt Code oder Text fuer die
Szene. Anbieter kommen aus einer festen Namensliste, Zahlen nur aus Treffern im Titel,
das Motiv waehlt Jev (TypeSafe) aus einer festen Liste. Ohne Key oder bei Fehlern
greift eine Stichwort-Regel - die Karte entsteht immer.

Oeffentliche Funktion: karte_daten(headline, einordnung, summary, source, datum,
dauer, badge) -> dict (JSON fuer {{KARTE_JSON}}).
"""
import json
import os
import re
import urllib.request

# Stile je Motiv (Daniel 26.09.: "kommt aufs Thema an"). 26.09. abends: Daniel fand die Karten zu
# gleichfoermig -> je Motiv mehrere passende Stile, Auswahl fest per Titel-Hash (gleicher Titel =
# gleiche Karte, verschiedene Titel = Abwechslung). Erster Eintrag = bisheriger Stil.
STILE_JE_MOTIV = {
    "gericht": ["blaupause", "zeitung", "kreide"], "politik": ["blaupause", "zeitung"],
    "rechenzentrum": ["blaupause", "daten"], "chip": ["blaupause", "daten", "kreide"],
    "hack": ["daten", "zeitung"], "zahl": ["daten", "zeitung", "kreide"], "netz": ["daten", "blaupause"],
    "energie": ["tusche", "blaupause"], "zitat": ["tusche", "zeitung", "kreide"],
    "roboter": ["tusche", "blaupause"], "deal": ["tusche", "zeitung"],
    "humanoid": ["tusche", "blaupause", "daten"], "auto": ["blaupause", "daten", "tusche"],
    "handy": ["daten", "tusche"], "forschung": ["kreide", "blaupause", "tusche"],
    "arbeit": ["tusche", "zeitung", "kreide"], "medizin": ["blaupause", "tusche"],
    "weltraum": ["daten", "blaupause"], "militaer": ["zeitung", "blaupause"], "bildung": ["kreide", "tusche"],
}
MOTIV_BESCHREIBUNG = {
    "gericht": "Gericht, Klage, Urteil, Verbot durch Behoerde, Regulierung mit Rechtsstreit",
    "politik": "Regierung, Gesetz, Politiker, Parlament, Staatsbesuch, Handelspolitik, Exportkontrolle",
    "rechenzentrum": "Rechenzentrum, Rechenleistung, Cloud-Infrastruktur, GPU-Cluster, Kapazitaet",
    "chip": "Chip, Prozessor, GPU-Hardware, neues KI-Modell oder Modell-Version wird vorgestellt",
    "hack": "Hackerangriff, Sicherheitsluecke, Datenleck, Missbrauch, Cyberangriff",
    "zahl": "Kern der Meldung ist eine Geldsumme: Finanzierung, Bewertung, Umsatz, Aktienkurs, Investition",
    "energie": "Strom, Energieversorgung, Kraftwerk, Turbine, Kuehlung, Stromverbrauch",
    "zitat": "Eine Person aeussert sich, warnt, fordert, kritisiert, gibt ein Interview",
    "roboter": "Industrieroboter, Roboterarm, Lieferroboter, Automatisierung in Fabrik oder Lager",
    "humanoid": "Humanoider Roboter mit Menschengestalt, z. B. Tesla Optimus, Figure, Unitree, Boston Dynamics Atlas",
    "auto": "Autonomes Fahren, Robotaxi, selbstfahrendes Auto, Waymo, Tesla FSD, Verkehr",
    "handy": "Smartphone, App, Chatbot-App, Assistent auf dem Handy, Verbraucher-Produkt, Update fuer Nutzer",
    "forschung": "Studie, Forschungsergebnis, wissenschaftliches Paper, Umfrage, Messung, Benchmark",
    "arbeit": "Jobs, Arbeitsmarkt, Beschaeftigte, Entlassungen, Buero, Gewerkschaft, Arbeitsalltag",
    "medizin": "Gesundheit, Medizin, Krankenhaus, Diagnose, Medikamente, Biologie, DNA",
    "weltraum": "Weltraum, Satellit, Rakete, Raumfahrt, Rechenzentrum im All",
    "militaer": "Militaer, Armee, Verteidigung, Drohnen, Krieg, Ruestung",
    "bildung": "Schule, Universitaet, Lernen, Lehrer, Studierende, Weiterbildung",
    "deal": "Zwei Firmen schliessen einen Vertrag, Partnerschaft, Uebernahme oder Liefervereinbarung",
    "netz": "Nichts davon passt eindeutig (allgemeine Produkt- oder Branchenmeldung)",
}
# Rueckwaerts-Kompatibilitaet (erster Stil je Motiv)
STIL_JE_MOTIV = {m: st[0] for m, st in STILE_JE_MOTIV.items()}

# Auftrag 6 (28.09.26): neue Stile, standardmaessig AUS - die Live-Karten bleiben unveraendert.
# Einschalten per Umgebungsvariable im Workflow:
#   KARTEN_NEUE_STILE="neon,typo,riso"  (oder "alle")  -> Stile kommen je Motiv zur Auswahl dazu
#   KARTEN_STIL_ZWANG="riso"                           -> jede Karte in diesem Stil (Vorschau/Test)
NEUE_STILE = ["neon", "typo", "riso"]
NEUE_STILE_JE_MOTIV = {
    "gericht": ["typo", "riso"], "politik": ["typo", "riso"], "rechenzentrum": ["neon"],
    "chip": ["neon", "typo"], "hack": ["neon", "typo"], "zahl": ["typo", "neon"], "netz": ["neon", "typo", "riso"],
    "energie": ["riso", "neon"], "zitat": ["typo", "riso"], "roboter": ["riso", "neon"], "deal": ["typo", "riso"],
    "humanoid": ["neon", "riso"], "auto": ["neon", "riso"], "handy": ["neon", "typo"], "forschung": ["riso", "typo"],
    "arbeit": ["riso", "typo"], "medizin": ["riso", "neon"], "weltraum": ["neon"], "militaer": ["riso", "typo"],
    "bildung": ["riso", "typo"],
}


def _aktive_neue_stile():
    roh = os.environ.get("KARTEN_NEUE_STILE", "").strip().lower()
    if roh in ("1", "alle", "all", "ja"):
        return list(NEUE_STILE)
    return [s for s in re.split(r"[,\s]+", roh) if s in NEUE_STILE]


def _stil(motiv, headline):
    """Fester Stil je Titel: FNV-Hash wie in der Vorlage, Index in STILE_JE_MOTIV
    (plus eingeschaltete neue Stile, siehe NEUE_STILE_JE_MOTIV)."""
    zwang = os.environ.get("KARTEN_STIL_ZWANG", "").strip().lower()
    alle = set(NEUE_STILE) | {st for liste in STILE_JE_MOTIV.values() for st in liste}
    if zwang in alle:
        return zwang
    h = 2166136261
    for ch in (headline or ""):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    aktiv = _aktive_neue_stile()
    stile = STILE_JE_MOTIV[motiv] + [st for st in NEUE_STILE_JE_MOTIV.get(motiv, []) if st in aktiv]
    return stile[h % len(stile)]


_TYPO_STOPP = set("""aber allem allen alles als also auch auf aus bei beim bereits beziehungsweise damit dann dass
dem den der des die dies diese diesem diesen dieser dieses doch durch eine einem einen einer eines etwa fuer für gegen
haben hat hatte ihre ihren ihrem jetzt kann kein keine mehr mit nach neue neuen neuer neues nicht noch nun oder ohne
sich sind soll sollen sowie ueber über unter vom von vor waren warum was weil weiter weitere welche wenn werden wie
will wird wurde zum zur zwischen laut bericht meldung heute""".split())


def typo_worte(headline, geld=None, anbieter=None, einordnung=""):
    """Stichworte fuer den Typo-Stil: nur Woerter, die woertlich im Titel stehen (Zahl, Modellname,
    Anbieter, dann die laengsten Hauptwoerter). Hoechstens drei, keine Erfindung."""
    titel = headline or ""
    worte = []
    if geld:
        worte.append(geld["zahl"])
    else:
        pr = _PROZENT.search(titel)
        if pr:
            worte.append(pr.group(1) + " %")
    m = _MODELL.search(titel)
    if m:
        worte.append(m.group(1))
    # Anbieter nur, wenn er vorne im Titel steht (Hauptakteur, nicht "... fuer Google-Kalender")
    muster = dict(ANBIETER).get(anbieter[0]) if anbieter else None
    treffer = re.search(muster, titel) if muster else None
    if treffer and treffer.start() < len(titel) * 0.5 and len(worte) < 2:
        worte.append(ANZEIGE.get(anbieter[0], anbieter[0]))
    # Hauptwoerter: lang und in der Einordnung wieder aufgegriffen = tragend fuer die Meldung
    eo = (einordnung or "").lower()
    kandidaten = []
    for i, tok in enumerate(re.split(r"[\s:;,.!?\u201e\u201c\"()/]+", titel)):
        for teil in tok.split("-"):
            teil = teil.strip("'’")
            if len(teil) < 5 or len(teil) > 20 or teil.lower() in _TYPO_STOPP or not teil[:1].isupper():
                continue
            echo = eo.count(teil.lower()[:6]) if len(teil) >= 6 else eo.count(teil.lower())
            kandidaten.append((-(len(teil) + 6 * min(echo, 2)), i, teil))
    for _, _, teil in sorted(kandidaten):
        if len(worte) >= 3:
            break
        if not any(teil.lower() in w.lower() or w.lower() in teil.lower() for w in worte):
            worte.append(teil)
    return worte[:3]


# Anbieter-Zeichen, die die Vorlage kennt (MARKEN in breaking_news_card_v2.html)
ANBIETER = [
    ("anthropic", r"\bAnthropic|\bClaude\b"), ("openai", r"\bOpenAI|\bChatGPT|\bGPT-\d"),
    ("google", r"\bGoogle|\bGemini\b|\bDeepMind"), ("meta", r"\bMeta\b|\bMetas\b|\bZuckerberg"),
    ("microsoft", r"\bMicrosoft|\bCopilot\b"), ("nvidia", r"\bNvidia|\bNVIDIA"),
    ("xai", r"\bxAI\b|\bGrok\b"), ("deepseek", r"\bDeepSeek"), ("mistral", r"\bMistral\b"),
    ("amazon", r"\bAmazon\b|\bAWS\b"),
]
_GELD = re.compile(r"(\d{1,4}(?:[.,]\d{1,3})?)\s*-?\s*(Billionen|Milliarden|Mrd\.?|Millionen|Mio\.?)"
                   r"\s*-?\s*(US-Dollar|Dollar|Euro|\$|€)", re.I)
_PROZENT = re.compile(r"(\d{1,3}(?:,\d)?)\s*(?:Prozent|%)")
_MODELL = re.compile(r"\b((?:GPT|Gemini|Claude|Opus|Sonnet|Llama|Grok|Qwen|DeepSeek|Mistral|Kimi)[- ]?[A-Za-z]*\s?\d+(?:[.,]\d+)?)\b")
_NEGATIV_WORTE = re.compile(r"stopp|gestoppt|beendet|gibt .* auf|aufgegeben|verbot|untersag|scheiter|abgesagt|"
                            r"streicht|kippt|verliert|entlass|klagt|verklagt|sperrt|blockiert", re.I)
JEV_API = "https://api.typesafe.ai/v1/systemone"
ANZEIGE = {"openai": "OpenAI", "xai": "xAI", "deepseek": "DeepSeek", "amazon": "Amazon", "anthropic": "Anthropic",
           "google": "Google", "meta": "Meta", "microsoft": "Microsoft", "nvidia": "Nvidia", "mistral": "Mistral"}


def _geld(headline):
    m = _GELD.search(headline or "")
    if not m:
        return None
    wert = float(m.group(1).replace(".", "").replace(",", ".")) if "," in m.group(1) else float(m.group(1))
    einheit = {"billionen": "Bio.", "milliarden": "Mrd.", "mrd": "Mrd.", "millionen": "Mio.", "mio": "Mio."}[
        m.group(2).lower().rstrip(".")]
    waehrung = "€" if m.group(3).lower() in ("euro", "€") else "$"
    text = ("%s %s %s" % (m.group(1).replace(".", ","), einheit, waehrung))
    return {"zahl": text, "zahl_wert": wert, "zahl_einheit": "%s %s" % (einheit, waehrung)}


def _jev(headline, summary, key):
    """Motiv (Choice) + negativ (Noul) in einem Aufruf. None bei Fehler."""
    body = json.dumps({
        "model": "jev-latest",
        "state": {"titel": headline, "zusammenfassung": (summary or "")[:400]},
        "questions": {
            "motiv": {"type": "choice",
                      "instructions": "Welches Bildmotiv passt am besten zu dieser KI-Nachricht (`titel`, `zusammenfassung`)?",
                      "criteria": MOTIV_BESCHREIBUNG},
            "negativ": {"type": "noul",
                        "instructions": "Beschreibt `titel`, dass etwas gestoppt, abgesagt, verboten, verloren oder "
                                        "gescheitert ist?",
                        "criteria": {"true": "Ja: Stopp, Absage, Verbot, Niederlage vor Gericht, Rueckzug, Scheitern.",
                                     "false": "Nein: Start, Wachstum, Ankuendigung, neutrale Meldung."}},
        }}).encode("utf-8")
    req = urllib.request.Request(JEV_API, data=body, headers={"Authorization": "Bearer " + key,
                                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        a = json.loads(r.read())["answers"]
    return a["motiv"]["choice"], a["motiv"].get("confidence", 0), float(a["negativ"]["noul"])


def _regel_motiv(text):
    """Rueckfall ohne Jev: erstes passendes Stichwort."""
    regeln = [("humanoid", r"humanoid|optimus|figure 0|unitree|atlas"), ("auto", r"robotaxi|autonom\w* fahr|waymo|selbstfahr"),
              ("militaer", r"milit|armee|drohne|pentagon|verteidigung|krieg"), ("medizin", r"medizin|klinik|krankenh|gesundheit|diagnos"),
              ("weltraum", r"weltraum|satellit|rakete|orbit"), ("bildung", r"schule|universit|studier|lehrer"),
              ("forschung", r"studie|forscher|umfrage|paper|benchmark"), ("arbeit", r"jobs?\b|arbeitsmarkt|entlass|gewerkschaft|beschäftigt"),
              ("handy", r"smartphone|iphone|android|\bapp\b"),
              ("hack", r"hack|leck|sicherheitsl|angriff|cyber"), ("gericht", r"gericht|klage|urteil|verbot"),
              ("energie", r"strom|energie|turbine|kraftwerk"), ("rechenzentrum", r"rechenzentr|data ?cent|gpu-cluster"),
              ("chip", r"chip|prozessor|modell"), ("deal", r"deal|partnerschaft|übernimmt|vertrag"),
              ("politik", r"regierung|gesetz|präsident|minister|trump|eu-"), ("roboter", r"roboter|humanoid"),
              ("zitat", r"warnt|sagt|fordert|kritisiert")]
    for motiv, muster in regeln:
        if re.search(muster, text, re.I):
            return motiv
    return "netz"


def karte_daten(headline, einordnung, summary="", source="", datum="", dauer=20, badge="Breaking", motiv_vorgabe=None):
    text = "%s %s" % (headline or "", summary or "")
    # Reihenfolge wie im Text (erster genannter Anbieter = Hauptakteur, beim Deal Partner A)
    treffer = [(m.start(), n) for n, muster in ANBIETER for m in [re.search(muster, text)] if m]
    anbieter = [n for _, n in sorted(treffer)]
    geld = _geld(headline)
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    quelle_wahl = "regel"
    motiv, negativ = None, bool(_NEGATIV_WORTE.search(headline or ""))
    if motiv_vorgabe in STILE_JE_MOTIV:
        # Vorschau/Kontaktbogen: Motiv der schon gerenderten Karte uebernehmen, kein Jev-Aufruf
        motiv, key = motiv_vorgabe, ""
    if key:
        try:
            motiv, conf, p_neg = _jev(headline, summary, key)
            negativ = p_neg >= 0.6
            quelle_wahl = "jev %.2f" % conf
            if conf < 0.5:
                # Jev unsicher -> neutrales Motiv statt einer Szene, die etwas Falsches behauptet
                motiv = "netz"
        except Exception as e:
            print("  [KARTE v2] Jev fehlgeschlagen (%s) - Stichwort-Regel" % e.__class__.__name__)
            motiv = None
    if motiv not in STILE_JE_MOTIV:
        motiv = _regel_motiv(headline or "")
    # Motive, die Daten brauchen, sonst ausweichen
    if motiv == "zahl" and not geld:
        motiv = "netz"
    # Deal-Szene zeigt zwei Partner-Zeichen -> nur mit zwei erkannten Anbietern
    # (die fruehere Titelanfang-Heuristik griff bei deutschen Substantiven daneben)
    if motiv == "deal" and len(anbieter) < 2:
        motiv = "zahl" if geld else "netz"
    k = {"stil": _stil(motiv, headline), "motiv": motiv, "titel": headline, "einordnung": einordnung,
         "quelle": source, "datum": datum, "dauer": dauer, "badge": badge, "anbieter": anbieter[:1],
         "negativ": negativ, "bildzeile": motiv.upper() if motiv != "netz" else "", "wahl": quelle_wahl}
    if k["stil"] == "typo":
        k["typo_worte"] = typo_worte(headline, geld, anbieter, einordnung)
    if geld:
        k.update(geld)
        k["zahl_label"] = "gestoppt" if negativ and motiv == "energie" else ""
    if motiv == "zahl":
        k["zahl_oben"] = " · ".join(ANZEIGE[a] for a in anbieter[:2])
        pr = _PROZENT.search(headline or "")
        if pr:
            steigt = re.search(r"steig|spring|legt .*zu|plus|hoch", headline, re.I)
            k["zweit_zahl"] = ("+" if steigt else "") + pr.group(1) + " %"
            k["zweit_label"] = "AKTIE" if re.search(r"aktie", headline, re.I) else ""
            k["kerzen"] = bool(steigt and re.search(r"aktie", headline, re.I))
    if motiv == "deal":
        k["partner"] = [ANZEIGE[a] for a in anbieter[:2]]
    if motiv == "chip":
        m = _MODELL.search(headline or "")
        k["chip_label"] = m.group(1) if m else ""
    if motiv == "gericht" and anbieter:
        k["parteien"] = ["Pentagon" if re.search(r"pentagon", headline, re.I) else "", anbieter[0].upper()]
    return k
