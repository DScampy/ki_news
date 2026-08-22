"""
generate_news_cards.py
======================
Liest news.json, ruft Groq API für Einordnung auf, befüllt das HTML-Template,
generiert Audio via Google Cloud TTS (Studio-C weiblich / Studio-B männlich,
pro Karte zufällig gewählt), startet record.js (Playwright) für jede Karte,
schreibt cards.json.

Ablauf:
  1. news.json einlesen → Top-N Storys nach Score
  2. Groq API → Einordnung (3–4 Sätze, ScampyKI-Stimme)
  3. Google TTS → MP3 (bestimmt Video-Länge)
  4. HTML-Template befüllen → /tmp/cards/<id>.html
  5. record.js aufrufen → assets/cards/<id>.mp4 (mit Audio)
  6. cards.json schreiben
"""

import base64
import json
import os
import random
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

# ─── Konfiguration ────────────────────────────────────────────────────────────

GROQ_API_KEY     = os.environ.get("GROQ_CHAT_KEY", "")
GROQ_URL         = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS      = [
    "openai/gpt-oss-120b",       # Ersatz fuer llama-3.3-70b-versatile (Groq schaltet es 16.08.2026 ab)
    "gemma2-9b-it",
    "llama-3.1-8b-instant",      # schnellstes als letzter Fallback
]

OPENROUTER_KEY    = os.environ.get("OPENROUTER_KEY", "")
OPENROUTER_URL    = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS = [
    "google/gemma-4-31b-it:free",              # Quality 65 — bestes Free-Modell
    "nvidia/nemotron-3-super-120b-a12b:free",  # Quality 60 — Nvidia 120B, 1M ctx
    # 22.08.26: openai/gpt-oss-120b:free und meta-llama/llama-3.3-70b-instruct:free
    # entfernt. Beide :free-Varianten stehen nicht mehr im OpenRouter-Katalog
    # (Live-Abgleich 22.08. ueber /api/v1/models). Achtung, nicht verwechseln:
    # "openai/gpt-oss-120b" OHNE :free-Suffix in GROQ_MODELS weiter oben ist ein
    # Groq-Modell und laeuft weiterhin - das ist ein anderer Anbieter.
    "z-ai/glm-5.2:free",                       # 22.08. neu im Katalog, live geprueft
    "google/gemini-2.5-flash-lite",            # bezahlter Anker, $0.10/$0.40 je 1M
    "meta-llama/llama-3.3-70b-instruct",       # paid Anker
]

GOOGLE_TTS_KEY   = os.environ.get("GOOGLE_TTS_KEY", "")
# Zwei Studio-Stimmen, pro Karte zufaellig gewaehlt (random.choice in main()) —
# kein festes Muster, keine Alternierung. (name, ssmlGender) muss zusammenpassen,
# sonst kann die Google-API unerwartet reagieren.
# STAND 16.07.26: de-DE-Studio-B klingt laut Daniels Hoerbeleg in Live-Karten
# maennlich (unkontrollierter Beleg — voice_used der konkret gehoerten Karten
# wurde nicht rekonstruiert). Fuer kontrollierte Verifikation: eine Karte mit
# voice_used=de-DE-Studio-B aus cards.json gezielt anhoeren und dieses Datum
# hier eintragen. Bis dahin gilt die Zuordnung als plausibel, nicht als bewiesen.
GOOGLE_TTS_VOICES = [
    ("de-DE-Studio-C", "FEMALE"),
    ("de-DE-Studio-B", "MALE"),
]

# ── Farb-Themes: pro Karte zufaellig gewaehlt (--bg/--cyan/--orange/--text/...) ──
# Ueberschreibt die :root-Defaults im Template via injiziertem <style>-Block
# (siehe THEME_CSS in fill_template-Aufruf). Erste Palette = bisheriger Standard.
CARD_THEMES = [
    {"bg": "#03060F", "cyan": "#00E5FF", "orange": "#FF6B00", "text": "#E8EDF8",
     "muted": "rgba(232,237,248,.55)", "dimgrey": "rgba(232,237,248,.28)"},
    {"bg": "#0A0414", "cyan": "#FF2E9A", "orange": "#C6FF00", "text": "#F3E8FF",
     "muted": "rgba(243,232,255,.55)", "dimgrey": "rgba(243,232,255,.28)"},
    {"bg": "#0B0620", "cyan": "#9D4EFF", "orange": "#FFC542", "text": "#EDE7FA",
     "muted": "rgba(237,231,250,.55)", "dimgrey": "rgba(237,231,250,.28)"},
    {"bg": "#020A04", "cyan": "#39FF6A", "orange": "#FF3B3B", "text": "#E4FBE9",
     "muted": "rgba(228,251,233,.55)", "dimgrey": "rgba(228,251,233,.28)"},
    {"bg": "#03101A", "cyan": "#2FB8FF", "orange": "#FF6F61", "text": "#E6F4FB",
     "muted": "rgba(230,244,251,.55)", "dimgrey": "rgba(230,244,251,.28)"},
]

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "9096438")

TOP_N          = 5
CARD_WIDTH     = 420
CARD_HEIGHT    = 660
CARD_DURATION  = 8     # Fallback-Dauer wenn kein TTS
MAX_DURATION   = 35    # Hard-Cap: niemand hört sich eine 50s-Karte an
MAX_SENTENCES  = 3      # Einordnung wird auf max. N Sätze gekappt (Text + TTS) — von 4 auf 3
                         # reduziert, da 4 Saetze TTS oft ueber MAX_DURATION (35s) trieben
                         # und den Hard-Cap mitten im Satz zuschlagen liessen
FORCE_RENDER   = os.environ.get("FORCE_RENDER", "0") == "1"

MAX_STATE_LINKS  = 60   # wie telegram_state.json: nur die juengsten Links merken
MAX_CARDS_DISPLAY = 20  # cards.json akkumuliert ueber mehrere Laeufe statt geleert zu werden

ROOT_DIR       = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent))

NEWS_JSON      = ROOT_DIR / "news.json"
ASSETS_DIR     = ROOT_DIR / "assets" / "cards"
TEMPLATE_PATH  = Path(__file__).with_name("breaking_news_card_template.html")
RECORD_JS      = Path(__file__).with_name("record.js")
CARDS_JSON     = ROOT_DIR / "cards.json"
CARD_STATE_JSON = ROOT_DIR / "card_state.json"  # Dedup-Gedaechtnis, analog telegram_state.json
DASHBOARD_CONFIG_JSON = ROOT_DIR / "dashboard_config.json"  # featured_links/force_cards (Admin-Pin)
TMP_DIR        = Path("/tmp/cards")

