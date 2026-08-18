# -*- coding: utf-8 -*-
"""
Scoring-Fix 18.08.2026 — Modell-Launches erreichen die LLM-Bewertung nicht.
VERSION 2 (nach Gegenpruefung, drei echte Regex-Luecken behoben)

ANWENDEN:  python scoring-modell-fix-180826.py
           (im ki-news-Ordner, patcht ki_news.py an Ort und Stelle, legt .bak an)

ERST ANWENDEN, WENN DER SPRACH-GUARD-FIX LIVE UND VERIFIZIERT IST.

--------------------------------------------------------------------------
WAS SICH GEGENUEBER VERSION 1 GEAENDERT HAT

V1 wurde gegen 9 selbst ausgesuchte Testfaelle geprueft. Das war zirkulaer —
die Faelle, die im Befund als BELEG standen, waren nicht darunter. Drei
echte Luecken kamen so durch:

1. `stellt\\s+\\S+\\s+vor` fing nur EIN Wort zwischen "stellt" und "vor".
   "xAI stellt Grok Build vor" (zwei Woerter) fiel durch — ausgerechnet ein
   Beleg aus dem Befund. Behoben: trennbare Verben werden jetzt als Klammer
   im Satz gesucht (`stellt .* vor`), nicht mit fester Wortdistanz.
   Betrifft auch "Google stellt das neue Gemini 3.7 Flash Modell ... vor"
   (acht Woerter dazwischen) und "Meta fuehrt Muse Image und Muse Video ein".

2. Produkt-/Modus-Launches ohne Modellfamilie im Titel fielen durch.
   Behoben: die Herstellerquelle zaehlt als gleichwertiges Signal —
   Release-Verb UND (Modellfamilie ODER First-Party-Feed).
   Fangt jetzt "Grok Imagine Quality Mode API wird eingefuehrt" (xAI News).

3. CASE_STUDY verlangte "Wie ..." am Satzanfang. "Virgin Atlantic optimiert
   die Customer Journeys mit ChatGPT Work" bekam keinen Malus, obwohl der
   Befund ihn als Beispiel auffuehrte. Behoben: zusaetzliches Muster
   "<Verb> ... mit <Produktname>" plus "customer journey".

Neu dazu: Ausschlussliste KEIN_LAUNCH. Bei der Messung gegen echte Daten
fielen Preisaenderungen, Forschungsblogs, Sicherheitsvorfaelle und
Personaleinstellungen ("stellt X ein") als Fehltreffer auf.

--------------------------------------------------------------------------
BEFUND (unveraendert, verifiziert an archive.json, 1040 Artikel, 08.-18.08.)

pick_top_news() Z.1144: legacy_results = [score_cluster(c) for c in clusters]
                Z.1146: sortiert danach, nur die TOP 10 bekommen einen
                        LLM-Call (LLM_SCORE_CANDIDATES = 10)

score_cluster() ist damit der Tuersteher fuer die intelligente Bewertung.
Formel: source_score (Quellenzahl x 15, max 60) + prestige + keywords.

Am 14.07.2026 wurden "model"/"modell" aus KI_KEYWORDS_SUBSTR UND aus
IMPORTANCE_KEYWORDS entfernt (berechtigt: "modell" ist im Deutschen generisch,
Apple-Pencil-Fehlalarm). Nebenwirkung, bisher unbemerkt: kein Signal mehr fuer
"hier erscheint ein neues Modell".

Hersteller-Ankuendigung am Tag 0:
    1 Quelle x 15 + Prestige 10 + Keywords 0 = ~25  -> unter der Tuerschwelle
    -> kein LLM-Call -> behaelt 25 -> Verfall (-5/Tag) raeumt sie in 5 Tagen auf 0

105 Artikel haengen exakt auf base_score 25. Darunter 12 echte Launches,
u.a. "Claude Opus 5 wird vorgestellt" (Rang 114 von 155).
Dieselbe Nachricht aus zweiter Hand: base 77-89.

--------------------------------------------------------------------------
MESSUNG V2 (gegen 188 echte Kandidaten aus archive.json, nicht kuratiert)

  37 Artikel bekommen den Bonus  = 3,4 pro Tag
   3 Artikel bekommen den Malus
  10 von 10 der im Befund als Beleg genannten Launches werden erfasst

Ehrlich zur Trefferqualitaet: von den 37 sind rund 7 Feature- oder
Produktankuendigungen statt Modell-Launches (ElevenLabs MCP-Connector,
xAI Connectors, Google Credentio, Gemini App-Integrationen). Das ist
vertretbar, WEIL der Bonus kein Ranking ist, sondern nur ein Kandidatenfilter:
Wer durch die Tuer kommt, wird vom LLM inhaltlich bewertet und faellt dort
zurueck, wenn er nichts hergibt. Ein Fehltreffer kostet einen LLM-Call,
keine Sichtbarkeit.

ABER: 3,4 Bonus-Artikel pro Tag bei 10 Kandidatenplaetzen ist ein Drittel.
Ohne Gegenmassnahme verdraengt der Fix andere Storys aus der LLM-Bewertung.
Deshalb hebt dieser Patch LLM_SCORE_CANDIDATES von 10 auf 13 — der Fix nimmt
damit niemandem etwas weg. Kosten: 3 zusaetzliche LLM-Calls pro Lauf.
Wer das nicht will: CANDIDATES_NEU unten auf 10 setzen, dann bleibt alles
beim Alten und die Release-Kandidaten konkurrieren um dieselben 10 Plaetze.

--------------------------------------------------------------------------
KILL-SWITCH

Taucht nach 3 Laeufen kein einziger Modell-Launch in den Top 5 auf, ist nicht
die Keyword-Schicht das Problem, sondern die source_score-Gewichtung
(Quellenzahl x 15 dominiert alles). Dann NICHT weiter an Keywords drehen —
source_score deckeln. Das ist eine Entscheidung fuer Daniel, keine Reparatur.

MESSUNG DANACH: ki-news-gold-standard-daily reaktivieren, 5 Tage sammeln,
gegen Baseline 2,0/5 vergleichen (Phase-3-Iterationsgate).
"""
import io
import shutil
import sys

