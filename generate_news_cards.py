"""
generate_news_cards.py
======================
Liest news.json, ruft Groq API für Einordnung auf, befüllt das HTML-Template,
generiert Audio via Google Cloud TTS (Studio-C weiblich),
startet record.js (Playwright) für jede Karte, schreibt cards.json.

Ablauf:
  1. news.json einlesen → Top-N Storys nach Score
  2. Groq API → Einordnung (2 Sätze, ScampyKI-Stimme)
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
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
    "llama-3.3-70b-versatile",
]

GOOGLE_TTS_KEY   = os.environ.get("GOOGLE_TTS_KEY", "")
GOOGLE_TTS_VOICE = "de-DE-Studio-C"   # weiblich, Note 2

TOP_N          = 5
CARD_WIDTH     = 420
CARD_HEIGHT    = 660
CARD_DURATION  = 8     # Fallback-Dauer wenn kein TTS

ROOT_DIR       = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent))

NEWS_JSON      = ROOT_DIR / "news.json"
ASSETS_DIR     = ROOT_DIR / "assets" / "cards"
TEMPLATE_PATH  = Path(__file__).with_name("breaking_news_card_template.html")
RECORD_JS      = Path(__file__).with_name("record.js")
CARDS_JSON     = ROOT_DIR / "cards.json"
TMP_DIR        = Path("/tmp/cards")

SYSTEM_PROMPT = (
    "Du bist ScampyKI — kritischer KI-Journalist, skeptisch gegenüber Hype. "
    "Schreib in 1–2 prägnanten deutschen Sätzen eine nüchterne Einordnung der News. "
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

def groq_einordnung(headline: str, summary: str) -> str:
    """Ruft Groq API auf mit Fallback-Modellkette."""
    if not GROQ_API_KEY:
        print("  [WARN] GROQ_API_KEY nicht gesetzt — Einordnung wird übersprungen.")
        return "Keine Einordnung verfügbar (API-Key fehlt)."

    for model in GROQ_MODELS:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": f"News: {headline}\n\nZusammenfassung: {summary}"}
            ],
            "max_tokens": 120,
            "temperature": 0.7,
        }).encode("utf-8")

        req = urllib.request.Request(
            GROQ_URL, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"].strip()
                return clean_markdown(text)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                print(f"  [WARN] Groq {model}: {e.code} — versuche nächstes Modell.")
                continue
            body = e.read().decode("utf-8", errors="replace")
            print(f"  [ERROR] Groq HTTP {e.code}: {body[:200]}")
            return "Einordnung nicht verfügbar."
        except Exception as e:
            print(f"  [ERROR] Groq Fehler: {e}")
            return "Einordnung nicht verfügbar."

    return "Einordnung nicht verfügbar (alle Modelle erschöpft)."


# ─── Template & Rendering ─────────────────────────────────────────────────────

def fill_template(template: str, fields: dict) -> str:
    result = template
    for key, value in fields.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


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
    cards_meta = []

    for i, article in enumerate(articles_sorted, start=1):
        headline = article.get("title", article.get("headline", "")).strip()
        source   = article.get("source", article.get("publisher", "Unbekannt")).strip()
        summary  = article.get("summary", article.get("description", "")).strip()

        if not headline:
            print(f"  [SKIP] Artikel {i}: kein Titel.")
            continue

        slug     = f"{today}-{slugify(headline)}"
        html_out = TMP_DIR / f"{slug}.html"
        mp4_out  = ASSETS_DIR / f"{slug}.mp4"
        mp4_url  = f"assets/cards/{slug}.mp4"

        print(f"\n[{i}/{len(articles_sorted)}] {headline[:60]}...")

        # Einordnung via Groq
        einordnung = groq_einordnung(headline, summary)
        kontext    = summary[:280] if summary else "–"

        # TTS generieren — bestimmt Video-Länge
        audio_path, video_dauer = generate_tts(einordnung, slug)

        # HTML befüllen
        filled = fill_template(template, {
            "HEADLINE":   headline,
            "QUELLE":     source,
            "DATUM":      today,
            "KONTEXT":    kontext,
            "EINORDNUNG": einordnung,
        })
        html_out.write_text(filled, encoding="utf-8")
        print(f"  ✓ HTML: {html_out.name}")

        if mp4_out.exists():
            print(f"  → {mp4_out.name} wird überschrieben.")

        success = render_card(html_out, mp4_out, audio_path, video_dauer)
        if not success:
            print(f"  [WARN] Rendering fehlgeschlagen — Karte übersprungen.")
            continue

        print(f"  ✓ MP4:  {mp4_out.name}")

        cards_meta.append({
            "id":       slug,
            "headline": headline,
            "mp4_url":  mp4_url,
            "date":     today,
            "source":   source,
            "duration": video_dauer,
        })

    with open(CARDS_JSON, "w", encoding="utf-8") as f:
        json.dump(cards_meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ cards.json: {len(cards_meta)} Karten → {CARDS_JSON}")


if __name__ == "__main__":
    main()
