# -*- coding: utf-8 -*-
"""
Sammelpatch 19.08.2026 — drei Aenderungen in einem Upload.

ANWENDEN:  python patch-190826.py      (im ki-news-Ordner)
           legt ki_news.py.bak an, prueft per AST nach, rollt bei Fehler zurueck.

Basis: Repo-Stand 822b56f (19.08. 15:52), enthaelt den Sprach-Guard-Fix vom 18.08.
Ersetzt scoring-modell-fix-180826.py — dieses Skript enthaelt dessen Teil C mit.

--------------------------------------------------------------------------
TEIL A — Encoding: LaTeX-Escapes ohne geschweifte Klammern

Nach dem Sprach-Guard-Fix blieb ein Fall uebrig, gefunden am 19.08. in
archive.json (Eintrag vom 16.08., also vor dem Fix entstanden):

    Anthropics Bio-Waffen-Filter inaktiv f{"o}r ... 133 Millionen Anfragen ungesch"uzt
                                          ^^^^^^                             ^^^^^
                                          gefixt                             NICHT gefixt

`_fix_latex_escapes` kannte nur die Form mit Klammern. Die klammerlose Form
`"u` mitten im Wort blieb stehen.

Warum das eng gefasst werden MUSS: ein nacktes `"u` -> `ü` wuerde legitime
Anfuehrungszeichen zerstoeren (`der "Ultrafast"-Modus` -> `der ülträfast`).
Die Ersetzung greift deshalb nur, wenn links UND rechts ein Kleinbuchstabe
steht — also wirklich mitten im Wort:

    ungesch"uzt   -> ungeschützt      (h davor, z danach)
    der "Ultrafast"-Modus -> unveraendert   (Leerzeichen davor)
    KI"Agenten    -> unveraendert           (Grossbuchstabe, nicht in [oua])

RUECKWIRKEND WIRKT DAS NICHT. Was vor dem Fix in archive.json gelandet ist,
bleibt kaputt (aktuell 1 Eintrag vom 16.08.). Fuer den Altbestand liegt
`cleanup-archive-encoding.py` daneben — der laeuft NUR auf Zuruf und zeigt
erst einen Vorschlag, bevor er etwas schreibt.

--------------------------------------------------------------------------
TEIL B — Kyrillisch im deutschen Text

Im Summary desselben Eintrags stand:

    "... war fast ein Jahr lang senderстви, wodurch ..."
                                      ^^^^^ kyrillisch

Der Prompt verbietet Fremdschrift ausdruecklich (Z. 1855), aber der einzige
Code-Guard dagegen — `_CJK_PATTERN` / `_has_foreign_script()` — deckt nur
CJK/Kana/Hangul ab. Kyrillisch fiel durch.

Fix: die vorhandene Zeichenklasse um den kyrillischen Block erweitern.
Kein neuer Mechanismus, keine neue Entscheidungslogik — die bestehende
Behandlung greift dann automatisch mit.

Haeufigkeit: 1 Treffer in 1385 Eintraegen. Bewusst KEIN Verwerfen und kein
Zeichen-Strippen (das ergaebe "senderстви" -> "sender", also stillen
Textverlust). Die Lehre aus dem Sprach-Guard: ein Guard, der Inhalte
wegwirft, richtet mehr Schaden an als der Fehler, den er faengt.

--------------------------------------------------------------------------
TEIL C — Release-Signatur (unveraendert aus scoring-modell-fix-180826.py V2)

score_cluster() ist der Tuersteher fuer die LLM-Bewertung: nur die Top-N
nach diesem Legacy-Score bekommen einen LLM-Call. Seit dem 14.07.-Fix, der
"model"/"modell" als zu generisch entfernte, gibt es kein Signal mehr fuer
"hier erscheint ein neues Modell" — eine Hersteller-Ankuendigung am Tag 0
hat 1 Quelle, landet bei ~25 und kommt nie durch die Tuer.

Belegt an archive.json (08.-18.08.): 105 Artikel auf base_score 25, darunter
12 echte Launches. "Claude Opus 5 wird vorgestellt" stand auf Rang 114 von 155.

Gemessen gegen 188 echte Kandidaten: 37 Bonus-Treffer (3,4/Tag), 3 Malus,
11 von 11 belegten Launches erfasst, 7 von 7 Regressionsfaellen sauber.

LLM_SCORE_CANDIDATES geht 10 -> 13, damit die neuen Kandidaten anderen
Storys keinen Platz wegnehmen. Kosten: 3 LLM-Calls pro Lauf.
Wer das nicht will: CANDIDATES_NEU unten auf 10 setzen.

KILL-SWITCH (Teil C): Taucht nach 3 Laeufen kein Modell-Launch in den Top 5
auf, ist nicht die Keyword-Schicht das Problem, sondern die
source_score-Gewichtung (Quellenzahl x 15). Dann NICHT weiter an Keywords
drehen — source_score deckeln, und das ist Daniels Entscheidung.

MESSUNG DANACH: ki-news-gold-standard-daily reaktivieren, 5 Tage sammeln,
gegen Baseline 2,0/5 vergleichen (Phase-3-Iterationsgate).
"""
import io
import shutil
import sys

