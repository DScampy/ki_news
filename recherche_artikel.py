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
  4. Pruefer-Modell (PRUEFER_MODELLE, seit 30.10.): je Absatz gegen die Fundstellen seiner Quellen,
     Antwort = Liste nicht gedeckter Aussagen, leer = bestanden. Alle Modelle ausgefallen = nicht
     bestanden. Jev (TypeSafe) laeuft nur noch im Schatten mit (Werte im Register, kein Einfluss).

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
import urllib.error
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
JEV_MAX_AUFRUFE = 60             # Saetze je Artikel (Titel/Anriss + 4-6 Absaetze, real ~25-30)
JEV_MAX_QUELLTEXT = 24000        # 7 Quellen a TEXT_JE_QUELLE + Kopfzeilen, nichts kappen
# Bumpen, wenn sich die Jev-Pruefung aendert: Entwuerfe, die NUR an Jev gescheitert sind und
# mit einer aelteren Fassung geprueft wurden, bekommen einmal einen neuen Versuch.
PRUEFUNG_VERSION = 4              # 3: Fundstelle (29.10.), 4: Pruefer-Modell statt Jev (30.10.)
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

_FRAGE_SATZ = {
    "type": "noul",
    "instructions": "Ist jede Tatsachenbehauptung im Satz `satz` (Zahlen, Namen, Rollen, Daten, Ereignisse, "
                    "Zuschreibungen) durch `quellen` gedeckt? `kontext` ist der umgebende Absatz und dient "
                    "nur dem Verständnis (worauf sich \"er\", \"dagegen\" usw. beziehen), geprüft wird nur "
                    "`satz`. Übersetzung ins Deutsche und eigene Formulierung sind erlaubt. Ein Satz, der "
                    "nur einordnet, was die Quellen sagen oder nicht sagen (z. B. ein benannter Widerspruch), "
                    "ist gedeckt, wenn die Quellen das so hergeben.",
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
    # Entwuerfe, die nur an einer aelteren Jev-Pruefung scheiterten, zaehlen nicht als erledigt
    erledigt = {l for e in register.values() for l in e.get("links", [])
                if not (e.get("status") == "entwurf" and e.get("pruefung", 1) < PRUEFUNG_VERSION
                        and e.get("gruende") and all(g.startswith("Jev") for g in e["gruende"]))}
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
        "Antworte NUR mit gültigem JSON, ohne Erklärung. Anführungszeichen im Text nur als „ “, "
        "nie als gerades Anführungszeichen:\n"
        '{"titel": "ein Aussagesatz, höchstens 90 Zeichen, ohne Schlusspunkt", '
        '"anriss": "1 bis 2 Sätze, höchstens 260 Zeichen", '
        '"absaetze": [{"text": "250 bis 700 Zeichen", "quellen": [1, 2]}], '
        '"tags": ["höchstens 3 Schlagwörter"]}\n'
        "4 bis 6 Absätze.\n\nQuellen:\n\n" + "\n\n".join(teile)
    )


def _anfrage(p, modell, key, reasoning, system="", temperature=0.3):
    nachrichten = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": p}]
    nutzlast = {"model": modell, "max_tokens": 8000, "temperature": temperature,
                "messages": nachrichten, "usage": {"include": True}}
    if reasoning:
        nutzlast["reasoning"] = reasoning
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(nutzlast).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://ki-news.live/", "X-Title": "KI News Recherche-Artikel"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def _fehlertext(e):
    """Haengt die Begruendung aus der Fehlerantwort an (e.text). 29.10. 16 UTC: Sonnet und Gemini
    lieferten beide HTTP 429, im Log stand nur der Code - nicht, ob Rate-Limit, Schluessel-Limit
    oder Anbieter. OpenRouter schickt {"error": {"message": ..., "metadata": ...}}, keine Geheimnisse."""
    try:
        roh = e.read().decode("utf-8", "replace")
        try:
            f = json.loads(roh).get("error") or {}
            text = " ".join(str(x) for x in (f.get("message"), f.get("metadata")) if x) or roh
        except ValueError:
            text = roh
    except Exception:
        text = ""
    e.text = _sauber(text)[:300]
    return e.text


