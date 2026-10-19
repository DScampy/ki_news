#!/usr/bin/env python3
"""Instagram-Caption fuer eine Karte (19.10.26, G3: "Quelle in der Insta-Caption", Daniel 30.08.).

Bisher war die Caption nur die Ueberschrift. Jetzt:
    <Ueberschrift>

    <Einordnung>

    Quelle: <Verlag>
    Mehr KI-News: ki-news.live

Quelle: zuerst der echte Verlag aus news.json/archive.json (`link_verlag` des Karten-Links), sonst der
bereinigte Feed-Name. Sammel-Feeds ohne Verlag (AlignedNews, Digg AI, China AI Labs) -> keine
Quellenzeile, weil der Feed-Name nicht der Verlag ist. Keine Hashtags.
Jeder Fehler -> nur die Ueberschrift (altes Verhalten). Genutzt von check_insta_queue.py und post_to_insta.py.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
MAX_LAENGE = 2200          # Instagram-Grenze fuer Captions
SCHLUSS = "Mehr KI-News: ki-news.live"
SAMMEL_FEEDS = {"AlignedNews", "Digg AI", "China AI Labs"}
FEED_NAMEN = {"Anthropic Research": "Anthropic", "Anthropic News": "Anthropic",
              "Google AI Blog": "Google", "Sächsische Zeitung KI": "Sächsische Zeitung"}
DOMAIN_NAMEN = {"reuters.com": "Reuters", "wsj.com": "WSJ", "bloomberg.com": "Bloomberg",
                "ft.com": "Financial Times", "cnbc.com": "CNBC", "nytimes.com": "New York Times",
                "theverge.com": "The Verge", "techcrunch.com": "TechCrunch", "siliconangle.com": "SiliconAngle",
                "arstechnica.com": "Ars Technica", "wired.com": "Wired", "heise.de": "Heise",
                "golem.de": "Golem", "the-decoder.de": "The Decoder", "finance.yahoo.com": "Yahoo Finance",
                "qz.com": "Quartz", "theinformation.com": "The Information", "axios.com": "Axios",
                "techrepublic.com": "TechRepublic", "wccftech.com": "WCCFtech", "cnet.com": "CNet"}
SAMMEL_DOMAINS = {"digg.com", "news.google.com", "alignednews.com", "news.ycombinator.com"}


def _karten_links(card: dict) -> list:
    out = []
    for l in card.get("links") or []:
        u = l if isinstance(l, str) else (l.get("url") or l.get("link") or "")
        if u:
            out.append(u)
    return out


def _verlag(links: list, basis: Path):
    if not links:
        return None
    gesucht = set(links)
    for name in ("news.json", "archive.json"):
        try:
            d = json.loads((basis / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict):
            items = d.get("news") or d.get("items") or d.get("archive") or []
        else:
            items = d if isinstance(d, list) else []
        for it in items:
            if isinstance(it, dict) and it.get("link") in gesucht and it.get("link_verlag"):
                host = urlparse(it["link_verlag"]).netloc.lower()
                host = host[4:] if host.startswith("www.") else host
                if not host:
                    continue
                if host in SAMMEL_DOMAINS:
                    return None
                if host == "yahoo.com" or host.endswith(".yahoo.com"):
                    return "Yahoo"
                return DOMAIN_NAMEN.get(host, host)
    return None


def quelle(card: dict, basis: Path = BASE):
    v = _verlag(_karten_links(card), basis)
    if v:
        return v
    s = (card.get("source") or "").strip()
    if not s or s in SAMMEL_FEEDS:
        return None
    s = FEED_NAMEN.get(s, s)
    for suffix in (" AI", " KI"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s or None


def caption(card: dict, basis: Path = BASE) -> str:
    titel = (card.get("headline") or "").strip()
    try:
        einordnung = (card.get("einordnung") or "").strip()
        q = quelle(card, basis)
        fuss = (f"Quelle: {q}\n" if q else "") + SCHLUSS
        platz = MAX_LAENGE - len(titel) - len(fuss) - 4
        if einordnung and platz > 50:
            if len(einordnung) > platz:
                einordnung = einordnung[: platz - 1].rsplit(" ", 1)[0] + "…"
            return f"{titel}\n\n{einordnung}\n\n{fuss}"
        return f"{titel}\n\n{fuss}"[:MAX_LAENGE]
    except Exception as e:
        print(f"WARN insta_caption: {e.__class__.__name__} - nur Ueberschrift")
        return titel


if __name__ == "__main__":     # Probe: python3 insta_caption.py [anzahl]
    import sys
    karten = json.loads((BASE / "cards.json").read_text(encoding="utf-8"))
    for k in karten[: int(sys.argv[1]) if len(sys.argv) > 1 else 3]:
        print(caption(k), "\n" + "-" * 40)
