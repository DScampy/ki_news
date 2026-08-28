# -*- coding: utf-8 -*-
"""gleiches_ereignis(a, b) -- beschreiben zwei Meldungen dasselbe Ereignis?

Herkunft: ox-Schleife (02 Projekte/Wissen aufbauen/ox-analyse), Lauf 4 vom
27.08.2026, Runde 3. Stand 180 von 219 Punkten, 0 von 74 Gegenprobe-Paaren
zerrissen. Der Code ist automatisch erzeugt und von Hand geprueft.

ACHTUNG -- NUR MIT ZUSAETZLICHEM AEHNLICHKEITS-GATE VERWENDEN.

Am echten Tagesbestand (57 Shadow-Storys, 27.08.) erreicht die Funktion allein
75-78 % Praezision. Das reicht nicht: eine falsche Zusammenfuehrung laesst eine
Meldung komplett verschwinden und setzt eine falsche Aussage in Karte und
Telegram-Post, waehrend eine fehlende Zusammenfuehrung nur einen Platz kostet.
Die Fehler sind also nicht gleich teuer.

Beispiel vom 26.08. (Startseite): sie fuehrt "Nvidia kauft Hugging Face fuer
12,9 Milliarden" und "Nvidia uebernimmt Hugging Face fuer 12,9 Milliarden"
korrekt zusammen -- wirft aber "Nvidias Gewinn verdoppelt sich auf 59,69
Milliarden" mit hinein. Sie ist dort nicht einmal transitiv.

MIT dem Gate (zusaetzlich normalisierte Textaehnlichkeit >= 0.62) waren im
selben Test 7 von 7 Zusammenfuehrungen richtig. Genau dieser Fall trennt sauber:
die Dublette liegt bei 0.72, der Gewinn-Artikel bei 0.50.

Deshalb wird die Funktion in ki_news.py ausschliesslich ueber _ist_dublette()
aufgerufen, das beide Bedingungen prueft.
"""
import re
from difflib import SequenceMatcher
from collections import Counter

_STOP = set("""der die das den dem des ein eine einen einem eines und oder aber ist sind war
wird werden wurde wurden hat haben hatte von vom zum zur im in an auf für mit nach über unter
aus bei als auch noch nicht kein keine sich sie er es wir ihr man mehr sehr schon nur wie was
wer dass wenn um so""".split())

_GENERIC = {"chips/gpus", "chips", "gpus", "rechenzentren", "datenschutz",
            "exportkontrollen", "open source", "agi"}

_GENERIC_VERBS = {"fügt", "hinzu", "bringt", "stellt", "startet", "lanciert",
                  "veröffentlicht", "kündigt", "setzt", "rollt", "bietet",
                  "plant", "zeigt", "nennt"}

_PRICE = ("preis", "prozent", "%", "kosten", "teurer", "verteuer")
_PARTNER = ("partner", "zusammen", "deal", "kooper", "übernahm", "übernahme")
_STOCK = ("aktie", "aktien", "steigt", "stieg", "zuwachs", "zunahme", "kurs", "wert")
_LITIGATION = ("klage", "verklagt", "gerichts", "anklage", "recht", "prozess")
_EVENT = _PRICE + _PARTNER + _STOCK + _LITIGATION

_VETO_TOPICS = {
    "klage": ("verklagt", "klagt", "gerichts", "anklage"),
    "cyber": ("cyberangriff", "kraftwerk", "hack"),
}

# ---------------------------------------------------------------------------

def _strip_source(s: str) -> str:
    s = re.sub(r"\((?:[^)]*(?:via|über|update)[^)]*)\)", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\[(?:[^\]]*(?:update|bericht)[^\]]*)\]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+[–\-]\s*[A-ZÄÖÜ][\w\s]*(?:Labs|TradingView|Reuters)\w*\s*$", " ", s)
    s = re.sub(r"\s+\b(via|per)\b\s+\S.*$", " ", s)
    return s