def schreibe(p, modell, key):
    # 29.10.26, erster Live-Lauf: Sonnet und Gemini lieferten keinen auswertbaren Text (0 Zeichen
    # Titel). Wie bei Nemotron/gpt-oss in ki_news.py: denkende Modelle verbrauchen das Budget fuers
    # Denken. Darum Denken drosseln und mehr Budget; lehnt ein Endpunkt den Parameter ab (HTTP 400),
    # einmal ohne. Leere/kaputte Antworten werden mit Grund protokolliert statt still verworfen.
    try:
        roh = _anfrage(p, modell, key, {"effort": "low", "exclude": True})
    except urllib.error.HTTPError as e:
        _fehlertext(e)
        if e.code != 400:
            raise
        print(f"[RECHERCHE] {modell}: HTTP 400 mit reasoning-Parameter ({e.text}), zweiter Versuch ohne")
        try:
            roh = _anfrage(p, modell, key, None)
        except urllib.error.HTTPError as e2:
            _fehlertext(e2)
            raise
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


def _jev(text, kontext, quellen_text, key):
    body = json.dumps({"model": "jev-latest",
                       "state": {"satz": text[:1500], "kontext": kontext[:2500], "quellen": quellen_text[:JEV_MAX_QUELLTEXT]},
                       "questions": {"gedeckt": _FRAGE_SATZ}}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.loads(r.read())["answers"]["gedeckt"]["noul"])


def _saetze(text):
    """Saetze; Kurzstuecke (z. B. nach "z. B.") haengen am vorigen Satz. Kein Schnitt nach
    Ziffer+Punkt: "bis zum 4. November 2026" wurde am 29.10. in zwei Saetze zerlegt."""
    out = []
    for s in re.split(r"(?<=[^\d\s][.!?])\s+(?=[A-ZÄÖÜ0-9„])", text.strip()):
        if out and len(s) < 25:
            out[-1] += " " + s
        elif s:
            out.append(s)
    return out


_STOPP = set("aber alle auch beim bereits damit dann dass dabei denn deren diese dieser dieses doch eine einem "
             "einen einer eines etwa gegen hatte haben jedoch kann laut mehr nach noch nicht nur oder rund sein "
             "seine seit sich sind soll sowie über unter viel vom von vor wird wurde zwei drei weil wenn wie "
             "zum zur zwischen dort hier dies diesem erst".split())


def _anker(satz, dp):
    """Was ein Beleg enthalten muss: Zahlen (mit Schreibvarianten), Namen, Inhaltswoerter."""
    zahlen = [dp._zahl_varianten(z) for z in dp._zahlen(satz)]
    namen = {w.lower() for w in re.findall(r"\b[A-Za-z][\w-]*(?:\d|[a-z][A-Z])[\w.-]*", satz)}
    # gross geschriebene Woerter ausser dem Satzanfang (Firmen, Produkte, Personen, Benchmarks)
    namen |= {w.lower() for w in re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]+\b", satz.split(" ", 1)[-1])
              if len(w) > 3 and w.lower() not in _STOPP}
    # Wortstamm (6 Zeichen): "Verfuegbarkeit" soll "verfuegbar" finden (30.10.: Heise-Satz "bald" verpasst)
    woerter = {w[:6] for w in re.findall(r"[a-zäöüß]{5,}", satz.lower()) if w not in _STOPP}
    return zahlen, namen, woerter


