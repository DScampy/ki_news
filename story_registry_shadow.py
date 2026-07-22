# -*- coding: utf-8 -*-
"""Story-Registry im SHADOW-MODE (20.07.2026).

Loggt, welche frischen Cluster an bekannte Storys ANGEDOCKT WORDEN WAEREN —
veraendert NICHTS am Pipeline-Output (kein Merge, kein Score, kein Frontend).
Architektur (Design v2 + A7-Fixes aus dem Offline-Harness, cluster-harness/):
  Stufe 1: Embedding-Kandidat  cos(Cluster-Zentroid, Story-Zentroid) >= 0.75
  Stufe 2: Gates R1 (gemeinsame Entitaet noetig) + R3 (Personalie nur mit Name)
  Stufe 3: LLM-Judge (1 gebatchter Call; Fehler/429/unparsebar => NICHT andocken)
A7-Fix 1: Story-Zentroid wird beim Anlegen EINGEFROREN (kein Update beim
          Andocken) — gegen den Story-Magnet-Effekt (Apple-Chip-Fall).
A7-Fix 2: Judge-Prompt gehaertet gegen Eigennamen-als-Idiom ("DeepSeek-Moment").

Vertragsregeln:
- story_registry_shadow.json: GENERIERT, genau EIN Schreiber (diese Datei),
  nie manuell editieren. Persistenz via git add im Workflow.
- entities.json wird NUR GELESEN.
- Fehler blockieren NIE die Pipeline (Invariante I8): nur Log, kein Raise.
- Kill-Switch: Hook-Aufruf in ki_news.py entfernen — sonst nichts noetig.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ki_news.shadow_registry")

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
THETA_ATTACH = 0.75
MAX_AGE_DAYS = 4
MAX_CANDIDATES = 25          # Kill-Switch-Symptom: mehr => Lauf ueberspringen + WARN
REGISTRY_FILE = "story_registry_shadow.json"

_WORD = re.compile(r"[a-zA-ZäöüÄÖÜß][\w\-']+")
PERSONALIE = re.compile(
    r"verl[äa]e?sst|steps down|tritt zur[üu]ck|leaves|scheidet aus|r[üu]cktritt", re.I)

JUDGE_SYSTEM = (
    "Du bist ein strenger Dedup-Pruefer fuer Nachrichtenartikel. Zwei Artikel sind "
    "NUR dann dieselbe Story, wenn sie dasselbe konkrete Ereignis beschreiben. "
    "NICHT dieselbe Story: nur gleiches Unternehmen, nur aehnliches Thema, "
    "verschiedene Produkte, verschiedene Personen, verschiedene Ereignisse. "
    "ACHTUNG: Ein Firmen- oder Produktname als Metapher, Idiom oder Vergleich "
    "('DeepSeek-Moment', 'das iPhone der KI', 'ein Sputnik-Moment') macht die "
    "genannte Firma NICHT zum Handelnden — entscheidend ist, WER im Ereignis "
    "handelt, nicht wer als Vergleich erwaehnt wird. "
    "Antworte NUR mit der Paar-Nummer gefolgt von JA oder NEIN (Beispiel: '3: JA'), "
    "eine Zeile pro Paar, alle Paare, keine Erklaerung.")


def _centroid(vecs):
    import numpy as np
    m = np.mean(np.stack(vecs), axis=0)
    n = float(np.linalg.norm(m))
    return m / n if n > 0 else m


def _load_entities(base):
    try:
        ents = json.loads((base / "entities.json").read_text(encoding="utf-8"))["entities"]
        return [(e["id"], re.compile("|".join(e["aliasse"]), re.I)) for e in ents]
    except Exception as e:
        logger.warning("Shadow-Registry: entities.json nicht lesbar (%s) - R1 uebersprungen", e)
        return None


def _entities_of(patterns, text):
    return frozenset(eid for eid, pat in patterns if pat.search(text))


def _token_df(base):
    """Dokumentfrequenz ueber archive.json-Titel (fuer R3 seltene Tokens)."""
    try:
        arch = json.loads((base / "archive.json").read_text(encoding="utf-8"))
        entries = arch.get("entries", arch) if isinstance(arch, dict) else arch
        from collections import Counter
        df = Counter()
        for e in entries:
            for t in {t.casefold() for t in _WORD.findall(e.get("title") or "")}:
                df[t] += 1
        return df
    except Exception:
        return None


def _judge(pairs, llm_fn, modelle):
    """Ein gebatchter Call. Rueckgabe: dict nr->True/False. Fehler => alles False."""
    lines = []
    for i, (a, b) in enumerate(pairs, 1):
        lines.append(f"{i}) A: {a}\n    B: {b}")
    user = ("Beurteile fuer jedes der folgenden Paare: ist B dieselbe Story wie A?\n\n"
            + "\n\n".join(lines))
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user}]
    content = None
    for model in modelle:
        try:
            content = llm_fn(model, messages, max_tokens=300)
            if content:
                break
        except Exception as e:
            logger.info("Shadow-Judge: Modell %s nicht verfuegbar (%s)", model, e)
    verdicts = {i: False for i in range(1, len(pairs) + 1)}   # Fail-safe: NEIN
    if not content:
        logger.warning("Shadow-Judge: kein Modell erreichbar - alle %d Kandidaten NICHT angedockt (Fail-safe)", len(pairs))
        return verdicts
    for m in re.finditer(r"(\d+)\s*[:\)]\s*(JA|NEIN)", content, re.I):
        n = int(m.group(1))
        if n in verdicts:
            verdicts[n] = m.group(2).upper() == "JA"
    return verdicts


def update_story_registry_shadow(base_dir, news_list, cluster_fn, llm_fn, modelle):
    """Hook aus ki_news.main(). Niemals raisen - alle Fehler nur loggen."""
    try:
        _run(Path(base_dir), news_list, cluster_fn, llm_fn, modelle)
    except Exception as e:
        logger.exception("Shadow-Registry fehlgeschlagen (Pipeline unbeeinflusst): %s", e)


def _run(base, news_list, cluster_fn, llm_fn, modelle):
    t0 = datetime.utcnow()
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("Shadow-Registry: sentence-transformers fehlt - Lauf uebersprungen "
                       "(Workflow-Step 'Shadow-Registry Abhaengigkeiten' noch nicht aktiv?)")
        return
    import numpy as np

    reg_path = base / REGISTRY_FILE
    today = date.today().isoformat()
    registry = {}
    if reg_path.exists():
        try:
            registry = json.loads(reg_path.read_text(encoding="utf-8")).get("stories", {})
        except Exception:
            logger.warning("Shadow-Registry: %s unlesbar - Registry startet neu", REGISTRY_FILE)
    # Aging
    cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    registry = {sid: st for sid, st in registry.items() if st.get("last_seen", "") >= cutoff}

    clusters = cluster_fn(list(news_list), None)
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    def embed(titles):
        vecs = model.encode([t for t in titles if t], batch_size=64,
                            show_progress_bar=False, normalize_embeddings=True)
        return [np.asarray(v, dtype=np.float32) for v in vecs]

    ent_patterns = _load_entities(base)
    df = _token_df(base)
    sum_of = {n.get("title", ""): (n.get("summary") or "")[:250] for n in news_list}

    sids = sorted(registry)
    cents = (np.stack([np.asarray(registry[s]["centroid"], dtype=np.float32) for s in sids])
             if sids else None)

    candidates = []   # (cluster_idx, sid, sim)
    cluster_vecs = {}
    for ci, c in enumerate(clusters):
        titles = [m.get("title", "") for m in c]
        cv = _centroid(embed(titles))
        cluster_vecs[ci] = cv
        if cents is None:
            continue
        sims = cents @ cv
        bi = int(np.argmax(sims))
        best_sid, best_sim = sids[bi], float(sims[bi])
        if best_sim < THETA_ATTACH:
            continue
        # Stufe 2: Gates
        cl_text = " ".join(titles) + " " + " ".join(sum_of.get(t, "") for t in titles)
        st = registry[best_sid]
        st_text = " ".join(st["titles"]) + " " + st.get("summary", "")
        if ent_patterns is not None:
            if not (_entities_of(ent_patterns, cl_text) & _entities_of(ent_patterns, st_text)):
                logger.info("SHADOW-GATE R1 blockt: %.3f '%s' -> '%s'",
                            best_sim, titles[0][:60], st["rep_title"][:60])
                continue
        if df and PERSONALIE.search(" ".join(titles)) and PERSONALIE.search(" ".join(st["titles"])):
            rc = {t.casefold() for t in _WORD.findall(" ".join(titles))
                  if df.get(t.casefold(), 0) <= 3 and len(t) > 3}
            rs = {t.casefold() for t in _WORD.findall(" ".join(st["titles"]))
                  if df.get(t.casefold(), 0) <= 3 and len(t) > 3}
            if not (rc & rs):
                logger.info("SHADOW-GATE R3 blockt: %.3f '%s' -> '%s'",
                            best_sim, titles[0][:60], st["rep_title"][:60])
                continue
        candidates.append((ci, best_sid, best_sim))

    # A9-Fix: Kill-Switch darf nur den Judge ueberspringen, NICHT die
    # uebersprungenen Cluster als "neue Story" behandeln - sonst dockt der
    # Kill-Switch-Fall genau die Duplikate NICHT an, die er verhindern soll,
    # und blaeht die Registry weiter auf (Teufelskreis: mehr Storys -> mehr
    # Kandidaten -> Kill-Switch feuert oefter -> noch mehr Storys).
    skipped_by_killswitch = set()
    if len(candidates) > MAX_CANDIDATES:
        logger.warning("Shadow-Registry: %d Kandidaten (> %d) - Judge uebersprungen, "
                       "KEIN Andocken geloggt, KEINE neuen Storys fuer diese Cluster. "
                       "Symptom pruefen (theta/Registry)!",
                       len(candidates), MAX_CANDIDATES)
        skipped_by_killswitch = {ci for ci, sid, sim in candidates}
        candidates = []

    # Stufe 3: Judge (ein Call)
    attached = 0
    if candidates:
        pairs = []
        for ci, sid, sim in candidates:
            a_t = clusters[ci][0].get("title", "")
            pairs.append((f"{a_t} | {sum_of.get(a_t, '')}",
                          f"{registry[sid]['rep_title']} | {registry[sid].get('summary', '')}"))
        verdicts = _judge(pairs, llm_fn, modelle)
        for i, (ci, sid, sim) in enumerate(candidates, 1):
            rep = clusters[ci][0].get("title", "")
            if verdicts.get(i):
                st = registry[sid]
                st["titles"] = (st["titles"] + [m.get("title", "") for m in clusters[ci]])[-20:]
                st["links"] = (st.get("links", []) + [m.get("link", "") for m in clusters[ci]])[-20:]
                st["last_seen"] = today
                st["attach_count"] = st.get("attach_count", 0) + 1
                # A7-Fix 1: Zentroid bleibt EINGEFROREN - kein Update.
                attached += 1
                logger.info("SHADOW-ATTACH (Judge JA): %.3f '%s' -> %s '%s'",
                            sim, rep[:60], sid, st["rep_title"][:60])
            else:
                logger.info("SHADOW-JUDGE NEIN: %.3f '%s' -> '%s'",
                            sim, rep[:60], registry[sid]["rep_title"][:60])

    # Neue Storys anlegen (alle Cluster, die nicht angedockt haben)
    judged_yes = set()
    if candidates:
        for i, (ci, sid, sim) in enumerate(candidates, 1):
            if verdicts.get(i):
                judged_yes.add(ci)
    next_id = max([int(s.split("-")[-1]) for s in registry] + [0]) + 1
    for ci, c in enumerate(clusters):
        if ci in judged_yes or ci in skipped_by_killswitch:
            continue
        rep = c[0].get("title", "")
        if not rep:
            continue
        sid = f"st-{next_id:05d}"
        next_id += 1
        registry[sid] = {
            "rep_title": rep,
            "summary": sum_of.get(rep, ""),
            "titles": [m.get("title", "") for m in c],
            "links": [m.get("link", "") for m in c],
            "centroid": [round(float(x), 5) for x in cluster_vecs[ci]],
            "created": today,
            "last_seen": today,
            "attach_count": 0,
        }

    out = {
        "_hinweis": "GENERIERT von story_registry_shadow.py (SHADOW-MODE) - NICHT manuell editieren.",
        "updated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "stories": registry,
    }
    reg_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    dt = (datetime.utcnow() - t0).total_seconds()
    logger.info("Shadow-Registry: %d Storys, %d Kandidaten, %d haette angedockt, "
                "%d wegen Kill-Switch uebersprungen (weder Andock noch neue Story), %.1fs",
                len(registry), len(candidates), attached, len(skipped_by_killswitch), dt)
