#!/usr/bin/env python3
"""Release-Automat (28.09.26, Auftrag 5, Release-Teil).

Macht aus neuen Eintraegen in hersteller.json (hersteller_feed.py) Artikel-Entwuerfe
"<Modell>: was es kann" im Stil von Daniels Hand-Artikel (Titel, Stand, Hinweis-
kasten, nummerierte Abschnitte mit Zitat-Karten und Quellen-Links).

Redaktionsregeln (Daniel):
- Nur Aussagen aus den Quellen. Der Artikel besteht aus woertlichen Zitaten der
  offiziellen Ankuendigung (mit Link), den Zahlen-Saetzen daraus (woertlich), und
  den Meldungen der Pipeline, die das Modell nennen (Titel/Zusammenfassung wie im
  Feed). Einleitung und Eckdaten werden aus den Feldern gebaut, ohne Sprachmodell.
- Optional: deutsche Uebersetzung der Zitate mit dem Modell, das die Pipeline schon
  nutzt (hersteller_feed.uebersetze, OPENROUTER_KEY). Verworfen, wenn sie eine Zahl
  enthaelt, die im Original fehlt. Ohne Key bleibt das Original stehen.
- Sichtbar "Automatische Zusammenstellung", Entwurf in artikel/entwurf/ (noindex),
  Freigabe ueber dossiers_freigabe.json (id "release-<slug>"), dann artikel/<slug>.html.
- Kein Em-Dash. Hype-Woerter werden gemeldet, Zitate aber nicht umgeschrieben.

Aufruf: python3 release_automat.py [--max N] [--dry-run] [--ohne-uebersetzung]
"""
import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import hersteller_feed as hf
from dossier_automat import VERBOTEN, ENTWURF_DIR, FREIGABE, sitemap_eintrag, _datum_lang

BASE = Path(__file__).resolve().parent
MAX_ZITATE = 6
MAX_ZAHLEN = 8


def slug(text):
    t = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]


def _e(s):
    return html.escape(re.sub(r"\s+", " ", str(s or "")).strip().replace("—", "-").replace("–", "-"), quote=True)


def absaetze(seite):
    """Fliesstext-Absaetze der offiziellen Seite: <p>-Inhalte ohne Navigation/CSS."""
    out = []
    for roh in re.findall(r"<p[^>]*>(.*?)</p>", seite, re.S):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", roh))).strip()
        t = re.sub(r"\s+([.,;:!?])", r"\1", t)  # Leerzeichen aus entfernten Tags vor Satzzeichen
        if len(t) < 70 or "{" in t or "}" in t:
            continue
        if any(len(w) > 32 for w in t.split()):  # zusammengeklebte Navigation
            continue
        if t in out:
            continue
        woerter = t.split()
        gross = sum(1 for w in woerter if w[:1].isupper()) / max(1, len(woerter))
        if not re.search(r"[a-z][.!?:]", t) or gross > 0.6:  # Navigation, Menues, Datumsleisten
            continue
        out.append(t)
    return out


def saetze_mit_zahlen(texte, modell):
    """Saetze mit Zahlen (Benchmarks, Preise, Prozent) woertlich; Modellnummern allein zaehlen nicht."""
    ohne_modell = re.escape(re.sub(r"\s+", " ", modell))
    funde = []
    for t in texte:
        for satz in re.split(r"(?<=[.!?])\s+", t):
            rest = re.sub(ohne_modell, "", satz, flags=re.I)
            rest = re.sub(r"\b(?:GPT|Claude|Opus|Sonnet|Haiku|Fable|Gemini|Llama|Grok|Qwen|DeepSeek)[\s-]?[\d.]+", "", rest, flags=re.I)
            if re.search(r"\d", rest) and 30 < len(satz) < 400 and satz not in funde:
                funde.append(satz)
    return funde[:MAX_ZAHLEN]