# TTS-Akronyme: werden per SSML <say-as interpret-as="characters"> buchstabiert,
# damit die Studio-Voice die DEUTSCHE Buchstabier-Aussprache nutzt statt die
# englische zu raten. Bug 25.06.: "xAI" -> "schai" (kein Eintrag vorhanden),
# "KI" trotz altem Text-Trick "K I" -> "kai" (reiner Text mit Leerzeichen
# zwingt die Stimme NICHT zur Buchstabier-Phonetik - SSML-Markup schon).
# Erweiterbar, sobald neue Faelle auffallen.
TTS_SPELL_OUT = {"KI", "xAI", "RL", "LLM", "API", "GPU", "CPU", "NSFW", "HBM", "DRAM"}

# TTS-Wortersatz: ganze Woerter mit falscher Betonung, die KEINE Buchstabier-
# Faelle sind (z.B. "SpaceX" - kein Akronym, sondern ein Markenname mit
# Grossbuchstaben-X mittendrin; "Space X" wird normal vorgelesen).
PRONOUNCE_FIXES = {
    "SpaceX": "Space X",
}


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def build_tts_ssml(text: str) -> str:
    """Baut SSML aus Klartext fuer die Google-TTS-Synthese. Reihenfolge wichtig:
    1) PRONOUNCE_FIXES (Wortersatz) auf Klartext anwenden
    2) XML-Escape (Akronyme aus TTS_SPELL_OUT enthalten keine Sonderzeichen,
       sind also escape-sicher und werden danach trotzdem korrekt gefunden)
    3) Akronyme mit <say-as interpret-as="characters"> markieren
    """
    for original, spoken in PRONOUNCE_FIXES.items():
        text = re.sub(rf"\b{re.escape(original)}\b", spoken, text)
    text = _xml_escape(text)
    for acro in sorted(TTS_SPELL_OUT, key=len, reverse=True):
        text = re.sub(
            rf"\b{re.escape(acro)}\b",
            f'<say-as interpret-as="characters">{acro}</say-as>',
            text,
        )
    return f"<speak>{text}</speak>"

# Ton-Umbau (02.07.26, Daniels Vorgabe): Persona-Muster statt Verbotsliste.
# Vorher war der Prompt fast nur "was NICHT" (nicht kindlich, kein Drama, ...) -
# schwache Free-Modelle brauchen aber POSITIV-Anker. Neues Muster (wie in den
# bekannten Persona-Prompt-Sammlungen, z.B. f/awesome-chatgpt-prompts):
# 1) WER spricht MIT WEM in WELCHER Situation, 2) kompakte Regeln,
# 3) Few-Shot-Beispiele. Die Guardrails vom 27.06. (keine Spitznamen fuer
# Institutionen) bleiben erhalten - als Regel UND im Negativ-Beispiel.
SYSTEM_PROMPT = (
    "Du bist ScampyKI. Stell dir vor: Ein Kollege auf Arbeit, der mit KI nichts am Hut hat, "
    "fragt dich in der Pause, was diese News eigentlich bedeutet. Du erklärst es ihm in 2-3 "
    "kurzen deutschen Sätzen (ca. 15-20 Sekunden Redezeit) - so, dass er es versteht, ohne "
    "sich dumm zu fühlen, und danach weiß, warum es ihn betrifft oder eben nicht.\n"
    "WICHTIG: Dein Text erscheint öffentlich auf einer News-Seite - der Kollege ist nur ein "
    "Stilbild für Ton und Niveau. Schreibe NIEMALS aus einer Firmen-Wir-Perspektive: kein "
    "'wir', 'uns', 'unser Unternehmen', 'bei uns im Betrieb' - du kennst weder den Leser "
    "noch dessen Firma.\n"
    "\n"
    "Regeln:\n"
    "- Alltagssprache und Vergleiche aus dem Arbeits-/Alltagsleben, kein Fachjargon. Wenn ein "
    "Fachbegriff sein muss, sofort mit einem greifbaren Vergleich erklären.\n"
    "- Erwachsenensprache: KEINE Spitznamen oder Personifizierungen für Länder/Behörden/Firmen "
    "(nicht 'Onkel Sam hat Schiss', sondern 'Die US-Regierung traut dem Modell nicht').\n"
    "- Skeptisch gegenüber Hype: sag ehrlich, wenn etwas nur PR oder Branchen-Standard ist "
    "(eine Finanzierungsrunde ist KEINE Sensation, nur weil die Zahl gross ist).\n"
    "- Konkrete Zahlen statt vager Worte. Jeder Satz bringt neue Information.\n"
    "- KEINE Weichmacher-Kette: 'möglicherweise', 'könnte', 'eventuell' höchstens EINMAL, "
    "wenn wirklich etwas offen ist - sonst klare Aussagen. Ein Kollege, der auf jede Frage "
    "'vielleicht' sagt, hilft niemandem.\n"
    "- Beginne NICHT mit dem Firmen-/Produktnamen, wenn die Headline schon damit endet "
    "(klingt beim Vorlesen wie eine Wiederholung - stattdessen 'Das Modell...', 'Im Kern...').\n"
    "- Kein Lob, kein Marketing-Sprech, kein übertriebenes Drama, kein Gedankenstrich.\n"
    "\n"
    "So klingt das (Beispiele fuer den Ton, Inhalte NICHT kopieren):\n"
    "News: US-Regierung hebt Sperre fuer KI-Modell auf.\n"
    "GUT: 'Die US-Regierung hatte das staerkste Modell von Anthropic monatelang gesperrt, jetzt "
    "ist es wieder da. Das ist ungefaehr so, als duerfte BMW seinen schnellsten Motor ploetzlich "
    "wieder verkaufen. Heisst fuer uns: Der Werkzeugkasten, mit dem gerade halb Amerika arbeitet, "
    "ist wieder komplett.'\n"
    "News: Startup sammelt 65 Millionen Dollar fuer KI-Videos.\n"
    "GUT: 'Ein Startup bekommt 65 Millionen Dollar, um Videos per KI zu bauen. Klingt riesig, ist "
    "in der Branche gerade aber eher Standard als Sensation. Spannend wird es erst, wenn daraus "
    "ein Produkt wird, das du und ich wirklich benutzen.'\n"
    "SCHLECHT (so NICHT): 'Onkel Sam hat Schiss vor der schlauen Maschine.' (Kinderbuch-Ton, "
    "Personifizierung) / 'Dies wirft die Frage auf, inwiefern regulatorische Rahmenbedingungen...' "
    "(Akademiker-Sprech).\n"
    "\n"
    "Fokus immer: Was bedeutet das wirklich, und warum sollte es meinen Kollegen interessieren?"
)

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 50) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:max_len].rstrip("-")


# ── Themen-Dedup: gleiches Thema von verschiedenen Quellen/Links erkennen ──
# Link-Dedup (card_sent) greift nicht, wenn 3 Portale denselben Vorfall unter
# 3 verschiedenen URLs melden (z.B. "Android 17" gleichzeitig bei SiliconAngle,
# Heise, Golem). Deshalb zusaetzlich ein simpler Keyword-Overlap-Check auf der
# Headline — analog zur Telegram-Logik, aber themenbasiert statt linkbasiert.
_STOPWORDS_DE = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "eines", "und", "oder", "in", "im", "ins", "am", "an", "auf",
    "fuer", "für", "mit", "von", "vom", "zu", "zur", "zum", "ist", "sind",
    "sich", "nach", "ueber", "über", "aus", "bei", "als", "auch", "wird",
    "werden", "wurde", "wurden", "hat", "haben", "hatte", "kann", "koennen",
    "können", "soll", "sollen", "neue", "neuer", "neues", "neuen", "jetzt",
    "wie", "was", "wer", "wo", "warum", "vor", "um", "so", "noch", "schon",
    "nicht", "kein", "keine", "mehr", "sein", "ihre", "ihr", "alle", "alles",
}

