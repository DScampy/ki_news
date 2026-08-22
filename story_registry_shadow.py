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
MAX_PASS3_PAIRS_PER_RUN = 60  # Pass-3 (s.u.): Cap auf tatsaechlich an den Judge gehende
                              # Story-Paare (nach th+R1-Gate), NICHT auf rohe Storyzahl -
                              # aus dem Pass-2-Kalibrierungsfehler vom 04.08. gelernt (falsche
                              # Referenzgroesse gewaehlt). Empirisch gegen die reale Registry
                              # gemessen (07.08.2026, 647 aktive Storys, einmaliger Vollabgleich
                              # ohne Cache): 46 Paare ueber th=0.75 + R1-Gate. 60 gibt Puffer fuer
                              # den ersten Lauf (Backlog); danach sollte die Zahl durch den
                              # checked_pairs-Cache stark sinken (nur neue Storys seit dem
                              # letzten Lauf muessen neu verglichen werden). Nach den ersten
                              # produktiven Laeufen mit SHADOW-PASS3-PAIRS-Log neu kalibrieren,
                              # nicht raten.
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
    # 14.08.26: meta-llama/llama-3.3-70b-instruct:free entfernt - Live-Check
    # gegen OpenRouter /api/v1/models (14.08.26) zeigt: die :free-Variante
    # existiert nicht mehr im Katalog, nur noch die bezahlte ID ohne
    # ":free"-Suffix (steht unten als Fallback drin). Lieferte seit mind.
    # 12.08. durchgehend HTTP 404. Siehe identischer Fund in ki_news.py MODELLE.
    # gpt-oss-20b:free ergaenzt - live gegen die echte API getestet (gleiche
    # Familie wie gpt-oss-120b oben, kein Reasoning-Zwang-Problem). NVIDIA-
    # Nemotron-Modelle bewusst NICHT hier: brauchen reasoning:{enabled:false},
    # dieser Datei fehlt der Schalter aus ki_news.py's _call_llm_api() - erst
    # nachziehen, wenn diese Judge-Kette denselben Fix bekommt.
    # 22.08.26: gpt-oss-20b:free entfernt - dasselbe Ende wie oben bei
    # llama-3.3-70b-instruct:free, nur acht Tage spaeter. Live-Abgleich gegen
    # /api/v1/models am 22.08.: nicht mehr im Katalog. In ki_news.py MODELLE
    # hat dieselbe ID vorher 63x HTTP 404 produziert.
    # Ersatz: z-ai/glm-5.2:free, am 22.08. neu im Katalog und im Batch-Format
    # live geprueft. Nemotron bleibt auch hier draussen - dieser Datei fehlt
    # weiterhin der reasoning:{enabled:false}-Schalter aus _call_llm_api().
    "z-ai/glm-5.2:free",
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
            # 11.08.2026: leerer Response OHNE Exception wurde bisher gar nicht
            # geloggt - der Fallback griff still, ohne dass sichtbar war, WARUM
            # das bevorzugte Modell (meist gpt-oss-120b) nicht verwendet wurde.
            # Rein additiv (nur Log, keine Logik-Aenderung) - macht die bisher
            # unsichtbare Fallback-Quote diagnostizierbar.
            logger.info("Shadow-Judge: Modell %s lieferte leeren Response (kein Fehler, "
                        "kein Inhalt) - naechstes Modell", model)
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


