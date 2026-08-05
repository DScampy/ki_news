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
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ki_news.shadow_registry")

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
THETA_ATTACH = 0.75
MAX_AGE_DAYS = 4
MAX_CANDIDATES = 25          # Kill-Switch-Symptom: mehr => Lauf ueberspringen + WARN
MAX_ORPHANS_FOR_PASS2 = 40   # Pass-2 (s.u.) ueberspringen, wenn mehr unangedockte
                              # Fresh-Cluster in einem Lauf entstehen - Symptom pruefen.
                              # (04.08.2026: von 15 auf 40 angehoben - reale Orphan-Zahl
                              # lag bei 20-29/Lauf, Cap war gegen die falsche Referenzgroesse
                              # kalibriert (Pass-1-Kandidaten ~0-4/Lauf statt Neu-Storys
                              # ~10-25/Lauf, A10-Fix-Stand). Pass-2 hat seit Deploy 03.08.
                              # dadurch noch NIE gemergt - alle 3 geloggten Laeufe lagen
                              # ueber dem alten Cap. Kill-Switch: faellt ein Pass-2-Judge-
                              # Call bei realer Paarzahl (siehe SHADOW-PASS2-PAIRS-Log) aus
                              # (Timeout/unparsebar), Cap zurueck auf 15 und stattdessen
                              # einen Deckel auf die GATE-PASSING-Paarzahl einziehen, nicht
                              # auf die rohe Orphan-Zahl.
REGISTRY_FILE = "story_registry_shadow.json"

