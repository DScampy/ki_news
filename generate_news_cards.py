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
    "llama-3.3-70b-versatile",   # stärkstes Groq-Modell zuerst
    "gemma2-9b-it",
    "llama-3.1-8b-instant",      # schnellstes als letzter Fallback
]

OPENROUTER_KEY    = os.environ.get("OPENROUTER_KEY", "")
OPENROUTER_URL    = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS = [
    "google/gemma-4-31b-it:free",              # Quality 65 — bestes Free-Modell
    "nvidia/nemotron-3-super-120b-a12b:free",  # Quality 60 — Nvidia 120B, 1M ctx
    "openai/gpt-oss-120b:free",                # Quality 55 — OpenAI OSS 120B
    "meta-llama/llama-3.3-70b-instruct:free",  # Quality 24 — bewährter Fallback
    "meta-llama/llama-3.3-70b-instruct",       # paid Anker
]

GOOGLE_TTS_KEY   = os.environ.get("GOOGLE_TTS_KEY", "")
# Zwei Studio-Stimmen, pro Karte zufaellig gewaehlt (random.choice in main()) —
# kein festes Muster, keine Alternierung. (name, ssmlGender) muss zusammenpassen,
# sonst kann die Google-API unerwartet reagieren.
# HINWEIS: de-DE-Studio-B als MALE ist die ueblich kolportierte Zuordnung
# (Gegenstueck zu de-DE-Studio-C FEMALE), aber NICHT 1:1 aus Googles offizieller
# Tabelle bestaetigt (das "-B"-Suffix ist je Sprache nicht konsistent mit Gender —
# z.B. ist bg-BG-Standard-B FEMALE). Vor Produktivlauf einmal eine Testkarte
# mit der maennlichen Stimme anhoeren, um das zu verifizieren.
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

SYSTEM_PROMPT = (
    "Du bist ScampyKI — erklärst einem Freund am Tisch, was diese News wirklich bedeutet. "
    "Schreib 2–3 prägnante deutsche Sätze (ca. 15–20 Sekunden Lesezeit). "
    "Umgangssprachlich, kurze direkte Sätze, kein Fachjargon-Geschwurbel — wenn ein abstrakter "
    "Begriff nötig ist, mit einem konkreten Beispiel oder Vergleich greifbar machen. "
    "Skeptisch gegenüber Hype, aber nicht akademisch-distanziert: lieber 'Heißt im Klartext...' "
    "als 'Dies wirft die Frage auf, ob...'. "
    "Beginne NICHT mit dem Firmen-/Produktnamen, wenn die Headline schon damit endet — sonst "
    "klingt es beim Vorlesen wie eine Wiederholung (z.B. nicht 'Mistral Small 4 ist...' direkt nach "
    "einer Headline, die mit 'Mistral Small 4' endet; stattdessen 'Das Modell...', 'Im Kern...'). "
    "Keine Wiederholungen — jeder Satz bringt neue Information. "
    "Kein Lob, kein Marketing-Sprech. Fokus: Was bedeutet das wirklich?"
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
    return {
        w.lower() for w in words
        if len(w) > 2 and w[0].isupper() and w.lower() not in _GENERIC_NOUNS_DE
    }


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


def limit_sentences(text: str, max_sentences: int = MAX_SENTENCES) -> str:
    """Kappt Text auf max. N Saetze, damit Einordnung (und TTS-Dauer) nicht ausufern."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:max_sentences]).strip()


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

def _llm_call(url: str, headers: dict, model: str, headline: str, summary: str) -> str | None:
    """Generischer LLM-Aufruf. Gibt Text zurück oder None bei Fehler."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"News: {headline}\n\nZusammenfassung: {summary}"}
        ],
        "max_tokens": 120,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return clean_markdown(data["choices"][0]["message"]["content"].strip())
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
    lower = text.lower()
    leak_markers = [
        "we need", "i need", "let me", "as an ai", "i should",
        "concise german", "no repetitions", "here is a", "here's a",
        "note:", "this response", "i'll write", "i will write",
        "task is to", "instructions say",
    ]
    if any(marker in lower for marker in leak_markers):
        return "Meta-Kommentar-Leak erkannt"
    german_markers = [
        " der ", " die ", " das ", " und ", " ist ", " nicht ", " eine ",
        " einen ", " für ", " mit ", " auf ", " dass ", " wird ", " sich ",
        " kein ", " keine ",
    ]
    padded = f" {lower} "
    if not any(marker in padded for marker in german_markers):
        return "keine deutschen Signalwoerter gefunden (vermutlich falsche Sprache)"
    return None