def berichterstattung(modell, news, archiv):
    n = re.sub(r"[^a-z0-9.]+", " ", modell.lower()).strip()
    treffer, gesehen = [], set()
    for a in list(news) + list(archiv):
        if not isinstance(a, dict) or not a.get("link") or a["link"] in gesehen or a.get("dub_von"):
            continue
        t = re.sub(r"[^a-z0-9.]+", " ", ((a.get("title") or "") + " " + (a.get("summary") or "")).lower())
        if n and n in t:
            gesehen.add(a["link"])
            treffer.append(a)
    treffer.sort(key=lambda a: a.get("first_seen") or a.get("date") or "", reverse=True)
    return treffer[:10]


def baue_release(r, news, archiv, uebersetzen):
    seite, gelesen = "", False
    try:
        seite = hf._get(r["url"], timeout=25)
        gelesen = True
    except Exception:
        pass
    texte = absaetze(seite) if gelesen else []
    if not texte and r.get("text_en"):
        texte = [r["text_en"]]
    elif not texte and r.get("text"):
        texte = [r["text"]]
    zitate = texte[:MAX_ZITATE]
    zahlen = saetze_mit_zahlen(texte, r["modell"])
    de = {}
    if uebersetzen:
        for z in zitate + zahlen:
            u = uebersetzen(z)
            if u:
                de[z] = u
    return {"r": r, "gelesen": gelesen and bool(absaetze(seite)), "zitate": zitate, "zahlen": zahlen, "de": de,
            "berichte": berichterstattung(r["modell"], news, archiv)}


def zitat_karte(text, de, quelle, link):
    innen = f'<p class="rl-q">„{_e(text)}“</p>'
    if de:
        innen = f'<p class="rl-de">{_e(de)}</p><details><summary>Original (Englisch)</summary>{innen}</details>'
    return (f'<article class="rl-card">{innen}<p class="rl-meta">{_e(quelle)} · '
            f'<a href="{_e(link)}" target="_blank" rel="noopener noreferrer">Zur Ankündigung ↗</a></p></article>')