# Im Deutschen wird JEDES Substantiv grossgeschrieben, nicht nur Eigennamen -
# ohne diese Liste wuerde entity_words() unten staendig generische Woerter wie
# "Partnerschaft" oder "Technologie" als "Eigenname" werten und dadurch zwei
# voellig unterschiedliche Storys faelschlich als Duplikat erkennen (False-
# Positive-Merge). Pragmatische, von Hand kuratierte Liste haeufiger generischer
# Substantive aus KI-News-Headlines - kein Anspruch auf Vollstaendigkeit, bei
# neuen Faellen ergaenzen.
_GENERIC_NOUNS_DE = {
    "deal", "partnerschaft", "technologie", "unternehmen", "modell", "modelle",
    "initiative", "ankuendigung", "ankündigung", "effekt", "investition",
    "investitionen", "milliarden", "millionen", "dollar", "euro", "computing",
    "dienste", "dienst", "labor", "startup", "startups", "plattform", "system",
    "systeme", "studie", "bericht", "update", "version", "funktion",
    "funktionen", "produkt", "produkte", "release", "feature", "features",
    "abkommen", "vertrag", "deals", "milliardendeal",
}


def topic_keywords(headline: str) -> set:
    """Normalisierte Schluesselwoerter einer Headline (lowercase, ohne Stopwords/
    Kurzwoerter) — Basis fuer den Themen-Aehnlichkeits-Check."""
    words = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", headline.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS_DE}


# Firmen-Namensvarianten: gleiche Entitaet, unterschiedliches Wort (Kurzname
# vs. offizieller Name). Fund 26.06.: "ON Semiconductor" (CNBC) vs. "Onsemi"
# (SiliconAngle) bei derselben Synaptics-Uebernahme -> nur "synaptics" als
# gemeinsame Entitaet, Schwelle (>=2) verfehlt, zwei Karten fuer eine Story.
# Mapping wird NACH der Eigennamen-Extraktion angewendet (siehe entity_words),
# damit die Gross-/Kleinschreibungs-Erkennung selbst unangetastet bleibt -
# nur der Vergleichswert wird auf den kanonischen Namen normalisiert. Gleiches
# Pattern/gleiche Liste wie COMPANY_ALIASES in ki_news.py - bei neuen Faellen
# in BEIDEN Dateien ergaenzen.
ENTITY_ALIASES = {
    "onsemi": "semiconductor",
}


def entity_words(headline: str) -> set:
    """Grossgeschriebene Tokens aus dem ORIGINAL-Titel (Eigennamen: Firmen-,
    Produkt-, Personennamen wie "SpaceX", "Reflection", "Samsung"). Zweites,
    robusteres Dedup-Signal neben topic_keywords(): dieselbe Story wird von
    verschiedenen Quellen oft komplett unterschiedlich formuliert
    ("Milliardendeal" vs. "Computer-Abkommen mit Reflection AI"), nennt aber
    fast immer dieselben Eigennamen. topic_keywords() verliert das Case-Signal
    (alles lowercase), deshalb separat VOR dem Lowercasing extrahiert. Muss aus
    dem Original-Titel kommen, nicht aus dem schon normalisierten Keyword-Set."""
    words = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", headline)
    raw = {
        w.lower() for w in words
        if len(w) > 2 and w[0].isupper() and w.lower() not in _GENERIC_NOUNS_DE
    }
    return {ENTITY_ALIASES.get(w, w) for w in raw}


def topics_match(a: set, b: set, ent_a: set = None, ent_b: set = None, threshold: float = 0.45) -> bool:
    """True wenn vermutlich dasselbe Thema. Zwei Signale, ODER-verknuepft:
    1) Jaccard-Overlap der normalisierten Keyword-Sets (greift bei aehnlich
       formulierten Headlines).
    2) Mind. 2 gemeinsame Eigennamen (greift, wenn der Wort-Jaccard durch
       komplett unterschiedliche Formulierung unter die Schwelle faellt, aber
       z.B. "SpaceX" + "Reflection" in beiden Headlines stehen — beobachtet bei
       3 verschiedenen Quellen, die denselben Deal meldeten, ohne dass Signal 1
       das erkannt hat)."""
    if a and b:
        overlap = len(a & b) / len(a | b)
        if overlap >= threshold:
            return True
    if ent_a and ent_b and len(ent_a & ent_b) >= 2:
        return True
    return False


def random_theme_css() -> str:
    """Baut einen <style>:root{...}</style>-Block mit zufaellig gewaehlter Palette,
    der nach dem Haupt-<style> im Template eingefuegt wird und dessen Defaults
    per Source-Order ueberschreibt (gleiche Spezifitaet, kommt aber spaeter)."""
    t = random.choice(CARD_THEMES)
    return (
        "<style>:root{"
        f"--bg:{t['bg']};--cyan:{t['cyan']};--orange:{t['orange']};"
        f"--text:{t['text']};--muted:{t['muted']};--dimgrey:{t['dimgrey']};"
        "}</style>"
    )


def clean_markdown(text: str) -> str:
    """Entfernt Markdown-Formatierung aus Text."""
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return text.strip()


# Deutsche Signalwoerter (gemeinsam genutzt von _looks_invalid() fuer die Einordnung
# UND _looks_german() fuer Headline/Kontext, siehe unten). Bewusst keine harte
# Sprach-ID-Bibliothek - reicht als Fangnetz gegen unuebersetzten Text.
GERMAN_MARKERS = [
    " der ", " die ", " das ", " und ", " ist ", " nicht ", " eine ",
    " einen ", " für ", " mit ", " auf ", " dass ", " wird ", " sich ",
    " kein ", " keine ", " ein ", " im ", " den ",
]


def _looks_german(text: str) -> bool:
    """True wenn der Text deutsche Signalwoerter enthaelt.

    Bug-Fix (08.07.26, Daniels ZML-Karten-Fund): ki_news.py setzt fuer jeden Artikel
    zunaechst {"title_de": Originaltitel, "summary": ""} als Platzhalter (siehe
    summarize_news()) und ueberschreibt ihn nur bei erfolgreicher Uebersetzung. Schlaegt
    die Uebersetzung fuer einen Artikel komplett fehl (alle Modelle im Batch abgelehnt/
    Fehler), bleibt der englische Original-Titel stehen und wurde bisher UNGEPRUEFT auf
    die Karte gerendert ("Hot French startup ZML releases..."). generate_news_cards.py
    prueft bisher nur die LLM-generierte Einordnung auf Sprache (_looks_invalid()),
    nicht Headline/Kontext, die direkt aus news.json kommen. Diese Funktion schliesst
    die Luecke, angewandt auf die Headline vor dem Rendern (siehe main())."""
    lower = f" {(text or '').lower()} "
    return any(marker in lower for marker in GERMAN_MARKERS)