def fundstelle(satz, quellen_liste, dp, vorher="", fenster=700, schritt=250, anzahl=3):
    """Die Ausschnitte der genannten Quellen, die am meisten Zahlen/Namen/Woerter des Satzes
    enthalten (29.10.26, Daniels Entscheidung A). Jev fand wortgleiche Belege in 6.000 Zeichen
    Quelltext nicht zuverlaessig (Mistral: "62 Punkten" stand fast woertlich bei The Decoder,
    p=0,73). Mit dem passenden Ausschnitt muss es nur noch vergleichen, nicht suchen.
    vorher: der Satz davor, schwach gewichtet ("Das Modell liegt ... vorn" meint das Modell von
    eben). Liefert "" wenn kein Ausschnitt genug Treffer hat."""
    zahlen, namen, woerter = _anker(satz, dp)
    v_zahlen, v_namen, _ = _anker(vorher, dp) if vorher else ([], set(), set())
    kandidaten = []
    for q in quellen_liste:
        t = q["text"]
        for start in range(0, max(1, len(t) - fenster // 2), schritt):
            stueck = t[start:start + fenster]
            sl = stueck.lower()
            punkte = (3 * sum(any(v in stueck for v in vs) for vs in zahlen)
                      + 2 * sum(n in sl for n in namen) + sum(w in sl for w in woerter)
                      + sum(any(v in stueck for v in vs) for vs in v_zahlen) + sum(n in sl for n in v_namen - namen))
            kandidaten.append((punkte, q["nr"], start, stueck))
    kandidaten.sort(key=lambda x: -x[0])
    if not kandidaten or kandidaten[0][0] < 4:
        return ""
    gewaehlt = []
    for punkte, nr, start, stueck in kandidaten:
        if punkte < max(4, kandidaten[0][0] // 2):
            break
        if any(nr == g[0] and abs(start - g[1]) < fenster for g in gewaehlt):
            continue                      # keine fast gleichen Ausschnitte doppelt
        gewaehlt.append((nr, start, stueck))
        if len(gewaehlt) >= anzahl:
            break
    nach_nr = {q["nr"]: q for q in quellen_liste}
    return "\n\n".join(f"[{nr}] {nach_nr[nr]['medium']}: …{stueck}…" for nr, start, stueck in gewaehlt)


# ── Pruefer-Modell (30.10.26, Daniels Entscheidung 1) ──────────────────────────
# Jev gab satzweise auch dann 0,1-0,6, wenn der Beleg fast woertlich im kurzen Ausschnitt stand
# (Gemini 30.10.: Exploitgym 0,62, "tagelang" 0,11). Jetzt entscheidet ein Sprachmodell: ein Aufruf
# je Artikel, je Absatz die Fundstellen, Antwort = Liste der NICHT gedeckten Aussagen. Leer = raus.
# Kette nur fuer Ausfaelle (Fehler, leer, kaputtes/unvollstaendiges JSON). Ein echtes Urteil
# "nicht gedeckt" ist endgueltig, es wird nicht beim naechsten Modell nachgefragt.
# Nemotron Ultra free (Daniels Wunsch) traegt laut ki_news.log die Uebersetzung (107 OK, 0x 429 im
# Log-Fenster 30.10.), als Pruefer aber ungemessen. Backup gemini-3.8-flash: Sieger der Oberklasse im
# Richter-Vergleich 02.10. (KIVault ox-analyse/MESSUNG_021026_Richter-Stabilitaet.md: 39/38 von 41,
# 0 Fehlurteile, 3 s). Reihenfolge nach tools/pruefer_vergleich.py (Workflow "Pruefer-Vergleich").
PRUEFER_MODELLE = ["nvidia/nemotron-3-ultra-550b-a55b:free", "google/gemini-3.8-flash"]
PRUEFER_BELEG_JE_ABSATZ = 5000
_PRUEFER_SYSTEM = ("Du bist Faktenprüfer für eine deutsche Nachrichtenseite. Du prüfst Absätze ausschließlich gegen "
                   "die mitgelieferten Belegstellen (deutsch oder englisch). Kein Vorwissen benutzen.")


def _pruefer_reasoning(modell):
    # wie ki_news.py: Nemotron denkt sonst das Budget leer und liefert kaputtes JSON
    return {"enabled": False} if modell.startswith("nvidia/") else {"effort": "low", "exclude": True}


def pruefer_material(a, quellen, dp):
    """[(id, text, belege)] - P0 = Titel+Anriss (alle Quellen), P1.. = Absaetze (ihre Quellen)."""
    nach_nr = {q["nr"]: q for q in quellen}

    def belege(text, nrs):
        liste = [nach_nr[n] for n in nrs if n in nach_nr]
        stuecke = []
        saetze = _saetze(text)
        for satz, vorher in zip(saetze, [""] + saetze[:-1]):
            for teil in (fundstelle(satz, liste, dp, vorher) or fundstelle(text, liste, dp, anzahl=4)).split("\n\n"):
                if teil and teil not in stuecke:
                    stuecke.append(teil)
        return "\n".join(stuecke)[:PRUEFER_BELEG_JE_ABSATZ]

    kopf = f"{a['titel']}. {a['anriss']}"
    teile = [("P0", kopf, belege(kopf, list(nach_nr)))]
    teile += [(f"P{i}", x["text"], belege(x["text"], x["quellen"])) for i, x in enumerate(a["absaetze"], 1)]
    return teile


def pruefer_prompt(teile):
    return ("Prüfe jeden Absatz: Steht jede Tatsachenbehauptung (Zahl, Name, Rolle, Datum, Ereignis, Zuschreibung "
            "an eine Quelle wie \"laut Heise\") so oder sinngemäß in den Belegen DIESES Absatzes? Übersetzung und eigene "
            "Formulierung sind erlaubt. Einordnende Sätze (\"die Quellen widersprechen sich\") sind gedeckt, wenn die "
            "Belege das hergeben. Antworte NUR mit JSON: {\"<id>\": [\"zitierte nicht gedeckte Aussage: kurzer Grund\"], "
            "...}. Leere Liste, wenn alles gedeckt ist. Jede id muss vorkommen.\n\n"
            + "\n\n".join(f"### {i}\nAbsatz: {t}\nBelege:\n{b or '(keine Belegstelle gefunden)'}" for i, t, b in teile))


def pruefer_urteil(teile, modell, key):
    """{id: [nicht gedeckte Aussagen]} + Nutzungsdaten. ValueError, wenn die Antwort unbrauchbar ist."""
    p = pruefer_prompt(teile)
    try:
        roh = _anfrage(p, modell, key, _pruefer_reasoning(modell), _PRUEFER_SYSTEM, 0)
    except urllib.error.HTTPError as e:
        _fehlertext(e)
        if e.code != 400:
            raise
        roh = _anfrage(p, modell, key, None, _PRUEFER_SYSTEM, 0)
    wahl = (roh.get("choices") or [{}])[0]
    text = (wahl.get("message") or {}).get("content") or ""
    if isinstance(text, list):
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    try:
        urteil = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        raise ValueError(f"kein JSON (finish_reason={wahl.get('finish_reason')}, Anfang {text[:120]!r})")
    fehlt = [i for i, _, _ in teile if not isinstance(urteil.get(i), list)]
    if fehlt:
        raise ValueError(f"unvollständig, fehlt {fehlt}")
    return {i: [_sauber(x) for x in urteil[i] if _sauber(x)] for i, _, _ in teile}, roh.get("usage") or {}


def pruefe_llm(a, quellen, dp, key, modelle=None):
    """Liefert (fehler, info). Fehler leer = bestanden. Alle Modelle ausgefallen = nicht bestanden."""
    import time
    teile = pruefer_material(a, quellen, dp)
    info = {"ausfaelle": []}
    for modell in modelle or PRUEFER_MODELLE:
        start = time.time()
        try:
            urteil, usage = pruefer_urteil(teile, modell, key)
        except Exception as e:
            grund = f"{modell}: {type(e).__name__} {getattr(e, 'code', '')} {getattr(e, 'text', '') or e}"
            print(f"[RECHERCHE] Prüfer ausgefallen: {grund[:300]}")
            info["ausfaelle"].append(grund[:200])
            continue
        info.update(modell=modell, sekunden=round(time.time() - start, 1), kosten=usage.get("cost"))
        namen = {"P0": "Titel/Anriss"}
        fehler = [f"Prüfer: {namen.get(i, 'Absatz ' + i[1:])}: {x[:200]}" for i, liste in urteil.items() for x in liste]
        return fehler, info
    return ["Prüfer: kein Modell lieferte ein Urteil"], info


def pruefe_jev(a, quellen, key, dp=None):
    """Jev je SATZ gegen die vollstaendigen Quellen seines Absatzes (Titel+Anriss: alle Quellen).
    Liefert (fehler, werte).

    29.10.26, erster echter Artikel (Gemini 4 Carbon): Je Absatz lag Jev bei 0,14-0,73, obwohl
    jede geprueft Aussage in den Quellen stand. Zwei Gruende: Der Quelltext wurde bei 12.000
    Zeichen gekappt (Absatz 1 nannte 6 Quellen a 3.000, Heise mit "vier Wochen" fehlte), und ein
    dichter Absatz mit fuenf Zahlen aus drei Quellen bekommt bei der kleinsten Unsicherheit einen
    niedrigen Wert. Satzweise sieht Jev genau das Material, das auch das Schreibmodell hatte,
    und der Pruefbericht nennt den Satz, der nicht gedeckt ist. Schwelle bleibt JEV_SCHWELLE.
    Ab PRUEFUNG_VERSION 3 (Daniels Entscheidung A): statt ganzer Quellen nur die Fundstelle
    (siehe fundstelle()); satzweise mit ganzen Quellen fand Jev woertliche Belege nicht."""
    if not key:
        return ["Jev: kein TYPESAFE_API_KEY"], []
    nach_nr = {q["nr"]: q for q in quellen}

    def qtext(nrs):
        return "\n\n".join(f"[{n}] {nach_nr[n]['medium']}: {nach_nr[n]['titel']}. {nach_nr[n]['text']}"
                           for n in nrs if n in nach_nr)

    def belege(satz, vorher, absatz, nrs):
        """Fundstelle des Satzes; ohne eigene Zahlen/Namen (reine Einordnung wie "Hier
        widersprechen sich die Quellen") die Fundstellen des ganzen Absatzes; sonst alles."""
        if dp is not None:
            liste = [nach_nr[n] for n in nrs if n in nach_nr]
            fs = fundstelle(satz, liste, dp, vorher) or fundstelle(absatz, liste, dp, anzahl=4)
            if fs:
                return fs
        return qtext(nrs)

    def zerlegt(text):
        s = _saetze(text)
        return zip(s, [""] + s[:-1])

    kopf = f"{a['titel']}. {a['anriss']}"
    teile = [("Titel/Anriss", s, kopf, belege(s, v, kopf, list(nach_nr))) for s, v in zerlegt(kopf)]
    for i, x in enumerate(a["absaetze"], 1):
        teile += [(f"Absatz {i}", s, x["text"], belege(s, v, x["text"], x["quellen"]))
                  for s, v in zerlegt(x["text"])]
    if len(teile) > JEV_MAX_AUFRUFE:
        return [f"Jev: {len(teile)} Sätze, mehr als {JEV_MAX_AUFRUFE} Prüfungen"], []
    fehler, werte = [], []
    for name, satz, kontext, qt in teile:
        try:
            p = _jev(satz, kontext, qt, key)
        except Exception as e:
            return fehler + [f"Jev nicht erreichbar ({type(e).__name__})"], werte
        werte.append(round(p, 2))
        if p < JEV_SCHWELLE:
            fehler.append(f'Jev: {name} nicht gedeckt (p={p:.2f}): "{satz[:140]}"')
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
        artikel, fehler, modell, jev_werte, pinfo = None, ["kein Modell lieferte Text"], "", [], {}
        for modell in MODELLE[:MAX_SCHREIBVERSUCHE]:
            try:
                artikel = schreibe(p, modell, key)
            except Exception as e:
                print(f"[RECHERCHE] {modell}: {type(e).__name__} {getattr(e, 'code', '')} {getattr(e, 'text', '')}".rstrip())
                artikel, fehler = None, [f"{modell}: {type(e).__name__}"]
                continue
            fehler = pruefe_text(artikel, quellen, dp, entities)
            print(f"[RECHERCHE] {modell}: {len(fehler)} Verstoesse {fehler[:4]}")
            if not fehler:
                break
        if artikel and not fehler:
            fehler, pinfo = pruefe_llm(artikel, quellen, dp, key)
            print(f"[RECHERCHE] Prüfer {pinfo.get('modell')} ({pinfo.get('sekunden')} s, {pinfo.get('kosten')} $) -> "
                  f"{'bestanden' if not fehler else fehler}")
            if jev_key:                   # Jev nur noch zum Vergleich, entscheidet nicht (30.10.)
                jev_fehler, jev_werte = pruefe_jev(artikel, quellen, jev_key, dp)
                print(f"[RECHERCHE] Jev (Schatten) {jev_werte}: {len(jev_fehler)} Saetze unter {JEV_SCHWELLE}")
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
                   "quellen": len(quellen), "modell": modell, "jev": jev_werte, "pruefer": pinfo, "gruende": fehler,
                   "links": k["links"], "pruefung": PRUEFUNG_VERSION,
                   "artikel": artikel}
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
