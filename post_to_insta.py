#!/usr/bin/env python3
"""
Postet eine News-Card als Reel auf scampy_ki (Instagram-Login-Flow).
Laeuft in GitHub Actions im Repo-Root (wo cards.json liegt).
Liest cards.json selbst -> keine URL noetig.

Env-Variablen:
  IG_USER_ID       (Secret)  = 17841476614625141
  IG_ACCESS_TOKEN  (Secret)  = langlebiger Token
  CARD_ID          (Input)   = ID oder Teilstring aus cards.json. Leer = neueste Card.
  CAPTION          (Input)   = optionaler Caption-Override. Leer = Ueberschrift + Einordnung + Quelle (insta_caption.py).
  SITE_BASE        (optional)= Basis-URL, Default https://ki-news.live
"""
import os
import sys
import json
import time
import requests

GRAPH = "https://graph.instagram.com/v23.0"
SITE_BASE = os.environ.get("SITE_BASE", "https://ki-news.live").rstrip("/")

IG = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]
CARD_ID = os.environ.get("CARD_ID", "").strip()
CAPTION_OVERRIDE = os.environ.get("CAPTION", "").strip()


def die(msg: str) -> None:
    print(msg)
    sys.exit(1)


def pick_card() -> dict:
    if not os.path.exists("cards.json"):
        die("FEHLER: cards.json nicht gefunden - Workflow muss im Repo-Root laufen.")
    with open("cards.json", encoding="utf-8") as f:
        cards = json.load(f)
    if not cards:
        die("FEHLER: cards.json ist leer.")
    if not CARD_ID:
        return cards[0]  # neueste
    for c in cards:
        if CARD_ID == c.get("id") or CARD_ID in c.get("id", "") or CARD_ID in c.get("mp4_url", ""):
            return c
    die(f"FEHLER: Keine Card zu '{CARD_ID}' gefunden. IDs siehe cards.json.")


def main() -> None:
    card = pick_card()
    # 26.09.26: Medien koennen absolut im Repo ki_news_media liegen
    # 20.10.26: 9:16-Video (mp4_hoch_url) bevorzugen, wenn erreichbar; sonst wie bisher die Website-Karte
    _abs = lambda u: u if u.startswith("http") else f"{SITE_BASE}/{u.lstrip('/')}"
    video_url = _abs(card['mp4_url'])
    if card.get('mp4_hoch_url'):
        try:
            if requests.head(_abs(card['mp4_hoch_url']), timeout=15, allow_redirects=True).status_code == 200:
                video_url = _abs(card['mp4_hoch_url'])
        except requests.RequestException:
            pass
    try:  # 19.10.26 (G3): Einordnung + Quelle, bei jedem Fehler nur die Ueberschrift
        from insta_caption import caption as _insta_caption
        caption = CAPTION_OVERRIDE or _insta_caption(card)
    except Exception as e:
        print(f"WARN insta_caption: {e.__class__.__name__} - nur Ueberschrift")
        caption = CAPTION_OVERRIDE or card.get("headline", "")
    print(f"Card:    {card.get('id')}")
    print(f"Video:   {video_url}")
    print(f"Caption: {caption}")

    # 1) Reel-Container erstellen
    data = requests.post(
        f"{GRAPH}/{IG}/media",
        data={"media_type": "REELS", "video_url": video_url,
              "caption": caption, "access_token": TOKEN},
        timeout=60,
    ).json()
    creation_id = data.get("id")
    if not creation_id:
        die(f"FEHLER Container: {data}")
    print(f"Container: {creation_id}")

    # 2) Auf Verarbeitung warten (max ~90 s)
    status = ""
    for _ in range(30):
        time.sleep(3)
        status = requests.get(
            f"{GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": TOKEN}, timeout=30,
        ).json().get("status_code", "")
        print(f"Status: {status}")
        if status == "FINISHED":
            break
        if status == "ERROR":
            die("FEHLER: Verarbeitung fehlgeschlagen - meist Video-Format oder URL nicht oeffentlich.")
    else:
        die("FEHLER: Timeout - Video nicht rechtzeitig verarbeitet. Spaeter nochmal starten.")

    # 3) Veroeffentlichen
    pub = requests.post(
        f"{GRAPH}/{IG}/media_publish",
        data={"creation_id": creation_id, "access_token": TOKEN}, timeout=60,
    ).json()
    if not pub.get("id"):
        die(f"FEHLER Publish: {pub}")
    print(f"OK: Gepostet auf scampy_ki! Media-ID: {pub['id']}")


if __name__ == "__main__":
    main()