ZIEL = "ki_news.py"
CANDIDATES_NEU = 13

# ---------------------------------------------------------------- TEIL A
A_ALT = '''def _fix_latex_escapes(text: str) -> str:
    """LaTeX-Umlaut-Escapes durch echte Umlaute ersetzen. No-op wenn keine da."""
    t = text or ""'''

A_NEU = '''# Klammerlose Variante (Fund 19.08.26): 'ungesch"uzt' statt 'ungesch{"u}tzt'.
# Bewusst eng: nur zwischen zwei Kleinbuchstaben, sonst wuerden legitime
# Anfuehrungszeichen zerstoert (der "Ultrafast"-Modus bleibt unangetastet).
_LATEX_INLINE = re.compile(r'(?<=[a-zäöüß])"([oua])(?=[a-zäöüß])')
_INLINE_MAP = {"o": "ö", "u": "ü", "a": "ä"}


def _fix_latex_escapes(text: str) -> str:
    """LaTeX-Umlaut-Escapes durch echte Umlaute ersetzen. No-op wenn keine da."""
    t = text or ""
    if '"' in t:
        t = _LATEX_INLINE.sub(lambda m: _INLINE_MAP[m.group(1)], t)'''

# ---------------------------------------------------------------- TEIL B
B_ALT = """    _CJK_PATTERN = re.compile(r'[一-鿿぀-ヿ가-힣]')"""
B_NEU = """    # 19.08.26 um Kyrillisch erweitert: im Summary eines Eintrags vom 16.08.
    # stand "war fast ein Jahr lang senderстви" - der Guard griff nicht, weil
    # er nur CJK/Kana/Hangul kannte.
    _CJK_PATTERN = re.compile(r'[一-鿿぀-ヿ가-힣Ѐ-ӿ]')"""

# ---------------------------------------------------------------- TEIL C
C_ANKER = '''# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)'''

