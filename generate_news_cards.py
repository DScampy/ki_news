"""
generate_news_cards.py
======================
Liest news.json, ruft Groq API für Einordnung auf, befüllt das HTML-Template,
generiert Audio via Google Cloud TTS (Studio-C weiblich),
startet record.js (Playwright) für jede Karte, schreibt cards.json.

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
GOOGLE_TTS_VOICE = "de-DE-Studio-C"   # weiblich, Note 2

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "9096438")

TOP_N          = 5
CARD_WIDTH     = 420
CARD_HEIGHT    = 660
CARD_DURATION  = 8     # Fallback-Dauer wenn kein TTS
MAX_DURATION   = 35    # Hard-Cap: niemand hört sich eine 50s-Karte an
MAX_SENTENCES  = 4      # Einordnung wird auf max. N Sätze gekappt (Text + TTS)
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

# TTS-Ausspracheliste: einzelne Buchstaben/Begriffe, die die Studio-Voice falsch betont.
# Erweiterbar, sobald neue Faelle auffallen (z.B. ueber die Admin-Seite gepflegt).
PRONOUNCE_FIXES = {
    "KI":     "K I",
    "DRAM":   "D-RAM",
    "SpaceX": "Space X",
    "HBM":    "H B M",
}

SYSTEM_PROMPT = (
    "Du bist ScampyKI — kritischer KI-Journalist, skeptisch gegenüber Hype. "
    "Schreib 3–4 prägnante deutsche Sätze als nüchterne Einordnung der News (ca. 25–30 Sekunden Lesezeit). "
    "Keine Wiederholungen — jeder Satz bringt neue Information. "
    "Kein Lob, kein Marketing-Sprech. Fokus: Was bedeutet das wirklich?"
)

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 50) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:max_len].rstrip("-")


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


def apply_pronounce_fixes(text: str) -> str:
    """Wendet die PRONOUNCE_FIXES-Liste fuer korrekte TTS-Aussprache an (Wortgrenzen)."""
    for original, spoken in PRONOUNCE_FIXES.items():
        text = re.sub(rf"\b{re.escape(original)}\b", spoken, text)
    return text


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

def generate_tts(text: str, slug: str) -> tuple:
    """
    Generiert MP3 via Google Cloud TTS (Studio-C weiblich).
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
        "input": {"text": text},
        "voice": {
            "languageCode": "de-DE",
            "name": GOOGLE_TTS_VOICE,
            "ssmlGender": "FEMALE",
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.0,
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
        print(f"  ✓ TTS:  {audio_path.name} ({dauer:.1f}s → {video_dauer}s Video)")
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


def send_card_to_telegram(mp4_path: Path, headline: str, einordnung: str) -> bool:
    """Schickt das fertige MP4 via Telegram sendVideo."""
    if not TELEGRAM_TOKEN:
        print("  [INFO] TELEGRAM_TOKEN nicht gesetzt — kein Telegram-Versand.")
        return False

    import io
    boundary = "ScampyBoundary" + os.urandom(6).hex()
    caption  = f"🤖 {headline}\n\n{einordnung}"[:1024]

    body = io.BytesIO()
    # Felder
    for name, value in [("chat_id", TELEGRAM_CHAT_ID), ("caption", caption)]:
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
    try:
        card_sent = json.loads(CARD_STATE_JSON.read_text(encoding="utf-8")).get("sent_links", {})
    except Exception:
        pass

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

        # ── Themen-Dedup: Artikel-Link schon mal verarbeitet? ──────────────
        if link and link in card_sent:
            print(f"  [SKIP] Artikel {i}: Thema bereits abgedeckt ({link}) — keine neue Karte.")
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

        # TTS-Text: Headline zuerst, dann Einordnung — Ausspracheliste anwenden
        headline_tts   = apply_pronounce_fixes(headline)
        einordnung_tts = apply_pronounce_fixes(einordnung_clean)
        tts_text = f"{headline_tts}. {einordnung_tts}"

        # TTS generieren — bestimmt Video-Länge
        audio_path, video_dauer = generate_tts(tts_text, slug)

        # HTML befüllen (einordnung_clean: kein [OR]-Label auf der Karte)
        filled = fill_template(template, {
            "HEADLINE":   headline,
            "QUELLE":     source,
            "DATUM":      today,
            "KONTEXT":    kontext,
            "EINORDNUNG": einordnung_clean,
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
            })
            if link:
                card_sent[link] = today
            continue

        success = render_card(html_out, mp4_out, audio_path, video_dauer)
        if not success:
            print(f"  [WARN] Rendering fehlgeschlagen — Karte übersprungen.")
            continue

        print(f"  ✓ MP4:  {mp4_out.name}")

        # Karte direkt an Telegram schicken (einordnung_clean: kein [OR]-Label)
        send_card_to_telegram(mp4_out, headline, einordnung_clean)

        cards_meta.append({
            "id":       slug,
            "headline": headline,
            "mp4_url":  mp4_url,
            "date":     today,
            "source":   source,
            "duration": video_dauer,
            "llm_used": llm_used,
        })
        if link:
            card_sent[link] = today

    # ── Dedup-Gedaechtnis speichern, auf juengste Links begrenzt ────────────
    if len(card_sent) > MAX_STATE_LINKS:
        card_sent = dict(sorted(card_sent.items(), key=lambda kv: kv[1])[-MAX_STATE_LINKS:])
    try:
        CARD_STATE_JSON.write_text(
            json.dumps({"sent_links": card_sent, "stand": today}, ensure_ascii=False, indent=2),
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
