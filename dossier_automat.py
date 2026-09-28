#!/usr/bin/env python3
"""Dossier-Automat (28.09.26, Auftrag 5 Dossier-Teil + Auftrag 7.1 Chronoskop).

Macht aus den Entwicklungslinien in news.json (ki_news.py _linien_dossiers(),
linie.html#l=<id>) ausfuehrliche Dossier-Artikel im Chronoskop-Layout:
Zeit-Scrubber, vertikale Zeitachse, Dossier-Fenster je Ereignis mit allen
Quellen der Story und eingebetteter News-Karte (MP4), Legende, Export.

Redaktionsregeln (Daniel):
- Es steht nur drin, was in den Daten steht: Titel, Datum, Quelle, Link und
  Zusammenfassung je Ereignis kommen aus news.json/archive.json, Karten aus
  cards.json. Der Einleitungssatz wird aus Zaehlwerten gebaut, NICHT von einem
  Sprachmodell geschrieben. Der Kurztext "Worum es geht" erscheint nur, wenn die
  Pipeline ihn bereits durch ihre Deckungspruefung gelassen hat (dossier.worum).
- Sichtbar gekennzeichnet als "Automatische Zusammenstellung".
- Entwurf zuerst: artikel/entwurf/linie-<id>.html, noindex, nicht in Navigation,
  Sitemap oder Feeds. Freigabe: Linien-ID in dossiers_freigabe.json eintragen,
  dann schreibt der naechste Lauf artikel/dossier-<id>.html und traegt die Seite
  in sitemap.xml ein.
- Kein Em-Dash im sichtbaren Text. Verbotene Hype-Woerter werden im Bericht
  gemeldet (in Quelltexten nicht umgeschrieben, damit nichts verfaelscht wird).

Aufruf: python3 dossier_automat.py [--linie ID ...] [--max N] [--dry-run]
"""
import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENTWURF_DIR = BASE / "artikel" / "entwurf"
FREIGABE = BASE / "dossiers_freigabe.json"
SITEMAP = BASE / "sitemap.xml"
MIN_EREIGNISSE = 3
LUECKE_TAGE = 3
VERBOTEN = ["revolutionär", "revolutionaer", "bahnbrechend", "game-changer", "gamechanger", "disruptiv",
            "paradigmenwechsel", "nahtlos", "tiefgreifend", "wegweisend"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def _lade(name, default):
    try:
        return json.loads((BASE / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def _sauber(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s.replace("—", "-").replace("–", "-")


def _e(s):
    return html.escape(_sauber(s), quote=True)


def _datum_lang(iso):
    try:
        d = date.fromisoformat(iso[:10])
        return f"{d.day}. {MONATE[d.month - 1]} {d.year}"
    except Exception:
        return iso or ""


def _datum_kurz(iso):
    try:
        d = date.fromisoformat(iso[:10])
        return f"{d.day:02d}.{d.month:02d}."
    except Exception:
        return iso or ""


def _fold(v):
    v = str(v or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "s"), ("ae", "a"), ("oe", "o"), ("ue", "u"), ("ss", "s")):
        v = v.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", v)


class KartenIndex:
    """Wie window.klCardFor() in assets/ki-layout.js: erst Link, dann Titel-Praefix."""

    def __init__(self, karten):
        self.idx = []
        for c in karten if isinstance(karten, list) else (karten or {}).get("cards", []):
            if c and c.get("mp4_url") and c.get("headline"):
                self.idx.append({"key": _fold(c["headline"]), "links": c.get("links") or [],
                                 "mp4": c["mp4_url"], "poster": c.get("poster_url") or "",
                                 "headline": c["headline"], "id": c.get("id", "")})

    def fuer(self, links, titel):
        for l in links:
            for c in self.idx:
                if l and l in c["links"]:
                    return c
        k = _fold(titel)
        if not k:
            return None
        for c in self.idx:
            if len(c["key"]) >= 25 and k.startswith(c["key"][:45]):
                return c
        return None


def story_schluessel(art):
    """story_id wird je Lauf neu vergeben (s003 heute ist nicht s003 gestern). Ein
    Cluster ist darum nur: gleiche ID + gleicher Erfassungstag + gleiche Cluster-
    Kennwerte aus demselben Lauf. Ohne story_id: kein Cluster."""
    if not art or not art.get("story_id"):
        return None
    return (art["story_id"], art.get("first_seen") or art.get("date") or "",
            art.get("story_cluster_score"), art.get("story_article_count"))


def baue_linie(lid, linie, artikel_nach_link, artikel_nach_story, karten):
    ereignisse = sorted(linie.get("e") or [], key=lambda e: (e.get("d") or "", e.get("t") or ""))
    dossier = linie.get("dossier") or {}
    abseits = set(dossier.get("abseits") or [])
    out = []
    for i, e in enumerate(ereignisse):
        link = e.get("l") or ""
        art = artikel_nach_link.get(link) or {}
        sid = art.get("story_id") or ""
        quellen, gesehen = [], set()
        for a in [art] + artikel_nach_story.get(story_schluessel(art), []):
            if not a or not a.get("link") or a["link"] in gesehen:
                continue
            gesehen.add(a["link"])
            quellen.append({
                "quelle": _sauber(a.get("source")), "titel": _sauber(a.get("title")), "link": a["link"],
                "datum": a.get("first_seen") or a.get("date") or "",
                "volltext": bool(a.get("full_text")) and not a.get("paywalled"),
                "paywall": bool(a.get("paywalled")), "dublette": bool(a.get("dub_von")),
            })
        if not quellen and link:
            quellen.append({"quelle": _sauber(e.get("q")), "titel": _sauber(e.get("t")), "link": link,
                            "datum": e.get("d") or "", "volltext": False, "paywall": False, "dublette": False})
        for name in art.get("dub_quellen") or []:
            quellen.append({"quelle": _sauber(name), "titel": "", "link": "", "datum": "",
                            "volltext": False, "paywall": False, "dublette": True})
        karte = karten.fuer([q["link"] for q in quellen if q["link"]], e.get("t") or art.get("title"))
        luecke = 0
        if i:
            try:
                luecke = (date.fromisoformat(e.get("d")) - date.fromisoformat(ereignisse[i - 1].get("d"))).days
            except Exception:
                luecke = 0
        out.append({
            "k": e.get("k") or "", "datum": e.get("d") or "", "titel": _sauber(e.get("t")),
            "zusammenfassung": _sauber(e.get("z") or art.get("summary")), "quelle": _sauber(e.get("q")),
            "link": link, "bild": art.get("image") or "", "score": art.get("score"),
            "region": art.get("region") or "", "story_id": sid,
            "befund": any(q["volltext"] for q in quellen),
            "abseits": (e.get("k") in abseits), "luecke_tage": luecke if luecke > LUECKE_TAGE else 0,
            "quellen": quellen,
            "karte": {"mp4": karte["mp4"], "poster": karte["poster"], "headline": _sauber(karte["headline"])} if karte else None,
        })
    quellen_namen = sorted({q["quelle"] for ev in out for q in ev["quellen"] if q["quelle"]})
    return {
        "id": lid, "titel": _sauber(dossier.get("titel")), "worum": _sauber(dossier.get("worum")),
        "seit": linie.get("seit") or (out[0]["datum"] if out else ""),
        "bis": out[-1]["datum"] if out else "", "ereignisse": out, "quellen": quellen_namen,
    }


def hype_funde(d):
    text = " ".join([d["titel"], d["worum"]] + [e["titel"] + " " + e["zusammenfassung"] for e in d["ereignisse"]]).lower()
    return sorted({w for w in VERBOTEN if w in text})


def einleitung(d):
    n = len(d["ereignisse"])
    q = len(d["quellen"])
    mit_karte = sum(1 for e in d["ereignisse"] if e["karte"])
    span = f"zwischen dem {_datum_lang(d['seit'])} und dem {_datum_lang(d['bis'])}" if d["seit"] != d["bis"] \
        else f"am {_datum_lang(d['seit'])}"
    satz = f"Diese Zusammenstellung verfolgt {n} Meldungen {span}, berichtet von {q} Quelle{'n' if q != 1 else ''}."
    if mit_karte:
        satz += f" Zu {mit_karte} Meldung{'en' if mit_karte != 1 else ''} gibt es eine News-Karte als Video."
    return satz


def _medien_url(u, root):
    if not u:
        return ""
    if u.startswith("https://"):
        return u
    return root + u.lstrip("/") if not u.startswith("http") else ""


def rendere(d, stand, entwurf=True):
    root = "../../" if entwurf else "../"
    titel = d["titel"] or d["ereignisse"][-1]["titel"]
    desc = _sauber(einleitung(d))[:158]
    slug = f"entwurf/linie-{d['id']}" if entwurf else f"dossier-{d['id']}"
    canonical = f"https://ki-news.live/artikel/{slug}.html"
    robots = "noindex, nofollow" if entwurf else "index, follow"
    n = len(d["ereignisse"])
    tage = 0
    try:
        tage = (date.fromisoformat(d["bis"]) - date.fromisoformat(d["seit"])).days + 1
    except Exception:
        pass
    leit = next((e for e in reversed(d["ereignisse"]) if e["bild"].startswith("https://")), None)
    daten = {"linie": d["id"], "titel": titel, "stand": stand, "entwurf": entwurf,
             "ereignisse": [{k: v for k, v in e.items() if k != "bild"} for e in d["ereignisse"]]}

    daten_json = json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")

    def pill(t, cls=""):
        return f'<span class="px-pill {cls}">{_e(t)}</span>'

    zeitleiste, fenster = [], []
    for i, e in enumerate(d["ereignisse"]):
        marken = []
        marken.append(pill("Befund", "px-pill--beleg") if e["befund"] else pill("Nur Anriss", "px-pill--anriss"))
        if e["abseits"]:
            marken.append(pill("Abseits", "px-pill--risiko"))
        if any(q["dublette"] for q in e["quellen"]):
            marken.append(pill("Dublette", "px-pill--dub"))
        if e["karte"]:
            marken.append(pill("Karte", "px-pill--karte"))
        if e["luecke_tage"]:
            zeitleiste.append(f'<li class="px-luecke" aria-label="Dossier-Lücke">Dossier-Lücke: {e["luecke_tage"]} Tage ohne Meldung</li>')
        zeitleiste.append(
            f'<li class="px-punkt" data-i="{i}" id="e{i}">'
            f'<button type="button" class="px-punkt-knopf" data-i="{i}" aria-controls="px-fenster" aria-pressed="false">'
            f'<span class="px-punkt-datum">{_e(_datum_kurz(e["datum"]))}{" · Start" if i == 0 else ""}{" · neuester Stand" if i == n - 1 and n > 1 else ""}</span>'
            f'<span class="px-punkt-titel">{_e(e["titel"])}</span>'
            f'<span class="px-punkt-meta">{_e(e["quelle"])} · {len([q for q in e["quellen"] if q["link"]])} Beleg{"e" if len([q for q in e["quellen"] if q["link"]]) != 1 else ""}</span>'
            f'<span class="px-punkt-marken">{"".join(marken)}</span></button></li>'
        )
        belege = []
        for q in e["quellen"]:
            art = "Volltext" if q["volltext"] else ("Paywall, nur Anriss" if q["paywall"] else "Zusammenfassung")
            if q["dublette"] and not q["link"]:
                belege.append(f'<li class="px-beleg px-beleg--dub"><span class="px-beleg-quelle">{_e(q["quelle"])}</span>'
                              f'<span class="px-beleg-art">Gleiche Meldung, zusammengeführt</span></li>')
                continue
            belege.append(
                f'<li class="px-beleg"><a href="{_e(q["link"])}" target="_blank" rel="noopener noreferrer">'
                f'<span class="px-beleg-quelle">{_e(q["quelle"])}</span>'
                f'<span class="px-beleg-titel">{_e(q["titel"] or e["titel"])}</span>'
                f'<span class="px-beleg-art">{_e(art)}{" · " + _e(_datum_kurz(q["datum"])) if q["datum"] else ""}{" · Dublette" if q["dublette"] else ""} ↗</span></a></li>'
            )
        medien = ""
        if e["karte"]:
            mp4 = _medien_url(e["karte"]["mp4"], root)
            poster = _medien_url(e["karte"]["poster"], root)
            medien = (f'<figure class="px-karte"><video controls playsinline preload="none"'
                      f'{" poster=" + chr(34) + _e(poster) + chr(34) if poster else ""} src="{_e(mp4)}"></video>'
                      f'<figcaption>News-Karte: {_e(e["karte"]["headline"])}</figcaption></figure>')
        fenster.append(
            f'<article class="px-ereignis" data-i="{i}" id="f{i}"{"" if i == n - 1 else " hidden"}>'
            f'<div class="px-ereignis-kopf"><span class="px-mono">{_e(_datum_lang(e["datum"]))} · Ereignis {i + 1} von {n}</span>'
            f'{"<span class=" + chr(34) + "px-mono" + chr(34) + ">Score " + str(e["score"]) + "</span>" if isinstance(e["score"], (int, float)) else ""}</div>'
            f'<h3 class="px-ereignis-titel">{_e(e["titel"])}</h3>'
            f'{"<p class=" + chr(34) + "px-ereignis-text" + chr(34) + ">" + _e(e["zusammenfassung"]) + "</p>" if e["zusammenfassung"] else ""}'
            f'{"<p class=" + chr(34) + "px-hinweis px-hinweis--risiko" + chr(34) + ">Abseits: Diese Meldung hängt laut automatischer Prüfung nur lose am Thema der Linie.</p>" if e["abseits"] else ""}'
            f'{medien}'
            f'<h4 class="px-abschnitt">Belege ({len([q for q in e["quellen"] if q["link"]])})</h4><ul class="px-belege">{"".join(belege)}</ul>'
            f'</article>'
        )

    worum = (f'<section class="px-worum"><h2 class="px-abschnitt">Worum es geht</h2><p>{_e(d["worum"])}</p>'
             f'<p class="px-klein">Kurztext automatisch erstellt und gegen die Zusammenfassungen der Meldungen geprüft.</p></section>'
             if d["worum"] else "")
    bild = (f'<img class="px-leit-bild" src="{_e(leit["bild"])}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            if leit else "")
    status = ("Entwurf, nicht freigegeben" if entwurf else "Freigegeben")
    quellen_liste = ", ".join(d["quellen"][:12]) + (" und weitere" if len(d["quellen"]) > 12 else "")

    return f"""<!DOCTYPE html>
<html class="dark" lang="de">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<link rel="icon" type="image/png" href="{root}s-logo.png"/>
<title>{_e(titel)} · Dossier · KI News</title>
<meta name="description" content="{_e(desc)}"/>
<meta name="robots" content="{robots}"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:type" content="article"/>
<meta property="og:title" content="{_e(titel)}"/>
<meta property="og:description" content="{_e(desc)}"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:image" content="{_e(leit['bild']) if leit else 'https://ki-news.live/s-logo.png'}"/>
<meta property="og:locale" content="de_DE"/>
<meta property="og:site_name" content="KI News"/>
<link rel="stylesheet" href="{root}assets/ki-tw.css"/>
<link rel="stylesheet" href="{root}assets/ki-fonts.css"/>
<script src="{root}assets/ki-icons.js" defer></script>
<script>window.KI_ROOT = "{root}";</script>
<style>
/* Chronoskop-Dossier (28.09.26). Formensprache der Seite: Karten 12px, 1px-Neon-Rahmen,
   CSS-Variablen aus ki-layout.js; Akzente: Lime = aktiver Zeitpunkt, Rot = Abseits/Risiko,
   Blau = Befund (Volltext lag vor). */
:root {{
  --px-bg: #05080c; --px-card: rgba(12, 20, 28, 0.92); --px-ink: #eef3f5; --px-muted: #93a4ae;
  --px-line: rgba(var(--neon-rgb, 0, 212, 255), 0.18); --px-lime: #c6f432; --px-rot: #ff5a5f;
  --px-blau: #4ea8ff; --px-violett: #a78bfa;
}}
html.light {{
  --px-bg: #f4f7f9; --px-card: rgba(255, 255, 255, 0.96); --px-ink: #0f172a; --px-muted: #5b6b78;
  --px-line: rgba(0, 150, 190, 0.22); --px-lime: #5f8a00; --px-rot: #c62828; --px-blau: #1565c0;
}}
body {{ background: var(--px-bg); color: var(--px-ink); }}
.px-wrap {{ max-width: 1240px; margin: 0 auto; padding: 72px 16px 64px; }}
.px-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--px-muted); }}
.px-status {{ display: flex; flex-wrap: wrap; gap: 6px 18px; padding: 10px 0; border-block: 1px solid var(--px-line); margin-bottom: 18px; }}
.px-status b {{ color: var(--px-ink); font-weight: 600; }}
.px-karte-rahmen, .px-panel, .px-hero {{ background: var(--px-card); border: 1px solid var(--px-line); border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(var(--neon-rgb, 0, 212, 255), .04), 0 12px 40px rgba(0, 0, 0, .18); }}
.px-hero {{ position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 24px; padding: clamp(20px, 3vw, 36px); }}
.px-kennung {{ display: inline-flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
.px-pill {{ display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 3px 10px; font: 600 10px/1.4 ui-monospace, monospace;
  letter-spacing: .06em; text-transform: uppercase; border: 1px solid var(--px-line); color: var(--px-muted); white-space: nowrap; }}
.px-pill--auto {{ color: var(--accent, #00d4ff); border-color: rgba(var(--neon-rgb, 0, 212, 255), .45); }}
.px-pill--entwurf {{ color: var(--px-lime); border-color: currentColor; }}
.px-pill--beleg {{ color: var(--px-blau); border-color: currentColor; }}
.px-pill--anriss {{ color: var(--px-muted); }}
.px-pill--risiko {{ color: var(--px-rot); border-color: currentColor; }}
.px-pill--dub {{ color: var(--px-violett); border-color: currentColor; }}
.px-pill--karte {{ color: var(--accent, #00d4ff); }}
.px-titel {{ font: 700 clamp(30px, 4.6vw, 54px)/1.04 'Space Grotesk', sans-serif; letter-spacing: -.03em; margin: 6px 0 16px; overflow-wrap: anywhere; hyphens: auto; }}
.px-intro {{ font: 400 17px/1.6 'Work Sans', sans-serif; color: var(--px-muted); max-width: 62ch; }}
.px-metriken {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-self: end; }}
.px-metrik {{ border: 1px solid var(--px-line); border-radius: 12px; padding: 12px; background: rgba(var(--neon-rgb, 0, 212, 255), .03); }}
.px-metrik b {{ display: block; font: 700 26px/1 'Space Grotesk', sans-serif; }}
.px-leit {{ position: relative; border-radius: 12px; overflow: hidden; min-height: 180px; background: linear-gradient(145deg, #07141d, #182a3a 60%, #10121c); }}
.px-leit-bild {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .55; }}
.px-leit::after {{ content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, transparent 30%, rgba(0, 0, 0, .55)); }}
.px-leit .px-mono {{ position: absolute; left: 12px; bottom: 10px; z-index: 1; color: #dfe8ec; }}
.px-rechts {{ display: grid; gap: 12px; align-content: start; }}
.px-worum {{ margin: 18px 0 0; padding: 18px 20px; border-left: 3px solid var(--accent, #00d4ff); background: var(--px-card); border-radius: 0 12px 12px 0; }}
.px-worum p {{ font: 400 16px/1.65 'Work Sans', sans-serif; margin: 6px 0 0; }}
.px-klein {{ font-size: 12px !important; color: var(--px-muted); }}
.px-scrubber {{ margin: 18px 0; padding: 14px 18px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 16px; align-items: center; }}
.px-scrubber input[type=range] {{ width: 100%; accent-color: var(--px-lime); }}
.px-werkbank {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 16px; align-items: start; }}
.px-panel {{ padding: 16px; min-width: 0; }}
.px-panel-kopf {{ display: flex; justify-content: space-between; gap: 8px; align-items: baseline; margin-bottom: 10px; }}
.px-panel-kopf h2 {{ font: 700 18px/1.2 'Space Grotesk', sans-serif; margin: 0; }}
.px-zeit {{ list-style: none; margin: 0; padding: 0 0 0 16px; border-left: 1px dashed var(--px-line); display: grid; gap: 8px; }}
.px-punkt {{ position: relative; }}
.px-punkt::before {{ content: ""; position: absolute; left: -22px; top: 16px; width: 11px; height: 11px; border-radius: 50%; background: var(--px-bg); border: 2px solid var(--px-line); }}
.px-punkt.aktiv::before {{ background: var(--px-lime); border-color: var(--px-lime); box-shadow: 0 0 12px var(--px-lime); }}
.px-punkt-knopf {{ all: unset; box-sizing: border-box; display: grid; gap: 4px; width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid transparent; cursor: pointer; }}
.px-punkt-knopf:hover, .px-punkt-knopf:focus-visible {{ border-color: var(--px-line); background: rgba(var(--neon-rgb, 0, 212, 255), .04); }}
.px-punkt.aktiv .px-punkt-knopf {{ border-color: var(--px-lime); background: rgba(198, 244, 50, .06); }}
.px-punkt-knopf:focus-visible {{ outline: 2px solid var(--accent, #00d4ff); outline-offset: 2px; }}
.px-punkt-datum {{ font: 600 11px/1.3 ui-monospace, monospace; letter-spacing: .06em; color: var(--px-muted); text-transform: uppercase; }}
.px-punkt-titel {{ font: 600 15px/1.35 'Space Grotesk', sans-serif; overflow-wrap: anywhere; }}
.px-punkt-meta {{ font-size: 12px; color: var(--px-muted); }}
.px-punkt-marken {{ display: flex; flex-wrap: wrap; gap: 5px; }}
.px-luecke {{ font: 600 10px/1.3 ui-monospace, monospace; letter-spacing: .08em; text-transform: uppercase; color: var(--px-muted);
  padding: 6px 12px; border: 1px dashed var(--px-line); border-radius: 999px; justify-self: start; }}
.px-fenster {{ position: sticky; top: 72px; }}
.px-ereignis-kopf {{ display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }}
.px-ereignis-titel {{ font: 700 clamp(20px, 2.2vw, 26px)/1.2 'Space Grotesk', sans-serif; margin: 8px 0 10px; overflow-wrap: anywhere; }}
.px-ereignis-text {{ font: 400 15.5px/1.65 'Work Sans', sans-serif; margin: 0 0 12px; }}
.px-hinweis {{ font-size: 13px; padding: 8px 12px; border-radius: 12px; border: 1px solid; }}
.px-hinweis--risiko {{ color: var(--px-rot); }}
.px-abschnitt {{ font: 600 11px/1.3 ui-monospace, monospace; letter-spacing: .1em; text-transform: uppercase; color: var(--accent, #00d4ff); margin: 16px 0 8px; }}
.px-belege {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }}
.px-beleg a, .px-beleg--dub {{ display: grid; gap: 2px; padding: 9px 12px; border: 1px solid var(--px-line); border-radius: 12px; color: inherit; text-decoration: none; }}
.px-beleg a:hover, .px-beleg a:focus-visible {{ border-color: rgba(var(--neon-rgb, 0, 212, 255), .6); box-shadow: 0 0 14px rgba(var(--neon-rgb, 0, 212, 255), .18); }}
.px-beleg-quelle {{ font: 700 11px/1.3 ui-monospace, monospace; text-transform: uppercase; letter-spacing: .06em; color: var(--px-blau); }}
.px-beleg-titel {{ font-size: 14px; line-height: 1.4; overflow-wrap: anywhere; }}
.px-beleg-art {{ font-size: 12px; color: var(--px-muted); }}
.px-karte {{ margin: 12px 0; }}
.px-karte video {{ display: block; width: min(260px, 100%); aspect-ratio: 420 / 660; object-fit: contain; background: #000; border-radius: 12px; border: 1px solid var(--px-line); }}
.px-karte figcaption {{ font-size: 12px; color: var(--px-muted); margin-top: 6px; }}
.px-legende {{ margin-top: 18px; padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px 18px; }}
.px-legende dt {{ margin-bottom: 4px; }}
.px-legende dd {{ margin: 0; font-size: 13px; color: var(--px-muted); line-height: 1.5; }}
.px-fuss {{ margin-top: 18px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }}
.px-knopf {{ border: 1px solid var(--px-line); background: transparent; color: var(--px-ink); border-radius: 999px; padding: 7px 14px; font: 600 12px/1.2 'Work Sans', sans-serif; cursor: pointer; }}
.px-knopf:hover, .px-knopf:focus-visible {{ border-color: var(--accent, #00d4ff); color: var(--accent, #00d4ff); }}
@media (max-width: 860px) {{
  .px-hero, .px-werkbank {{ grid-template-columns: minmax(0, 1fr); }}
  .px-fenster {{ position: static; }}
  .px-scrubber {{ grid-template-columns: minmax(0, 1fr) auto; }}
  .px-scrubber > .px-mono:first-child {{ grid-column: 1 / -1; }}
}}
@media (max-width: 420px) {{ .px-metriken {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} .px-metrik b {{ font-size: 20px; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; transition: none !important; }} }}
</style>
</head>
<body class="font-body-lg">
<script src="{root}assets/ki-layout.js"></script>
<main class="px-wrap" id="px-dossier">
  <div class="px-status px-mono" aria-label="Datenstand">
    <span>Datenstand <b>{_e(stand)}</b></span><span>Linie <b>{_e(d['id'])}</b></span>
    <span>Ereignisse <b>{n}</b></span><span>Quellen <b>{len(d['quellen'])}</b></span><span>Status <b>{_e(status)}</b></span>
  </div>
  <header class="px-hero">
    <div>
      <div class="px-kennung">{pill('Automatische Zusammenstellung', 'px-pill--auto')}{pill('Entwurf', 'px-pill--entwurf') if entwurf else ''}{pill('Dossier')}</div>
      <h1 class="px-titel">{_e(titel)}</h1>
      <p class="px-intro">{_e(einleitung(d))}</p>
    </div>
    <div class="px-rechts">
      <div class="px-leit">{bild}<span class="px-mono">Linie {_e(d['id'])} · seit {_e(_datum_kurz(d['seit']))}</span></div>
      <div class="px-metriken">
        <div class="px-metrik"><b>{n}</b><span class="px-mono">Ereignisse</span></div>
        <div class="px-metrik"><b>{len(d['quellen'])}</b><span class="px-mono">Quellen</span></div>
        <div class="px-metrik"><b>{tage}</b><span class="px-mono">Tage</span></div>
      </div>
    </div>
  </header>
  {worum}
  <section class="px-scrubber px-karte-rahmen" aria-label="Zeit-Scrubber">
    <span class="px-mono">Zeit-Scrubber</span>
    <input id="px-regler" type="range" min="0" max="{n - 1}" value="{n - 1}" step="1" aria-label="Ereignis auswählen" aria-valuetext="Ereignis {n} von {n}">
    <span class="px-mono" id="px-anzeige">{n} / {n}</span>
  </section>
  <section class="px-werkbank">
    <section class="px-panel" aria-labelledby="px-zeit-titel">
      <div class="px-panel-kopf"><h2 id="px-zeit-titel">Zeitachse</h2><span class="px-mono">ältestes oben</span></div>
      <ol class="px-zeit">{''.join(zeitleiste)}</ol>
    </section>
    <aside class="px-panel px-fenster" id="px-fenster" aria-live="polite" aria-label="Dossier-Fenster">
      <div class="px-panel-kopf"><h2>Dossier-Fenster</h2><span class="px-mono">Belege und Karte</span></div>
      {''.join(fenster)}
    </aside>
  </section>
  <section class="px-legende px-karte-rahmen" aria-label="Legende">
    <dl><dt>{pill('Befund', 'px-pill--beleg')}</dt><dd>Mindestens eine Quelle lag im Volltext vor.</dd></dl>
    <dl><dt>{pill('Nur Anriss')}</dt><dd>Nur Feed-Text oder Zusammenfassung, etwa wegen Paywall. Die Aussage ist berichtet, nicht geprüft.</dd></dl>
    <dl><dt>{pill('Dublette', 'px-pill--dub')}</dt><dd>Dieselbe Meldung erschien bei mehreren Quellen und wurde zusammengeführt.</dd></dl>
    <dl><dt>{pill('Abseits', 'px-pill--risiko')}</dt><dd>Laut automatischer Prüfung nur lose mit dem Thema der Linie verbunden.</dd></dl>
    <dl><dt><span class="px-luecke">Dossier-Lücke</span></dt><dd>Mehr als {LUECKE_TAGE} Tage ohne neue Meldung zwischen zwei Ereignissen.</dd></dl>
  </section>
  <footer class="px-fuss">
    <p class="px-klein" style="margin:0">Automatisch aus den Meldungen von ki-news.live zusammengestellt. Quellen: {_e(quellen_liste)}.
      <a href="{root}linie.html#l={_e(d['id'])}" style="color:var(--accent,#00d4ff)">Linie ansehen</a></p>
    <div style="display:flex;gap:8px"><button class="px-knopf" type="button" data-export="json">Export JSON</button>
      <button class="px-knopf" type="button" data-export="md">Schnellbericht (Markdown)</button></div>
  </footer>
</main>
<script type="application/json" id="px-daten">{daten_json}</script>
<script>
(function () {{
  "use strict";
  var daten; try {{ daten = JSON.parse(document.getElementById("px-daten").textContent); }} catch (e) {{ return; }}
  var n = daten.ereignisse.length, regler = document.getElementById("px-regler"), anzeige = document.getElementById("px-anzeige");
  var punkte = document.querySelectorAll(".px-punkt"), fenster = document.querySelectorAll(".px-ereignis");
  var schmal = window.matchMedia("(max-width: 860px)");
  function zeige(i, scrollen) {{
    i = Math.max(0, Math.min(n - 1, i));
    punkte.forEach(function (p) {{ var a = +p.dataset.i === i; p.classList.toggle("aktiv", a); p.querySelector("button").setAttribute("aria-pressed", a ? "true" : "false"); }});
    fenster.forEach(function (f) {{ f.hidden = +f.dataset.i !== i; if (f.hidden) {{ var v = f.querySelector("video"); if (v) v.pause(); }} }});
    regler.value = i; regler.setAttribute("aria-valuetext", "Ereignis " + (i + 1) + " von " + n);
    anzeige.textContent = (i + 1) + " / " + n;
    if (scrollen && schmal.matches) {{ var f = document.getElementById("px-fenster"); if (f) f.scrollIntoView({{ block: "start" }}); }}
  }}
  regler.addEventListener("input", function () {{ zeige(+regler.value, false); }});
  document.querySelectorAll(".px-punkt-knopf").forEach(function (b) {{ b.addEventListener("click", function () {{ zeige(+b.dataset.i, true); }}); }});
  document.addEventListener("keydown", function (ev) {{
    if (ev.target && /input|textarea|select/i.test(ev.target.tagName)) return;
    if (ev.key === "ArrowDown" || ev.key === "j") {{ zeige(+regler.value + 1, false); ev.preventDefault(); }}
    if (ev.key === "ArrowUp" || ev.key === "k") {{ zeige(+regler.value - 1, false); ev.preventDefault(); }}
  }});
  function laden(name, typ, inhalt) {{
    var a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([inhalt], {{ type: typ }})); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(function () {{ URL.revokeObjectURL(a.href); a.remove(); }}, 500);
  }}
  document.querySelectorAll("[data-export]").forEach(function (b) {{
    b.addEventListener("click", function () {{
      if (b.dataset.export === "json") return laden("dossier-" + daten.linie + ".json", "application/json", JSON.stringify(daten, null, 2));
      var md = ["# " + daten.titel, "", "Automatische Zusammenstellung, Datenstand " + daten.stand + ", Linie " + daten.linie, ""];
      daten.ereignisse.forEach(function (e) {{
        md.push("## " + e.datum + ": " + e.titel, "", e.zusammenfassung || "", "");
        e.quellen.forEach(function (q) {{ if (q.link) md.push("- " + q.quelle + ": " + q.link); }});
        md.push("");
      }});
      laden("dossier-" + daten.linie + ".md", "text/markdown", md.join("\\n"));
    }});
  }});
  zeige(n - 1, false);
}})();
</script>
</body>
</html>
"""


def sitemap_eintrag(url):
    try:
        s = SITEMAP.read_text(encoding="utf-8")
    except Exception:
        return False
    if url in s:
        return False
    zeile = f"  <url><loc>{url}</loc><lastmod>{date.today().isoformat()}</lastmod></url>\n"
    SITEMAP.write_text(s.replace("</urlset>", zeile + "</urlset>"), encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--linie", action="append", help="nur diese Linien-ID(s)")
    ap.add_argument("--max", type=int, default=0, help="hoechstens N Linien (nach Groesse)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    news = _lade("news.json", {})
    linien = news.get("linien") or {}
    archiv = _lade("archive.json", [])
    karten = KartenIndex(_lade("cards.json", []))
    freigabe = (_lade("dossiers_freigabe.json", {}) or {}).get("freigegeben") or {}
    stand = news.get("stand") or datetime.now().strftime("%d.%m.%Y %H:%M")

    nach_link, nach_story = {}, {}
    for art in list(archiv) + list(news.get("news") or []):  # news zuletzt: aktuellster Stand gewinnt
        if not isinstance(art, dict) or not art.get("link"):
            continue
        nach_link[art["link"]] = art
    for art in nach_link.values():
        key = story_schluessel(art)
        if key:
            nach_story.setdefault(key, []).append(art)
    for liste in nach_story.values():
        liste.sort(key=lambda x: -(x.get("score") or 0))

    ids = [lid for lid, l in linien.items()
           if len(l.get("e") or []) >= MIN_EREIGNISSE and (l.get("dossier") or {}).get("titel")]
    ids.sort(key=lambda lid: -len(linien[lid]["e"]))
    if a.linie:
        ids = [i for i in ids if i in a.linie]
    if a.max:
        ids = ids[: a.max]

    print(f"dossier_automat: {len(ids)} Linien mit geprueftem Titel und >= {MIN_EREIGNISSE} Ereignissen")
    if not a.dry_run:
        ENTWURF_DIR.mkdir(parents=True, exist_ok=True)
    verzeichnis = []
    for lid in ids:
        d = baue_linie(lid, linien[lid], nach_link, nach_story, karten)
        funde = hype_funde(d)
        karten_n = sum(1 for e in d["ereignisse"] if e["karte"])
        print(f"  {lid}  {len(d['ereignisse']):>2} Ereignisse  {len(d['quellen']):>2} Quellen  {karten_n} Karten  "
              f"{d['titel'][:60]}" + (f"  HYPE-WOERTER in Quelltexten: {', '.join(funde)}" if funde else ""))
        if a.dry_run:
            continue
        (ENTWURF_DIR / f"linie-{lid}.html").write_text(rendere(d, stand, entwurf=True), encoding="utf-8")
        verzeichnis.append({"id": lid, "titel": d["titel"], "ereignisse": len(d["ereignisse"]),
                            "datei": f"artikel/entwurf/linie-{lid}.html", "hype": funde})
        if lid in freigabe:
            (BASE / "artikel" / f"dossier-{lid}.html").write_text(rendere(d, stand, entwurf=False), encoding="utf-8")
            if sitemap_eintrag(f"https://ki-news.live/artikel/dossier-{lid}.html"):
                print(f"    freigegeben -> artikel/dossier-{lid}.html, Sitemap ergaenzt")
    if not a.dry_run:
        # Verzeichnis fuer redaktion.html (welche Entwuerfe es gibt), ergaenzt statt ersetzt,
        # damit ein Lauf mit --linie/--max aeltere Entwuerfe nicht aus der Liste wirft.
        ziel = ENTWURF_DIR / "entwuerfe.json"
        try:
            alt = {e["id"]: e for e in json.loads(ziel.read_text(encoding="utf-8")).get("entwuerfe", [])}
        except Exception:
            alt = {}
        alt = {k: v for k, v in alt.items() if (BASE / v.get("datei", "")).exists()}
        for e in verzeichnis:
            alt[e["id"]] = e
        ziel.write_text(json.dumps({"stand": stand, "entwuerfe": sorted(alt.values(), key=lambda e: -e["ereignisse"])},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