C_NEU = '''# -------------------------
# Release-Signatur (Fix 18.08.26, V2)
# -------------------------
# score_cluster() ist der Tuersteher fuer die LLM-Bewertung (pick_top_news:
# nur die Top-N nach Legacy-Score bekommen einen LLM-Call). Seit dem
# 14.07.-Fix, der "model"/"modell" als zu generisch entfernte, gibt es kein
# Signal mehr fuer "hier erscheint ein neues Modell". Eine Hersteller-
# Ankuendigung am Tag 0 hat 1 Quelle -> ~25 Punkte -> unter der Schwelle.
# Gemessen an archive.json (08.-18.08.): 105 Artikel auf base_score 25,
# darunter 12 echte Launches ("Claude Opus 5 wird vorgestellt" = Rang 114/155).
#
# Der Bonus ist KEIN Ranking, sondern ein Kandidatenfilter: er oeffnet die
# Tuer zur LLM-Bewertung. Ein Fehltreffer kostet einen LLM-Call, keine
# Sichtbarkeit — das LLM stuft ihn danach selbst zurueck.
#
# Bewusst NICHT wieder eingefuehrt: nacktes "model"/"modell". Die Signatur
# verlangt ein Release-Verb UND (Modellfamilie ODER Herstellerquelle) —
# der Apple-Pencil-Fehlalarm vom 14.07. erfuellt das nicht.

FIRST_PARTY_SOURCES = {
    "OpenAI", "Anthropic News", "Anthropic Research", "Meta AI Blog",
    "xAI News", "Mistral News", "Qwen Blog", "Kimi Blog",
    "Google AI Blog", "DeepMind",
}

# Trennbare Verben als Satzklammer suchen, NICHT mit fester Wortdistanz:
# "xAI stellt Grok Build vor" hat zwei Woerter dazwischen, "Google stellt das
# neue Gemini 3.7 Flash Modell fuer Programmierung und KI-Agenten vor" acht.
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

# An echten Fehltreffern kalibriert: trotz Release-Verb kein Produkt-Launch.
KEIN_LAUNCH = re.compile(
    r"(preisgestaltung|preise|preis|abrechnung|tarif|"
    r"forschungsartikel|forschungsagenda|technische blogs|whitepaper|"
    r"bösartig|angriff|schwachstelle|sicherheitsvorfall|"
    r"einheit|abteilung|team|stellt\\s+\\S+\\s+ein\\b|einstellung|"
    r"meetup|hackathon|summit|konferenz|webinar)", re.I)

# Hersteller-Case-Studies: Marketing im Nachrichtenkanal. Greift unabhaengig
# davon, ob der Satz mit "Wie" beginnt. Partnerschafts- und Kooperations-
# meldungen bekommen bewusst KEINEN Malus — die sind oft echte News.
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

C_ALT_TOTAL = """    total = source_score + prestige_score + kw_score + penalty_score
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""

C_NEU_TOTAL = """    release_score = _release_signal(all_titles, {item["source"] for item in cluster})

    total = source_score + prestige_score + kw_score + penalty_score + release_score
    if release_score:
        logger.debug("score_cluster: Release-Signatur %+d - %s", release_score, all_titles[:70])
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label"""

C_ALT_CAND = "    LLM_SCORE_CANDIDATES = 10"
C_NEU_CAND = """    # 19.08.26: von 10 auf {n} angehoben. Die Release-Signatur bringt ~3,4
    # zusaetzliche Kandidaten pro Lauf durch die Tuer - ohne diese Anhebung
    # wuerden sie andere Storys aus der LLM-Bewertung verdraengen.
    LLM_SCORE_CANDIDATES = {n}""".format(n=CANDIDATES_NEU)


def main():
    src = io.open(ZIEL, encoding="utf-8").read()

    if "_release_signal" in src and "_LATEX_INLINE" in src:
        print("Patch ist bereits eingespielt - nichts zu tun.")
        return 0

    ersetzungen = [
        (A_ALT, A_NEU, "A: _fix_latex_escapes"),
        (B_ALT, B_NEU, "B: _CJK_PATTERN"),
        (C_ANKER, C_NEU, "C: Release-Signatur"),
        (C_ALT_TOTAL, C_NEU_TOTAL, "C: score_cluster-Summe"),
    ]
    if CANDIDATES_NEU != 10:
        ersetzungen.append((C_ALT_CAND, C_NEU_CAND, "C: LLM_SCORE_CANDIDATES"))

    for alt, _neu, name in ersetzungen:
        if src.count(alt) != 1:
            print("ABBRUCH: Anker '%s' nicht eindeutig (%d Treffer)." % (name, src.count(alt)))
            print("ki_news.py weicht vom erwarteten Stand ab - Patch von Hand pruefen.")
            return 1

    shutil.copy(ZIEL, ZIEL + ".bak")
    for alt, neu, _name in ersetzungen:
        src = src.replace(alt, neu, 1)
    io.open(ZIEL, "w", encoding="utf-8").write(src)

    import py_compile
    py_compile.compile(ZIEL, doraise=True)

    # py_compile prueft nur Syntax. Eine Konstante, die versehentlich in einem
    # Kommentar landet, faellt dabei NICHT auf - deshalb explizit nachsehen.
    check = io.open(ZIEL, encoding="utf-8").read()
    pflicht = [
        ("_release_signal", "\ndef _release_signal"),
        ("_LATEX_INLINE", "\n_LATEX_INLINE = re.compile"),
        ("Kyrillisch-Block", "Ѐ-ӿ"),
    ]
    if CANDIDATES_NEU != 10:
        pflicht.append(("LLM_SCORE_CANDIDATES", "\n    LLM_SCORE_CANDIDATES = %d" % CANDIDATES_NEU))
    fehlt = [n for n, muster in pflicht if muster not in check]
    if fehlt:
        shutil.copy(ZIEL + ".bak", ZIEL)
        print("ABBRUCH: %s nicht auf Code-Ebene. Zurueckgerollt." % ", ".join(fehlt))
        return 1

    print("OK - ki_news.py gepatcht (A+B+C, LLM_SCORE_CANDIDATES = %d)" % CANDIDATES_NEU)
    print("Backup: ki_news.py.bak")
    print("Hochladen, dann 3 Laeufe beobachten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