def _norm(s: str) -> str:
    s = _strip_source(s)
    s = s.lower().replace("'s", " ").replace("\u2019s", " ")
    s = re.sub(r"[^a-zäöüß0-9%. ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _tokens(s: str):
    return [t for t in _norm(s).split()
            if t not in _STOP and t not in _GENERIC_VERBS and len(t) > 1]

def _capital_words(text):
    """Wortschätze, die mit einem Großbuchstaben beginnen (Produkt‑/Markennamen)."""
    return set(re.findall(r'\b[A-ZÄÖÜ][A-Za-z0-9]+\b', text))

def _replace_caps(txt, caps):
    for w in caps:
        txt = re.sub(r'\b' + re.escape(w) + r'\b', '<PROD>', txt)
    return txt

def _tok_sim(x, y):
    if x == y:
        return 1.0
    if min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x)):
        return 1.0
    if min(len(x), len(y)) >= 5:
        r = SequenceMatcher(None, x, y).ratio()
        if r >= 0.72:
            return r
    sx = x[:-1] if len(x) >= 5 else x
    sy = y[:-1] if len(y) >= 5 else y
    if sx == sy and len(sx) >= 4:
        return 0.9
    if min(len(sx), len(sy)) >= 4 and (sx.startswith(sy) or sy.startswith(sx)):
        return 0.9
    for suf in ("ern", "en", "er", "es", "e", "n", "s"):
        if x.endswith(suf) and len(x) - len(suf) >= 4:
            x2 = x[:-len(suf)]
            if x2 == y or (len(y) >= 4 and (y.startswith(x2) or x2.startswith(y))):
                return 0.9
        if y.endswith(suf) and len(y) - len(suf) >= 4:
            y2 = y[:-len(suf)]
            if y2 == x or (len(x) >= 4 and (x.startswith(y2) or y2.startswith(x))):
                return 0.9
    return 0.0

def _match_count(A, B):
    used = set()
    c = 0
    for a in A:
        best_i, best_s = None, 0.0
        for i, b in enumerate(B):
            if i in used:
                continue
            s = _tok_sim(a, b)
            if s > best_s:
                best_i, best_s = i, s
        if best_i is not None:
            used.add(best_i)
            c += 1
    return c

def _qty_numbers(text):
    out = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(\S{0,14})", text):
        val, tail = m.group(1), m.group(2)
        v = float(val.replace(",", "."))
        unit = None
        if tail.startswith("%") or tail.startswith("prozent"):
            unit = "pct"
        elif re.search(r"(milliarden|mrd|billion)", tail):
            unit = "bn"
        elif tail.startswith("million"):
            unit = "mn"
        elif re.search(r"(dollar|usd|euro)", tail):
            unit = "cur"
        if unit:
            out.append((unit, v))
    return out

def _num_check(ta, tb):
    qa, qb = _qty_numbers(ta), _qty_numbers(tb)
    if not qa or not qb:
        return None
    for ua, va in qa:
        for ub, vb in qb:
            if ua == ub and abs(va - vb) <= max(0.6, 0.06 * max(va, vb)):
                return True
    return False

def _companies(ents):
    out = set()
    for e in ents or []:
        e = e.strip().lower()
        if e and e not in _GENERIC:
            out.add(e)
    return out

def _ints(text):
    return set(int(m.group(1)) for m in re.finditer(r"\b(\d{1,4})\b", text))

def _has(text, kws):
    return any(k in text for k in kws)

# ---------------------------------------------------------------------------