ZIEL = "ki_news.py"
CANDIDATES_NEU = 13          # auf 10 setzen, wenn keine zusaetzlichen LLM-Calls gewuenscht

ANKER = '''# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)'''

NEU = '''# -------------------------
# Release-Signatur (Fix 18.08.26, V2)
# -------------------------
# Warum: score_cluster() ist der Tuersteher fuer die LLM-Bewertung
# (pick_top_news: nur die Top-N nach Legacy-Score bekommen einen LLM-Call).
# Seit dem 14.07.-Fix, der "model"/"modell" als zu generisch entfernt hat,
# gibt es kein Signal mehr fuer "hier erscheint ein neues Modell". Eine
# Hersteller-Ankuendigung am Tag 0 hat nur eine Quelle und landet bei ~25 —
# unter der Tuerschwelle. Gemessen an archive.json (08.-18.08.): 105 Artikel
# haengen auf base_score 25, darunter 12 echte Launches, u.a. "Claude Opus 5
# wird vorgestellt" (Rang 114 von 155).
#
# Der Bonus ist KEIN Ranking, sondern ein Kandidatenfilter: er oeffnet die
# Tuer zur LLM-Bewertung. Ein Fehltreffer kostet einen LLM-Call, keine
# Sichtbarkeit — das LLM stuft ihn danach selbst zurueck.
#
# Bewusst NICHT wieder eingefuehrt: nacktes "model"/"modell". Die Signatur
# verlangt ein Release-Verb UND (Modellfamilie ODER Herstellerquelle) —
# der Apple-Pencil-Fehlalarm vom 14.07. erfuellt das nicht.

# Feeds, die der Hersteller selbst betreibt. Eine Ankuendigung von dort hat
# per Definition nur eine Quelle, genau am Tag 0.
FIRST_PARTY_SOURCES = {
    "OpenAI", "Anthropic News", "Anthropic Research", "Meta AI Blog",
    "xAI News", "Mistral News", "Qwen Blog", "Kimi Blog",
    "Google AI Blog", "DeepMind",
}

# Trennbare Verben als Klammer im Satz suchen, NICHT mit fester Wortdistanz.
# ("xAI stellt Grok Build vor" hat zwei Woerter dazwischen, "Google stellt das
#  neue Gemini 3.7 Flash Modell fuer Programmierung und KI-Agenten vor" acht.)
RELEASE_TRENNBAR = re.compile(
    r"(stellt\\b.*\\bvor\\b|führt\\b.*\\bein\\b|bringt\\b.*\\b(heraus|auf den markt)\\b)", re.I)

RELEASE_DIREKT = re.compile(
    r"(vorgestellt|vorstellung von|veröffentlicht|veroeffentlicht|eingeführt|"
    r"launcht|launches|unveils|introduc\\w+|debuts|releases?|ist da|is here|"
    r"jetzt verfügbar|now available|ab sofort verfügbar|angekündigt|startet)", re.I)

MODELL_FAMILIEN = re.compile(
    r"\\b(gpt|claude|gemini|llama|mistral|qwen|deepseek|grok|kimi|glm|opus|"
    r"sonnet|haiku|muse|sora|veo|imagen|flux|nova|command|phi|falcon|voxtral|"
    r"nemotron|daybreak|mai-code|seedance|minimax)\\b", re.I)

# An echten Fehltreffern kalibriert: das hier ist trotz Release-Verb kein
# Produkt-Launch (Preisaenderung, Forschungsblog, Sicherheitsvorfall,
# Personaleinstellung "stellt X ein", Veranstaltung).
KEIN_LAUNCH = re.compile(
    r"(preisgestaltung|preise|preis|abrechnung|tarif|"
    r"forschungsartikel|forschungsagenda|technische blogs|whitepaper|"
    r"bösartig|angriff|schwachstelle|sicherheitsvorfall|"
    r"einheit|abteilung|team|stellt\\s+\\S+\\s+ein\\b|einstellung|"
    r"meetup|hackathon|summit|konferenz|webinar)", re.I)

# Hersteller-Case-Studies: Marketing im Nachrichtenkanal. Greift unabhaengig
# davon, ob der Satz mit "Wie" beginnt. Partnerschafts- und Kooperations-
# meldungen bekommen bewusst KEINEN Malus, die sind oft echte News.
CASE_STUDY = re.compile(
    r"(wie\\s+\\S+.*(nutzt|verwendet|transformiert|optimiert|einsetzt)|"
    r"case study|customer story|erfahrungsbericht|customer journey|"
    r"\\b(optimiert|transformiert|automatisiert|beschleunigt)\\b.*"
    r"\\bmit\\s+(chatgpt|claude|gemini|copilot|mistral|grok)\\b)", re.I)

RELEASE_BONUS = 20
CASE_STUDY_MALUS = -10


def _release_signal(all_titles: str, sources=()) -> int:
    """Punkte fuer 'hier erscheint ein neues Modell/Produkt'.

    all_titles ist lowercase (kommt aus score_cluster), sources ist die Menge
    der Quellennamen im Cluster.
    """
    if CASE_STUDY.search(all_titles):
        return CASE_STUDY_MALUS
    if KEIN_LAUNCH.search(all_titles):
        return 0
    if not (RELEASE_TRENNBAR.search(all_titles) or RELEASE_DIREKT.search(all_titles)):
        return 0
    if MODELL_FAMILIEN.search(all_titles):
        return RELEASE_BONUS
    if any(s in FIRST_PARTY_SOURCES for s in sources):
        return RELEASE_BONUS
    return 0


# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)'''

