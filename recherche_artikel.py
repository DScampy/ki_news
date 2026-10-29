#!/usr/bin/env python3
"""Recherche-Artikel (29.10.26, Daniel): aus mehreren Quellen zur selben Story ein eigener
Hintergrundartikel, inklusive offizieller Herstellerseite und deren Video/X-Post.

Unterschied zu dossier_automat/release_automat: Hier schreibt ein Sprachmodell Fliesstext
(Daniels Entscheidung B, 29.10.). Dafuer gelten harte Pruefungen, und nur was ALLE besteht,
geht automatisch raus ("wenn nach der Pruefung, dann raus damit"):

  1. Nur Quellenmaterial: Der Prompt verbietet Vorwissen. Jede Zahl, jedes Datum, jede Rolle
     und jede Person mit Kontext-Label muss im Material stehen (tools/deckungspruefung.pruefe,
     dieselbe Pruefung wie fuer die Einordnungen), dazu Produkt-/Firmennamen mit Ziffer oder
     Binnen-Grossbuchstabe (GPT-6, DeepMind) und jede Entitaet aus entities.json.
  2. Stil: kein Gedanken-/Halbgeviertstrich, kein Semikolon, kein Ausrufezeichen, keine
     Wir-Perspektive, keine Verbotswoerter, hoechstens ein Weichmacher, Laengen-Rahmen.
  3. Belege: jeder Absatz nennt mindestens eine Quellennummer.
  4. Jev (TypeSafe) je Absatz gegen die dort genannten Quellen und fuer Titel+Anriss gegen
     alles: "durch die Quellen gedeckt?" p >= JEV_SCHWELLE. Kein Key/Fehler = nicht bestanden.

Bestanden -> recherche/<slug>.html (indexierbar, recherche/sitemap.xml), meldungsseiten.py
verlinkt den Artikel als "Hintergrund" auf der Meldungsseite (ab dem naechsten Lauf).
Nicht bestanden -> artikel/entwurf/recherche-<slug>.html (noindex) mit Pruefbericht, damit
Daniel sieht, woran es lag. Eine Story wird nur einmal versucht (keine Kostenschleife).

Einziger Schreiber von recherche/ und artikel/entwurf/recherche-*.html (I5).
Laeuft als eigener Workflow-Schritt nach hersteller_feed.py, continue-on-error (I8).
Kill-Switch: RECHERCHE_AKTIV = False.

Aufruf: python3 recherche_artikel.py [--story SID] [--nur-entwurf] [--dry-run]
"""
import argparse
import html
import importlib.util
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meldungsseiten as ms

RECHERCHE_AKTIV = True
BASE = Path(__file__).resolve().parent
ORDNER = BASE / "recherche"
REGISTER = ORDNER / "index.json"
ENTWURF_DIR = BASE / "artikel" / "entwurf"
SITE = "https://ki-news.live"
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # Windows ohne tzdata (lokaler Test)
    BERLIN = timezone(timedelta(hours=1))

MIN_QUELLEN = 3                  # verschiedene Medien je Story
MIN_QUELLEN_MIT_HERSTELLER = 2   # ... oder 2, wenn die Herstellerseite dazukommt
MIN_TEXTQUELLEN = 2              # davon mit lesbarem Text (>= 600 Zeichen)
MAX_PRO_TAG = 2
MAX_PRO_LAUF = 1
TEXT_JE_QUELLE = 3000            # Zeichen Quelltext je Quelle im Prompt
JEV_SCHWELLE = 0.8
# 29.10.26 im OpenRouter-Katalog geprueft. Sonnet zuerst (Deutsch, haelt Regeln), ~0,03 $ je
# Artikel bei <= 2 Artikeln am Tag. Hoechstens MAX_SCHREIBVERSUCHE Modelle je Story.
MODELLE = ["anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash"]
MAX_SCHREIBVERSUCHE = 2

VERBOTEN = ["revolutionär", "bahnbrechend", "game-changer", "gamechanger", "disruptiv",
            "paradigmenwechsel", "nie dagewesen", "synergie", "nahtlos", "tiefgreifend",
            "vielschichtig", "facettenreich", "ganzheitlich", "richtungsweisend", "wegweisend",
            "zukunftsweisend", "spannend", "bleibt abzuwarten", "in einer welt", "zusammenfassend",
            "es ist wichtig zu beachten", "ehrlich gesagt", "offen gesagt", "verändert alles",
            "verändert die welt"]
