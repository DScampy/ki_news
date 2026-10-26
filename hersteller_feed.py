#!/usr/bin/env python3
"""hersteller.json: neue Modelle der grossen Hersteller (28.09.26, Auftrag 3).

Liest NUR offizielle Kanaele der Hersteller (Blog-RSS, News-Seiten) und schreibt
die Modell-Releases der letzten RELEASE_TAGE Tage nach hersteller.json. Das
Start-Hero-Modul in index.html zeigt daraus die Kachel "Frisch auf dem Markt";
fehlt die Datei oder ist die Liste leer, blendet sich die Kachel aus.

Regeln:
- Nichts erfinden: Titel, Datum, Text, Bild und Video stammen aus der Quelle
  (Feed-Eintrag bzw. og:-Tags der offiziellen Release-Seite).
- Einziger LLM-Einsatz: der Kurztext wird woertlich ins Deutsche uebersetzt
  (OPENROUTER_KEY + Modellkette aus add_reactions.py, kein neues Secret). Das
  Original steht in text_en. Ohne Key, bei Fehler oder wenn die Uebersetzung
  eine Zahl enthaelt, die im Original fehlt, bleibt der englische Text.
- Ein Eintrag ist ein Release, wenn der Titel mit "Introducing/Announcing/..."
  beginnt oder mit einem Modellnamen, UND einen Modellnamen mit Versionsnummer
  enthaelt (GPT-6 Sol, Claude Opus 5.5, Gemini 3.8 Live, DeepSeek-V4.1-Flash ...).
  Kundenberichte ("... with GPT-6 Astra") fallen damit heraus.
- Abgleich mit news.json: passt eine Meldung (gleicher Link oder Modellname im
  Titel), stehen news_link/story_id im Eintrag. Das Hero-Modul zeigt einen
  Release nicht, wenn dieselbe Meldung gerade als Top-Story laeuft.
- Faellt eine Quelle aus, bleiben die bisherigen Eintraege dieses Herstellers
  stehen (sofern noch im Zeitfenster). Fallen ALLE aus, bleibt die Datei unberuehrt.

Optional: OPENROUTER_KEY (Uebersetzung). Aufruf: python3 hersteller_feed.py [--dry-run] [--heute YYYY-MM-DD]
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover - sehr alte Python-Versionen
    BERLIN = timezone(timedelta(hours=2))

BASE = Path(__file__).resolve().parent
OUT = BASE / "hersteller.json"
RELEASE_TAGE = 14
MAX_EINTRAEGE = 12
UA = "Mozilla/5.0 (compatible; ki-news.live hersteller-feed; +https://ki-news.live)"

# (Hersteller, Art, URL). Spiegel-Feeds (Olshansk/rss-feeds) sind 1:1-Abzuege der
# offiziellen Seiten und laufen in ki_news.py seit Juli als Primaerquellen. Fuer
# Anthropic zusaetzlich die News-Seite direkt: der Spiegel hat "Claude Opus 5.5"
# (22.09.26) nicht erfasst.
QUELLEN = [
    ("OpenAI", "rss", "https://openai.com/news/rss.xml"),
    ("Anthropic", "anthropic", "https://www.anthropic.com/news"),
    ("Anthropic", "rss", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml"),
    ("Google", "rss", "https://deepmind.google/blog/rss.xml"),
    ("Google", "rss", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_google_ai.xml"),
    ("Meta", "rss", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml"),
    ("xAI", "rss", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_xainews.xml"),
    ("Mistral", "rss", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_mistral.xml"),
    ("Alibaba Qwen", "rss", "https://qwenlm.github.io/blog/index.xml"),
    ("DeepSeek", "deepseek", "https://api-docs.deepseek.com/news/news260910"),
    # 28.09.26: ElevenLabs hat keinen RSS-Feed; die Blog-Uebersicht ist serverseitig
    # gerendert (<article><h2><a href="/blog/..."> + <time datetime>). Eleven v4 (28.09.)
    # fehlte sonst in Kachel und Registry.
    ("ElevenLabs", "elevenlabs", "https://elevenlabs.io/blog"),
    # 26.10.26 (Daniel): Kimi K3.1 Pro (24.10.) fehlte in der Kachel - es gab keine Kimi-Quelle.
    # kimi.com/blog hat kein RSS, der Google-News-Feed aus ki_news.py kennt nur K3 (Juni).
    # Die Uebersicht listet die Tech-Blogs neueste zuerst, Datum/Titel stehen nur auf der
    # Beitragsseite, s. lies_kimi().
    ("Moonshot Kimi", "kimi", "https://www.kimi.com/blog"),
    # 26.10.26 (Daniel): sechs weitere Hersteller, Kanaele am 26.10. geprueft. Keiner hat einen
    # brauchbaren RSS-Feed ausser Nvidia; Olshansk-Spiegel gibt es fuer keinen.
    ("MiniMax", "minimax", "https://www.minimax.io/blog"),
    # /en/blog und /en/news sind JS-Huellen, die Startseite rendert "Latest updates" (6 Eintraege).
    # Seedream 5.0 Flash (01.10.) steht dort nicht - ByteDance kuendigt nicht alles hier an.
    ("ByteDance Seed", "seed", "https://seed.bytedance.com/en/"),
    # z.ai/blog gibt 404, die Release Notes der Doku sind serverseitig (ein Block je Datum).
    ("Z.ai", "zai", "https://docs.z.ai/release-notes/new-released"),
    ("Nvidia", "rss", "https://developer.nvidia.com/blog/feed"),
    ("Microsoft", "microsoft", "https://microsoft.ai/blog/"),
    ("Black Forest Labs", "bfl", "https://bfl.ai/blog"),
]

# 26.10.26: Hersteller mit gemischten Blogs. Ein Release zaehlt nur, wenn das Modell zur eigenen
# Familie gehoert (Nvidia-Tutorials nennen oft Gemma oder Llama). "ueberall": Microsoft schreibt
# Fliesstext-Titel ("Pushing the quality-cost frontier with MAI-Image-2.6"), dort darf der
# eigene Modellname irgendwo im Titel stehen.
QUELLEN_FAMILIE = {
    "MiniMax": (r"^MiniMax", False), "ByteDance Seed": (r"^Seed", False), "Z.ai": (r"^GLM", False),
    "Nvidia": (r"^Nemotron", False), "Microsoft": (r"^MAI-", True), "Black Forest Labs": (r"^FLUX", False),
}

# Modellfamilien; danach muss eine Versionsnummer folgen (Muse Spark 1.1, GPT-6).
_FAMILIEN = (
    r"GPT|o\d|Claude(?:\s+(?:Opus|Sonnet|Haiku|Fable))?|Opus|Sonnet|Haiku|Fable|"
    r"Gemini|Gemma|Veo|Imagen|Lyria|WeatherNext|Llama|Muse(?:\s+(?:Spark|Image|Video))?|"
    r"Grok(?:\s+Imagine)?|Mistral(?:\s+(?:Large|Medium|Small))?|Magistral|Codestral|Devstral|"
    r"Voxtral|Pixtral|Ministral|Qwen|DeepSeek|Kimi(?:[\s\-]?K)?|GLM|ChatGPT\s+Images|"  # Kimi K3.1 Pro, Kimi-K2.6
    r"Eleven(?:\s+(?:Music|Multilingual|Flash|Turbo))?|Scribe|"
    # 26.10.26 (Daniel): sechs weitere Hersteller - MiniMax M3.1, Seedream 5.0/Seedance 2.0/Seed 2.0,
    # Nemotron 3.5, MAI-Image-2.6/MAI-Base-2, FLUX.2/FLUX 3
    r"MiniMax(?:[\s\-]?[A-Z]|\s+(?:Music|Speech|Hailuo|Video))?|Seed(?:ream|ance)?|Nemotron|MAI-(?:Image|Base|Voice|Code|Transcribe|DS)|FLUX\.?"
)
_ZUSATZ = (
    r"Pro|Flash|Lite|Live|Sol|Luna|Astra|Mini|Nano|Ultra|Max|Plus|Turbo|Thinking|"
    r"Extended|Vision|Exp|Preview|Coder|Code|Instruct|Omni|Image|Video|Cyber|Fast|Edit|"
    r"Opus|Sonnet|Haiku|Fable|Medium|Large|Small|Deep\s+Think|text-to-speech|TTS|"
    r"Prime|Super|VL|Klein|Kontext|Dev|Schnell|Air|Action"
)
MODELL_RE = re.compile(
    rf"\b((?:{_FAMILIEN})[\s\-‑]?V?\d[\w.]*(?:[\s\-‑](?:{_ZUSATZ})\b)*)",
    re.IGNORECASE,
)
START_RE = re.compile(
    r"^\s*(introducing|announcing|meet|launching|releasing|say hello|hello,?)\b", re.IGNORECASE
)
VERBOTEN_RE = re.compile(  # Kundenberichte, Fallstudien, Sicherheitsberichte
    r"\b(with|using|helps?|trusts?|cuts?|boosts?|builds?|turns?|safety overview|system card|"
    r"prompt caching|remarks)\b",
    re.IGNORECASE,
)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _text(s, maxlen=260):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip().replace("—", "-").replace("–", "-")
    if len(s) <= maxlen:
        return s
    cut = s[:maxlen]
    satz = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: satz + 1] if satz > 80 else cut.rsplit(" ", 1)[0] + " ...").strip()


# 26.10.26: "NVIDIA Nemotron 3.5 Super VL Powers ..." beginnt mit dem Herstellernamen, und
# "One-take Creation ...: Introducing Seedance 2.5" kuendigt erst nach dem Doppelpunkt an.
_HERSTELLER_PRAEFIX = re.compile(r"^(?:NVIDIA|Microsoft(?:\s+AI)?|ByteDance(?:\s+Seed)?|Black Forest Labs|"
                                 r"Z\.ai|Moonshot AI)\s+", re.IGNORECASE)
_ANKUENDIGUNG_DAVOR = re.compile(r"\b(?:introducing|announcing|meet)\s*$", re.IGNORECASE)


def modell_aus_titel(titel, ueberall=False):
    """Modellname aus dem Titel, oder '' wenn es kein Modell-Release ist. ueberall=True: der
    Modellname darf irgendwo stehen (nur fuer Quellen mit Familienfilter, s. QUELLEN_FAMILIE)."""
    t = (titel or "").replace("‑", "-").strip()
    m = MODELL_RE.search(t)
    if not m:
        return ""
    if ueberall:
        return re.sub(r"\s+", " ", m.group(1)).strip(" -")
    ohne = _HERSTELLER_PRAEFIX.sub("", t)
    beginnt_mit_modell = ohne.lower().startswith(m.group(1).lower()[:4])
    if not (START_RE.match(t) or beginnt_mit_modell or _ANKUENDIGUNG_DAVOR.search(t[: m.start()])):
        return ""
    if VERBOTEN_RE.search(t[: m.start()]) and not START_RE.match(t):
        return ""
    name = re.sub(r"\s+", " ", m.group(1)).strip(" -")
    return name


def _datum(s):
    s = (s or "").strip()
    if not s:
        return None
    for fn in (parsedate_to_datetime, lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))):
        try:
            d = fn(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def lies_rss(xml_txt):
    A = "{http://www.w3.org/2005/Atom}"
    M = "{http://search.yahoo.com/mrss/}"
    root = ET.fromstring(xml_txt.encode("utf-8"))
    out = []
    for it in root.findall(".//item") + root.findall(f".//{A}entry"):
        titel = it.findtext("title") or it.findtext(f"{A}title") or ""
        link = it.findtext("link") or ""
        if not link:
            el = it.find(f"{A}link")
            link = el.get("href", "") if el is not None else ""
        datum = _datum(it.findtext("pubDate") or it.findtext(f"{A}published") or it.findtext(f"{A}updated"))
        text = it.findtext("description") or it.findtext(f"{A}summary") or ""
        bild = video = ""
        for el in it.findall("enclosure") + it.findall(f"{M}content") + it.findall(f"{M}thumbnail"):
            url, typ = el.get("url", ""), el.get("type", "") or el.get("medium", "")
            if "video" in typ and not video:
                video = url
            elif ("image" in typ or el.tag.endswith("thumbnail")) and not bild:
                bild = url
        out.append({"titel": titel.strip(), "url": link.strip(), "datum": datum,
                    "text": text, "poster": bild, "video_url": video})
    return out


def lies_anthropic(seite):
    """anthropic.com/news: Karten <a href="/slug"> mit Ueberschrift und <time>."""
    out = []
    for m in re.finditer(r'<a href="(/[a-z0-9][a-z0-9/-]*)"[^>]*>(.*?)</a>', seite, re.S):
        inner = m.group(2)
        h = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", inner, re.S) or \
            re.search(r'<span[^>]*[Tt]itle[^>]*>(.*?)</span>', inner, re.S)
        t = re.search(r"<time[^>]*>(.*?)</time>", inner, re.S)
        if not h or not t:
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", inner, re.S)
        out.append({"titel": _text(h.group(1), 200), "url": "https://www.anthropic.com" + m.group(1),
                    "datum": _datum(_text(t.group(1), 40)), "text": p.group(1) if p else "",
                    "poster": "", "video_url": ""})
    return out


def lies_elevenlabs(seite):
    """elevenlabs.io/blog: <article> mit <h2><a href="/blog/slug">Titel</a></h2> und <time datetime>."""
    out = []
    for art in re.findall(r"<article[^>]*>(.*?)</article>", seite, re.S):
        a = re.search(r'<h[1-4][^>]*>\s*<a[^>]*href="(/blog/[a-z0-9-]+)"[^>]*>(.*?)</a>', art, re.S)
        t = re.search(r'<time[^>]*datetime="([^"]+)"', art)
        if not a or not t:
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", art, re.S)
        out.append({"titel": _text(a.group(2), 200), "url": "https://elevenlabs.io" + a.group(1),
                    "datum": _datum(t.group(1)), "text": p.group(1) if p else "",
                    "poster": "", "video_url": ""})
    return out


def lies_deepseek(seite):
    """DeepSeek-API-Doku: Seitenleiste 'DeepSeek-V4.1-Flash Release 2026/09/10'."""
    out, gesehen = [], set()
    for slug, titel in re.findall(r'href="/news/(news\d{6})"[^>]*>(?:<[^>]+>)*([^<]+)', seite):
        m = re.match(r"(.+?)\s+Release\s+(\d{4}/\d{2}/\d{2})$", titel.strip())
        if not m or slug in gesehen:
            continue
        gesehen.add(slug)
        out.append({"titel": m.group(1).strip() + " Release", "url": f"https://api-docs.deepseek.com/news/{slug}",
                    "datum": _datum(m.group(2)), "text": "", "poster": "", "video_url": ""})
    return out


KIMI_MAX_BEITRAEGE = 3


def lies_kimi(seite):
    """kimi.com/blog: Liste <a href="/blog/kimi-k3-1-pro">, neueste zuerst, Titel dort nur
    chinesisch. Die ersten KIMI_MAX_BEITRAEGE Modell-Beitraege werden geoeffnet: Titel aus
    og:title ("Kimi K3.1 Pro Tech Blog: ..."), Datum aus datePublished, sonst dateModified
    (26.10.: K3.1 Pro hat nur dateModified 2026-10-24, K3 gar keins - ohne Datum kein Eintrag)."""
    out = []
    slugs = list(dict.fromkeys(re.findall(r'href="/blog/(kimi-[a-z0-9-]+)"', seite)))
    for slug in slugs[:KIMI_MAX_BEITRAEGE]:
        url = f"https://www.kimi.com/blog/{slug}"
        try:
            s = _get(url, timeout=15)
        except Exception:
            continue
        roh = s.replace('\\"', '"')
        d = (re.search(r'"datePublished":"(\d{4}-\d{2}-\d{2})', roh)
             or re.search(r'"dateModified":"(\d{4}-\d{2}-\d{2})', roh))

        def meta(name):
            m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % name, s)
            return html.unescape(m.group(1)) if m else ""

        titel = meta("og:title")
        if not d or not titel:
            continue
        out.append({"titel": titel, "url": url, "datum": _datum(d.group(1)),
                    "text": meta("og:description"), "poster": meta("og:image"), "video_url": ""})
    return out


def _eintrag(titel, url, datum, text="", poster=""):
    return {"titel": html.unescape(re.sub(r"<[^>]+>", "", titel or "")).strip(), "url": url,
            "datum": _datum(datum), "text": text, "poster": poster, "video_url": ""}


def lies_minimax(seite):
    """minimax.io/blog: Karten <a href="/blog/<slug>"><section><img alt="Titel">...
    2026-10-19</span></section><h3>Titel</h3>."""
    out = []
    for slug, karte in re.findall(r'<a [^>]*href="/blog/([^"]+)"[^>]*><section[^>]*>(.*?)</a>', seite, re.S):
        d = re.search(r"(\d{4}-\d{2}-\d{2})</span>", karte)
        t = re.search(r"<h3[^>]*>(.*?)</h3>", karte, re.S) or re.search(r'<img alt="([^"]+)"', karte)
        if d and t:
            out.append(_eintrag(t.group(1), f"https://www.minimax.io/blog/{slug}", d.group(1)))
    return out


def lies_seed(seite):
    """seed.bytedance.com/en/: Block "Latest updates", <a href=".../blog/<slug>"> ... <h3>Titel</h3>
    <div><span>Jul 31, 2026</span>."""
    out, gesehen = [], set()
    for link, titel, datum in re.findall(
            r'<a [^>]*href="([^"]*/blog/[^"]+)"[^>]*>(?:(?!</a>).){0,1500}?<h3[^>]*>([^<]+)</h3>\s*<div[^>]*>'
            r'\s*<span[^>]*>([A-Z][a-z]{2,8} \d{1,2}, \d{4})</span>', seite, re.S):
        url = link if link.startswith("http") else "https://seed.bytedance.com" + link
        if url not in gesehen:     # die Startseite rendert den Block mehrfach (Desktop/Mobil)
            gesehen.add(url)
            out.append(_eintrag(titel, url, datum))
    return out


def lies_zai(seite):
    """docs.z.ai Release Notes: <div ... update-container" id="2026-08-26">, darin zuerst das
    Datum, dann der Modellname ("GLM-5.3-Flash"), dann die Beschreibung."""
    out = []
    bloecke = re.split(r'update-container" id="(\d{4}-\d{2}-\d{2})"', seite)
    for datum, teil in zip(bloecke[1::2], bloecke[2::2]):
        txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", teil[:8000]))).replace("​", "")
        txt = txt.split(datum, 1)[-1].strip(" >")
        name = txt.split(" ", 1)[0]
        out.append(_eintrag(name, f"https://docs.z.ai/release-notes/new-released#{datum}", datum,
                            text=_text(txt[len(name):])))
    return out


MS_MAX_BEITRAEGE = 4


def lies_microsoft(seite):
    """microsoft.ai/blog: Karten <a title="<Titel> Link" href="https://microsoft.ai/news/<slug>/">,
    ohne Datum. Die neuesten MS_MAX_BEITRAEGE Beitraege werden geoeffnet (datePublished im JSON-LD).
    Der Feed microsoft.ai/feed/ ist leer (26.10.)."""
    out, gesehen = [], set()
    for titel, url in re.findall(r'title="([^"]+?) Link"\s+href="(https://microsoft\.ai/news/[^"]+)"', seite):
        if url in gesehen:
            continue
        gesehen.add(url)
        if len(gesehen) > MS_MAX_BEITRAEGE:
            break
        try:
            s = _get(url, timeout=15)
        except Exception:
            continue
        d = re.search(r'"datePublished":"([^"]+)"', s)
        og = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', s)
        if d:
            out.append(_eintrag(html.unescape(titel), url, d.group(1), poster=og.group(1) if og else ""))
    return out


def lies_bfl(seite):
    """bfl.ai/blog: <a aria-label="Read blog post: <Titel>" href="/blog/<slug>"> mit
    <time dateTime="2026-10-15T15:00:00.000Z"> in der Karte (nicht jede Karte hat eins)."""
    out = []
    for titel, slug, karte in re.findall(
            r'<a [^>]*aria-label="Read blog post: ([^"]+)"[^>]*href="/blog/([^"]+)"[^>]*>(.*?)</a>', seite, re.S):
        d = re.search(r'<time[^>]*dateTime="([^"]+)"', karte)
        if d:
            out.append(_eintrag(html.unescape(titel), f"https://bfl.ai/blog/{slug}", d.group(1)))
    return out


def og_tags(url):
    """og:image / og:video / og:description der offiziellen Release-Seite."""
    try:
        seite = _get(url, timeout=15)
    except Exception:
        return {}
    tags = {}
    for prop, content in re.findall(
        r'<meta[^>]+(?:property|name)="(og:[a-z:_]+|twitter:[a-z:_]+|description)"[^>]+content="([^"]*)"', seite
    ):
        tags.setdefault(prop, html.unescape(content))
    for content, prop in re.findall(
        r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="(og:[a-z:_]+|description)"', seite
    ):
        tags.setdefault(prop, html.unescape(content))
    # 28.09.26: Hersteller setzen selten og:video. Das Hero-Video der Release-Seite steht
    # aber als erste MP4 im Quelltext (Anthropic: cdn.sanity.io "MobyHero", ElevenLabs:
    # eleven-public-cdn h264_720.mp4). Nur https-MP4 auf der eigenen CDN des Herstellers.
    m = re.search(r'https://(?:cdn\.sanity\.io|eleven-public-cdn\.elevenlabs\.io|[a-z0-9.-]*'
                  r'(?:openai|anthropic|google|deepmind|gstatic|googleusercontent|meta|fbcdn|mistral|'
                  r'x\.ai|qwen|deepseek)[a-z0-9.-]*)/[^"\'\\\s<>]+?\.mp4', seite)
    if m:
        tags.setdefault("seite:video", m.group(0))
    return tags


MAX_UEBERSETZUNG = 1200


def _zahlen(s):
    return set(re.findall(r"\d+(?:[.,]\d+)?", (s or "").replace(",", ".")))


def uebersetze(text, modelle=None, key=None):
    """Woertliche deutsche Uebersetzung des Kurztexts, oder None."""
    key = key if key is not None else os.environ.get("OPENROUTER_KEY", "").strip()
    if not key or not (text or "").strip():
        return None
    # 28.09.26: laengere Texte nicht anschneiden (vorher text[:600] -> gekuerzte Uebersetzung
    # stand als vollstaendiges Zitat im Release-Entwurf). Zu lang: Original bleibt stehen.
    if len(text) > MAX_UEBERSETZUNG:
        return None
    if modelle is None:
        try:
            from add_reactions import TRANSLATE_MODELLE as modelle
        except Exception:
            return None
    prompt = (
        "Uebersetze den folgenden Text aus der Ankuendigung eines KI-Herstellers woertlich "
        "ins Deutsche. Nichts hinzufuegen, nichts weglassen, keine Wertung. Jeden Satz "
        "uebersetzen. Modell- und Produktnamen unveraendert lassen. Bindestriche in "
        "zusammengesetzten Woertern behalten (Code-Migration, KI-Werkzeuge). Keinen "
        "Gedankenstrich als Satzzeichen verwenden. Umlaute verwenden. Anrede in der "
        f"Sie-Form. Nur die Uebersetzung ausgeben.\n\nText: {text}"
    )
    for modell in modelle:
        try:
            data = json.dumps({"model": modell, "max_tokens": 900,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=data, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "HTTP-Referer": "https://ki-news.live/", "X-Title": "KI News Hersteller-Feed"})
            with urllib.request.urlopen(req, timeout=40) as r:
                antwort = json.loads(r.read())["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  Uebersetzung fehlgeschlagen mit {modell}: {type(e).__name__}")
            continue
        antwort = _text((antwort or "").strip().strip('"'), 2 * MAX_UEBERSETZUNG)
        if not antwort or len(antwort) > 2 * len(text) + 40:
            continue
        # Deutsch ist fast nie kuerzer als das Englische; deutlich kuerzer = Saetze fehlen
        if len(antwort) < 0.8 * len(text):
            print(f"  Uebersetzung verworfen (gekuerzt {len(antwort)}/{len(text)} Zeichen): {antwort[:60]!r}")
            continue
        if not _zahlen(antwort) <= _zahlen(text):
            print(f"  Uebersetzung verworfen (neue Zahl): {antwort[:80]!r}")
            continue
        return antwort
    return None


def _nur_https(u):
    return u if isinstance(u, str) and u.startswith("https://") else ""


def _norm(s):
    return re.sub(r"[^a-z0-9.]+", " ", (s or "").lower()).strip()


def news_abgleich(eintrag, news):
    """Passende Meldung in news.json: gleicher Link oder Modellname im Titel."""
    modell = _norm(eintrag["modell"])
    for n in news:
        if n.get("link") and n.get("link") == eintrag["url"]:
            return n
    if len(modell) < 5:
        return None
    for n in news:
        if modell in _norm(n.get("title_en") or "") or modell in _norm(n.get("title") or ""):
            return n
    return None


def baue(heute, alt, news, mit_og=True, log=print, uebersetzen=uebersetze):
    grenze = heute - timedelta(days=RELEASE_TAGE)
    kandidaten, ok_hersteller, fehl = {}, set(), []
    for hersteller, art, url in QUELLEN:
        try:
            roh = _get(url)
            items = {"rss": lies_rss, "anthropic": lies_anthropic, "deepseek": lies_deepseek,
                     "elevenlabs": lies_elevenlabs, "kimi": lies_kimi, "minimax": lies_minimax,
                     "seed": lies_seed, "zai": lies_zai, "microsoft": lies_microsoft,
                     "bfl": lies_bfl}[art](roh)
            ok_hersteller.add(hersteller)
        except Exception as e:
            fehl.append(f"{hersteller} ({url}): {type(e).__name__}: {e}")
            continue
        n_rel = 0
        for it in items:
            if not it["datum"] or not (grenze <= it["datum"] <= heute + timedelta(days=1)):
                continue
            familie, ueberall = QUELLEN_FAMILIE.get(hersteller, (None, False))
            modell = modell_aus_titel(it["titel"], ueberall=ueberall)
            if not modell or (familie and not re.match(familie, modell, re.IGNORECASE)):
                continue
            key = (hersteller, modell.lower())
            # frueheste Meldung eines Modells gewinnt (die Ankuendigung, nicht der Nachklapp)
            if key in kandidaten and kandidaten[key]["_dt"] <= it["datum"]:
                continue
            n_rel += 1
            kandidaten[key] = {
                "hersteller": hersteller, "modell": modell, "datum": it["datum"].strftime("%Y-%m-%d"),
                "titel": _text(it["titel"], 140), "text": _text(it["text"]), "url": _nur_https(it["url"]),
                "x_url": "", "video_url": _nur_https(it["video_url"]), "poster": _nur_https(it["poster"]),
                "_dt": it["datum"],
            }
        log(f"  {hersteller:<13} {len(items):>4} Eintraege, {n_rel} Release-Kandidaten  ({url})")

    if not ok_hersteller:
        return None, fehl

    releases = sorted(kandidaten.values(), key=lambda r: r["_dt"], reverse=True)[:MAX_EINTRAEGE]
    for r in releases:
        r.pop("_dt", None)
        if mit_og and r["url"]:
            og = og_tags(r["url"])
            r["poster"] = r["poster"] or _nur_https(og.get("og:image") or og.get("twitter:image", ""))
            r["video_url"] = r["video_url"] or _nur_https(og.get("og:video") or og.get("og:video:url")
                                                           or og.get("og:video:secure_url", "")
                                                           or og.get("seite:video", ""))
            if not r["text"]:
                r["text"] = _text(og.get("og:description") or og.get("description", ""))
        if r["text"]:
            r["text_en"] = r["text"]
            cache = {a.get("url"): a for a in (alt or {}).get("releases", []) if a.get("text_en")}
            vorher = cache.get(r["url"])
            if vorher and vorher.get("text_en") == r["text_en"] and vorher.get("text") != r["text_en"]:
                r["text"] = vorher["text"]
            else:
                de = uebersetzen(r["text"]) if uebersetzen else None
                if de:
                    r["text"] = de
        treffer = news_abgleich(r, news)
        if treffer:
            r["news_link"] = treffer.get("link", "")
            if treffer.get("story_id"):
                r["story_id"] = treffer["story_id"]

    # ausgefallene Hersteller: alte Eintraege im Zeitfenster behalten
    for a in (alt or {}).get("releases", []):
        if a.get("hersteller") in ok_hersteller:
            continue
        d = _datum(a.get("datum"))
        if d and d >= grenze:
            releases.append(a)
    releases.sort(key=lambda r: r.get("datum", ""), reverse=True)
    return releases[:MAX_EINTRAEGE], fehl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="nur ausgeben, hersteller.json nicht schreiben")
    ap.add_argument("--heute", help="Stichtag YYYY-MM-DD (Test)")
    ap.add_argument("--ohne-og", action="store_true", help="Release-Seiten nicht fuer Bild/Video abrufen")
    a = ap.parse_args()

    jetzt = datetime.now(timezone.utc)
    heute = datetime.strptime(a.heute, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23) if a.heute else jetzt
    try:
        alt = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        alt = None
    try:
        news = json.loads((BASE / "news.json").read_text(encoding="utf-8")).get("news") or []
    except Exception:
        news = []

    print(f"hersteller_feed: Zeitfenster {RELEASE_TAGE} Tage bis {heute:%Y-%m-%d}")
    releases, fehl = baue(heute, alt, news, mit_og=not a.ohne_og)
    for f in fehl:
        print(f"  WARNUNG Quelle ausgefallen: {f}")
    if releases is None:
        print("hersteller_feed: ALLE Quellen ausgefallen - hersteller.json bleibt unveraendert")
        return 0

    daten = {"stand": jetzt.astimezone(BERLIN).strftime("%Y-%m-%d %H:%M"), "releases": releases}
    txt = json.dumps(daten, ensure_ascii=False, indent=2) + "\n"
    print(f"hersteller_feed: {len(releases)} Releases")
    for r in releases:
        print(f"  {r['datum']}  {r['hersteller']:<13} {r['modell']:<32} {r['url']}"
              + ("  [News: " + r["news_link"][:50] + "]" if r.get("news_link") else ""))
    if a.dry_run:
        print(txt)
        return 0
    OUT.write_text(txt, encoding="utf-8")
    try:
        meldungen_fortschreiben(releases)
    except Exception as e:  # darf hersteller.json nie kippen
        print(f"  WARNUNG Registry-Meldungen nicht fortgeschrieben: {e}")
    return 0


# Registry-Zweitquelle (28.09.26): hersteller.json haelt nur RELEASE_TAGE Tage. Die
# Registry (registry_bau/generiere_modelle_json.py) kennt sonst nur OpenRouter, wo
# z.B. Gemini 3.8 TTS und ElevenLabs fehlen. Diese Datei sammelt jeden erkannten
# Release dauerhaft; geloescht wird nichts, der erste Fund (Ankuendigung) gewinnt.
MELDUNGEN = BASE / "registry_bau" / "modelle_meldungen.json"


def meldungen_fortschreiben(releases, pfad=MELDUNGEN):
    try:
        alt = json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        alt = {"modelle": []}
    liste = alt.get("modelle") or []
    schon = {(m.get("hersteller"), _norm(m.get("modell"))) for m in liste}
    neu = 0
    for r in releases:
        key = (r["hersteller"], _norm(r["modell"]))
        if key in schon or not r.get("modell") or not r.get("datum"):
            continue
        schon.add(key)
        liste.append({"hersteller": r["hersteller"], "modell": r["modell"], "datum": r["datum"],
                      "url": r.get("url", ""), "titel": r.get("titel", "")})
        neu += 1
    if not neu and pfad.exists():
        return 0
    liste.sort(key=lambda m: (m["datum"], m["hersteller"], m["modell"]))
    daten = {"_hinweis": "GENERAT von hersteller_feed.py (dauerhaft, nichts wird geloescht). "
                         "Zweitquelle der Modell-Registry fuer Modelle, die OpenRouter nicht fuehrt.",
             "stand": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "modelle": liste}
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"hersteller_feed: {neu} neue Modelle in {pfad.name} ({len(liste)} gesamt)")
    return neu


if __name__ == "__main__":
    sys.exit(main())