ALT_TOTAL = """    total = source_score + prestige_score + kw_score + penalty_score
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""

NEU_TOTAL = """    release_score = _release_signal(all_titles, {item["source"] for item in cluster})

    total = source_score + prestige_score + kw_score + penalty_score + release_score
    if release_score:
        logger.debug("score_cluster: Release-Signatur %+d - %s", release_score, all_titles[:70])
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""

ALT_CAND = "    LLM_SCORE_CANDIDATES = 10"
NEU_CAND = """    # 18.08.26: von 10 auf {n} angehoben. Die Release-Signatur bringt ~3,4
    # zusaetzliche Kandidaten pro Lauf durch die Tuer - ohne diese Anhebung
    # wuerden sie andere Storys aus der LLM-Bewertung verdraengen.
    LLM_SCORE_CANDIDATES = {n}""".format(n=CANDIDATES_NEU)


def main():
    src = io.open(ZIEL, encoding="utf-8").read()

    if "_release_signal" in src:
        print("Fix ist bereits eingespielt - nichts zu tun.")
        return 0

    anker = [(ANKER, "Marker-Block"), (ALT_TOTAL, "score_cluster-Summe")]
    if CANDIDATES_NEU != 10:
        anker.append((ALT_CAND, "LLM_SCORE_CANDIDATES"))
    for a, name in anker:
        if src.count(a) != 1:
            print("ABBRUCH: Anker '%s' nicht eindeutig (%d Treffer)." % (name, src.count(a)))
            print("ki_news.py hat sich seit dem 18.08. veraendert - Patch von Hand pruefen.")
            return 1

    shutil.copy(ZIEL, ZIEL + ".bak")
    src = src.replace(ANKER, NEU, 1).replace(ALT_TOTAL, NEU_TOTAL, 1)
    if CANDIDATES_NEU != 10:
        src = src.replace(ALT_CAND, NEU_CAND, 1)
    io.open(ZIEL, "w", encoding="utf-8").write(src)

    import py_compile
    py_compile.compile(ZIEL, doraise=True)

    # py_compile prueft nur Syntax. Eine Konstante, die versehentlich in einem
    # Kommentar landet, faellt dabei NICHT auf - deshalb hier explizit nachsehen,
    # dass beide Namen wirklich auf Code-Ebene stehen. (Genau dieser Fehler ist
    # beim Bau dieses Skripts einmal passiert.)
    check = io.open(ZIEL, encoding="utf-8").read()
    fehlt = [n for n, muster in (
        ("_release_signal", "\ndef _release_signal"),
        ("LLM_SCORE_CANDIDATES", "\n    LLM_SCORE_CANDIDATES = %d" % CANDIDATES_NEU),
    ) if muster not in check]
    if fehlt:
        shutil.copy(ZIEL + ".bak", ZIEL)
        print("ABBRUCH: %s steht nicht auf Code-Ebene. Aenderung zurueckgerollt." % ", ".join(fehlt))
        return 1

    print("OK - ki_news.py gepatcht (LLM_SCORE_CANDIDATES = %d), Backup: ki_news.py.bak" % CANDIDATES_NEU)
    print("Naechster Schritt: hochladen, 3 Laeufe beobachten, dann")
    print("ki-news-gold-standard-daily reaktivieren fuer die Nachher-Messung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