WEICHMACHER = r"\b(?:möglicherweise|könnte\w*|eventuell|wirft die frage auf)\b"
WIR = r"\b(?:wir|uns|unser\w*)\b"

_FRAGE_GEDECKT = {
    "type": "noul",
    "instructions": "Ist jede Tatsachenbehauptung in `text` (Zahlen, Namen, Rollen, Daten, Ereignisse, "
                    "Zuschreibungen) durch `quellen` gedeckt? Übersetzung ins Deutsche und eigene "
                    "Formulierung sind erlaubt.",
    "criteria": {
        "true": "Ja: alles steht so oder sinngemäß in den Quellen, Herstellerangaben sind als solche "
                "erkennbar.",
        "false": "Nein: mindestens eine Behauptung fehlt in den Quellen, ist verfälscht, übertrieben, "
                 "als Tatsache statt als Herstellerangabe dargestellt oder der falschen Quelle/Person "
                 "zugeschrieben.",
    },
}


def _deckung():
    spec = importlib.util.spec_from_file_location("deckungspruefung", BASE / "tools" / "deckungspruefung.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lade(pfad, leer):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return leer


def _zahl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sauber(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ── Auswahl ──────────────────────────────────────────────────────────────────

def kandidaten(news, releases, register, nur_story=None):
    erledigt = {l for e in register.values() for l in e.get("links", [])}
    storys = {}
    for n in news:
        if n.get("link") and n.get("story_id"):
            storys.setdefault(n["story_id"], []).append(n)
    out = []
    for sid, glieder in storys.items():
        if nur_story and sid != nur_story:
            continue
        links = {l for g in glieder for l in ms._links(g)}
        if links & erledigt:
            continue
        medien = {(g.get("source") or "").strip().lower() for g in glieder} - {""}
        rel = next((r for r in releases if r.get("story_id") == sid or r.get("news_link") in links), None)
        if not (len(medien) >= MIN_QUELLEN or (rel and len(medien) >= MIN_QUELLEN_MIT_HERSTELLER)):
            continue
        rep = max(glieder, key=lambda x: _zahl(x.get("score")))
        out.append({"sid": sid, "rep": rep, "glieder": glieder, "links": sorted(links), "release": rel})
    out.sort(key=lambda k: _zahl(k["rep"].get("score")), reverse=True)
    return out


def _absaetze(seite):
    """Nur Fliesstext-Absaetze (<p> ab 60 Zeichen, ohne Dubletten), keine Menues/Listen."""
    s = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", seite)
    out, gesehen = [], set()
    for roh in re.findall(r"(?is)<p[^>]*>(.*?)</p>", s):
        t = _sauber(html.unescape(re.sub(r"<[^>]+>", " ", roh)))
        if len(t) >= 60 and t not in gesehen:
            gesehen.add(t)
            out.append(t)
    return " ".join(out)


def _quelltext(m, dp):
    """Artikeltext. Zuerst frisch von der Seite (nur Absaetze, ohne Navigation): full_text in
    news.json ist der Seitenanfang und besteht oft nur aus Menues ("heise+ entdecken Suchen Abo")."""
    for url in (m.get("link_verlag"), m.get("link")):
        if not url or "news.google.com" in url:
            continue
        try:
            seite = dp._get(url)
        except Exception:
            seite = ""
        t = _absaetze(seite) if seite else ""
        if len(t) < dp.MIN_QUELLTEXT and seite:
            t = dp.text_aus_html(seite)
        if len(t) >= dp.MIN_QUELLTEXT:
            return t
        break
    ft = m.get("full_text")
    return ft if isinstance(ft, str) and len(ft) >= dp.MIN_QUELLTEXT else ""


def material(k, dp):
    """Nummerierte Quellen: je Medium die Meldung mit dem laengsten Text, dazu die Herstellerseite."""
    quellen, gesehen = [], set()
    for g in sorted(k["glieder"], key=lambda x: -len(x.get("full_text") or "")):
        medium = (g.get("source") or "").strip()
        if not medium or medium.lower() in gesehen:
            continue
        gesehen.add(medium.lower())
        text = _quelltext(g, dp)
        quellen.append({"medium": medium, "titel": _sauber(g.get("title")), "link": g.get("link_verlag") or g.get("link"),
                        "text": _sauber(" ".join(x for x in (g.get("summary"), text) if x))[:TEXT_JE_QUELLE],
                        "hat_text": len(text) >= dp.MIN_QUELLTEXT, "hersteller": False})
    r = k["release"]
    if r and r.get("url"):
        text = _quelltext({"link": r["url"]}, dp)
        quellen.append({"medium": f"{r.get('hersteller') or 'Hersteller'} (offizielle Seite)",
                        "titel": _sauber(r.get("titel_en") or r.get("titel")), "link": r["url"],
                        "text": _sauber(" ".join(x for x in (r.get("text_en") or r.get("text"), text) if x))[:TEXT_JE_QUELLE],
                        "hat_text": len(text) >= dp.MIN_QUELLTEXT, "hersteller": True})
    for i, q in enumerate(quellen, 1):
        q["nr"] = i
    return quellen


def karte_zur_story(k, base=BASE):
    """Karte nur, wenn ihr HAUPTlink zur Story gehoert und sie nicht aelter als die Story ist.
    Ueber Zusatz-Links haengen alte Karten an neuen Storys (29.10.: Chrome-Karte vom 25.10. am
    Gemini-4-Carbon-Link), darum nicht ms._karten_nach_link."""
    roh = _lade(base / "cards.json", [])
    karten = roh if isinstance(roh, list) else roh.get("cards", [])
    ab = min((g.get("first_seen") or g.get("date") or "9999")[:10] for g in k["glieder"])
    for c in karten:
        links = c.get("links") or []
        links = [links] if isinstance(links, str) else links
        if links and links[0] in k["links"] and (c.get("date") or "")[:10] >= ab:
            return c
    return None


# ── Schreiben ────────────────────────────────────────────────────────────────

def prompt(quellen):
    teile = []
    for q in quellen:
        art = "Offizielle Herstellerseite" if q["hersteller"] else "Medienbericht"
        teile.append(f"[{q['nr']}] {q['medium']} ({art})\nTitel: {q['titel']}\nText: {q['text']}")
    return (
        "Du schreibst für ki-news.live einen deutschen Hintergrundartikel zu einer KI-Meldung. "
        "Grundlage sind AUSSCHLIESSLICH die nummerierten Quellen unten.\n\n"
        "Regeln:\n"
        "- Nur Fakten, die in mindestens einer Quelle stehen. Kein Vorwissen, keine Vermutung. Keine Zahl, "
        "kein Datum, kein Name, keine Rolle, die nicht in den Quellen steht.\n"
        "- Zahlen als Ziffern und genau wie in der Quelle, nicht umrechnen, nicht runden.\n"
        "- Jede Person beim ersten Auftauchen mit Rolle in Klammern, z. B. \"Sundar Pichai (Chef Google)\", "
        "aber nur mit einer Rolle, die in einer Quelle steht. Zusätze wie \"ehemalig\", \"früher\", "
        "\"bisherig\", \"designiert\" nur, wenn die Quelle sie nennt.\n"
        "- Angaben des Herstellers (Benchmarks, Versprechen) als seine Angaben kennzeichnen (\"laut Google\"), "
        "nicht als Tatsache.\n"
        "- Widersprechen sich Quellen (andere Zahl, anderes Datum), das offen benennen.\n"
        "- Erster Absatz: der wichtigste konkrete Fakt, mit Zahl, wenn eine da ist. Letzter Absatz: was offen "
        "bleibt oder was das konkret bedeutet, ohne Beruhigungsfloskel.\n"
        "- Ton: nüchtern, konkret, skeptisch gegenüber Hype. Satzlänge variieren, auch mal ein kurzer Satz.\n"
        "- Verboten: Gedankenstrich, Semikolon, Ausrufezeichen, \"wir\"/\"uns\", Hashtags, Emojis, die Wörter "
        "revolutionär, bahnbrechend, Game-Changer, disruptiv, Paradigmenwechsel, nahtlos, tiefgreifend, "
        "wegweisend, spannend, und Floskeln wie \"es bleibt abzuwarten\", \"in einer Welt\", \"nicht nur ... "
        "sondern auch\". \"könnte\", \"möglicherweise\", \"eventuell\" höchstens einmal im ganzen Text.\n"
        "- Jeder Absatz nennt die Nummern der Quellen, auf denen er beruht.\n\n"
        "Antworte NUR mit JSON, ohne Erklärung:\n"
        '{"titel": "ein Aussagesatz, höchstens 90 Zeichen, ohne Schlusspunkt", '
        '"anriss": "1 bis 2 Sätze, höchstens 260 Zeichen", '
        '"absaetze": [{"text": "250 bis 700 Zeichen", "quellen": [1, 2]}], '
        '"tags": ["höchstens 3 Schlagwörter"]}\n'
        "4 bis 6 Absätze.\n\nQuellen:\n\n" + "\n\n".join(teile)
    )


def _anfrage(p, modell, key, reasoning):
    nutzlast = {"model": modell, "max_tokens": 8000, "temperature": 0.3,
                "messages": [{"role": "user", "content": p}]}
    if reasoning:
        nutzlast["reasoning"] = reasoning
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(nutzlast).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://ki-news.live/", "X-Title": "KI News Recherche-Artikel"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def schreibe(p, modell, key):
    # 29.10.26, erster Live-Lauf: Sonnet und Gemini lieferten keinen auswertbaren Text (0 Zeichen
    # Titel). Wie bei Nemotron/gpt-oss in ki_news.py: denkende Modelle verbrauchen das Budget fuers
    # Denken. Darum Denken drosseln und mehr Budget; lehnt ein Endpunkt den Parameter ab (HTTP 400),
    # einmal ohne. Leere/kaputte Antworten werden mit Grund protokolliert statt still verworfen.
    try:
        roh = _anfrage(p, modell, key, {"effort": "low", "exclude": True})
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        print(f"[RECHERCHE] {modell}: HTTP 400 mit reasoning-Parameter, zweiter Versuch ohne")
        roh = _anfrage(p, modell, key, None)
    wahl = (roh.get("choices") or [{}])[0]
    antwort = (wahl.get("message") or {}).get("content") or ""
    if isinstance(antwort, list):          # manche Anbieter liefern Inhaltsbloecke
        antwort = "".join(b.get("text", "") for b in antwort if isinstance(b, dict))
    antwort = re.sub(r"^```(?:json)?\s*|\s*```$", "", antwort.strip())
    a = {}
    if "{" in antwort and "}" in antwort:
        try:
            a = json.loads(antwort[antwort.index("{"): antwort.rindex("}") + 1])
        except ValueError as e:
            print(f"[RECHERCHE] {modell}: JSON kaputt ({e}), Anfang: {antwort[:160]!r}")
    if not a:
        print(f"[RECHERCHE] {modell}: kein JSON. finish_reason={wahl.get('finish_reason')}, "
              f"{len(antwort)} Zeichen, usage={roh.get('usage')}, Anfang: {antwort[:160]!r}")
    absaetze = [{"text": _sauber(x.get("text")), "quellen": [int(q) for q in x.get("quellen") or []
                                                             if str(q).isdigit()]}
                for x in a.get("absaetze") or [] if isinstance(x, dict)]
    return {"titel": _sauber(a.get("titel")).rstrip("."), "anriss": _sauber(a.get("anriss")),
            "absaetze": absaetze, "tags": [_sauber(t) for t in (a.get("tags") or [])][:3]}


# ── Pruefen ──────────────────────────────────────────────────────────────────

def _volltext(a):
    return " ".join([a["titel"] + ".", a["anriss"]] + [x["text"] for x in a["absaetze"]])


def pruefe_text(a, quellen, dp, entities):
    """Harte Code-Pruefungen. Liefert die Liste der Verstoesse (leer = bestanden)."""
    fehler = []
    voll = _volltext(a)
    mat = " ".join(f"{q['medium']} {q['titel']} {q['text']}" for q in quellen)
    mat_l = mat.lower()

    if not a["titel"] or len(a["titel"]) > 100:
        fehler.append(f"Titel fehlt oder zu lang ({len(a['titel'])} Zeichen)")
    if not a["anriss"] or len(a["anriss"]) > 300:
        fehler.append(f"Anriss fehlt oder zu lang ({len(a['anriss'])} Zeichen)")
    if not 4 <= len(a["absaetze"]) <= 6:
        fehler.append(f"{len(a['absaetze'])} Absätze statt 4 bis 6")
    gueltig = {q["nr"] for q in quellen}
    for i, x in enumerate(a["absaetze"], 1):
        if not 120 <= len(x["text"]) <= 900:
            fehler.append(f"Absatz {i}: {len(x['text'])} Zeichen")
        if not x["quellen"] or not set(x["quellen"]) <= gueltig:
            fehler.append(f"Absatz {i}: Quellenangabe fehlt oder ungültig ({x['quellen']})")

    for zeichen, name in (("—", "Gedankenstrich"), ("–", "Halbgeviertstrich"), (";", "Semikolon"),
                          ("!", "Ausrufezeichen"), ("#", "Hashtag")):
        if zeichen in voll:
            fehler.append(f"{name} im Text")
    vl = voll.lower()
    fehler += [f'Verbotswort "{w}"' for w in VERBOTEN if w in vl]
    if len(re.findall(WEICHMACHER, vl)) > 1:
        fehler.append("mehr als ein Weichmacher")
    if re.search(WIR, vl):
        fehler.append("Wir-Perspektive")

    # Zahlen, Daten, Rollen, Personen: dieselbe Pruefung wie fuer die Einordnungen
    for t in dp.pruefe({"title": a["titel"], "summary": " ".join([a["anriss"]] + [x["text"] for x in a["absaetze"]])}, mat):
        fehler.append(f"{t['art']}: {t['befund']}")
    # Produkt-/Firmennamen mit Ziffer oder Binnen-Grossbuchstabe (GPT-6, DeepMind, H100). Deutsche
    # Kompositum-Endungen ("GPT-6-Modell", "H100-Chips") werden abgeschnitten, Bindestrich = Leerzeichen.
    mat_n = re.sub(r"[-\s]+", " ", mat_l)
    for tok in sorted(set(re.findall(r"[A-Za-zÄÖÜäöü0-9]+(?:[-.][A-Za-zÄÖÜäöü0-9]+)*", voll))):
        teile = tok.split("-")
        while len(teile) > 1 and re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]{2,}", teile[-1]):
            teile.pop()
        tok = "-".join(teile).rstrip(".")
        if not re.search(r"[A-Za-z]", tok) or not (re.search(r"\d", tok) or re.search(r"[a-z][A-Z]", tok)):
            continue
        if re.sub(r"[-\s]+", " ", tok.lower()) not in mat_n:
            fehler.append(f'Name "{tok}" nicht in den Quellen')
    # Personen mit Kontext-Label: "Vorname Nachname (Rolle)"
    for name in re.findall(r"\b([A-ZÄÖÜ][\w'-]+(?:\s+[A-ZÄÖÜ][\w'-]+){1,2})\s+\(", voll):
        if name.split()[-1].lower() not in mat_l:
            fehler.append(f'Person "{name}" nicht in den Quellen')
    for e in entities:
        muster = [re.compile(r"(?i)\b" + al + r"\b") for al in e.get("aliasse") or []]
        if any(m.search(voll) for m in muster) and not any(m.search(mat) for m in muster):
            fehler.append(f'Entität "{e.get("id")}" nicht in den Quellen')
    return fehler


def _jev(text, quellen_text, key):
    body = json.dumps({"model": "jev-latest", "state": {"text": text[:4000], "quellen": quellen_text[:12000]},
                       "questions": {"gedeckt": _FRAGE_GEDECKT}}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.loads(r.read())["answers"]["gedeckt"]["noul"])


def pruefe_jev(a, quellen, key):
    """Jev je Absatz gegen die genannten Quellen, Titel+Anriss gegen alle. Liefert (fehler, werte)."""
    if not key:
        return ["Jev: kein TYPESAFE_API_KEY"], []
    nach_nr = {q["nr"]: q for q in quellen}

    def qtext(nrs, je):
        return "\n\n".join(f"[{n}] {nach_nr[n]['medium']}: {nach_nr[n]['titel']}. {nach_nr[n]['text'][:je]}"
                           for n in nrs if n in nach_nr)

    teile = [("Titel und Anriss", f"{a['titel']}. {a['anriss']}", qtext(list(nach_nr), 2000))]
    teile += [(f"Absatz {i}", x["text"], qtext(x["quellen"], TEXT_JE_QUELLE))
              for i, x in enumerate(a["absaetze"], 1)]
    fehler, werte = [], []
    for name, text, qt in teile:
        try:
            p = _jev(text, qt, key)
        except Exception as e:
            return fehler + [f"Jev nicht erreichbar ({type(e).__name__})"], werte
        werte.append(round(p, 2))
        if p < JEV_SCHWELLE:
            fehler.append(f"Jev: {name} nicht gedeckt (p={p:.2f})")
    return fehler, werte


# ── Seite ────────────────────────────────────────────────────────────────────

_CSS_EXTRA = """
.kicker{font-size:.8125rem;color:var(--akzent);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
sup a{text-decoration:none;font-size:.75em;margin-left:1px}
ol.quellen{padding-left:1.25rem;font-size:.9375rem}
ol.quellen li{margin:.35rem 0}
.offiziell{border:1px solid var(--linie);border-radius:4px;padding:.9rem 1rem;margin:1.5rem 0}
.offiziell h2{margin-top:0}
.pruefung{background:var(--grund);border:1px solid var(--linie);border-radius:4px;padding:.75rem 1rem;font-size:.875rem}
.entwurf{border:2px solid #b45309;border-radius:4px;padding:.75rem 1rem;margin-bottom:1.25rem;font-size:.9375rem}
.yt{margin:0 0 1rem}
""".strip()


def _youtube_id(u):
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})", u or "")
    return m.group(1) if m else ""


