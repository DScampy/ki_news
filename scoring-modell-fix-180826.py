# -*- coding: utf-8 -*-
"""
Scoring-Fix 18.08.2026 — Modell-Launches erreichen die LLM-Bewertung nicht.

ANWENDEN:  python scoring-modell-fix-180826.py
           (im ki-news-Ordner, patcht ki_news.py an Ort und Stelle, legt .bak an)

ERST ANWENDEN, WENN DER SPRACH-GUARD-FIX LIVE UND VERIFIZIERT IST.
Sonst lassen sich die Wirkungen der beiden Aenderungen nicht trennen.

--------------------------------------------------------------------------
BEFUND (verifiziert an archive.json, 1040 Artikel, 08.-18.08.2026)

pick_top_news() Z.1144: legacy_results = [score_cluster(c) for c in clusters]
                Z.1146: nur die TOP 10 nach diesem Legacy-Score bekommen
                        ueberhaupt einen LLM-Call (LLM_SCORE_CANDIDATES = 10).

score_cluster() ist damit der Tuersteher fuer die intelligente Bewertung.
Seine Formel: source_score (Quellenzahl x 15, max 60) + prestige + keywords.

Am 14.07.2026 wurden "model"/"modell" aus KI_KEYWORDS_SUBSTR UND aus
IMPORTANCE_KEYWORDS entfernt — berechtigt, weil "modell" im Deutschen generisch
ist (Apple Pencil, Geschaeftsmodell) und einen Fehlalarm erzeugt hatte.
Nebenwirkung, bisher unbemerkt: es gibt seither KEIN Signal mehr fuer
"hier erscheint ein neues Modell".

Folge fuer eine Hersteller-Ankuendigung am Tag 0:
    1 Quelle x 15 + Prestige 10 + Keywords 0  =  ~25
    -> nicht unter den Top 10 -> kein LLM-Call -> behaelt 25 als Fallback
    -> Tagesverfall (-5/Tag) raeumt sie in 5 Tagen auf 0

Gemessen: 105 Artikel haengen exakt auf base_score 25. Darunter in 11 Tagen
12 echte Modell-Launches, u.a.:
    Claude Opus 5 wird vorgestellt              (Anthropic News, base 25 -> Rang 114)
    Muse Spark 1.1 wird vorgestellt             (Meta AI Blog,   base 25)
    Mistral AI stellt Forge vor                 (Mistral News,   base 25)
    Grok Imagine Quality Mode API eingefuehrt   (xAI News,       base 25)
    DeepSeek V4 Pro wird veroeffentlicht        (China AI Labs,  base 18)

Zum Vergleich dieselbe Nachricht aus zweiter Hand:
    "Google launches Gemini 3.7 Flash..."       (SiliconAngle,   base 77)

Die Formel belohnt strukturell das Nachbeben, nicht das Ereignis. Wer zuerst
berichtet — der Hersteller — hat per Definition eine Quelle.

--------------------------------------------------------------------------
FIX

Kein Schrauben am Endergebnis, nur die Tuer oeffnen: eine Release-Signatur
(Release-Verb UND Modellfamilie) gibt +20 im Legacy-Score. Damit kommt der
Launch unter die Top-10-Kandidaten und bekommt einen echten LLM-Score —
die inhaltliche Bewertung macht weiterhin das Modell, nicht die Heuristik.

Bewusst NICHT wieder eingefuehrt: nacktes "model"/"modell". Die Signatur
verlangt Release-Verb UND bekannte Modellfamilie — der Apple-Pencil-Fall
vom 14.07. matcht dabei nicht (kein Release-Verb + keine Modellfamilie).

Zusaetzlich -10 fuer Hersteller-Case-Studies ("Wie Zapier ... mit ChatGPT
transformiert"). Bewusst eng gefasst: Partnerschafts- und Kooperations-
Meldungen bekommen KEINEN Malus, die sind oft echte News.

KILL-SWITCH: Wenn nach 3 Laeufen kein einziger Modell-Launch in den Top 5
auftaucht, ist nicht die Keyword-Schicht das Problem, sondern die
source_score-Gewichtung (Quellenzahl x 15 dominiert). Dann NICHT weiter an
den Keywords drehen, sondern source_score deckeln — und das ist eine
Entscheidung fuer Daniel, keine Reparatur.

MESSUNG DANACH: ki-news-gold-standard-daily wieder aktivieren, 5 Tage
sammeln, gegen die Baseline 2,0/5 vergleichen (Phase-3-Iterationsgate).
"""
import io
import re
import shutil
import sys

ZIEL = "ki_news.py"