# Eigene Modell-Kette NUR fuer den Judge-Call (03.08.2026, Addendum A11
# embedding_report.md). Getrennt von ki_news.py's MODELLE (Uebersetzung/Posts) -
# absichtlich, damit dieser Fix die Uebersetzungs-Qualitaet/-Kosten nicht anfasst.
# gpt-oss-120b zuerst: entspricht dem in Design v2 §3 festgelegten und in A3/A4
# offline validierten Judge-Modell (92% Genauigkeit, 0 klare False-Merges ueber
# 3 Modellfamilien). Die bisherige Praxis (MODELLE = reine Free-Kette ohne
# gpt-oss-120b) war Implementierungs-Drift vom eigenen Design, kein Neuentwurf.
# Free-Modelle bleiben als Fallback, falls gpt-oss-120b (ueber OpenRouter/DeepInfra)
# mal nicht erreichbar ist - Verhalten degradiert dann auf den bisherigen Stand,
# wird nie schlechter (Invariante I8, Fail-safe = nicht andocken bleibt unberuehrt).
JUDGE_MODELLE = [
    "openai/gpt-oss-120b",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct",
]

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
    """Ein gebatchter Call. Rueckgabe: (dict nr->True/False, verwendetes Modell|None).
    Fehler => alles False, Modell None (Fail-safe).

    Modell-Rueckgabe (01.08.2026, Addendum A11 embedding_report.md): Merge-Qualitaets-
    Review fand 3 False-Merges; offline liess sich NICHT feststellen, welches Modell
    aus `modelle` sie tatsaechlich geurteilt hat, weil bisher nirgends geloggt wurde,
    welches Modell in der Fallback-Kette den Call gewonnen hat. Rein additiv - aendert
    nichts an der Urteils-Logik, nur an dem, was zurueckgegeben/geloggt wird."""
    lines = []
    for i, (a, b) in enumerate(pairs, 1):
        lines.append(f"{i}) A: {a}\n    B: {b}")
    user = ("Beurteile fuer jedes der folgenden Paare: ist B dieselbe Story wie A?\n\n"
            + "\n\n".join(lines))
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user}]
    content = None
    used_model = None
    for model in modelle:
        try:
            content = llm_fn(model, messages, max_tokens=300)
            if content:
                used_model = model
                break
        except Exception as e:
            logger.info("Shadow-Judge: Modell %s nicht verfuegbar (%s)", model, e)
    verdicts = {i: False for i in range(1, len(pairs) + 1)}   # Fail-safe: NEIN
    if not content:
        logger.warning("Shadow-Judge: kein Modell erreichbar - alle %d Kandidaten NICHT angedockt (Fail-safe)", len(pairs))
        return verdicts, None
    for m in re.finditer(r"(\d+)\s*[:\)]\s*(JA|NEIN)", content, re.I):
        n = int(m.group(1))
        if n in verdicts:
            verdicts[n] = m.group(2).upper() == "JA"
    return verdicts, used_model


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

    # Link-Dedup (23.07.2026): re-ingestierte Artikel (Link bereits Registry-Member)
    # werden an ihre bestehende Story angedockt (last_seen auffrischen), statt jeden
    # Lauf neu als Story angelegt / als Kandidat gezaehlt zu werden. Deterministisch,
    # kostenlos, kein False-Merge-Risiko (gleiche URL = gleicher Artikel). Behebt die
    # Re-Ingestion-Flut - die eigentliche Ursache fuer Kill-Switch-Dauerfeuer und
    # Registry-Bloat (verifiziert offline: Kandidaten/Lauf ~65 -> ~2). Cross-Source-
    # Duplikate (gleiche Story, andere URL) bleiben Sache von Gates + Judge.
    known_links = {l: sid for sid, st in registry.items()
                   for l in st.get("links", []) if l}
    _reingest = 0
    _fresh_news = []
    for _n in news_list:
        _l = _n.get("link") or ""
        if _l and _l in known_links:
            registry[known_links[_l]]["last_seen"] = today
            _reingest += 1
        else:
            _fresh_news.append(_n)
    news_list = _fresh_news
    if _reingest:
        logger.info("Shadow-Registry: %d re-ingestierte Artikel per Link angedockt "
                    "(kein Duplikat, kein Kandidat)", _reingest)

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
        verdicts, judge_model = _judge(pairs, llm_fn, modelle)
        model_tag = judge_model or "keins (Fail-safe)"
        for i, (ci, sid, sim) in enumerate(candidates, 1):
            rep = clusters[ci][0].get("title", "")
            if verdicts.get(i):
                st = registry[sid]
                st["titles"] = (st["titles"] + [m.get("title", "") for m in clusters[ci]])[-20:]
                st["links"] = (st.get("links", []) + [m.get("link", "") for m in clusters[ci]])[-20:]
                st["last_seen"] = today
                st["attach_count"] = st.get("attach_count", 0) + 1
                st["last_judge_model"] = judge_model  # A11: fuer Merge-Qualitaets-Review
                # A7-Fix 1: Zentroid bleibt EINGEFROREN - kein Update.
                attached += 1
                logger.info("SHADOW-ATTACH (Judge JA, Modell=%s): %.3f '%s' -> %s '%s'",
                            model_tag, sim, rep[:60], sid, st["rep_title"][:60])
            else:
                logger.info("SHADOW-JUDGE NEIN (Modell=%s): %.3f '%s' -> '%s'",
                            model_tag, sim, rep[:60], registry[sid]["rep_title"][:60])

    # PASS 2 (03.08.2026, Addendum A12/A13 embedding_report.md): UnionFind unter
    # den unangedockten Fresh-Clustern DESSELBEN LAUFS, bevor jeder einzeln als
    # neue Story angelegt wird. Herkunft: Reddit-Recherche fand ein Zwei-Pass-
    # Muster (3mins.news-Blogpost); offline (r8, synthetisches Eval-Set) und
    # gegen den echten Live-Snapshot (r9, 520 Storys) geprueft: 0 Mega-Entity-
    # Fehlurteile, 3 unabhaengige reale Fragmentierungsfaelle gefunden (u.a. der
    # Google-Earth-3x-Fall, der Daniel am 03.08. als 3x-Telegram-Spam auffiel).
    # Nutzt DIESELBEN Signale wie Pass 1 (θ=0,75-Kosinus, R1-Entitaeten-Gate,
    # JUDGE_MODELLE) - kein separater, laxerer Pfad. Fail-safe: jeder Fehler
    # oder zu viele Orphans (> MAX_ORPHANS_FOR_PASS2) -> Fallback auf das
    # bisherige Verhalten (jeder Cluster wird einzeln zur eigenen Story).
    judged_yes = set()
    if candidates:
        for i, (ci, sid, sim) in enumerate(candidates, 1):
            if verdicts.get(i):
                judged_yes.add(ci)
    orphans = [ci for ci in range(len(clusters))
               if ci not in judged_yes and ci not in skipped_by_killswitch
               and clusters[ci][0].get("title", "")]

    group_of = {ci: ci for ci in orphans}   # Default: jeder Orphan seine eigene Gruppe
    if len(orphans) >= 2:
        try:
            if len(orphans) > MAX_ORPHANS_FOR_PASS2:
                logger.warning("Shadow-Registry Pass-2: %d unangedockte Cluster (> %d) - "
                               "uebersprungen, jeder Cluster bleibt einzeln (Symptom pruefen!)",
                               len(orphans), MAX_ORPHANS_FOR_PASS2)
            else:
                p2_pairs_idx, p2_pairs_text = [], []
                for i in range(len(orphans)):
                    for j in range(i + 1, len(orphans)):
                        ci, cj = orphans[i], orphans[j]
                        sim = float(cluster_vecs[ci] @ cluster_vecs[cj])
                        if sim < THETA_ATTACH:
                            continue
                        ti = [m.get("title", "") for m in clusters[ci]]
                        tj = [m.get("title", "") for m in clusters[cj]]
                        text_i = " ".join(ti) + " " + " ".join(sum_of.get(t, "") for t in ti)
                        text_j = " ".join(tj) + " " + " ".join(sum_of.get(t, "") for t in tj)
                        if ent_patterns is not None and not (
                                _entities_of(ent_patterns, text_i) & _entities_of(ent_patterns, text_j)):
                            continue  # R1-Gate, exakt wie Pass 1
                        p2_pairs_idx.append((ci, cj))
                        p2_pairs_text.append((f"{ti[0]} | {sum_of.get(ti[0], '')}",
                                              f"{tj[0]} | {sum_of.get(tj[0], '')}"))
                # Sichtbarkeit fuer die naechste Cap-Kalibrierung (04.08.2026):
                # rohe Paare (n*(n-1)/2 vor jedem Filter) vs. tatsaechlich an den
                # Judge gegangene Paare (nach θ+R1-Gate).
                raw_pairs = len(orphans) * (len(orphans) - 1) // 2
                logger.info("Shadow-Registry Pass-2: %d Orphans, %d rohe Paare, "
                            "%d nach θ/R1-Gate an den Judge", len(orphans), raw_pairs,
                            len(p2_pairs_text))
                if p2_pairs_text:
                    p2_verdicts, p2_model = _judge(p2_pairs_text, llm_fn, modelle)
                    uf = {ci: ci for ci in orphans}

                    def _find(x):
                        while uf[x] != x:
                            uf[x] = uf[uf[x]]
                            x = uf[x]
                        return x

                    for i, (ci, cj) in enumerate(p2_pairs_idx, 1):
                        if p2_verdicts.get(i):
                            ri, rj = _find(ci), _find(cj)
                            if ri != rj:
                                uf[ri] = rj
                            logger.info("SHADOW-PASS2-MERGE (Modell=%s): '%s' + '%s'",
                                        p2_model or "keins (Fail-safe)",
                                        clusters[ci][0].get("title", "")[:60],
                                        clusters[cj][0].get("title", "")[:60])
                    group_of = {ci: _find(ci) for ci in orphans}
        except Exception as e:
            logger.warning("Shadow-Registry Pass-2 fehlgeschlagen (%s) - Fallback: "
                           "jeder Cluster bleibt einzeln wie bisher", e)
            group_of = {ci: ci for ci in orphans}

    groups = defaultdict(list)
    for ci in orphans:
        groups[group_of[ci]].append(ci)

    # Neue Storys anlegen: EINE Story pro Pass-2-Gruppe (statt pro Cluster).
    next_id = max([int(s.split("-")[-1]) for s in registry] + [0]) + 1
    for root, members in groups.items():
        titles, links, vecs = [], [], []
        for ci in members:
            c = clusters[ci]
            titles += [m.get("title", "") for m in c]
            links += [m.get("link", "") for m in c]
            vecs.append(cluster_vecs[ci])
        rep = titles[0] if titles else ""
        if not rep:
            continue
        sid = f"st-{next_id:05d}"
        next_id += 1
        registry[sid] = {
            "rep_title": rep,
            "summary": sum_of.get(rep, ""),
            "titles": titles,
            "links": links,
            "centroid": [round(float(x), 5) for x in (_centroid(vecs) if len(vecs) > 1 else vecs[0])],
            "created": today,
            "last_seen": today,
            "attach_count": 0,
            "pass2_merged": len(members) > 1,   # Transparenz fuer den naechsten Merge-Qualitaets-Review
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
