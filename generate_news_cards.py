"""
generate_news_cards.py
======================
Liest news.json, ruft Groq API für Einordnung auf, befüllt das HTML-Template,
startet record.js (Playwright) für jede Karte, schreibt cards.json.

Ablauf:
  1. news.json einlesen → Top-N Storys nach Score
  2. Groq API → Kontext + Einordnung (2 Sätze, ScampyKI-Stimme)
  3. HTML-Template befüllen → /tmp/cards/<id>.html
  4. record.js aufrufen → assets/cards/<id>.mp4
  5. cards.json schreiben
"""

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

GROQ_API_KEY   = os.environ.get("OPENROUTER_KEY", "")
GROQ_URL       = "https://openrouter.ai/api/v1/chat/completions"
GROQ_MODELS    = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
    "microsoft/phi-3-mini-128k-instruct:free",
    "meta-llama/llama-3.3-70b-instruct",   # paid fallback
]

TOP_N          = 5            # wie viele Storys verarbeitet werden
CARD_WIDTH     = 420
CARD_HEIGHT    = 660
CARD_DURATION  = 30           # Sekunden (kompletter Breaking-News-Zyklus)

ROOT_DIR       = Path(__file__).parent.parent.parent.parent   # Repo-Root
# Wenn als CI runner: Repo-Root ist CWD
ROOT_DIR       = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent))

NEWS_JSON      = ROOT_DIR / "news.json"
ASSETS_DIR     = ROOT_DIR / "assets" / "cards"
TEMPLATE_PATH  = Path(__file__).with_name("breaking_news_card_template.html")
RECORD_JS      = Path(__file__).with_name("record.js")
CARDS_JSON     = ROOT_DIR / "cards.json"
TMP_DIR        = Path("/tmp/cards")