def link_to_story_map(base_dir):
    """Oeffentlicher Lese-Zugriff (11.08.2026) fuer andere Pipeline-Schritte
    (aktuell: update_entity_graph), die wissen wollen, welcher Artikel-Link zu
    welcher Registry-Story gehoert - OHNE die Registry selbst zu veraendern
    (reiner Read-Only-Helper, kein neuer Schreiber, Invariante I5 unberuehrt).

    Fail-safe: bei jedem Fehler leeres dict -> Aufrufer faellt automatisch auf
    sein bisheriges Link-only-Verhalten zurueck (Invariante I8).
    """
    try:
        reg_path = Path(base_dir) / REGISTRY_FILE
        if not reg_path.exists():
            return {}
        stories = json.loads(reg_path.read_text(encoding="utf-8")).get("stories", {})
        return {link: sid for sid, st in stories.items() for link in st.get("links", []) if link}
    except Exception as e:
        logger.info("link_to_story_map: nicht verfuegbar (%s) - Aufrufer faellt auf Link-only zurueck", e)
        return {}


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
    pass3_checked = set()
    if reg_path.exists():
        try:
            _raw = json.loads(reg_path.read_text(encoding="utf-8"))
            registry = _raw.get("stories", {})
            pass3_checked = set(_raw.get("_pass3_checked", []))
        except Exception:
            logger.warning("Shadow-Registry: %s unlesbar - Registry startet neu", REGISTRY_FILE)
    # Aging
    cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    registry = {sid: st for sid, st in registry.items() if st.get("last_seen", "") >= cutoff}
    # Pass-3-Cache mit aussortieren: Eintraege, die eine inzwischen ausgealterte
    # (oder durch Pass-3 selbst gemergte) Story referenzieren, sind wertlos und
    # wuerden nur den Cache unbegrenzt wachsen lassen.
    pass3_checked = {p for p in pass3_checked
                     if all(sid in registry for sid in p.split("|"))}

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

    # PASS 3 (07.08.2026, Addendum A16 embedding_report.md): Story-vs-Story-Merge
    # UEBER LAeUFE HINWEG. Pass-1 vergleicht neue Artikel gegen bestehende Storys,
    # Pass-2 vergleicht unangedockte Cluster INNERHALB eines Laufs - aber sobald
    # zwei Storys erstmal unabhaengig voneinander EXISTIEREN, wurden sie nie wieder
    # gegeneinander geprueft. Konkreter Fund (Merge-Qualitaets-Review 07.08.): der
    # Google/DeepMind-Fuehrungswechsel (Hassabis-Ruecktritt + Dean-Abgang, 05.-07.08.)
    # zerfiel dadurch in 6 nie gemergte Storys ueber 3 Tage. Pass-3 vergleicht daher
    # ALLE aktuell aktiven Storys (die Registry aged ohnehin selbst nach MAX_AGE_DAYS
    # aus - kein eigenes Zeitfenster noetig) paarweise per bereits vorhandenem,
    # eingefrorenem Zentroid (A7-Fix 1 - kein Re-Embedding). Gleiches θ=0.75 + R1-Gate
    # wie Pass 1/2 - kein separater, laxerer Pfad.
    #
    # Modell-Entscheidung (Daniel, 07.08.): EIN starkes Modell (gpt-oss-120b zuerst
    # in JUDGE_MODELLE, wie ueberall sonst) statt 2-Modell-Konsens. Grund: die
    # 01.08.-Offline-Tests fanden bereits, dass 2-Modell-Konsens den Recall unter 80%
    # drueckt (vereinigt blinde Flecken statt sie auszugleichen) - und die real
    # betroffenen Story-Paare liegen mit 0.746-0.792 Similarity naeher an der
    # Ablehnungsschwelle als typische Pass-1-Attaches. Konsens haette hier vermutlich
    # genau die Faelle gekillt, fuer die Pass-3 gebaut wird. Nutzt dieselbe _judge()-
    # Funktion wie Pass 1/2 (kein neuer Code-Pfad, kein neues Fehlerbild).
    #
    # checked_pairs verhindert, dass dieselbe (bereits verneinte) Paarung jeden Lauf
    # erneut an den Judge geht - nur neue Storys seit dem letzten Lauf erzeugen neue
    # Paare. Fail-safe: jeder Fehler -> Pass-3 wird fuer diesen Lauf uebersprungen,
    # Registry bleibt unveraendert (Invariante I8-Analogon).
    try:
        sids_all = sorted(registry)
        if len(sids_all) >= 2:
            import numpy as _np
            cents_all = _np.stack([_np.asarray(registry[s]["centroid"], dtype=_np.float32)
                                    for s in sids_all])
            sim_matrix = cents_all @ cents_all.T
            text_of = {s: " ".join(registry[s]["titles"]) + " " + registry[s].get("summary", "")
                       for s in sids_all}
            ent_of = ({s: _entities_of(ent_patterns, text_of[s]) for s in sids_all}
                      if ent_patterns is not None else None)

            raw_pairs = []
            for i in range(len(sids_all)):
                for j in range(i + 1, len(sids_all)):
                    a, b = sids_all[i], sids_all[j]
                    key = "|".join(sorted((a, b)))
                    if key in pass3_checked:
                        continue
                    sim = float(sim_matrix[i, j])
                    if sim < THETA_ATTACH:
                        continue
                    if ent_of is not None and not (ent_of[a] & ent_of[b]):
                        continue
                    raw_pairs.append((a, b, sim))

            logger.info("Shadow-Registry Pass-3: %d Storys aktiv, %d neue Paare nach "
                        "θ/R1-Gate (vor Cap)", len(sids_all), len(raw_pairs))

            if len(raw_pairs) > MAX_PASS3_PAIRS_PER_RUN:
                logger.warning("Shadow-Registry Pass-3: %d Paare (> %d) - nur die "
                               "%d aehnlichsten diesen Lauf, Rest bleibt fuer naechsten "
                               "Lauf vorgemerkt (kein Cache-Eintrag)", len(raw_pairs),
                               MAX_PASS3_PAIRS_PER_RUN, MAX_PASS3_PAIRS_PER_RUN)
                raw_pairs.sort(key=lambda x: -x[2])
                raw_pairs = raw_pairs[:MAX_PASS3_PAIRS_PER_RUN]

            if raw_pairs:
                p3_pairs_text = [
                    (f"{registry[a]['rep_title']} | {registry[a].get('summary', '')}",
                     f"{registry[b]['rep_title']} | {registry[b].get('summary', '')}")
                    for a, b, sim in raw_pairs
                ]
                p3_verdicts, p3_model = _judge(p3_pairs_text, llm_fn, modelle)

                uf3 = {s: s for s in sids_all}

                def _find3(x):
                    while uf3[x] != x:
                        uf3[x] = uf3[uf3[x]]
                        x = uf3[x]
                    return x

                for i, (a, b, sim) in enumerate(raw_pairs, 1):
                    key = "|".join(sorted((a, b)))
                    pass3_checked.add(key)  # unabhaengig vom Urteil: nicht erneut fragen
                    if p3_verdicts.get(i):
                        ra, rb = _find3(a), _find3(b)
                        if ra != rb:
                            uf3[ra] = rb
                        logger.info("SHADOW-PASS3-MERGE (Modell=%s): %.3f '%s' <-> '%s'",
                                    p3_model or "keins (Fail-safe)", sim,
                                    registry[a]["rep_title"][:60],
                                    registry[b]["rep_title"][:60])
                    else:
                        logger.info("SHADOW-PASS3-JUDGE NEIN (Modell=%s): %.3f '%s' <-> '%s'",
                                    p3_model or "keins (Fail-safe)", sim,
                                    registry[a]["rep_title"][:60],
                                    registry[b]["rep_title"][:60])

                p3_groups = defaultdict(list)
                for s in sids_all:
                    p3_groups[_find3(s)].append(s)

                merged_count = 0
                for root, members in p3_groups.items():
                    if len(members) < 2:
                        continue
                    merged_count += len(members) - 1
                    # AElteste (per created-Datum, dann kleinste ID) Story ueberlebt -
                    # konsistent mit "erste Meldung gewinnt die Story-Identitaet".
                    members_sorted = sorted(members, key=lambda s: (registry[s].get("created", ""), s))
                    survivor = members_sorted[0]
                    surv = registry[survivor]
                    all_titles, all_links, all_cents = list(surv["titles"]), list(surv["links"]),                         [_np.asarray(surv["centroid"], dtype=_np.float32)]
                    latest_seen = surv.get("last_seen", today)
                    for absorbed_id in members_sorted[1:]:
                        absorbed = registry[absorbed_id]
                        all_titles += absorbed["titles"]
                        all_links += absorbed["links"]
                        all_cents.append(_np.asarray(absorbed["centroid"], dtype=_np.float32))
                        latest_seen = max(latest_seen, absorbed.get("last_seen", today))
                        surv["attach_count"] = surv.get("attach_count", 0) + absorbed.get("attach_count", 0) + 1
                        del registry[absorbed_id]
                    # Dedup, Reihenfolge egal - Titel/Links dienen nur Anzeige/Review.
                    seen_t, dedup_titles = set(), []
                    for t in all_titles:
                        if t not in seen_t:
                            seen_t.add(t); dedup_titles.append(t)
                    seen_l, dedup_links = set(), []
                    for l in all_links:
                        if l and l not in seen_l:
                            seen_l.add(l); dedup_links.append(l)
                    surv["titles"] = dedup_titles[-40:]
                    surv["links"] = dedup_links[-40:]
                    surv["last_seen"] = latest_seen
                    surv["centroid"] = [round(float(x), 5) for x in _centroid(all_cents)]
                    surv["pass3_merged"] = True
                if merged_count:
                    logger.info("Shadow-Registry Pass-3: %d Storys durch Merge zusammengefuehrt "
                                "(Modell=%s)", merged_count, p3_model or "keins (Fail-safe)")
    except Exception as e:
        logger.warning("Shadow-Registry Pass-3 fehlgeschlagen (%s) - Registry bleibt "
                       "unveraendert wie vor Pass-3", e)

    out = {
        "_hinweis": "GENERIERT von story_registry_shadow.py (SHADOW-MODE) - NICHT manuell editieren.",
        "updated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "stories": registry,
        "_pass3_checked": sorted(pass3_checked),
    }
    reg_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    dt = (datetime.utcnow() - t0).total_seconds()
    logger.info("Shadow-Registry: %d Storys, %d Kandidaten, %d haette angedockt, "
                "%d wegen Kill-Switch uebersprungen (weder Andock noch neue Story), %.1fs",
                len(registry), len(candidates), attached, len(skipped_by_killswitch), dt)
