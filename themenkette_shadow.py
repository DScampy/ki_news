# -*- coding: utf-8 -*-
"""
Themenkette SHADOW-MODE (14.09.2026)
====================================

Ordnet unsere Artikel den Entwicklungslinien ("Ketten") von HuggingNews zu und
schreibt das Ergebnis NUR in themenketten.json. Veraendert nichts an news.json,
Scores, Karten oder Telegram. Kill-Switch: Hook in ki_news.py entfernen oder
Secret HUGGINGNEWS_API loeschen (ohne Key wird der Schritt still uebersprungen).

Plan und Messung: KIVault/02 Projekte/Wissen aufbauen/ox-analyse/
  PLAN_140926_Themenkette.md, MESSUNG_140926_HuggingNews-Abgleich.md

Ablauf je Lauf
  1. HN-Feed (3 ET-Tage) + Detail je Story; /chain nur fuer Storys, deren Kette
     noch unbekannt ist. Ketten-ID = Slug des aeltesten Glieds.
  2. Stufe A (Ereignis): 5 naechste Artikel je HN-Story (Embedding >= 0,38),
     Richter "dasselbe konkrete Ereignis?", seit 16.09. als Zwei-Modell-Votum -
     ein einzelner Richter verwechselte in den dichten Debatten-Ketten drei
     benachbarte Ereignisse (Aehnlichkeit 0,71 bis 0,86).
  3. Stufe B (Thema, Daniels Regel): Artikel ohne Ereignis-Treffer, aber nah am
     Schwerpunkt einer Kette mit mind. 2 zugeordneten Artikeln, kommen nur nach
     eigener Pruefung rein ("behandelt DIESE Debatte direkt?"). rolle = "thema".
     16.09.26 nachgeschaerft (Handpruefung: 19 % Fehlgriffe): Schwelle 0,62,
     Entitaeten-Gate, geschaerfter Prompt, Zwei-Modell-Votum.
  4. themenketten.json schreiben. Urteile sind je (Story/Kette, Link) gecacht,
     jeder Lauf fragt nur neue Paare.

Invarianten: ein Schreiber (diese Datei), nie blockieren (jeder Fehler -> Log,
Pipeline laeuft weiter), harte Zeitgrenze ZEIT_BUDGET_S. HN-Texte werden nicht
gespeichert (robots.txt use=reference) - nur Slugs, Zeiten, Zuordnungen.
"""

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("ki_news")

NL = chr(10)

DATEI = "themenketten.json"
HN_API = "https://api.huggingnews.com/api/stories"
MODELL = "paraphrase-multilingual-MiniLM-L12-v2"
RICHTER = ["openai/gpt-oss-120b", "google/gemini-2.5-flash-lite"]
MIN_SIM_EREIGNIS = 0.38      # 16.09.: von 0,45 gesenkt - 13 Ereignisse kamen erst ueber Stufe B rein
KANDIDATEN_JE_STORY = 5
MIN_SIM_THEMA = 0.62         # 16.09.: von 0,55 angehoben (Stufe B hatte 19 % Fehlgriffe)
THEMA_JE_KETTE = 8
ZEIT_BUDGET_S = 420          # danach keine neuen Richter-Aufrufe mehr (16.09.: 300 war beim
                             # Kaltstart mit 101 neuen Ketten zu knapp)
PARALLEL = 6
AUFBEWAHREN_TAGE = 10


def _hn_holen(url, key, versuche=2):
    kopf = {"User-Agent": "ki-news.live", "Authorization": "Bearer " + key}
    for i in range(versuche):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < versuche - 1:
                time.sleep(3)
                continue
            raise