def rendere(b, stand, entwurf=True):
    r = b["r"]
    root = "../../" if entwurf else "../"
    s = slug(r["modell"]) + "-was-es-kann"
    titel = f'{r["modell"]}: was es kann'
    canonical = f"https://ki-news.live/artikel/{'entwurf/release-' if entwurf else ''}{s}.html"
    sub = (f'Automatische Zusammenstellung aus der offiziellen Ankündigung von {r["hersteller"]} vom {_datum_lang(r["datum"])}'
           + (f' und {len(b["berichte"])} Meldung{"en" if len(b["berichte"]) != 1 else ""} aus dem KI-News-Feed' if b["berichte"] else "")
           + f'. Stand: {stand}.')
    warn = ("Alle Angaben stammen aus den verlinkten Quellen und sind nicht unabhängig geprüft. Zitate und Zahlen stehen wörtlich "
            "wie in der Ankündigung des Herstellers.")
    if not b["gelesen"]:
        warn += " Die offizielle Seite ließ sich nicht maschinell lesen; zitiert ist der Text aus dem Feed des Herstellers."
    if b["de"]:
        warn += " Deutsche Fassungen sind automatisch übersetzt, das Original steht jeweils darunter."
    teile = []
    eck = [("Hersteller", r["hersteller"]), ("Modell", r["modell"]), ("Angekündigt", _datum_lang(r["datum"]))]
    eck_html = "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in eck)
    links = [f'<a class="rl-pill" href="{_e(r["url"])}" target="_blank" rel="noopener noreferrer">Offizielle Ankündigung ↗</a>']
    if r.get("x_url"):
        links.append(f'<a class="rl-pill" href="{_e(r["x_url"])}" target="_blank" rel="noopener noreferrer">X-Post ↗</a>')
    teile.append(f'<h2>1. Eckdaten</h2><dl class="rl-eck">{eck_html}</dl><p class="rl-links">{"".join(links)}</p>')
    if r.get("video_url"):
        vid = _e(r["video_url"])
        teile.append('<div class="rl-video" data-src="' + vid + '"><button type="button" class="rl-play">▶ Video der Ankündigung laden</button>'
                     '<p class="rl-meta">Lädt erst nach Klick (Datenschutz).</p></div>')
    elif r.get("poster"):
        teile.append(f'<img class="rl-bild" src="{_e(r["poster"])}" alt="" loading="lazy" referrerpolicy="no-referrer">')
    n = 2
    if b["zitate"]:
        karten = "".join(zitat_karte(z, b["de"].get(z), r["hersteller"], r["url"]) for z in b["zitate"])
        teile.append(f'<h2>{n}. Was neu ist, laut {_e(r["hersteller"])}</h2><div class="rl-grid">{karten}</div>'); n += 1
    if b["zahlen"]:
        karten = "".join(zitat_karte(z, b["de"].get(z), r["hersteller"], r["url"]) for z in b["zahlen"])
        teile.append(f'<h2>{n}. Zahlen aus der Ankündigung</h2><p class="rl-hinweis">Benchmarks, Preise und Prozentwerte, so wie der Hersteller sie nennt. '
                     f'Nicht nachgemessen.</p><div class="rl-grid">{karten}</div>'); n += 1
    if b["berichte"]:
        karten = "".join(
            f'<article class="rl-card"><p class="rl-meta">{_e(a.get("source"))} · {_e((a.get("first_seen") or a.get("date") or "")[:10])}</p>'
            f'<h3><a href="{_e(a["link"])}" target="_blank" rel="noopener noreferrer">{_e(a.get("title"))}</a></h3>'
            + (f'<p class="rl-bd">{_e(a.get("summary"))}</p>' if a.get("summary") else "") + "</article>"
            for a in b["berichte"])
        teile.append(f'<h2>{n}. Was andere berichten</h2><p class="rl-hinweis">Meldungen aus dem KI-News-Feed, die {_e(r["modell"])} nennen. '
                     f'Zusammenfassungen wie im Feed.</p><div class="rl-grid">{karten}</div>'); n += 1
    quellen = [r["url"]] + [a["link"] for a in b["berichte"]]
    teile.append(f'<h2>{n}. Quellen</h2><ol class="rl-quellen">' + "".join(
        f'<li><a href="{_e(q)}" target="_blank" rel="noopener noreferrer">{_e(q)}</a></li>' for q in quellen) + "</ol>")
    beschreibung = _e(f'{titel}. Automatische Zusammenstellung aus der Ankündigung von {r["hersteller"]} und der Berichterstattung.')[:160]
    return s, f"""<!DOCTYPE html>
<html class="dark" lang="de">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<link rel="icon" type="image/png" href="{root}s-logo.png"/>
<title>{_e(titel)} · KI News</title>
<meta name="description" content="{beschreibung}"/>
<meta name="robots" content="{'noindex, nofollow' if entwurf else 'index, follow'}"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:type" content="article"/>
<meta property="og:title" content="{_e(titel)}"/>
<meta property="og:description" content="{beschreibung}"/>
<meta property="og:image" content="{_e(r.get('poster') or 'https://ki-news.live/s-logo.png')}"/>
<link rel="stylesheet" href="{root}assets/ki-tw.css"/>
<link rel="stylesheet" href="{root}assets/ki-fonts.css"/>
<script src="{root}assets/ki-icons.js" defer></script>
<script>window.KI_ROOT = "{root}";</script>
<style>
:root {{ --rl-bg: #05080c; --rl-card: rgba(12, 20, 28, .9); --rl-ink: #eef3f5; --rl-muted: #93a4ae; --rl-line: rgba(var(--neon-rgb, 0, 212, 255), .18); }}
html.light {{ --rl-bg: #f4f7f9; --rl-card: #fff; --rl-ink: #0f172a; --rl-muted: #5b6b78; --rl-line: rgba(0, 150, 190, .22); }}
body {{ background: var(--rl-bg); color: var(--rl-ink); }}
.rl {{ max-width: 920px; margin: 0 auto; padding: 84px 16px 64px; }}
.rl-kenn {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
.rl-pill {{ display: inline-flex; border: 1px solid var(--rl-line); border-radius: 999px; padding: 4px 11px; font: 600 11px/1.4 ui-monospace, monospace; letter-spacing: .05em; text-transform: uppercase; color: var(--accent, #00d4ff); text-decoration: none; }}
.rl-pill--entwurf {{ color: #c6f432; border-color: currentColor; }}
h1 {{ font: 700 clamp(34px, 5.4vw, 58px)/1.04 'Space Grotesk', sans-serif; letter-spacing: -.03em; margin: 0 0 12px; overflow-wrap: anywhere; }}
.rl-sub {{ font: 400 16px/1.6 'Work Sans', sans-serif; color: var(--rl-muted); margin: 0 0 16px; }}
.rl-warn {{ border: 1px solid rgba(245, 158, 11, .5); background: rgba(245, 158, 11, .07); border-radius: 12px; padding: 12px 14px; font-size: 14px; line-height: 1.55; margin: 0 0 24px; }}
h2 {{ font: 700 24px/1.2 'Space Grotesk', sans-serif; margin: 34px 0 12px; }}
h3 {{ font: 600 16px/1.35 'Space Grotesk', sans-serif; margin: 0; }}
h3 a {{ color: inherit; text-decoration: none; }} h3 a:hover {{ color: var(--accent, #00d4ff); }}
.rl-eck {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 0; }}
.rl-eck div {{ border: 1px solid var(--rl-line); border-radius: 12px; padding: 12px; background: var(--rl-card); }}
.rl-eck dt {{ font: 600 10px/1.3 ui-monospace, monospace; letter-spacing: .08em; text-transform: uppercase; color: var(--rl-muted); }}
.rl-eck dd {{ margin: 4px 0 0; font: 700 18px/1.2 'Space Grotesk', sans-serif; }}
.rl-links {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; }}
.rl-grid {{ display: grid; gap: 10px; }}
.rl-card {{ border: 1px solid var(--rl-line); border-radius: 12px; padding: 14px 16px; background: var(--rl-card); display: grid; gap: 8px; }}
.rl-q {{ font: italic 400 15.5px/1.6 'Work Sans', sans-serif; margin: 0; }}
.rl-de {{ font: 400 16px/1.6 'Work Sans', sans-serif; margin: 0; }}
.rl-bd {{ font-size: 14px; line-height: 1.55; color: var(--rl-muted); margin: 0; }}
.rl-meta {{ font: 600 11px/1.4 ui-monospace, monospace; color: var(--rl-muted); margin: 0; }}
.rl-meta a {{ color: var(--accent, #00d4ff); text-decoration: none; }}
details summary {{ cursor: pointer; font-size: 12px; color: var(--rl-muted); }}
.rl-hinweis {{ font-size: 13px; color: var(--rl-muted); margin: -4px 0 10px; }}
.rl-bild {{ width: 100%; border-radius: 12px; border: 1px solid var(--rl-line); margin-top: 16px; }}
.rl-video {{ margin-top: 16px; border: 1px dashed var(--rl-line); border-radius: 12px; padding: 16px; text-align: center; }}
.rl-play {{ border: 1px solid var(--accent, #00d4ff); background: transparent; color: var(--accent, #00d4ff); border-radius: 999px; padding: 9px 16px; font: 600 13px/1 'Work Sans', sans-serif; cursor: pointer; }}
.rl-quellen {{ font-size: 13px; line-height: 1.7; padding-left: 20px; overflow-wrap: anywhere; }}
.rl-quellen a {{ color: var(--accent, #00d4ff); }}
</style>
</head>
<body class="font-body-lg">
<script src="{root}assets/ki-layout.js"></script>
<main class="rl">
  <div class="rl-kenn"><span class="rl-pill">Automatische Zusammenstellung</span>{'<span class="rl-pill rl-pill--entwurf">Entwurf</span>' if entwurf else ''}<span class="rl-pill">{_e(r['hersteller'])}</span></div>
  <h1>{_e(titel)}</h1>
  <p class="rl-sub">{_e(sub)}</p>
  <p class="rl-warn"><strong>Wichtig:</strong> {_e(warn)}</p>
  {''.join(teile)}
</main>
<script>
document.querySelectorAll(".rl-video").forEach(function (box) {{
  var b = box.querySelector(".rl-play"); if (!b) return;
  b.onclick = function () {{
    var src = box.getAttribute("data-src"), v = document.createElement("video");
    v.controls = true; v.autoplay = true; v.playsInline = true; v.src = src; v.style.width = "100%"; v.style.borderRadius = "12px";
    box.replaceChildren(v);
  }};
}});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ohne-uebersetzung", action="store_true")
    a = ap.parse_args()
    try:
        releases = json.loads((BASE / "hersteller.json").read_text(encoding="utf-8")).get("releases") or []
    except Exception:
        print("release_automat: keine hersteller.json - nichts zu tun")
        return 0
    news = json.loads((BASE / "news.json").read_text(encoding="utf-8"))
    archiv = json.loads((BASE / "archive.json").read_text(encoding="utf-8")) if (BASE / "archive.json").exists() else []
    freigabe = (json.loads(FREIGABE.read_text(encoding="utf-8")) if FREIGABE.exists() else {}).get("freigegeben") or {}
    stand = news.get("stand") or datetime.now().strftime("%d.%m.%Y %H:%M")
    uebersetzen = None if a.ohne_uebersetzung else hf.uebersetze
    ENTWURF_DIR.mkdir(parents=True, exist_ok=True)
    verzeichnis = []
    for r in releases[: a.max]:
        b = baue_release(r, news.get("news") or [], archiv, uebersetzen)
        s, seite = rendere(b, stand, entwurf=True)
        text = re.sub(r"<[^>]+>", " ", seite).lower()
        funde = sorted({w for w in VERBOTEN if w in text})
        print(f"  {r['modell']:<28} Zitate {len(b['zitate'])}  Zahlen {len(b['zahlen'])}  Berichte {len(b['berichte'])}  "
              f"Seite gelesen: {'ja' if b['gelesen'] else 'nein (Feed-Text)'}  uebersetzt: {len(b['de'])}"
              + (f"  HYPE: {', '.join(funde)}" if funde else ""))
        if a.dry_run:
            continue
        (ENTWURF_DIR / f"release-{s}.html").write_text(seite, encoding="utf-8")
        verzeichnis.append({"id": f"release-{s}", "typ": "release", "titel": f"{r['modell']}: was es kann",
                            "ereignisse": len(b["berichte"]), "datei": f"artikel/entwurf/release-{s}.html", "hype": funde})
        if f"release-{s}" in freigabe:
            _, live = rendere(b, stand, entwurf=False)
            (BASE / "artikel" / f"{s}.html").write_text(live, encoding="utf-8")
            sitemap_eintrag(f"https://ki-news.live/artikel/{s}.html")
    if verzeichnis:
        ziel = ENTWURF_DIR / "entwuerfe.json"
        try:
            alt = {e["id"]: e for e in json.loads(ziel.read_text(encoding="utf-8")).get("entwuerfe", [])}
        except Exception:
            alt = {}
        for e in verzeichnis:
            alt[e["id"]] = e
        ziel.write_text(json.dumps({"stand": stand, "entwuerfe": sorted(alt.values(), key=lambda e: -e.get("ereignisse", 0))},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