def rendere(a, k, quellen, karte, slug, stand, entwurf, bericht):
    esc = html.escape
    rep, r = k["rep"], k["release"]
    pfad = f"/recherche/{slug}.html"
    url = SITE + pfad
    bild = rep.get("image_local_gross") or rep.get("image_local") or (r or {}).get("poster") or ""
    robots = "noindex, nofollow" if entwurf else "index, follow, max-image-preview:large"
    n_medien = sum(1 for q in quellen if not q["hersteller"])
    datum = stand[:10]
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": a["titel"][:110],
          "description": a["anriss"][:200], "inLanguage": "de", "datePublished": stand, "dateModified": stand,
          "mainEntityOfPage": url, "isBasedOn": [q["link"] for q in quellen if q.get("link")],
          "author": {"@type": "Organization", "name": "KI News", "url": SITE + "/"},
          "publisher": {"@type": "Organization", "name": "KI News", "url": SITE + "/",
                        "logo": {"@type": "ImageObject", "url": SITE + "/s-logo.png"}}}
    if bild:
        ld["image"] = [bild]
    ld_txt = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    teile = [
        "<!DOCTYPE html>", '<html lang="de">', "<head>", '<meta charset="utf-8"/>',
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
        f"<title>{esc(a['titel'])} · KI News</title>",
        f'<meta name="description" content="{esc(a["anriss"][:200])}"/>',
        f'<meta name="robots" content="{robots}"/>',
    ]
    if not entwurf:
        teile.append(f'<link rel="canonical" href="{url}"/>')
    teile += [
        '<link rel="icon" type="image/png" href="/s-logo.png"/>',
        '<meta property="og:type" content="article"/>',
        f'<meta property="og:title" content="{esc(a["titel"])}"/>',
        f'<meta property="og:description" content="{esc(a["anriss"][:200])}"/>',
        f'<meta property="og:url" content="{url}"/>', '<meta property="og:locale" content="de_DE"/>',
    ]
    if bild:
        teile += [f'<meta property="og:image" content="{esc(bild)}"/>',
                  '<meta name="twitter:card" content="summary_large_image"/>']
    teile += [
        '<meta name="twitter:site" content="@ScampyKI"/>',
        '<link rel="stylesheet" href="/assets/ki-fonts.css"/>',
        f"<script>{ms._THEME_JS}</script>",
        f"<style>{ms._CSS}\n{_CSS_EXTRA}</style>",
        f'<script type="application/ld+json">{ld_txt}</script>',
        "</head>", "<body>",
        '<header class="kopf"><a class="marke" href="/">KI News</a>'
        '<nav class="nav"><a href="/">Startseite</a><a href="/dossiers.html">Dossiers</a>'
        '<a class="weg" href="/Archiv.html">Archiv</a></nav></header>',
        "<main>", "<article>",
    ]
    if entwurf:
        teile.append('<div class="entwurf"><strong>Entwurf, nicht veröffentlicht.</strong> Die automatische '
                     'Prüfung hat diesen Text angehalten:<ul>' +
                     "".join(f"<li>{esc(b)}</li>" for b in bericht) + "</ul></div>")
    teile += [
        f'<p class="kicker">Recherche · {n_medien} Quellen' + (" + Herstellerseite" if r else "") + "</p>",
        f'<p class="meta"><time datetime="{datum}">{ms._datum_de(datum)}</time></p>',
        f"<h1>{esc(a['titel'])}</h1>",
        f'<p class="anriss">{esc(a["anriss"])}</p>',
    ]
    video = (karte or {}).get("mp4_url") or ""
    if video:
        p = (karte or {}).get("poster_url") or ""
        pp = f' poster="{esc(p)}"' if p else ""
        teile.append(f'<figure><video controls playsinline preload="none"{pp}>'
                     f'<source src="{esc(video)}" type="video/mp4"/></video></figure>')
    elif bild:
        teile.append(f'<figure><img src="{esc(bild)}" alt="" loading="lazy"/></figure>')
    for x in a["absaetze"]:
        belege = "".join(f'<sup><a href="#q{n}">[{n}]</a></sup>' for n in x["quellen"])
        teile.append(f"<p>{esc(x['text'])}{belege}</p>")

    if r and r.get("url"):
        teile.append('<section class="offiziell">')
        teile.append(f"<h2>Offiziell von {esc(r.get('hersteller') or 'Hersteller')}</h2>")
        yt = _youtube_id(r.get("video_url"))
        if yt:
            teile.append(f'<div class="yt" data-yt="{esc(yt)}"></div>')
        elif (r.get("video_url") or "").startswith("https://"):
            pp = f' poster="{esc(r["poster"])}"' if (r.get("poster") or "").startswith("https://") else ""
            teile.append(f'<figure><video controls playsinline preload="none"{pp}>'
                         f'<source src="{esc(r["video_url"])}"/></video></figure>')
        teile.append(f'<p><a href="{esc(r["url"])}" rel="noopener" target="_blank">'
                     f'{esc(r.get("titel") or r.get("titel_en") or r["url"])}</a></p>')
        if (r.get("x_url") or "").startswith("https://x.com/"):
            teile.append(f'<blockquote class="twitter-tweet"><a href="{esc(r["x_url"])}">'
                         f'Beitrag von {esc(r.get("hersteller") or "")} auf X</a></blockquote>')
        teile.append("</section>")

    teile.append("<h2>Quellen</h2>")
    teile.append('<ol class="quellen">' + "".join(
        f'<li id="q{q["nr"]}">{esc(q["medium"])}: <a href="{esc(q["link"] or "")}" rel="noopener" '
        f'target="_blank">{esc(q["titel"])}</a></li>' for q in quellen) + "</ol>")
    if rep.get("seite"):
        teile.append(f'<p class="quelle">Zur Kurzmeldung: <a href="{esc(rep["seite"])}">{esc(ms._titel(rep))}</a></p>')
    teile.append("</article>")
    teile.append(
        '<p class="pruefung">So entsteht dieser Text: Ein Sprachmodell hat die oben verlinkten Quellen '
        'zusammengefasst. Vor der Veröffentlichung wurde automatisch geprüft, dass jede Zahl, jedes Datum '
        'und jeder Name in mindestens einer Quelle steht und dass jeder Absatz durch die genannten Quellen '
        'gedeckt ist. Fehler sind trotzdem möglich, maßgeblich sind die Originalquellen.</p>')
    teile += [
        "</main>",
        '<footer class="fuss"><a href="/">ki-news.live</a><a href="/Impressum.html">Impressum</a>'
        '<a href="/Datenschutz.html">Datenschutz</a></footer>',
        '<script src="/assets/ki-embed.js"></script>',
        "<script>(function(){if(!window.KIEmbed)return;document.querySelectorAll('[data-yt]').forEach("
        "function(el){el.innerHTML=KIEmbed.youtube(el.getAttribute('data-yt'),{label:'VIDEO'});});})();</script>",
        "</body>", "</html>", "",
    ]
    return "\n".join(teile)