ANKER = '''# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)'''

NEU = '''# -------------------------
# Release-Signatur (Fix 18.08.26)
# -------------------------
# Warum: score_cluster() ist der Tuersteher fuer die LLM-Bewertung
# (pick_top_news: nur die Top-10 nach Legacy-Score bekommen einen LLM-Call).
# Seit dem 14.07.-Fix, der "model"/"modell" als zu generisch entfernt hat,
# gibt es kein Signal mehr fuer "hier erscheint ein neues Modell". Eine
# Hersteller-Ankuendigung am Tag 0 hat nur eine Quelle und landet damit bei
# ~25 Punkten - unter der Tuerschwelle. Gemessen an archive.json (08.-18.08.):
# 12 echte Launches haengen auf diesem Plateau, u.a. "Claude Opus 5 wird
# vorgestellt" (Rang 114 von 155).
#
# Der Fix gibt KEINE Endpunkte, er oeffnet nur die Tuer: mit +20 kommt der
# Launch unter die Kandidaten und wird inhaltlich vom LLM bewertet.
#
# Bewusst NICHT wieder eingefuehrt: nacktes "model"/"modell". Die Signatur
# verlangt Release-Verb UND Modellfamilie - der Apple-Pencil-Fehlalarm vom
# 14.07. erfuellt beides nicht.
RELEASE_VERBEN = re.compile(
    r"(stellt\\s+\\S+\\s+vor|vorgestellt|vorstellung von|veröffentlicht|"
    r"führt\\s+\\S+\\s+ein|eingeführt|launcht|launches|unveils|introduc\\w+|"
    r"debuts|ist da|is here|jetzt verfügbar|now available|ab sofort verfügbar|"
    r"angekündigt)", re.I)

MODELL_FAMILIEN = re.compile(
    r"\\b(gpt|claude|gemini|llama|mistral|qwen|deepseek|grok|kimi|glm|opus|"
    r"sonnet|haiku|muse|sora|veo|imagen|flux|nova|command|phi|falcon|voxtral|"
    r"nemotron|daybreak|mai-code)\\b", re.I)

# Hersteller-Case-Studies: Marketing im Nachrichtenkanal. Eng gefasst -
# Partnerschafts-/Kooperationsmeldungen bekommen bewusst KEINEN Malus.
CASE_STUDY = re.compile(
    r"(wie\\s+\\S+\\s+.*(nutzt|verwendet|transformiert|optimiert|einsetzt)|"
    r"case study|customer story|erfahrungsbericht)", re.I)

RELEASE_BONUS = 20
CASE_STUDY_MALUS = -10


def _release_signal(all_titles: str) -> int:
    """Punkte fuer 'hier erscheint ein neues Modell'. all_titles ist lowercase."""
    if CASE_STUDY.search(all_titles):
        return CASE_STUDY_MALUS
    if RELEASE_VERBEN.search(all_titles) and MODELL_FAMILIEN.search(all_titles):
        return RELEASE_BONUS
    return 0


# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)'''

ALT_TOTAL = """    total = source_score + prestige_score + kw_score + penalty_score
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""

NEU_TOTAL = """    release_score = _release_signal(all_titles)

    total = source_score + prestige_score + kw_score + penalty_score + release_score
    if release_score > 0:
        logger.debug("score_cluster: Release-Signatur erkannt (+%d) - %s",
                     release_score, all_titles[:70])
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""


def main():
    src = io.open(ZIEL, encoding="utf-8").read()

    if "_release_signal" in src:
        print("Fix ist bereits eingespielt - nichts zu tun.")
        return 0
    for anker, name in ((ANKER, "Marker-Block"), (ALT_TOTAL, "score_cluster-Summe")):
        if src.count(anker) != 1:
            print("ABBRUCH: Anker '%s' nicht eindeutig gefunden (%d Treffer)."
                  % (name, src.count(anker)))
            print("ki_news.py wurde seit dem 18.08. veraendert - Patch von Hand pruefen.")
            return 1

    shutil.copy(ZIEL, ZIEL + ".bak")
    src = src.replace(ANKER, NEU, 1)
    src = src.replace(ALT_TOTAL, NEU_TOTAL, 1)
    io.open(ZIEL, "w", encoding="utf-8").write(src)

    import py_compile
    py_compile.compile(ZIEL, doraise=True)
    print("OK - ki_news.py gepatcht, Backup liegt als ki_news.py.bak")
    print("Naechster Schritt: hochladen, 3 Laeufe beobachten, dann")
    print("ki-news-gold-standard-daily reaktivieren fuer die Nachher-Messung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