def groq_einordnung(headline: str, summary: str) -> tuple[str, str]:
    """Groq → OpenRouter Fallback für ScampyKI-Einordnung.
    Gibt (text, model_label) zurueck. model_label dokumentiert, welches
    Modell/Provider den Text tatsaechlich geliefert hat — wird mit in
    cards.json geschrieben, damit Groq-vs-OpenRouter-Nutzung sichtbar bleibt,
    ohne auf (nicht committete) CI-Logs angewiesen zu sein."""
    # 1. Groq versuchen
    if GROQ_API_KEY:
        for model in GROQ_MODELS:
            result = _llm_call(
                GROQ_URL,
                {"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"},
                model, headline, summary
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
            result = _llm_call(OPENROUTER_URL, headers, model, headline, summary)
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
    Wenn card_id gesetzt ist, haengt ein Insta-Post-Button an (callback_data
    "ip:<card_id-Praefix>"). check_insta_queue.py liest Klicks darauf beim
    naechsten Cron-Lauf aus und postet genau diese Karte auf Instagram."""
    if not TELEGRAM_TOKEN:
        print("  [INFO] TELEGRAM_TOKEN nicht gesetzt — kein Telegram-Versand.")
        return False

    import io
    boundary = "ScampyBoundary" + os.urandom(6).hex()
    caption  = f"🤖 {headline}\n\n{einordnung}"[:1024]

    fields = [("chat_id", TELEGRAM_CHAT_ID), ("caption", caption)]
    if card_id:
        # 64-Byte-Limit von Telegram fuer callback_data -> Praefix kappen.
        cb = f"ip:{card_id}"[:64]
        reply_markup = json.dumps({
            "inline_keyboard": [[{"text": "📤 Auf Instagram posten", "callback_data": cb}]]
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

    articles_sorted = sorted(
        articles,
        key=lambda a: float(a.get("score", a.get("relevance", 0))),
        reverse=True,
    )[:TOP_N]

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
    try:
        _state = json.loads(CARD_STATE_JSON.read_text(encoding="utf-8"))
        card_sent = _state.get("sent_links", {})
        _sent_topics_raw = _state.get("sent_topics", {})
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
        headline = article.get("title", article.get("headline", "")).strip()
        source   = article.get("source", article.get("publisher", "Unbekannt")).strip()
        summary  = article.get("summary", article.get("description", "")).strip()
        link     = (article.get("link") or article.get("url") or "").strip()

        if not headline:
            print(f"  [SKIP] Artikel {i}: kein Titel.")
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

        print(f"\n[{i}/{len(articles_sorted)}] {headline[:60]}...")

        # Einordnung via Groq → OpenRouter Fallback (mit Inhalts-Validierung)
        einordnung, llm_used = groq_einordnung(headline, summary)
        kontext    = summary[:280] if summary else "–"

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
            print(f"  [WARN] Rendering fehlgeschlagen — Karte übersprungen.")
            continue

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

    # ── Dedup-Gedaechtnis speichern, auf juengste Links/Themen begrenzt ─────
    if len(card_sent) > MAX_STATE_LINKS:
        card_sent = dict(sorted(card_sent.items(), key=lambda kv: kv[1])[-MAX_STATE_LINKS:])
    if len(sent_topics) > MAX_STATE_LINKS:
        # Sortierschluessel ist jetzt verschachtelt (Migration auf dict-Format,
        # siehe Ladelogik oben) - kv[1]["date"] statt kv[1].
        sent_topics = dict(sorted(sent_topics.items(), key=lambda kv: kv[1]["date"])[-MAX_STATE_LINKS:])
    try:
        CARD_STATE_JSON.write_text(
            json.dumps(
                {"sent_links": card_sent, "sent_topics": sent_topics, "stand": today},
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


if __name__ == "__main__":
    main()