def gleiches_ereignis(a, b):
    # Normalisierte Titel und Tokens
    ta_raw, tb_raw = _norm(a["titel"]), _norm(b["titel"])
    Ta, Tb = _tokens(a["titel"]), _tokens(b["titel"])
    sim = SequenceMatcher(None, ta_raw, tb_raw).ratio()

    # 0️⃣ Produkt‑Abweichungs‑Erkennung (z. B. OpenCode ↔ OpenClaw)
    caps_a = _capital_words(a["titel"])
    caps_b = _capital_words(b["titel"])
    if caps_a ^ caps_b:
        ta_sub = _replace_caps(ta_raw, caps_a)
        tb_sub = _replace_caps(tb_raw, caps_b)
        if SequenceMatcher(None, ta_sub, tb_sub).ratio() >= 0.9:
            return False

    # 1️⃣ Zahlen‑Übereinstimmung (z. B. 10 Mrd., 15 %)
    nc = _num_check(ta_raw, tb_raw)
    if nc is False:
        return False

    # 2️⃣ Sehr hohe Text‑Ähnlichkeit (nach Produkt‑Check)
    if sim >= 0.62:
        return True

    # 3️⃣ Entitäten extrahieren
    ca = _companies(a.get("entitaeten"))
    cb = _companies(b.get("entitaeten"))
    inter = ca & cb
    sym_ent = ca ^ cb

    # 4️⃣ Token‑Overlap‑Metrik
    overlap = _match_count(Ta, Tb) / max(1, len(set(Ta) | set(Tb)))

    # 5️⃣ **Neue Regel** – unterschiedliche Ereignis‑Keywords bei gleicher Firma
    ev_a = _has(ta_raw, _EVENT)
    ev_b = _has(tb_raw, _EVENT)
    if inter and ev_a and ev_b:
        # wenn einer von beiden ausschließlich Stock‑Keywords enthält und der andere Deal‑/Preis‑Keywords,
        # dann unterschiedliche Ereignisse
        if (_has(ta_raw, _STOCK) and _has(tb_raw, _PARTNER)) or \
           (_has(tb_raw, _STOCK) and _has(ta_raw, _PARTNER)):
            return False

    # 6️⃣ gleiche Kern‑Firma, aber stark unterschiedliche weitere Entitäten → verschieden,
    #    außer wenn Preis/Partner/Nummern‑Hinweis vorhanden
    if inter and len(sym_ent) >= 2:
        if not (ev_a or ev_b or nc):
            return False

    # 7️⃣ Offensichtliche Firmen‑Divergenz
    if ca and cb and len(sym_ent) >= 3:
        return False

    # 8️⃣ Zahlen‑Konflikt bei geringer Token‑Übereinstimmung
    ia, ib = _ints(ta_raw), _ints(tb_raw)
    if ia and ib and not (ia & ib) and overlap < 0.15:
        return False

    # 9️⃣ Asymmetrische Entity‑Nutzung bei geringem Overlap
    if bool(ca) != bool(cb) and overlap < 0.2:
        return False

    # 🔟 Keine gemeinsamen Entitäten → verschieden
    if ca and cb and not inter:
        return False

    # 1️⃣1️⃣ Partner‑Stichwörter mit stark unterschiedlichem Firmenset
    if sym_ent and len(ca) + len(cb) >= 3 and _has(ta_raw, _PARTNER) and _has(tb_raw, _PARTNER):
        return False

    # 1️⃣2️⃣ Veto‑Themen (Klage vs Cyber) müssen übereinstimmen
    veto_a = any(k in ta_raw for kws in _VETO_TOPICS.values() for k in kws)
    veto_b = any(k in tb_raw for kws in _VETO_TOPICS.values() for k in kws)
    if veto_a != veto_b:
        return False
    if veto_a and veto_b and not inter:
        return False

    # 1️⃣3️⃣ Preis‑Erhöhungen → gleich, wenn gleiche Firmen
    if _has(ta_raw, _PRICE) and _has(tb_raw, _PRICE) and inter:
        return True

    # 1️⃣4️⃣ exakt gleiche Entity‑Menge (mind. 2) → sofort gleich
    if ca == cb and len(ca) >= 2:
        return True

    # 1️⃣5️⃣ gleiche Entity‑Menge (mind. 1) → gleich, wenn Zahlen‑/Preis‑Hinweis o.Ä.
    if ca and cb and ca == cb:
        if nc is True or (_has(ta_raw, _PRICE) and _has(tb_raw, _PRICE)):
            return True
        return overlap >= 0.10

    # 1️⃣6️⃣ **Neue Regel** – wenn beide Titel nur aus generischen Tokens bestehen
    #      (keine gemeinsamen inhaltlichen Tokens) und die Firmenmenge ist identisch,
    #      dann handelt es sich um unterschiedliche Ereignisse.
    if ca == cb and not inter and overlap < 0.12:
        return False

    # 1️⃣7️⃣ Default‑Schwelle für Token‑Overlap
    return overlap >= 0.10