def sitemap(register):
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for e in sorted(register.values(), key=lambda x: x["pfad"]):
        if e.get("status") == "veroeffentlicht":
            zeilen.append(f"  <url><loc>{SITE}{e['pfad']}</loc><lastmod>{e['datum']}</lastmod></url>")
    zeilen += ["</urlset>", ""]
    ms._schreiben_wenn_neu(ORDNER / "sitemap.xml", "\n".join(zeilen))


# ── Ablauf ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", help="nur diese story_id (Test)")
    ap.add_argument("--nur-entwurf", action="store_true", help="auch bestandene Texte nur als Entwurf")
    ap.add_argument("--dry-run", action="store_true", help="nichts schreiben, nur berichten")
    args = ap.parse_args()
    if not RECHERCHE_AKTIV:
        print("[RECHERCHE] aus (RECHERCHE_AKTIV = False)")
        return 0
    key = os.environ.get("OPENROUTER_KEY", "").strip()
    jev_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        print("[RECHERCHE] kein OPENROUTER_KEY, nichts zu tun")
        return 0

    news = _lade(BASE / "news.json", {}).get("news") or []
    releases = _lade(BASE / "hersteller.json", {}).get("releases") or []
    entities = _lade(BASE / "entities.json", {}).get("entities") or []
    register = _lade(REGISTER, {})
    jetzt = datetime.now(timezone.utc).replace(microsecond=0)
    heute = jetzt.astimezone(BERLIN).strftime("%Y-%m-%d")
    frei = MAX_PRO_TAG - sum(1 for e in register.values() if e.get("datum") == heute)
    if frei <= 0 and not args.story:
        print(f"[RECHERCHE] Tageslimit {MAX_PRO_TAG} erreicht")
        return 0

    dp = _deckung()
    kand = kandidaten(news, releases, register, args.story)
    print(f"[RECHERCHE] {len(kand)} Kandidaten (>= {MIN_QUELLEN} Medien oder Herstellerseite + "
          f"{MIN_QUELLEN_MIT_HERSTELLER}), frei heute: {frei}")
    versucht = 0
    for k in kand:
        if versucht >= (1 if args.story else min(MAX_PRO_LAUF, frei)):
            break
        quellen = material(k, dp)
        mit_text = sum(1 for q in quellen if q["hat_text"])
        if mit_text < MIN_TEXTQUELLEN:
            print(f"[RECHERCHE] {k['sid']} uebersprungen: nur {mit_text} Quellen mit Text "
                  f"({ms._titel(k['rep'])[:60]})")
            continue
        versucht += 1
        p = prompt(quellen)
        artikel, fehler, modell, jev_werte = None, ["kein Modell lieferte Text"], "", []
        for modell in MODELLE[:MAX_SCHREIBVERSUCHE]:
            try:
                artikel = schreibe(p, modell, key)
            except Exception as e:
                print(f"[RECHERCHE] {modell}: {type(e).__name__} {getattr(e, 'code', '')}")
                artikel, fehler = None, [f"{modell}: {type(e).__name__}"]
                continue
            fehler = pruefe_text(artikel, quellen, dp, entities)
            print(f"[RECHERCHE] {modell}: {len(fehler)} Verstoesse {fehler[:4]}")
            if not fehler:
                break
        if artikel and not fehler:
            fehler, jev_werte = pruefe_jev(artikel, quellen, jev_key)
            print(f"[RECHERCHE] Jev {jev_werte} -> {'bestanden' if not fehler else fehler}")
        if not artikel or not artikel["titel"]:
            print(f"[RECHERCHE] {k['sid']}: kein verwertbarer Text, {fehler}")
            continue

        bestanden = not fehler and not args.nur_entwurf
        slug = ms._slug(artikel["titel"])
        while slug in register:
            slug += "-2"
        karte = karte_zur_story(k)
        stand = jetzt.isoformat()
        seite = rendere(artikel, k, quellen, karte, slug, stand, not bestanden,
                        fehler or ["Testlauf mit --nur-entwurf"])
        ziel = (ORDNER / f"{slug}.html") if bestanden else (ENTWURF_DIR / f"recherche-{slug}.html")
        eintrag = {"pfad": f"/recherche/{slug}.html" if bestanden else f"/artikel/entwurf/recherche-{slug}.html",
                   "titel": artikel["titel"], "anriss": artikel["anriss"], "datum": heute,
                   "status": "veroeffentlicht" if bestanden else "entwurf", "story_id": k["sid"],
                   "quellen": len(quellen), "modell": modell, "jev": jev_werte, "gruende": fehler,
                   "links": k["links"]}
        print(f"[RECHERCHE] {eintrag['status']}: {eintrag['pfad']} ({len(quellen)} Quellen)")
        if args.dry_run:
            print(json.dumps(artikel, ensure_ascii=False, indent=1))
            continue
        ms._schreiben_wenn_neu(ziel, seite)
        register[slug] = eintrag

    if not args.dry_run and versucht:
        ORDNER.mkdir(exist_ok=True)
        ms._schreiben_wenn_neu(REGISTER, json.dumps(register, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        sitemap(register)
    return 0


if __name__ == "__main__":
    sys.exit(main())