def cap_headline(text: str, max_chars: int = 140) -> str:
    """Sicherheitsnetz (06.07.26, Daniels Karten-Screenshots): title_de kommt aus
    ki_news.py normalerweise als EIN Satz (dort jetzt per Prompt+Check erzwungen,
    siehe title_de-Fix 06.07.), aber diese Datei sollte sich nicht blind auf die
    Upstream-Garantie verlassen. Falls doch mal ein 2-Satz-Titel durchrutscht
    (oder ein Force-Card-Link/Alt-Cache-Eintrag einen alten Titel hat): nur den
    ERSTEN Satz behalten, zusaetzlich hart auf max_chars kappen. Grund: .headline
    im Template hat flex-shrink:0 (schrumpft nie) - ein ueberlanger Titel druecke
    sonst die komplette kontext-section (WAS IST PASSIERT) aus der fix 660px
    hohen Karte."""
    text = (text or "").strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(first_sentence) > max_chars:
        cut = first_sentence[:max_chars].rstrip()
        last_space = cut.rfind(" ")
        if last_space > 0:
            cut = cut[:last_space]
        first_sentence = cut + "…"
    return first_sentence


def limit_chars_sentence_safe(text: str, max_chars: int = 320) -> str:
    """Kuerzt Text auf max. max_chars Zeichen, OHNE mitten im Satz oder Wort
    abzuschneiden.

    Bug-Fix (05.07.26, Daniels Karten-Screenshots): `kontext = summary[:280]`
    war ein reiner Zeichen-Cut - schnitt regelmaessig mitten im Wort/Satz ab
    ("...im Bereich der Bildve"). limit_sentences() loest genau dieses Problem
    schon fuer die Einordnung (Satzgrenzen statt Zeichen-Guillotine) - dieser
    Fix ueberträgt das Muster auf KONTEXT, das bisher aussen vor war.
    Reihenfolge: 1) letztes Satzende INNERHALB des Budgets suchen, 2) falls
    keins vorhanden (Text ohne Satzzeichen im Budget), auf letzte Wortgrenze
    zurueckfallen + Ellipse - nie ein hartes Wortfragment wie "Bildve".
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    last_sentence_end = None
    for m in re.finditer(r'[.!?]["\'”]?(?=\s|$)', window):
        last_sentence_end = m
    if last_sentence_end:
        return window[:last_sentence_end.end()].strip()
    last_space = window.rfind(" ")
    if last_space > 0:
        window = window[:last_space]
    return window.rstrip(",;:– ") + "…"


def limit_sentences(text: str, max_sentences: int = MAX_SENTENCES) -> str:
    """Kappt Text auf max. N Saetze, damit Einordnung (und TTS-Dauer) nicht ausufern.

    Bug-Fix (02.07.26, Karten-Screenshot): von max_tokens abgeschnittene LLM-
    Antworten endeten mitten im Satz ("...wirft und wie sie") - das Fragment
    stand auf der Karte UND wurde von der TTS vorgelesen. Ein letzter Satz ohne
    Satzende-Zeichen faellt jetzt weg, sofern mind. ein vollstaendiger bleibt."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = sentences[:max_sentences]
    if len(kept) > 1 and kept[-1] and kept[-1][-1] not in ".!?\"'”":
        kept = kept[:-1]
    return " ".join(kept).strip()


