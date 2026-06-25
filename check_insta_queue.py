#!/usr/bin/env python3
"""
Liest Telegram-Button-Klicks ("📤 Auf Instagram posten") ab und postet die
passende Card auf Instagram. Laeuft per Cron (insta_queue.yml) - kein
Dauer-Server, kein Webhook. Telegram haelt nicht abgeholte Updates bis 24h
vor, ein Klick wird also spaetestens beim naechsten Cron-Tick verarbeitet.

Ablauf:
  1. getUpdates ab letztem verarbeiteten update_id (offset-Datei).
  2. Jede callback_query mit data "ip:<card_id-Praefix>" -> Card in
     cards.json suchen (gleiche Praefix-Logik wie post_to_insta.py).
  3. answerCallbackQuery (Spinner auf dem Button beenden, Feedback an Daniel).
  4. Card auf Instagram posten (gleiche Graph-API-Calls wie post_to_insta.py).
  5. offset-Datei aktualisieren, damit der Klick nicht doppelt verarbeitet wird.

Env-Variablen:
  TELEGRAM_TOKEN   (Secret)
  IG_USER_ID       (Secret)
  IG_ACCESS_TOKEN  (Secret)
  SITE_BASE        (optional) Default https://ki-news.live
"""
import os
import sys
import json
import time
import requests

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
IG = os.environ.get("IG_USER_ID", "").strip()
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
SITE_BASE = os.environ.get("SITE_BASE", "https://ki-news.live").rstrip("/")

GRAPH = "https://graph.instagram.com/v23.0"
OFFSET_FILE = "insta_telegram_offset.json"
CARDS_FILE = "cards.json"

CB_PREFIX = "ip:"


def load_offset() -> int:
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return json.load(f).get("last_update_id", 0)
    except Exception:
        return 0


def save_offset(update_id: int) -> None:
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_update_id": update_id}, f, indent=2)


def get_updates(offset: int) -> list:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": offset + 1, "timeout": 0}, timeout=20).json()
    if not resp.get("ok"):
        print(f"FEHLER getUpdates: {resp}")
        return []
    return resp.get("result", [])


def answer_callback(callback_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, data={"callback_query_id": callback_id, "text": text[:200]}, timeout=15)
    except Exception as e:
        print(f"WARN answerCallbackQuery: {e}")


def find_card(prefix: str) -> dict | None:
    if not os.path.exists(CARDS_FILE):
        return None
    with open(CARDS_FILE, encoding="utf-8") as f:
        cards = json.load(f)
    for c in cards:
        cid = c.get("id", "")
        if prefix == cid or cid.startswith(prefix) or prefix in cid:
            return c
    return None


def post_card_to_instagram(card: dict) -> str:
    """Identische Logik wie post_to_insta.py: Container -> warten -> publish."""
    video_url = f"{SITE_BASE}/{card['mp4_url'].lstrip('/')}"
    caption = card.get("headline", "")

    data = requests.post(
        f"{GRAPH}/{IG}/media",
        data={"media_type": "REELS", "video_url": video_url,
              "caption": caption, "access_token": IG_TOKEN},
        timeout=60,
    ).json()
    creation_id = data.get("id")
    if not creation_id:
        return f"FEHLER Container: {data}"

    status = ""
    for _ in range(30):
        time.sleep(3)
        status = requests.get(
            f"{GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": IG_TOKEN}, timeout=30,
        ).json().get("status_code", "")
        if status == "FINISHED":
            break
        if status == "ERROR":
            return "FEHLER: Verarbeitung fehlgeschlagen (Format/URL)."
    else:
        return "FEHLER: Timeout - Video nicht rechtzeitig verarbeitet."

    pub = requests.post(
        f"{GRAPH}/{IG}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_TOKEN}, timeout=60,
    ).json()
    if not pub.get("id"):
        return f"FEHLER Publish: {pub}"
    return f"OK: Gepostet auf scampy_ki! Media-ID: {pub['id']}"


def main() -> None:
    if not TG_TOKEN:
        print("FEHLER: TELEGRAM_TOKEN fehlt.")
        sys.exit(1)

    offset = load_offset()
    if not os.path.exists(OFFSET_FILE):
        save_offset(offset)  # Datei existiert dann auf jeden Fall (git add im Workflow braucht das)

    updates = get_updates(offset)
    if not updates:
        print("Keine neuen Telegram-Updates.")
        return

    highest_id = offset
    processed = 0

    for upd in updates:
        highest_id = max(highest_id, upd.get("update_id", highest_id))
        cq = upd.get("callback_query")
        if not cq:
            continue
        data = cq.get("data", "")
        if not data.startswith(CB_PREFIX):
            continue

        prefix = data[len(CB_PREFIX):]
        callback_id = cq.get("id", "")
        print(f"Insta-Klick erkannt: Praefix='{prefix}'")

        if not IG or not IG_TOKEN:
            answer_callback(callback_id, "FEHLER: IG-Secrets fehlen im Workflow.")
            print("FEHLER: IG_USER_ID/IG_ACCESS_TOKEN nicht gesetzt.")
            continue

        card = find_card(prefix)
        if not card:
            answer_callback(callback_id, "FEHLER: Card nicht in cards.json gefunden.")
            print(f"FEHLER: Keine Card zu Praefix '{prefix}' gefunden.")
            continue

        answer_callback(callback_id, "📤 Wird gerade gepostet...")
        result = post_card_to_instagram(card)
        print(result)
        answer_callback(callback_id, result[:200])
        processed += 1

    save_offset(highest_id)
    print(f"Fertig. {processed} Insta-Post(s) verarbeitet, offset={highest_id}.")


if __name__ == "__main__":
    main()
