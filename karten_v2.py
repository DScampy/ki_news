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

# Stil je Motiv (Daniel 26.09.: "kommt aufs Thema an")
STIL_JE_MOTIV = {
    "gericht": "blaupause", "politik": "blaupause", "rechenzentrum": "blaupause", "chip": "blaupause",
    "hack": "daten", "zahl": "daten", "netz": "daten",
    "energie": "tusche", "zitat": "tusche", "roboter": "tusche", "deal": "tusche",
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
    "roboter": "Roboter, humanoider Roboter, Automatisierung, autonome Fahrzeuge, Hardware-Geraet",
    "deal": "Zwei Firmen schliessen einen Vertrag, Partnerschaft, Uebernahme oder Liefervereinbarung",
    "netz": "Nichts davon passt eindeutig (allgemeine Produkt- oder Branchenmeldung)",
}
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
    regeln = [("hack", r"hack|leck|sicherheitsl|angriff|cyber"), ("gericht", r"gericht|klage|urteil|verbot"),
              ("energie", r"strom|energie|turbine|kraftwerk"), ("rechenzentrum", r"rechenzentr|data ?cent|gpu-cluster"),
              ("chip", r"chip|prozessor|modell"), ("deal", r"deal|partnerschaft|übernimmt|vertrag"),
              ("politik", r"regierung|gesetz|präsident|minister|trump|eu-"), ("roboter", r"roboter|humanoid"),
              ("zitat", r"warnt|sagt|fordert|kritisiert")]
    for motiv, muster in regeln:
        if re.search(muster, text, re.I):
            return motiv
    return "netz"


def karte_daten(headline, einordnung, summary="", source="", datum="", dauer=20, badge="Breaking"):
    text = "%s %s" % (headline or "", summary or "")
    # Reihenfolge wie im Text (erster genannter Anbieter = Hauptakteur, beim Deal Partner A)
    treffer = [(m.start(), n) for n, muster in ANBIETER for m in [re.search(muster, text)] if m]
    anbieter = [n for _, n in sorted(treffer)]
    geld = _geld(headline)
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    quelle_wahl = "regel"
    motiv, negativ = None, bool(_NEGATIV_WORTE.search(headline or ""))
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
    if motiv not in STIL_JE_MOTIV:
        motiv = _regel_motiv(headline or "")
    # Motive, die Daten brauchen, sonst ausweichen
    if motiv == "zahl" and not geld:
        motiv = "netz"
    # Deal-Szene zeigt zwei Partner-Zeichen -> nur mit zwei erkannten Anbietern
    # (die fruehere Titelanfang-Heuristik griff bei deutschen Substantiven daneben)
    if motiv == "deal" and len(anbieter) < 2:
        motiv = "zahl" if geld else "netz"
    k = {"stil": STIL_JE_MOTIV[motiv], "motiv": motiv, "titel": headline, "einordnung": einordnung,
         "quelle": source, "datum": datum, "dauer": dauer, "badge": badge, "anbieter": anbieter[:1],
         "negativ": negativ, "bildzeile": motiv.upper() if motiv != "netz" else "", "wahl": quelle_wahl}
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