def audio_dauer_sekunden(pfad: Path) -> float:
    """Liest Audio-Dauer via ffprobe. Gibt CARD_DURATION als Fallback zurück."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(pfad)],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return float(CARD_DURATION)


# ─── Google TTS ───────────────────────────────────────────────────────────────

def generate_tts(ssml: str, slug: str, voice_name: str, voice_gender: str) -> tuple:
    """
    Generiert MP3 via Google Cloud TTS.
    ssml: fertiges SSML-Dokument (siehe build_tts_ssml) - NICHT Klartext, sonst
    interpretiert Google die <speak>/<say-as>-Tags als wortwoertlich vorzulesenden Text.
    voice_name/voice_gender: pro Karte zufaellig aus GOOGLE_TTS_VOICES gewaehlt (siehe main()).
    Gibt (audio_path, video_dauer_sekunden) zurück.
    Bei Fehler: (None, CARD_DURATION).
    """
    if not GOOGLE_TTS_KEY:
        print("  [INFO] GOOGLE_TTS_KEY nicht gesetzt — kein Audio.")
        return None, CARD_DURATION

    url = (
        "https://texttospeech.googleapis.com/v1/text:synthesize"
        f"?key={GOOGLE_TTS_KEY}"
    )
    payload = json.dumps({
        "input": {"ssml": ssml},
        "voice": {
            "languageCode": "de-DE",
            "name": voice_name,
            "ssmlGender": voice_gender,
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.18,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())

        audio_data = base64.b64decode(result["audioContent"])
        audio_path = TMP_DIR / f"{slug}.mp3"
        audio_path.write_bytes(audio_data)

        dauer = audio_dauer_sekunden(audio_path)
        video_dauer = max(int(dauer) + 1, CARD_DURATION)  # +1s Puffer
        if video_dauer > MAX_DURATION:
            print(f"  [WARN] TTS-Dauer {dauer:.1f}s ueberschreitet Cap ({MAX_DURATION}s) — Video wird gekappt.")
            video_dauer = MAX_DURATION
        print(f"  ✓ TTS:  {audio_path.name} [{voice_name}] ({dauer:.1f}s → {video_dauer}s Video)")
        return audio_path, video_dauer

    except urllib.error.HTTPError as e:
        fehler = e.read().decode("utf-8", errors="replace")
        print(f"  [WARN] TTS HTTP {e.code}: {fehler[:200]} — fahre ohne Audio fort.")
        return None, CARD_DURATION
    except Exception as e:
        print(f"  [WARN] TTS Fehler: {e} — fahre ohne Audio fort.")
        return None, CARD_DURATION


# ─── Groq ─────────────────────────────────────────────────────────────────────

def _llm_call(url: str, headers: dict, model: str, headline: str, summary: str, note: str = "") -> str | None:
    """Generischer LLM-Aufruf. Gibt Text zurück oder None bei Fehler.
    note (27.06.26): optionale Ton-/Angle-Vorgabe vom Admin-Panel (force_cards),
    z.B. "ernst bleiben, keine Kindersprache" - steuert nur den Stil, ersetzt
    den Kartentext nicht (das LLM schreibt ihn weiterhin selbst)."""
    user_content = f"News: {headline}\n\nZusammenfassung: {summary}"
    if note:
        user_content += f"\n\nHinweis vom Nutzer (bitte bei Ton/Einordnung beachten): {note}"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content}
        ],
        # 02.07.26: 120 -> 220. 120 Tokens reichten fuer 3 deutsche Saetze oft
        # nicht -> Satz 3 wurde mitten im Wort gekappt (Screenshot-Fall). Die
        # Laengen-Kontrolle macht limit_sentences() (3-Saetze-Cap), nicht das
        # Token-Limit; 220 ist nur die Notbremse gegen Endlos-Antworten.
        "max_tokens": 220,
        "temperature": 0.7,
    }).encode("utf-8")
    # Bug-Fix (02.07.26): Groq lehnte ALLE Calls mit 403 "error code: 1010" ab -
    # das ist Cloudflares User-Agent-Block auf "Python-urllib/3.x", NICHT ein
    # Key-Problem (verifiziert: mit Browser-UA antwortet dieselbe API sauber mit
    # 401 invalid_api_key auf einen Test-Key; 1010 kommt VOR der Auth-Schicht).
    # Realistischer UA macht Groq wieder nutzbar - gilt fuer alle Provider-Calls.
    headers = dict(headers)
    headers.setdefault("User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            text = clean_markdown(choice["message"]["content"].strip())
            # Bug-Fix (05.07.26, Daniels Karten-Screenshots): Antworten, die vom
            # max_tokens-Limit MITTEN IM ERSTEN Satz gekappt wurden ("...das",
            # kein Satzende), rutschten bisher durch. limit_sentences() greift nur,
            # wenn mind. 2 Saetze vorhanden sind (sonst wuerde der Text komplett
            # verschwinden) - bei Abbruch im allerersten Satz gibt es aber nur
            # EIN Element, die Guard-Bedingung greift nicht, das Fragment landete
            # unveraendert auf der Karte. Statt am Text zu raten: die API sagt es
            # uns direkt (finish_reason="length") - das als Fehlschlag behandeln,
            # naechstes Modell in der Fallback-Kette versuchen lassen.
            if choice.get("finish_reason") == "length":
                print(f"  [WARN] {model}: Antwort von max_tokens abgeschnitten (finish_reason=length), verworfen: {text[:80]!r}")
                return None
            return text
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [WARN] LLM HTTP {e.code} ({url.split('/')[2]}): {body[:150]}")
        return None
    except Exception as e:
        print(f"  [WARN] LLM Fehler ({url.split('/')[2]}): {e}")
        return None


def _looks_invalid(text: str) -> str | None:
    """Gibt einen Grund zurueck, wenn der Text offensichtlich kein brauchbares
    deutsches Einordnungs-Statement ist (Meta-Kommentar-Leak oder falsche Sprache).
    None = Text ist OK.

    Hintergrund: schwache Free-Modelle antworten manchmal nicht mit der
    Einordnung selbst, sondern mit ihrer eigenen Gedankenkette/Instruktions-
    Wiedergabe ("We need to output 3-4 concise German sentences...") oder
    komplett auf Englisch. Solche Antworten werden hier wie ein HTTP-Fehler
    behandelt: verwerfen und zum naechsten Modell in der Fallback-Kette weiter.
    """
    if not text or len(text) < 15:
        return "zu kurz/leer"
    # Substanz-Check (05.07.26, Daniels Beispiel "Die neuen Workflows sind
    # vordefinierte Ablaeufe" - formal gueltiges Deutsch, aber inhaltsleer).
    # Schwache Fallback-Modelle liefern manchmal einen validen Ein-Satz-Fragment
    # statt der geforderten 2-3 Saetze. Schwelle bewusst strenger (Daniels Wahl):
    # weniger als 3 Saetze UND weniger als 120 Zeichen -> zu duenn, naechstes
    # Modell in der Fallback-Kette versuchen statt eine magere Karte zu bauen.
    sentence_count = len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])
    if sentence_count < 3 and len(text) < 120:
        return f"zu wenig Substanz ({sentence_count} Satz/Saetze, {len(text)} Zeichen)"
    lower = text.lower()
    leak_markers = [
        "we need", "i need", "let me", "as an ai", "i should",
        "concise german", "no repetitions", "here is a", "here's a",
        "note:", "this response", "i'll write", "i will write",
        "task is to", "instructions say",
    ]
    if any(marker in lower for marker in leak_markers):
        return "Meta-Kommentar-Leak erkannt"
    german_markers = GERMAN_MARKERS
    padded = f" {lower} "
    if not any(marker in padded for marker in german_markers):
        return "keine deutschen Signalwoerter gefunden (vermutlich falsche Sprache)"
    return None


def groq_einordnung(headline: str, summary: str, note: str = "") -> tuple[str, str]:
    """Groq → OpenRouter Fallback für ScampyKI-Einordnung.
    Gibt (text, model_label) zurueck. model_label dokumentiert, welches
    Modell/Provider den Text tatsaechlich geliefert hat — wird mit in
    cards.json geschrieben, damit Groq-vs-OpenRouter-Nutzung sichtbar bleibt,
    ohne auf (nicht committete) CI-Logs angewiesen zu sein.
    note: optionale Admin-Vorgabe (force_cards, siehe main()) fuer Ton/Angle."""
    # 1. Groq versuchen
    if GROQ_API_KEY:
        for model in GROQ_MODELS:
            result = _llm_call(
                GROQ_URL,
                {"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"},
                model, headline, summary, note
            )
            if result:
                invalid_reason = _looks_invalid(result)
                if invalid_reason:
                    print(f"  [WARN] Groq/{model} verworfen ({invalid_reason}): {result[:100]!r}")
                    continue
                return result, f"groq:{model}"
    else:
        print("  [INFO] GROQ_CHAT_KEY nicht gesetzt.")

    # 2. OpenRouter-Fallback
    if OPENROUTER_KEY:
        print("  [INFO] Groq failed/verworfen — versuche OpenRouter...")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer": "https://ki-news.live",
            "X-Title": "KI News Cards",
        }
        for model in OPENROUTER_MODELS:
            result = _llm_call(OPENROUTER_URL, headers, model, headline, summary, note)
            if result:
                invalid_reason = _looks_invalid(result)
                if invalid_reason:
                    print(f"  [WARN] OpenRouter/{model} verworfen ({invalid_reason}): {result[:100]!r}")
                    continue
                return result, f"openrouter:{model}"

    return "Einordnung nicht verfügbar.", "fallback:none"


# ─── Template & Rendering ─────────────────────────────────────────────────────

def fill_template(template: str, fields: dict) -> str:
    result = template
    for key, value in fields.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def send_card_to_telegram(mp4_path: Path, headline: str, einordnung: str, card_id: str = "") -> bool:
    """Schickt das fertige MP4 via Telegram sendVideo.
    Wenn card_id gesetzt ist, haengt ein Custom-Keyboard-Button mit dem Code
    "ip:<card_id>" an. Tippt Daniel drauf, schickt Telegram diesen Code als
    GANZ NORMALE Nachricht (kein callback_query mehr - Fund vom 24.07.26:
    Telegram wirft callback_query-Updates aus der getUpdates-Warteschlange
    binnen unter einer Minute, waehrend normale Nachrichten nachweislich
    >10 Min stehen bleiben; unser Cron laeuft nur alle 2h und hat dadurch
    praktisch jeden Klick verpasst). check_insta_queue.py liest ab jetzt
    Nachrichten, die mit "ip:" beginnen, statt Callback-Daten.
    Achtung: Custom-Keyboards sind chat-weit, nicht pro Nachricht - nur die
    juengste Karte zeigt den Button. Aeltere Karten: Code aus der Caption
    (falls noetig manuell) als Nachricht schicken, funktioniert genauso."""
    if not TELEGRAM_TOKEN:
        print("  [INFO] TELEGRAM_TOKEN nicht gesetzt — kein Telegram-Versand.")
        return False

    import io
    boundary = "ScampyBoundary" + os.urandom(6).hex()
    code = f"ip:{card_id}" if card_id else ""
    caption = f"🤖 {headline}\n\n{einordnung}"
    if code:
        caption += f"\n\nCode zum Posten: {code}"
    caption = caption[:1024]

    fields = [("chat_id", TELEGRAM_CHAT_ID), ("caption", caption)]
    if card_id:
        reply_markup = json.dumps({
            "keyboard": [[{"text": code}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        })
        fields.append(("reply_markup", reply_markup))

    body = io.BytesIO()
    # Felder
    for name, value in fields:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f"{value}\r\n".encode())
    # Video-Datei
    video_data = mp4_path.read_bytes()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="video"; filename="{mp4_path.name}"\r\n'.encode())
    body.write(b"Content-Type: video/mp4\r\n\r\n")
    body.write(video_data)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    data = body.getvalue()
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                print(f"  ✓ Telegram: Video gesendet")
                return True
            print(f"  [WARN] Telegram: {result}")
            return False
    except Exception as e:
        print(f"  [WARN] Telegram sendVideo Fehler: {e}")
        return False


def render_card(html_path: Path, mp4_path: Path,
                audio_path: Path | None = None,
                duration: int = CARD_DURATION) -> bool:
    """Ruft record.js via Node auf. Gibt True zurück bei Erfolg."""
    cmd = [
        "node", str(RECORD_JS),
        str(html_path), str(mp4_path),
        str(CARD_WIDTH), str(CARD_HEIGHT), str(duration),
    ]
    if audio_path and audio_path.exists():
        cmd.append(str(audio_path))

    print(f"  → render ({duration}s{', +audio' if audio_path else ''})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        print(f"  [ERROR] record.js:\n{result.stderr[-500:]}")
        return False
    if result.stdout:
        print(f"  {result.stdout.strip()}")
    return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    today = date.today().isoformat()

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if not NEWS_JSON.exists():
        print(f"[ERROR] {NEWS_JSON} nicht gefunden — Abbruch.")
        sys.exit(1)

    with open(NEWS_JSON, encoding="utf-8") as f:
        raw = json.load(f)

    articles = raw if isinstance(raw, list) else raw.get("news", raw.get("articles", []))

    articles_by_score = sorted(
        articles,
        key=lambda a: float(a.get("score", a.get("relevance", 0))),
        reverse=True,
    )

    # Bug-Fix (26.06.26): TOP_N waehlte bisher die N hoechst-bewerteten ARTIKEL,
    # nicht STORIES. Clustering (ki_news.py) vergibt story_id korrekt an Duplikate
    # (z.B. 2 Artikel zur selben Onsemi/Synaptics-Meldung), aber hier wurden beide
    # als getrennte Top-N-Plaetze gezaehlt - dadurch konnte 1 Story 2+ Plaetze
    # belegen und schwaechere, aber inhaltlich eigenstaendige Stories (z.B. ein
    # gepinnter Artikel) knapp aus dem Fenster fallen, obwohl das Clustering schon
    # wusste, dass es Duplikate sind. Fix: pro story_id nur den ersten (= hoechst
    # bewerteten) Artikel behalten, erst DANACH auf TOP_N kappen. Artikel ohne
    # story_id (= "" oder fehlend) gelten als eigene Story (kein Dedup-Risiko).
    seen_story_ids = set()
    articles_deduped = []
    for a in articles_by_score:
        sid = a.get("story_id") or ""
        if sid and sid in seen_story_ids:
            continue
        if sid:
            seen_story_ids.add(sid)
        articles_deduped.append(a)

    # ── Force-Cards (27.06.26): Admin-Hebel fuer garantierte Karte + Nachricht ──
    # dashboard_config.json -> force_cards: [{"link": ..., "note": "..."}].
    # Grund: featured_links (Pin) gibt nur einen Score-BOOST - der konkurriert
    # weiterhin mit allen anderen Stories um die TOP_N-Plaetze und kann trotzdem
    # verlieren (siehe Heise-Polizeigesetz-Fall 26.06., 3 Tage Anlauf gebraucht).
    # force_cards ist bewusst ein hartes Commitment statt eines weichen Signals:
    # garantierter ZUSAETZLICHER Slot (TOP_N bleibt fuer alle anderen unberuehrt),
    # einmalig (kein neuer State noetig - das bestehende card_sent-Link-Dedup
    # unten verhindert von selbst eine zweite Karte fuer denselben Link in einem
    # spaeteren Lauf). "note" wird unten als Ton-/Angle-Vorgabe an den LLM-Prompt
    # durchgereicht (siehe groq_einordnung-Aufruf), ersetzt den Kartentext NICHT.
    force_cards = []
    try:
        _dash_cfg = json.loads(DASHBOARD_CONFIG_JSON.read_text(encoding="utf-8"))
        force_cards = _dash_cfg.get("force_cards", []) or []
    except Exception:
        pass

    forced_articles = []
    forced_links = set()
    if force_cards:
        by_link = {(a.get("link") or "").strip(): a for a in articles}
        for fc in force_cards:
            f_link = (fc.get("link") or "").strip()
            f_note = (fc.get("note") or "").strip()
            if not f_link or f_link in forced_links:
                continue
            art = by_link.get(f_link)
            if not art:
                print(f"  [WARN] Force-Card-Link nicht in news.json gefunden: {f_link}")
                continue
            art = dict(art)            # Kopie - _force_note ist transient, nie zurueckschreiben
            art["_force_note"] = f_note
            forced_articles.append(art)
            forced_links.add(f_link)

    # Normale Top_N-Auswahl bekommt die forcierten Links nicht nochmal (sonst
    # doppelt gezaehlt) - sie laufen als eigener, zusaetzlicher Block vorneweg.
    #
    # Card-Hungersnot-Fix (03.07.26): Der Top-N-Schnitt passierte bisher VOR
    # dem card_sent-Dedup (das erst in der Verarbeitungsschleife greift). Waren
    # alle N hoechstgescorten Links schon abgedeckt - heute passiert, nachdem
    # die OpenAI-5%-Welle + Monster-Cluster-Nachwehen die kompletten Top-5
    # verbrannt hatten - prueften ALLE Folgelaeufe immer wieder dieselben 5
    # toten Kandidaten: 0 neue Karten den ganzen Tag, obwohl frische Storys ab
    # Platz 6 bereitstanden. Fix: bereits abgedeckte Links VOR dem Top-N-
    # Schnitt ausfiltern. Das Themen-Dedup in der Schleife unten bleibt als
    # zweite Stufe unveraendert (es braucht die teureren Keyword-Signaturen).
    _pre_sent = set()
    try:
        _pre_sent = set(json.loads(CARD_STATE_JSON.read_text(encoding="utf-8")).get("sent_links", {}))
    except Exception:
        pass
    articles_sorted = forced_articles + [
        a for a in articles_deduped
        if (a.get("link") or "").strip() not in forced_links
        and (a.get("link") or "").strip() not in _pre_sent
    ][:TOP_N]

    if not articles_sorted:
        print("[WARN] Keine Artikel in news.json gefunden — nichts zu tun.")
        return

    if not TEMPLATE_PATH.exists():
        print(f"[ERROR] Template nicht gefunden: {TEMPLATE_PATH}")
        sys.exit(1)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # ── Dedup-Gedaechtnis laden (analog telegram_state.json) ───────────────
    card_sent = {}
    # {"<keyword keyword ...>": {"date": "<datum>", "entities": [...]}}  — themenbasiert,
    # ueber Laeufe hinweg. "entities" = Eigennamen-Signal fuer topics_match(), siehe dort.
    sent_topics = {}
    render_failures = {}  # {link: anzahl} — Render-Failure-Zaehler, Phase 1.2 (12.07.2026)
    # Haertung 16.07.26 (Senior-Review): Give-up erst am Lauf-Ende entscheiden, damit ein
    # global kaputtes Rendering (Node/Playwright-Ausfall) nicht alle Storys blacklistet.
    _renders_ok_this_run = 0
    _render_fails_this_run = 0
    _incremented_this_run = set()
    try:
        _state = json.loads(CARD_STATE_JSON.read_text(encoding="utf-8"))
        card_sent = _state.get("sent_links", {})
        _sent_topics_raw = _state.get("sent_topics", {})
        render_failures = _state.get("render_failures", {})
        # Rueckwaerts-kompatibel: alte Eintraege waren reine Datum-Strings ohne
        # "entities" - ohne diese Normalisierung wuerde prev_info["date"] unten
        # auf alten Staenden mit AttributeError/TypeError krachen.
        for _k, _v in _sent_topics_raw.items():
            sent_topics[_k] = _v if isinstance(_v, dict) else {"date": _v, "entities": []}
    except Exception:
        pass

    # Themen, die in DIESEM Lauf schon verarbeitet wurden (faengt z.B. 3 Karten
    # zum selben Vorfall von 3 unterschiedlichen Quellen/Links ab).
    seen_topics_this_run = []  # Liste von (keyword_set, entity_set, headline) fuer Log-Ausgabe

    # ── Bisherige cards.json laden, damit wir akkumulieren statt ueberschreiben ──
    existing_cards = []
    try:
        existing_cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    except Exception:
        pass

    cards_meta = []

    for i, article in enumerate(articles_sorted, start=1):
        headline = cap_headline(article.get("title", article.get("headline", "")).strip())
        source   = article.get("source", article.get("publisher", "Unbekannt")).strip()
        summary  = article.get("summary", article.get("description", "")).strip()
        link     = (article.get("link") or article.get("url") or "").strip()

        if not headline:
            print(f"  [SKIP] Artikel {i}: kein Titel.")
            continue

        # ── Sprach-Check (08.07.26, ZML-Fund): title_de-Uebersetzung in ki_news.py
        # fehlgeschlagen -> englischer Original-Titel blieb stehen. Nicht als "sent"
        # markieren, damit der naechste Lauf es erneut versucht, sobald die
        # Uebersetzung geklappt hat (kein card_sent/sent_topics-Eintrag hier).
        if not _looks_german(headline):
            print(f"  [SKIP] Artikel {i}: Headline wirkt unuebersetzt/nicht Deutsch "
                  f"({headline[:60]!r}) — ki_news.py-Uebersetzung fehlgeschlagen, "
                  f"naechster Lauf versucht es erneut.")
            continue

        # ── Link-Dedup: exakt dieser Artikel-Link schon mal verarbeitet? ────
        if link and link in card_sent:
            print(f"  [SKIP] Artikel {i}: Link bereits abgedeckt ({link}) — keine neue Karte.")
            continue

        # ── Themen-Dedup: gleiches Thema, anderer Link/andere Quelle? ──────
        # Faengt z.B. "Android 17" gleichzeitig bei 3 Portalen ab (Telegram-Logik
        # uebertragen: nichts doppelt posten, auch wenn der Link sich unterscheidet).
        kw  = topic_keywords(headline)
        ent = entity_words(headline)
        duplicate_topic = False
        for prev_kw_str, prev_info in sent_topics.items():
            prev_date = prev_info["date"]
            prev_ent  = set(prev_info.get("entities", []))
            if topics_match(kw, set(prev_kw_str.split()), ent, prev_ent):
                print(f"  [SKIP] Artikel {i}: Thema bereits am {prev_date} abgedeckt (Headline-Overlap) — keine neue Karte.")
                duplicate_topic = True
                break
        if not duplicate_topic:
            for prev_kw, prev_ent, prev_headline in seen_topics_this_run:
                if topics_match(kw, prev_kw, ent, prev_ent):
                    print(f"  [SKIP] Artikel {i}: gleiches Thema wie bereits in diesem Lauf verarbeitet (\"{prev_headline[:50]}\") — keine neue Karte.")
                    duplicate_topic = True
                    break
        if duplicate_topic:
            if link:
                card_sent[link] = today  # diesen Link kuenftig auch ueber Link-Dedup abfangen
            continue

        slug     = f"{today}-{slugify(headline)}"
        html_out = TMP_DIR / f"{slug}.html"
        mp4_out  = ASSETS_DIR / f"{slug}.mp4"
        mp4_url  = f"assets/cards/{slug}.mp4"

        force_note = article.get("_force_note", "")
        tag = " [FORCE-CARD]" if link in forced_links else ""
        print(f"\n[{i}/{len(articles_sorted)}]{tag} {headline[:60]}...")

        # Einordnung via Groq → OpenRouter Fallback (mit Inhalts-Validierung)
        einordnung, llm_used = groq_einordnung(headline, summary, force_note)
        # 05.07.26: satzsicherer Cut statt summary[:280] (siehe limit_chars_sentence_safe)
        kontext    = limit_chars_sentence_safe(summary, 320) if summary else "–"

        # Hard-Cap auf max. N Saetze — verhindert ausufernde TTS-Dauer strukturell
        einordnung_clean = limit_sentences(einordnung)

        # TTS-Text: Headline zuerst, dann Einordnung — als SSML synthetisieren
        # (Akronym-Buchstabierung via <say-as>, siehe build_tts_ssml).
        tts_ssml = build_tts_ssml(f"{headline}. {einordnung_clean}")

        # TTS generieren — bestimmt Video-Länge. Stimme pro Karte zufaellig waehlen
        # (kein festes Muster/Alternieren — random.choice() pro Iteration).
        voice_name, voice_gender = random.choice(GOOGLE_TTS_VOICES)
        audio_path, video_dauer = generate_tts(tts_ssml, slug, voice_name, voice_gender)

        # Badge-Label nach Score-Tier: nicht jede Karte ist wirklich "breaking" -
        # bei einheitlichem Label auf allen Karten verliert das Wort seine
        # Bedeutung (Cry-Wolf-Effekt), Leser ignorieren es nach ein paar Tagen.
        # Schwelle 50 ist eine erste Hypothese aus der Score-Verteilung in
        # news.json (0-85), nicht aus Klick-/Lesedaten - ggf. nachjustieren.
        score = float(article.get("score", article.get("relevance", 0)))
        badge_label = "BREAKING" if score >= 50 else "AKTUELL"

        # HTML befüllen (einordnung_clean: kein [OR]-Label auf der Karte)
        filled = fill_template(template, {
            "HEADLINE":    headline,
            "QUELLE":      source,
            "DATUM":       today,
            "KONTEXT":     kontext,
            "EINORDNUNG":  einordnung_clean,
            "THEME_CSS":   random_theme_css(),
            "BADGE_LABEL": badge_label,
        })
        html_out.write_text(filled, encoding="utf-8")
        print(f"  ✓ HTML: {html_out.name}")

        if mp4_out.exists() and not FORCE_RENDER:
            print(f"  → {mp4_out.name} existiert bereits — überspringe (force_render=false).")
            cards_meta.append({
                "id":       slug,
                "headline": headline,
                "mp4_url":  mp4_url,
                "date":     today,
                "source":   source,
                "duration": CARD_DURATION,
                "llm_used": llm_used,
                "voice_used": voice_name,
            })
            if link:
                card_sent[link] = today
            seen_topics_this_run.append((kw, ent, headline))
            if kw:
                sent_topics[" ".join(sorted(kw))] = {"date": today, "entities": sorted(ent)}
            continue

        success = render_card(html_out, mp4_out, audio_path, video_dauer)
        if not success:
            _render_fails_this_run += 1
            if not link:
                # Ohne Link-Schluessel kein Zaehler moeglich — ehrlich loggen, nicht
                # faelschlich "dauerhaft uebersprungen" behaupten (Fix 16.07.26).
                print(f"  [WARN] Rendering fehlgeschlagen (kein Link-Schluessel) — nächster Lauf versucht erneut.")
                continue
            tries = render_failures.get(link, 0) + 1
            render_failures[link] = tries
            _incremented_this_run.add(link)
            print(f"  [WARN] Rendering fehlgeschlagen (Versuch {tries}/3) — Entscheidung am Lauf-Ende.")
            continue
        _renders_ok_this_run += 1
        if link:
            render_failures.pop(link, None)  # Selbstheilung bei Erfolg

        print(f"  ✓ MP4:  {mp4_out.name}")

        # Karte direkt an Telegram schicken (einordnung_clean: kein [OR]-Label)
        # card_id=slug -> Insta-Post-Button auf der Karte (siehe check_insta_queue.py)
        send_card_to_telegram(mp4_out, headline, einordnung_clean, card_id=slug)

        cards_meta.append({
            "id":       slug,
            "headline": headline,
            "mp4_url":  mp4_url,
            "date":     today,
            "source":   source,
            "duration": video_dauer,
            "llm_used": llm_used,
            "voice_used": voice_name,
        })
        if link:
            card_sent[link] = today
        seen_topics_this_run.append((kw, ent, headline))
        if kw:
            sent_topics[" ".join(sorted(kw))] = {"date": today, "entities": sorted(ent)}

    # ── Render-Failure-Auswertung (16.07.26): Give-up nur bei kartenspezifischem
    # Fehler. Sind in diesem Lauf ≥2 Renders gescheitert und KEINES gelungen, ist
    # das ein Infrastruktur-Verdacht (Node/Playwright global kaputt) — dann die in
    # diesem Lauf erhoehten Zaehler wieder zuruecknehmen, nichts blacklisten.
    if _render_fails_this_run >= 2 and _renders_ok_this_run == 0:
        print(f"  [WARN] Alle {_render_fails_this_run} Renders dieses Laufs fehlgeschlagen — Infrastruktur-Verdacht, Zähler nicht erhöht.")
        for _l in _incremented_this_run:
            if _l in render_failures:
                render_failures[_l] -= 1
                if render_failures[_l] <= 0:
                    del render_failures[_l]
    else:
        for _l in [l for l, n in list(render_failures.items()) if n >= 3]:
            card_sent[_l] = today
            del render_failures[_l]
            print(f"  [GIVE-UP] 3x Render-Fehler — Link dauerhaft übersprungen: {_l}")

    # ── Dedup-Gedaechtnis speichern, auf juengste Links/Themen begrenzt ─────
    if len(card_sent) > MAX_STATE_LINKS:
        card_sent = dict(sorted(card_sent.items(), key=lambda kv: kv[1])[-MAX_STATE_LINKS:])
    if len(sent_topics) > MAX_STATE_LINKS:
        # Sortierschluessel ist jetzt verschachtelt (Migration auf dict-Format,
        # siehe Ladelogik oben) - kv[1]["date"] statt kv[1].
        sent_topics = dict(sorted(sent_topics.items(), key=lambda kv: kv[1]["date"])[-MAX_STATE_LINKS:])
    if len(render_failures) > MAX_STATE_LINKS:
        render_failures = dict(list(render_failures.items())[-MAX_STATE_LINKS:])
    try:
        CARD_STATE_JSON.write_text(
            json.dumps(
                {"sent_links": card_sent, "sent_topics": sent_topics,
                 "render_failures": render_failures, "stand": today},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  [WARN] card_state.json nicht schreibbar: {e}")

    # ── cards.json: neue Karten + bisherige akkumulieren statt ueberschreiben ──
    merged = {c["id"]: c for c in existing_cards if isinstance(c, dict) and c.get("id")}
    for c in cards_meta:
        merged[c["id"]] = c
    cards_final = sorted(merged.values(), key=lambda c: c.get("date", ""), reverse=True)[:MAX_CARDS_DISPLAY]

    with open(CARDS_JSON, "w", encoding="utf-8") as f:
        json.dump(cards_final, f, ensure_ascii=False, indent=2)

    print(f"\n✅ cards.json: {len(cards_final)} Karten ({len(cards_meta)} neu/aktualisiert in diesem Lauf) → {CARDS_JSON}")
    print(f"   Render-Fehler offen (werden erneut versucht): {len(render_failures)}")


if __name__ == "__main__":
    main()