SYSTEM_PROMPT = (
    "Du bist ScampyKI — das ist das KI-News-Alter-Ego von Daniel Scampy. "
    "Stil: direkt, trocken, manchmal sarkastisch. Keine Floskeln, kein Hype, kein Marketing-Sprech. "
    "Verbotene Phrasen: 'Das zeigt', 'Dies verdeutlicht', 'Es bleibt abzuwarten', 'bahnbrechend', 'revolutionär'. "
    "Frag dich: Wer profitiert wirklich? Was wird nicht gesagt? Was klingt größer als es ist? "
    "Schreib 1–2 knappe deutsche Sätze. Kein Satzzeichen am Ende außer Punkt. "
    "Ton: gut informierter Skeptiker mit Fachkenntnis — nicht zynisch um des Zynismus willen, aber klar im Urteil."
)

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 50) -> str:
    """Einfacher Slug: lowercase, nur alphanumerisch + Bindestriche."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:max_len].rstrip("-")


def groq_einordnung(headline: str, summary: str) -> str:
    """Ruft OpenRouter API auf, versucht Modelle der Reihe nach bei Rate-Limits."""
    if not GROQ_API_KEY:
        print("  [WARN] OPENROUTER_KEY nicht gesetzt — Einordnung wird übersprungen.")
        return "Keine Einordnung verfügbar (API-Key fehlt)."

    user_msg = f"News: {headline}\n\nZusammenfassung: {summary}"

    for model in GROQ_MODELS:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg}
            ],
            "max_tokens": 120,
            "temperature": 0.7,
        }).encode("utf-8")

        req = urllib.request.Request(
            GROQ_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "HTTP-Referer": "https://dscampy.github.io/ki_news",
                "X-Title": "ScampyKI News Cards",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"].strip()
                # Markdown-Artefakte bereinigen
                text = re.sub(r"~~(.+?)~~", r"\1", text)  # ~~strikethrough~~
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold**
                text = re.sub(r"\*(.+?)\*", r"\1", text)       # *italic*
                print(f"  ✓ Einordnung via {model}")
                return text
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 503):
                print(f"  [WARN] {model} Rate-Limit ({e.code}) — nächstes Modell")
                continue
            print(f"  [ERROR] {model} HTTP {e.code}: {body[:200]}")
            return "Einordnung nicht verfügbar."
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {model}: {e}")
            continue

    print("  [ERROR] Alle Modelle erschöpft — keine Einordnung.")
    return "Einordnung nicht verfügbar."


def fill_template(template: str, fields: dict) -> str:
    """Ersetzt alle {{PLACEHOLDER}} im Template."""
    result = template
    for key, value in fields.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def render_card(html_path: Path, mp4_path: Path) -> bool:
    """Ruft record.js via Node auf. Gibt True zurück bei Erfolg."""
    cmd = [
        "node",
        str(RECORD_JS),
        str(html_path),
        str(mp4_path),
        str(CARD_WIDTH),
        str(CARD_HEIGHT),
        str(CARD_DURATION),
    ]
    print(f"  → render: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  [ERROR] record.js:\n{result.stderr[-500:]}")
        return False
    if result.stdout:
        print(f"  {result.stdout.strip()}")
    return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    today = date.today().isoformat()

    # Verzeichnisse anlegen
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # news.json einlesen
    if not NEWS_JSON.exists():
        print(f"[ERROR] {NEWS_JSON} nicht gefunden — Abbruch.")
        sys.exit(1)

    with open(NEWS_JSON, encoding="utf-8") as f:
        raw = json.load(f)

    # news.json kann als Liste oder als Dict mit 'articles'-Key vorliegen
    articles = raw if isinstance(raw, list) else raw.get("news", raw.get("articles", []))

    # Sortieren nach Score (absteigend), Top-N nehmen
    articles_sorted = sorted(
        articles,
        key=lambda a: float(a.get("score", a.get("relevance", 0))),
        reverse=True,
    )[:TOP_N]

    if not articles_sorted:
        print("[WARN] Keine Artikel in news.json gefunden — nichts zu tun.")
        return

    # Template laden
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

        # Slug für Dateinamen
        slug     = f"{today}-{slugify(headline)}"
        html_out = TMP_DIR / f"{slug}.html"
        mp4_out  = ASSETS_DIR / f"{slug}.mp4"
        mp4_url  = f"assets/cards/{slug}.mp4"

        print(f"\n[{i}/{len(articles_sorted)}] {headline[:60]}...")

        # Einordnung via Groq
        einordnung = groq_einordnung(headline, summary)
        kontext    = summary[:280] if summary else "–"

        # Template befüllen
        filled = fill_template(template, {
            "HEADLINE":   headline,
            "QUELLE":     source,
            "DATUM":      today,
            "KONTEXT":    kontext,
            "EINORDNUNG": einordnung,
        })
        html_out.write_text(filled, encoding="utf-8")
        print(f"  ✓ HTML: {html_out}")

        # MP4 rendern — überspringen wenn bereits vorhanden (wie Telegram-Texte)
        force = os.environ.get("FORCE_RENDER", "").lower() in ("1", "true", "yes")
        if mp4_out.exists() and not force:
            print(f"  → {mp4_out.name} existiert bereits — überspringe (FORCE_RENDER=1 zum Erzwingen).")
            cards_meta.append({
                "id":       slug,
                "headline": headline,
                "mp4_url":  mp4_url,
                "date":     today,
                "source":   source,
            })
            continue

        success = render_card(html_out, mp4_out)
        if not success:
            print(f"  [WARN] Rendering fehlgeschlagen — Karte wird übersprungen.")
            continue

        print(f"  ✓ MP4:  {mp4_out}")

        cards_meta.append({
            "id":       slug,
            "headline": headline,
            "mp4_url":  mp4_url,
            "date":     today,
            "source":   source,
        })

    # cards.json schreiben (neueste zuerst)
    with open(CARDS_JSON, "w", encoding="utf-8") as f:
        json.dump(cards_meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ cards.json geschrieben: {len(cards_meta)} Karten → {CARDS_JSON}")


if __name__ == "__main__":
    main()