def _json_antwort(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        nummern = json.loads(m.group(0)).get("gleich")
    except (ValueError, AttributeError):
        return None
    return nummern if isinstance(nummern, list) else None


def _richter_votum(llm_fn, prompt, anzahl):
    """Stufe B (16.09.26): beide Richter muessen zustimmen. Faellt einer aus,
    zaehlt das Urteil des anderen allein - nie mehr als vorher, aber auch kein
    Totalausfall der Stufe."""
    stimmen = []
    for modell in RICHTER:
        try:
            nummern = _json_antwort(llm_fn(modell, [{"role": "user", "content": prompt}], max_tokens=2000))
        except Exception as e:
            logger.info("Themenkette: Votum %s fehlgeschlagen (%s)", modell, e.__class__.__name__)
            continue
        if nummern is not None:
            stimmen.append({int(n) - 1 for n in nummern if str(n).isdigit() and 0 < int(n) <= anzahl})
    if not stimmen:
        return None
    einig = set.intersection(*stimmen) if len(stimmen) > 1 else stimmen[0]
    return sorted(einig)


def _artikelzeile(i, a):
    return "%d) [%s] %s -- %s" % (i + 1, a["source"], a["titel"], a["summary"][:160])


def _prompt_ereignis(story, artikel):
    return ("HuggingNews-Story:\n%s -- %s\n\nArtikel:\n%s\n\n"
            "Welche Artikel berichten ueber DASSELBE KONKRETE EREIGNIS wie die Story "
            "(nicht nur dasselbe Thema, dieselbe Firma oder eine Reaktion darauf)? "
            "Antworte nur mit JSON: {\"gleich\": [Nummern]} - leere Liste, wenn keiner."
            % (story["title"], story["summary"][:300], "\n".join(_artikelzeile(i, a) for i, a in enumerate(artikel))))


def _prompt_thema(glieder_titel, artikel):
    """16.09.26 geschaerft: die vier Fehlermuster der Handpruefung stehen jetzt
    ausdruecklich im Prompt (konkurrierendes Geruecht zur selben Firma, anderes
    Produkt derselben Marke, Sammel-Newsletter, blosse Stichwortnaehe)."""
    regeln = (
        "Welche Artikel behandeln DIREKT diese Entwicklungslinie - als Analyse, Einordnung, "
        "Reaktion, Pro/Contra oder als weiteres Ereignis derselben Linie?" + NL +
        "NICHT dazu zaehlen:" + NL +
        "- Artikel ueber ein anderes Produkt oder eine andere Meldung derselben Firma" + NL +
        "- konkurrierende Geruechte oder Spekulationen zu einem anderen Verlauf derselben Sache" + NL +
        "- Sammelmeldungen, Newsletter oder Wochenrueckblicke mit vielen Themen" + NL +
        "- Artikel, die nur dieselben Stichwoerter oder dieselbe Branche teilen" + NL +
        "Im Zweifel NICHT zuordnen. "
        "Antworte nur mit JSON: {\"gleich\": [Nummern]} - leere Liste, wenn keiner.")
    return ("Eine Entwicklungslinie in den KI-Nachrichten besteht aus diesen Ereignissen:" + NL +
            "- " + (NL + "- ").join(glieder_titel[:12]) + NL + NL +
            "Artikel:" + NL +
            NL.join(_artikelzeile(i, a) for i, a in enumerate(artikel)) + NL + NL + regeln)


def _lade(pfad):
    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def update_themenketten_shadow(base_dir, news_list, llm_fn):
    start = time.time()
    key = os.environ.get("HUGGINGNEWS_API_KEY", "").strip()
    if not key:
        logger.info("Themenkette: kein HUGGINGNEWS_API_KEY - Schritt uebersprungen")
        return None
    base = Path(base_dir)
    pfad = base / DATEI
    zustand = _lade(pfad)
    ketten_von = zustand.get("kette_von", {})          # hn_slug -> ketten_root
    ketten = zustand.get("ketten", {})                  # root -> {ursprung, glieder}
    urteile_a = zustand.get("urteile_ereignis", {})     # hn_slug -> {geprueft, ja}
    urteile_b = zustand.get("urteile_thema", {})        # root -> {geprueft, ja}
    zuordnung = zustand.get("zuordnung", {})            # link -> {...}
    stat = {"hn_storys": 0, "ketten_neu": 0, "richter_a": 0, "richter_b": 0,
            "zeitgrenze": False, "fehler": 0}

    # 1. HN-Storys + Ketten
    feed = _hn_holen(HN_API, key)
    slugs = [s["slug"] for g in feed.get("dayGroups", []) for s in g.get("stories", [])]

    def _detail(slug):
        try:
            return slug, _hn_holen(HN_API + "/" + urllib.parse.quote(slug), key)
        except Exception:
            return slug, None

    storys = []
    with ThreadPoolExecutor(8) as pool:
        for slug, d in pool.map(_detail, slugs):
            if d is None:
                stat["fehler"] += 1
                continue
            storys.append({"slug": slug, "title": d.get("title", ""),
                           "summary": d.get("summary") or "", "event": d.get("eventTimeApprox")})
    stat["hn_storys"] = len(storys)

    def _kette(slug):
        try:
            return slug, _hn_holen(HN_API + "/" + urllib.parse.quote(slug) + "/chain", key).get("stories") or []
        except Exception:
            return slug, None

    offen = [s["slug"] for s in storys if s["slug"] not in ketten_von]
    with ThreadPoolExecutor(8) as pool:
        ergebnisse = list(pool.map(_kette, offen))
    for slug, glieder in ergebnisse:
        if glieder is None:
            stat["fehler"] += 1
            continue
        if slug in ketten_von:      # schon ueber eine andere Story dieses Laufs erfasst
            continue
        s = next(x for x in storys if x["slug"] == slug)
        if not glieder:
            glieder = [{"slug": s["slug"], "eventTimeApprox": s["event"]}]
        root = glieder[0]["slug"]
        k = ketten.setdefault(root, {"ursprung": glieder[0].get("eventTimeApprox"), "glieder": []})
        for x in glieder:
            if x["slug"] not in k["glieder"]:
                k["glieder"].append(x["slug"])
            ketten_von[x["slug"]] = root
        stat["ketten_neu"] += 1
    storys = [s for s in storys if s["slug"] in ketten_von]
    if not storys:
        logger.info("Themenkette: keine HN-Storys mit Kette - nichts zu tun")
        return stat

    # Unsere Artikel (Originaltitel, wenn im Uebersetzungs-Cache)
    cache = _lade(base / "summary-cache.json")
    artikel = [{"link": n["link"], "source": n.get("source", ""),
                "titel": ((cache.get(n["link"]) or {}).get("title_orig") if isinstance(cache.get(n["link"]), dict) else None) or n.get("title", ""),
                "summary": (n.get("summary") or "")[:250], "first_seen": n.get("first_seen"),
                "story_id": n.get("story_id")}
               for n in news_list if n.get("link")]
    if not artikel:
        return stat

    from sentence_transformers import SentenceTransformer
    import numpy as np
    modell = SentenceTransformer(MODELL, device="cpu")
    v_hn = np.asarray(modell.encode([s["title"] + ". " + s["summary"][:250] for s in storys],
                                    batch_size=64, show_progress_bar=False, normalize_embeddings=True))
    v_ar = np.asarray(modell.encode([a["titel"] + ". " + a["summary"] for a in artikel],
                                    batch_size=64, show_progress_bar=False, normalize_embeddings=True))
    sim = v_hn @ v_ar.T
    idx_von = {a["link"]: i for i, a in enumerate(artikel)}

    # 2. Stufe A
    auftraege = []
    for si, s in enumerate(storys):
        u = urteile_a.setdefault(s["slug"], {"geprueft": [], "ja": []})
        neu = [int(j) for j in np.argsort(-sim[si])[:KANDIDATEN_JE_STORY]
               if sim[si, j] >= MIN_SIM_EREIGNIS and artikel[j]["link"] not in u["geprueft"]]
        if neu:
            auftraege.append((si, neu))

    def _a(auftrag):
        si, neu = auftrag
        if time.time() - start > ZEIT_BUDGET_S:
            return si, neu, "zeit"
        return si, neu, _richter_votum(llm_fn, _prompt_ereignis(storys[si], [artikel[j] for j in neu]), len(neu))

    with ThreadPoolExecutor(PARALLEL) as pool:
        for si, neu, nr in pool.map(_a, auftraege):
            if nr == "zeit":
                stat["zeitgrenze"] = True
                continue
            stat["richter_a"] += 1
            if nr is None:
                stat["fehler"] += 1
                continue
            u = urteile_a[storys[si]["slug"]]
            u["geprueft"] += [artikel[j]["link"] for j in neu]
            u["ja"] += [artikel[neu[i]]["link"] for i in nr]

    heute = datetime.now(timezone.utc).date().isoformat()
    for si, s in enumerate(storys):
        root = ketten_von[s["slug"]]
        for link in urteile_a.get(s["slug"], {}).get("ja", []):
            j = idx_von.get(link)
            if j is None:
                continue
            alt = zuordnung.get(link)
            if alt and alt.get("rolle") == "ereignis" and alt.get("sim", 0) >= float(sim[si, j]):
                continue
            zuordnung[link] = {"kette": root, "rolle": "ereignis", "hn_slug": s["slug"],
                               "sim": round(float(sim[si, j]), 3), "seit": (alt or {}).get("seit", heute)}

    # 3. Stufe B - Ketten mit mind. 2 zugeordneten Artikeln
    try:
        from story_registry_shadow import _load_entities, _entities_of
        ent_muster = _load_entities(base)
    except Exception as e:
        logger.info("Themenkette: Entitaeten-Gate inaktiv (%s)", e.__class__.__name__)
        ent_muster = None
    je_kette = {}
    for link, z in zuordnung.items():
        if z["rolle"] == "ereignis" and link in idx_von:
            je_kette.setdefault(z["kette"], []).append(idx_von[link])
    auftraege_b = []
    for root, mitglieder in je_kette.items():
        if len(mitglieder) < 2:
            continue
        hn_idx = [si for si, s in enumerate(storys) if ketten_von[s["slug"]] == root]
        schwerpunkt = np.mean(np.vstack([v_ar[mitglieder]] + ([v_hn[hn_idx]] if hn_idx else [])), axis=0)
        schwerpunkt /= (np.linalg.norm(schwerpunkt) or 1.0)
        u = urteile_b.setdefault(root, {"geprueft": [], "ja": []})
        # Entitaeten-Gate (16.09.26, wie Gate R1 der Shadow-Registry): ein Artikel
        # kommt nur vor den Richter, wenn er mindestens eine Entitaet mit der Kette
        # teilt. Ohne entities.json entfaellt das Gate (fail-open).
        kette_ents = set()
        if ent_muster:
            for si in hn_idx:
                kette_ents |= _entities_of(ent_muster, storys[si]["title"] + " " + storys[si]["summary"][:250])
            for j in mitglieder:
                kette_ents |= _entities_of(ent_muster, artikel[j]["titel"] + " " + artikel[j]["summary"])
        nah = sorted(((float(v_ar[j] @ schwerpunkt), j) for j in range(len(artikel))
                      if artikel[j]["link"] not in zuordnung and artikel[j]["link"] not in u["geprueft"]
                      and (not kette_ents
                           or _entities_of(ent_muster, artikel[j]["titel"] + " " + artikel[j]["summary"]) & kette_ents)),
                     reverse=True)
        neu = [j for s_, j in nah if s_ >= MIN_SIM_THEMA][:THEMA_JE_KETTE]
        if neu:
            titel = [storys[si]["title"] for si in hn_idx] or [artikel[j]["titel"] for j in mitglieder]
            auftraege_b.append((root, neu, titel))

    def _b(auftrag):
        root, neu, titel = auftrag
        if time.time() - start > ZEIT_BUDGET_S:
            return root, neu, "zeit"
        return root, neu, _richter_votum(llm_fn, _prompt_thema(titel, [artikel[j] for j in neu]), len(neu))

    with ThreadPoolExecutor(PARALLEL) as pool:
        for root, neu, nr in pool.map(_b, auftraege_b):
            if nr == "zeit":
                stat["zeitgrenze"] = True
                continue
            stat["richter_b"] += 1
            if nr is None:
                stat["fehler"] += 1
                continue
            urteile_b[root]["geprueft"] += [artikel[j]["link"] for j in neu]
            for i in nr:
                link = artikel[neu[i]]["link"]
                urteile_b[root]["ja"].append(link)
                if link not in zuordnung:
                    zuordnung[link] = {"kette": root, "rolle": "thema", "seit": heute}

    # 4. Aufraeumen + schreiben
    grenze = (datetime.now(timezone.utc) - timedelta(days=AUFBEWAHREN_TAGE)).date().isoformat()
    aktuell = set(idx_von)
    zuordnung = {l: z for l, z in zuordnung.items() if l in aktuell or z.get("seit", heute) >= grenze}
    genutzt = {z["kette"] for z in zuordnung.values()} | {ketten_von[s["slug"]] for s in storys}
    ketten = {r: k for r, k in ketten.items() if r in genutzt}
    ketten_von = {sl: r for sl, r in ketten_von.items() if r in ketten}
    urteile_a = {sl: u for sl, u in urteile_a.items() if sl in ketten_von}
    urteile_b = {r: u for r, u in urteile_b.items() if r in ketten}
    for u in list(urteile_a.values()) + list(urteile_b.values()):
        u["geprueft"] = [l for l in u["geprueft"] if l in aktuell]
        u["ja"] = [l for l in u["ja"] if l in aktuell]

    stat.update({
        "dauer_s": round(time.time() - start, 1),
        "zuordnungen_ereignis": sum(z["rolle"] == "ereignis" and l in aktuell for l, z in zuordnung.items()),
        "zuordnungen_thema": sum(z["rolle"] == "thema" and l in aktuell for l, z in zuordnung.items()),
        "ketten_mit_artikeln": len({z["kette"] for l, z in zuordnung.items() if l in aktuell}),
    })
    daten = {
        "_hinweis": "SHADOW-MODE, nur Beobachtung. Schreiber: themenkette_shadow.py. Keine HN-Texte (use=reference).",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lauf": stat, "ketten": ketten, "kette_von": ketten_von, "zuordnung": zuordnung,
        "urteile_ereignis": urteile_a, "urteile_thema": urteile_b,
    }
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("THEMENKETTE: %s", json.dumps(stat, ensure_ascii=False))
    return stat
