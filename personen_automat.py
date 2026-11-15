"""Personen-Seiten (15.11.26): kurzer Lebenslauf je Person, jede Angabe mit Beleg.

Ablage:   personen/index.html (Liste), personen/<id>.html (je Person), personen/index.json (fuer die
          Chips in der Meldungsansicht), personen/cache.json (Wikidata und Pruefergebnisse),
          personen/entwurf/<id>.html (ohne Freigabe, noindex), personen/sitemap.xml (erst ab INDEX_AB).
Liste:    personen.json, von Hand gepflegt. Dieses Skript liest sie nur.

Regeln (Plan vom 15.11.26, von Daniel freigegeben):
- Stationen kommen aus Wikidata (CC0): Amt (P39), Arbeitgeber (P108), Ausbildung (P69) und Gruendung
  (P112 am Unternehmen). Wikipedia-Text wird nicht uebernommen (CC BY-SA), Fotos gibt es keine.
- Eine Station erscheint nur mit Beleg. Beleg A: die Wikidata-Aussage nennt eine Quelle ausserhalb der
  Wikipedia. Eine Adresse (P854) wird abgerufen und muss Nachname und Organisation enthalten. Eine
  Datenbank (P248) zaehlt, wenn sie kein Wikimedia-Projekt ist. Beleg B: eine eigene Meldung, und ein
  Pruefmodell bestaetigt, dass der Meldungstext die Angabe traegt. Ohne Beleg faellt die Zeile weg.
- Beginn und Ende stehen nur mit Beleg A da. Meldet eine eigene Meldung das Ende, steht dort
  "Ende gemeldet am" mit dem Datum der Meldung.
- Nie gelesen oder gezeigt: Ehe, Kinder, Eltern, Wohnort, Vermoegen, Geburtsdatum. Das Skript nimmt
  aus Wikidata nur die vier Stationsarten oben.
- "aktuell" steht nur, wenn eine Meldung der letzten AKTUELL_TAGE die Rolle als aktuell beschreibt. Ein
  fehlendes Enddatum in Wikidata reicht nicht. Darum heisst es "Beginn 2013" und nie "seit 2013".
- Gegenprobe: Meldet ein Titel der letzten WANDEL_TAGE Ruecktritt, Abgang oder Nachfolge, steht oben
  "Hinweis zur Rolle" mit Link zur Meldung.
- schutz "nur_fall" (zum Beispiel Alice Huang): keine Seite, kein Wikidata-Abruf, nur ein Chip, der
  zum Fall fuehrt. "gesperrt": die Seite zeigt nur einen Hinweis.
- noindex bis INDEX_AB, danach index und Sitemap.

Einziger Schreiber aller Dateien unter personen/ (I5). Faellt Wikidata, eine Quelle oder das
Pruefmodell aus, bleibt der letzte Stand aus cache.json stehen (I8).
Kill-Switch PERSONEN_AKTIV: False schreibt nur noch personen/index.json mit "aktiv": false, damit die
Chips verschwinden. Die Seiten bleiben stehen.
Aufruf im Workflow nach den Entwuerfen: python personen_automat.py (braucht OPENROUTER_KEY fuer Beleg B).
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERSONEN_AKTIV = True           # Kill-Switch, siehe oben
INDEX_AB = "2026-12-01"         # vorher noindex (Plan F5: zwei Wochen Probezeit)
WD_ALTER_STUNDEN = 20           # Wikidata je Person hoechstens einmal am Tag
URL_PRUEF_MAX = 40              # Quellenabrufe je Lauf
URL_ZEIT_MAX = 120              # Sekunden fuer alle Quellenabrufe zusammen
URL_FEHLER_WIEDER_TAGE = 7      # nicht erreichbare Quelle erst nach einer Woche erneut
MODELL_AKTIV = True             # Beleg B ueber das Pruefmodell
MODELL_PRUEF_MAX = 40           # Modellaufrufe je Lauf
BELEG_B_WIEDER_TAGE = 7         # bestaetigte Meldung haelt eine Woche, dann neu pruefen
WANDEL_TAGE = 7
NEWS_MAX = 5
VORSCHLAG_MIN = 5               # Personen-Vorschlag ab so vielen Titeln in 7 Tagen
PRUEFER_MODELLE = ["google/gemini-3.8-flash", "anthropic/claude-haiku-5.5"]

SITE = "https://ki-news.live"
ORDNER = "personen"
UA_WD = "ki-news.live personen_automat (https://ki-news.live)"
UA_WEB = "Mozilla/5.0 (compatible; ki-news.live personen_automat; +https://ki-news.live)"

# Nur diese Eigenschaften werden aus Wikidata gelesen. Alles andere (Familie, Wohnort, Vermoegen,
# Geburtsdatum) wird nie angefasst.
STATIONEN = {"P39": "amt", "P108": "arbeit", "P69": "ausbildung"}
ORG_QUALIFIER = ("P2389", "P642", "P108")
KEINE_QUELLE = ("wikipedia.org", "wikidata.org", "wikimedia.org", "wikiwand.com", "dbpedia.org",
                "wikiquote.org", "wikisource.org")
ROLLEN = {"chief executive officer": "CEO", "chief financial officer": "CFO",
          "chief technology officer": "CTO", "chief operating officer": "COO",
          "chief scientist": "Chefwissenschaft", "chairperson": "Vorsitz", "chair": "Vorsitz",
          "président-directeur général": "CEO", "managing director": "Geschäftsführung",
          "president": "Präsidentschaft", "board member": "Aufsichtsgremium",
          "member of the board of directors": "Aufsichtsgremium"}
ART_TEXT = {"amt": "", "arbeit": "Arbeitgeber", "ausbildung": "Ausbildung", "gruendung": "Gründung"}
AKTUELL_TAGE = 60               # "aktuell" nur, wenn eine so junge Meldung die Rolle als aktuell beschreibt
WANDEL_RX = re.compile(r"Rücktritt|tritt\s+(\S+\s+){0,3}zurück|zurückgetreten|verlässt|entlassen|gefeuert|"
                       r"gestürzt|abgesetzt|Abgang|Nachfolger|übernimmt\s+(den\s+)?(CEO|Chef)|"
                       r"steps?\s+down|resign|ousted|fired")
# Meldungen mit diesen Woertern pruefen wir zuerst, sie tragen die Angabe am ehesten.
STICHWORT_RX = {
    "gruendung": re.compile(r"[Gg]ründ|[Ff]ound|[Mm]itbegründ"),
    "amt": re.compile(r"CEO|CFO|CTO|COO|[Cc]hef|[Vv]orsitz|[Pp]räsident|[Cc]hief|[Pp]resident|[Dd]irektor"),
    "ausbildung": re.compile(r"[Ss]tudi|[Aa]bsolvent|[Gg]raduat|[Aa]lumn"),
}
# Rollenwoerter, die im Zitat des Pruefmodells stehen muessen (Test 15.11.: Flash Lite bestaetigte
# "CFO" fuer Colette Kress aus einem Text, der nur "Interims-CEO" sagt).
ROLLEN_RX = {
    "CEO": re.compile(r"CEO|\bChef(in)?\b|[Kk]onzernchef|[Vv]orstandschef|[Vv]orstandsvorsitz|[Cc]hief [Ee]xecutive"),
    "CFO": re.compile(r"CFO|[Ff]inanzchef|[Ff]inanzvorst|[Cc]hief [Ff]inancial"),
    "CTO": re.compile(r"CTO|[Tt]echnikchef|[Tt]echnologiechef|[Cc]hief [Tt]echnology"),
    "COO": re.compile(r"COO|[Cc]hief [Oo]perating|[Bb]etriebschef"),
    "Vorsitz": re.compile(r"[Vv]orsitz|[Cc]hair|[Aa]ufsichtsratschef|[Vv]erwaltungsratschef"),
    "Präsidentschaft": re.compile(r"[Pp]räsident|[Pp]resident"),
    "Chefwissenschaft": re.compile(r"[Cc]hefwissenschaft|[Cc]hief [Ss]cientist"),
}
VORSCHLAG_RX = re.compile(r"(?:CEO|Chef|Chefin|Gründer|Gründerin|Mitgründer|Mitgründerin|Präsident|"
                          r"Präsidentin|Forscher|Forscherin|Managerin|Manager)\s+"
                          r"([A-Z][a-zé]+(?:[- ][A-Z][a-zé]+){1,2})\b")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue", "ß": "ss"})


def log(text):
    print(f"[PERSONEN] {text}", flush=True)


def _jetzt():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _alter_stunden(iso, jetzt):
    try:
        return (jetzt - datetime.fromisoformat(iso)).total_seconds() / 3600
    except Exception:
        return 1e9


def _json_lesen(pfad, leer):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception:
        return leer


def _schreiben_wenn_neu(pfad, text):
    """True, wenn geschrieben wurde. Unveraenderte Dateien bleiben unangetastet."""
    pfad = Path(pfad)
    try:
        if pfad.exists() and pfad.read_text(encoding="utf-8") == text:
            return False
    except Exception:
        pass
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8", newline="\n")
    return True


def _datum_de(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return iso or ""


def _domain(url):
    try:
        d = urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return ""
    return d[4:] if d.startswith("www.") else d


# ---------------------------------------------------------------------------------------------
# Meldungen und Abgleich
# ---------------------------------------------------------------------------------------------

def meldungen_laden(base):
    """Alle Meldungen aus Archiv-Monaten, archive.json und news.json, eine je Link."""
    gesehen = {}
    dateien = sorted((base / "archiv-monate").glob("*.json")) + [base / "archive.json", base / "news.json"]
    for f in dateien:
        d = _json_lesen(f, [])
        if isinstance(d, dict):
            d = d.get("news") or d.get("items") or []
        for n in d if isinstance(d, list) else []:
            if isinstance(n, dict) and n.get("link"):
                gesehen[n["link"]] = n
    return list(gesehen.values())


def _datum(n):
    return (n.get("first_seen") or n.get("date") or "")[:10]


class Abgleich:
    """Gleiche Regeln wie in assets/ki-layout.js: ausschluss entfernen, dann voller Name oder
    Nachname mit Kontext im selben Text."""

    def __init__(self, p):
        self.muster = [re.compile(x) for x in p.get("muster") or []]
        self.kurz = [re.compile(x) for x in p.get("kurz") or []]
        self.kontext = re.compile(p["kontext"]) if p.get("kontext") else None
        self.aus = [re.compile(x) for x in p.get("ausschluss") or []]

    def trifft(self, text):
        for r in self.aus:
            text = r.sub(" ", text)
        if any(r.search(text) for r in self.muster):
            return True
        if any(r.search(text) for r in self.kurz):
            return self.kontext is None or bool(self.kontext.search(text))
        return False


def treffer_sammeln(personen, meldungen):
    """Je Person: Liste (meldung, im_titel), neueste zuerst."""
    abgl = {p["id"]: Abgleich(p) for p in personen}
    out = {p["id"]: [] for p in personen}
    for n in meldungen:
        titel = n.get("title") or ""
        text = titel + " \n " + (n.get("summary") or "")
        for pid, a in abgl.items():
            if a.trifft(text):
                out[pid].append((n, a.trifft(titel)))
    for pid in out:
        out[pid].sort(key=lambda x: (x[0].get("first_seen") or x[0].get("date") or ""), reverse=True)
    return out


# ---------------------------------------------------------------------------------------------
# Wikidata
# ---------------------------------------------------------------------------------------------

def _hole_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA_WD, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _zeit(q):
    """Wikidata-Zeitwert -> (JJJJ-MM-TT, Genauigkeit) oder None."""
    try:
        v = q[0]["datavalue"]["value"]
        return [v["time"][1:11], int(v.get("precision", 9))]
    except Exception:
        return None


def _belege_aus(c):
    urls, stated, wiki = [], [], False
    for r in c.get("references") or []:
        s = r.get("snaks") or {}
        for x in s.get("P854", []):
            u = (x.get("datavalue") or {}).get("value")
            if isinstance(u, str):
                urls.append(u)
        for x in s.get("P248", []):
            sid = ((x.get("datavalue") or {}).get("value") or {}).get("id")
            if sid:
                stated.append(sid)
        if "P143" in s or "P4656" in s:
            wiki = True
    return urls, stated, wiki


def wikidata_person(qid):
    """Nur die Stationen. Rueckgabe ist bereits auf die erlaubten Eigenschaften beschnitten."""
    roh = _hole_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    e = list(roh["entities"].values())[0]
    stationen = []
    for prop, art in STATIONEN.items():
        for c in e.get("claims", {}).get(prop, []):
            if c.get("rank") == "deprecated":
                continue
            wert = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
            if not isinstance(wert, dict) or not wert.get("id"):
                continue
            q = c.get("qualifiers") or {}
            org = None
            for oq in ORG_QUALIFIER:
                for x in q.get(oq, []):
                    org = org or (((x.get("datavalue") or {}).get("value")) or {}).get("id")
            urls, stated, wiki = _belege_aus(c)
            stationen.append({"id": c.get("id"), "prop": prop, "art": art, "wert": wert["id"], "org": org,
                              "von": _zeit(q.get("P580")), "bis": _zeit(q.get("P582")),
                              "urls": urls, "stated": stated, "wiki_import": wiki})
    return {"lastrevid": e.get("lastrevid"), "modified": e.get("modified"), "stationen": stationen}


def wikidata_gruendungen(qids):
    """P112 (gegruendet von) steht am Unternehmen. Eine SPARQL-Abfrage fuer alle Personen."""
    if not qids:
        return {}
    werte = " ".join(f"wd:{q}" for q in qids)
    abfrage = ("SELECT ?p ?org ?st ?url ?stated ?n WHERE { VALUES ?p { " + werte + " } "
               "?org p:P112 ?st . ?st ps:P112 ?p . "
               "OPTIONAL { ?st prov:wasDerivedFrom ?ref . OPTIONAL { ?ref pr:P854 ?url } "
               "OPTIONAL { ?ref pr:P248 ?stated } } "
               "{ SELECT ?org (COUNT(DISTINCT ?f) AS ?n) WHERE { ?org wdt:P112 ?f } GROUP BY ?org } }")
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(abfrage)
    d = _hole_json(url, timeout=60)
    out = {}
    for b in d["results"]["bindings"]:
        p = b["p"]["value"].rsplit("/", 1)[-1]
        sid = b["st"]["value"].rsplit("/", 1)[-1]
        st = out.setdefault(p, {}).setdefault(sid, {
            "id": sid, "prop": "P112", "art": "gruendung", "wert": b["org"]["value"].rsplit("/", 1)[-1],
            "org": None, "von": None, "bis": None, "urls": [], "stated": [], "wiki_import": False,
            "gruender": int(b.get("n", {}).get("value") or 1)})
        if "url" in b and b["url"]["value"] not in st["urls"]:
            st["urls"].append(b["url"]["value"])
        if "stated" in b:
            s = b["stated"]["value"].rsplit("/", 1)[-1]
            if s not in st["stated"]:
                st["stated"].append(s)
    return {p: list(v.values()) for p, v in out.items()}


def labels_holen(qids, cache):
    fehlt = sorted({q for q in qids if q and q not in cache})
    for i in range(0, len(fehlt), 50):
        teil = fehlt[i:i + 50]
        d = _hole_json("https://www.wikidata.org/w/api.php?action=wbgetentities&props=labels|aliases"
                       "&languages=de|en&format=json&ids=" + "|".join(teil))
        for k, v in (d.get("entities") or {}).items():
            k = (v.get("redirects") or {}).get("from") or k
            l = v.get("labels") or {}
            al = [a["value"] for sp in ("en", "de") for a in (v.get("aliases") or {}).get(sp, [])]
            cache[k] = {"de": (l.get("de") or {}).get("value"), "en": (l.get("en") or {}).get("value"),
                        "aliase": [a for a in al if len(a) >= 4][:6]}


def _label(cache, q):
    e = cache.get(q) or {}
    return e.get("de") or e.get("en") or q


def _hat_label(cache, q):
    e = cache.get(q) or {}
    return bool(e.get("de") or e.get("en"))


def _name(cache, q):
    """Anzeigename einer Organisation: ohne Rechtsform und ohne Schlusspunkt."""
    return _ZUSATZ.sub("", _label(cache, q)).rstrip(".") or q


_ZUSATZ = re.compile(r",?\s+(Inc\.?|Corporation|Corp\.?|Ltd\.?|LLC|PBC|GmbH|AG|SE|plc|Co\.)$")


def _varianten(cache, q):
    e = cache.get(q) or {}
    out = []
    for v in [e.get("de"), e.get("en")] + list(e.get("aliase") or []):
        if not v:
            continue
        for w in (v, _ZUSATZ.sub("", v)):
            if len(w) >= 3 and w not in out:
                out.append(w)
    return out


def _rolle(cache, q):
    e = cache.get(q) or {}
    en = (e.get("en") or "").lower()
    return ROLLEN.get(en) or e.get("de") or e.get("en") or q


# ---------------------------------------------------------------------------------------------
# Beleg A: Quelle abrufen
# ---------------------------------------------------------------------------------------------

def _seitentext(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA_WEB, "Accept-Language": "en,de;q=0.8"})
    with urllib.request.urlopen(req, timeout=10) as r:
        roh = r.read(600_000)
        cs = r.headers.get_content_charset() or "utf-8"
    t = roh.decode(cs, "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


class Quellenpruefung:
    def __init__(self, cache, jetzt):
        self.cache = cache.setdefault("urls", {})
        self.jetzt = jetzt
        self.abrufe = 0
        self.start = time.time()

    def pruefe(self, url, nachname, orgs):
        """'ok', 'fehlt', 'fehler' oder None (heute nicht geprueft)."""
        if not url.startswith("http") or any(_domain(url).endswith(d) for d in KEINE_QUELLE):
            return "fehlt"
        key = hashlib.sha1(f"{url}|{nachname}|{'|'.join(orgs)}".encode()).hexdigest()[:16]
        alt = self.cache.get(key)
        if alt and (alt["e"] != "fehler" or _alter_stunden(alt["t"], self.jetzt) < URL_FEHLER_WIEDER_TAGE * 24):
            return alt["e"]
        if self.abrufe >= URL_PRUEF_MAX or time.time() - self.start > URL_ZEIT_MAX:
            return alt["e"] if alt else None
        self.abrufe += 1
        try:
            t = _seitentext(url)
            rx_org = _wortsuche(orgs)
            ok = bool(_wortsuche([nachname]).search(t)) and (rx_org is None or bool(rx_org.search(t)))
            e = "ok" if ok else "fehlt"
        except Exception as ex:
            e = "fehler"
            log(f"Quelle nicht erreichbar: {_domain(url)} ({type(ex).__name__} {getattr(ex, 'code', '')})")
        self.cache[key] = {"e": e, "t": _iso(self.jetzt), "u": url[:300]}
        return e


# ---------------------------------------------------------------------------------------------
# Beleg B: eigene Meldung, Pruefmodell
# ---------------------------------------------------------------------------------------------

_PRUEF_SYSTEM = ("Du pruefst, ob ein kurzer Nachrichtentext eine Angabe ueber eine Person ausdruecklich "
                 "bestaetigt. Du nutzt nur den Text, kein eigenes Wissen. Antworte nur mit JSON.")


def _anfrage(prompt, modell, key, reasoning):
    nutzlast = {"model": modell, "max_tokens": 1500, "temperature": 0, "usage": {"include": True},
                "messages": [{"role": "system", "content": _PRUEF_SYSTEM}, {"role": "user", "content": prompt}]}
    if reasoning:
        nutzlast["reasoning"] = reasoning
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(nutzlast).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://ki-news.live/", "X-Title": "KI News Personen"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


class Modellpruefung:
    def __init__(self, cache, jetzt):
        self.cache = cache.setdefault("modell", {})
        self.jetzt = jetzt
        self.key = os.environ.get("OPENROUTER_KEY", "").strip() if MODELL_AKTIV else ""
        self.aufrufe = 0
        self.kosten = 0.0
        self.aus = False

    def pruefe(self, name, angabe, n):
        """{'angabe': 'ja'|'nein', 'zitat': str, 'ende': 'ja'|'nein'|'offen'} oder None."""
        text = ((n.get("title") or "") + ". " + (n.get("summary") or ""))[:1500]
        key = hashlib.sha1(f"{name}|{angabe}|{n.get('link')}".encode()).hexdigest()[:16]
        if key in self.cache:
            return self.cache[key]["r"]
        if not self.key or self.aus or self.aufrufe >= MODELL_PRUEF_MAX:
            return None
        prompt = (f"Person: {name}\nAngabe: {angabe}\nText: {text}\n\n"
                  "Bestaetigt der Text die Angabe ausdruecklich? Eine Rolle zaehlt auch, wenn der Text sagt, "
                  "dass die Person sie gerade abgibt oder verloren hat. Eine andere Rolle bei derselben Firma "
                  "zaehlt nicht.\n"
                  'Antworte nur mit JSON: {"angabe": "ja" oder "nein", "zitat": "die woertliche Stelle aus dem '
                  'Text, die die Angabe traegt, sonst leer", "ende": "ja", "nein" oder "offen"}.\n'
                  'ende = "ja" nur, wenn der Text sagt, dass die Person diese Rolle nicht mehr hat oder abgibt. '
                  'ende = "nein", wenn der Text sie als aktuell beschreibt. Sonst "offen".')
        for modell in PRUEFER_MODELLE:
            self.aufrufe += 1
            try:
                try:
                    roh = _anfrage(prompt, modell, self.key, {"effort": "low", "exclude": True})
                except urllib.error.HTTPError as e:
                    if e.code != 400:
                        raise
                    roh = _anfrage(prompt, modell, self.key, None)
                inhalt = roh["choices"][0]["message"]["content"] or ""
                m = re.search(r"\{.*?\}", inhalt, re.S)
                r = json.loads(m.group(0)) if m else {}
                r = {"angabe": "ja" if str(r.get("angabe")).lower() == "ja" else "nein",
                     "zitat": str(r.get("zitat") or "")[:400],
                     "ende": str(r.get("ende")).lower() if str(r.get("ende")).lower() in ("ja", "nein") else "offen"}
                self.kosten += float((roh.get("usage") or {}).get("cost") or 0)
                self.cache[key] = {"r": r, "t": _iso(self.jetzt), "m": modell}
                return r
            except Exception as ex:
                log(f"Pruefmodell {modell} ausgefallen: {type(ex).__name__} {getattr(ex, 'code', '')}")
                if getattr(ex, "code", None) in (401, 402, 403):
                    self.aus = True
                    return None
        return None


# ---------------------------------------------------------------------------------------------
# Stationen belegen
# ---------------------------------------------------------------------------------------------

def _angabe_text(st, labels):
    org = _label(labels, st["org"] or st["wert"])
    if st["art"] == "amt":
        rolle = _rolle(labels, st["wert"])
        return f"hat oder hatte die Rolle {rolle}" + (f" bei {org}" if st["org"] else "")
    if st["art"] == "arbeit":
        return f"arbeitet oder arbeitete bei {org}"
    if st["art"] == "gruendung":
        return f"hat {org} gegruendet oder mitgegruendet"
    return f"hat an {org} studiert oder dort eine Ausbildung gemacht"


def _rollen_rx(labels, q):
    r = _rolle(labels, q)
    if r in ROLLEN_RX:
        return ROLLEN_RX[r]
    e = labels.get(q) or {}
    return _wortsuche([w for w in (e.get("de"), e.get("en")) if w])


_ZITAT_NORM = re.compile(r"[\s\"'„“”‚‘’]+")


def _zitat_ok(r, n, st, labels):
    """Das Zitat muss woertlich im Meldungstext stehen und das Kernwort der Angabe enthalten:
    die Rolle beim Amt, ein Wort fuer Gruenden bei der Gruendung, sonst die Organisation."""
    def norm(x):
        return _ZITAT_NORM.sub(" ", x or "").strip().lower()
    z = norm(r.get("zitat")).rstrip(".")
    text = norm((n.get("title") or "") + ". " + (n.get("summary") or ""))
    if len(z) < 8 or z not in text:
        return False
    if st["art"] == "amt":
        rx = _rollen_rx(labels, st["wert"])
    elif st["art"] == "gruendung":
        rx = STICHWORT_RX["gruendung"]
    else:
        rx = _wortsuche(_orgs(st, labels))
    return bool(rx and rx.search(r.get("zitat") or ""))


def _orgs(st, labels):
    q = st["org"] or (st["wert"] if st["art"] != "amt" else None)
    return _varianten(labels, q) if q else []


def _wortsuche(worte):
    """Ein Ausdruck fuer mehrere Woerter, Gross- und Kleinschreibung egal, nur ganze Woerter."""
    worte = [w for w in worte if w]
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in worte) + r")(?![\w])", re.I) if worte else None


def stationen_belegen(p, roh, labels, treffer, quellen, modell, cache_b, jetzt):
    """Gibt (gezeigt, weggelassen) zurueck. gezeigt: Liste fertiger Stationen."""
    nachname = p["name"].split()[-1]
    gezeigt, weg = [], 0
    texte = [(n, (n.get("title") or "") + " " + (n.get("summary") or "")) for n, _ in treffer]
    grenze_wandel = (jetzt - timedelta(days=30)).strftime("%Y-%m-%d")
    # Gruendung und Amt zuerst. Ein Arbeitgeber, zu dem schon ein Amt oder eine Gruendung steht,
    # entfaellt (Messung 15.11.: "Microsoft · CEO" und "Microsoft · Arbeitgeber" doppelt).
    roh = sorted(roh, key=lambda st: _ART_ORDNUNG[st["art"]])
    gezeigte_orgs = set()
    for st in roh:
        ziel_q = st["org"] or st["wert"]
        if not _hat_label(labels, ziel_q) or (st["art"] == "amt" and not _hat_label(labels, st["wert"])):
            weg += 1             # ohne deutschen oder englischen Namen nicht darstellbar
            continue
        if st["art"] == "arbeit" and st["wert"] in gezeigte_orgs:
            continue
        orgs = _orgs(st, labels)
        rx = _wortsuche(orgs)
        mit_org = [(n, t) for n, t in texte if rx and rx.search(t)]
        # Reihenfolge der Pruefung: juengste Meldung mit Ruecktritt oder Abgang (fuer das Ende), dann
        # Meldungen mit passendem Stichwort, dann die neuesten.
        kw = STICHWORT_RX.get(st["art"])
        kandidaten = []
        if st["art"] in ("amt", "arbeit"):
            kandidaten += [n for n, t in mit_org if _datum(n) >= grenze_wandel and WANDEL_RX.search(t)][:1]
        if kw:
            kandidaten += [n for n, t in mit_org if kw.search(t)][:2]
        kandidaten += [n for n, _ in mit_org[:2]]
        kandidaten = list({id(n): n for n in kandidaten}.values())[:3]
        beleg = None
        for u in st["urls"]:
            if quellen.pruefe(u, nachname, orgs) == "ok":
                beleg = {"art": "quelle", "url": u, "text": _domain(u)}
                break
        if not beleg:
            for sq in st["stated"]:
                l = _label(labels, sq)
                if (_hat_label(labels, sq) and "wiki" not in l.lower()
                        and sq not in ("Q2013", "Q328", "Q48183", "Q52")):
                    beleg = {"art": "datenbank", "url": None, "text": l}
                    break
        b = None
        # Beleg B (ohne Beleg A) und Abgleich des Endes (Amt und Arbeit ohne Enddatum): die zwei neuesten
        # Meldungen, die Person und Organisation nennen. Eine bestaetigte Meldung bleibt Beleg, bis eine
        # neuere das Ende meldet oder sie aelter als BELEG_B_WIEDER_TAGE ist.
        if not beleg or (st.get("bis") is None and st["art"] in ("amt", "arbeit")):
            sk = f"{p['id']}|{st['id']}"
            alt = cache_b.get(sk)
            neu = None
            for n in kandidaten:
                r = modell.pruefe(p["name"], _angabe_text(st, labels), n)
                if r and r["angabe"] == "ja" and _zitat_ok(r, n, st, labels):
                    neu = {"link": n.get("link"), "seite": n.get("seite"), "titel": n.get("title"),
                           "datum": _datum(n), "quelle": n.get("source"), "ende": r["ende"], "t": _iso(jetzt)}
                    break
            b = alt
            if neu and (not alt or (neu["ende"] == "ja" and alt.get("ende") != "ja")
                        or _alter_stunden(alt["t"], jetzt) > BELEG_B_WIEDER_TAGE * 24):
                b = cache_b[sk] = neu
            if b and not beleg:
                beleg = {"art": "meldung", "url": b.get("seite") or b.get("link"),
                         "text": f"Meldung vom {_datum_de(b['datum'])}" + (f", {b['quelle']}" if b.get("quelle") else "")}
        if not beleg:
            weg += 1
            continue
        daten = beleg["art"] in ("quelle", "datenbank")
        laeuft = st["art"] in ("amt", "arbeit")
        ende_meldung = ({"datum": b["datum"], "url": b.get("seite") or b.get("link"),
                         "neu": bool(WANDEL_RX.search(b.get("titel") or ""))}
                        if b and laeuft and b.get("ende") == "ja" else None)
        beendet = bool((st.get("bis") and daten) or ende_meldung)
        gezeigte_orgs.add(ziel_q)
        jung = (jetzt - timedelta(days=AKTUELL_TAGE)).strftime("%Y-%m-%d")
        gezeigt.append({
            "art": st["art"], "wert": st["wert"], "org": st["org"],
            "titel": _name(labels, ziel_q) if st["art"] != "amt" or st["org"] else _rolle(labels, st["wert"]),
            "rolle": _rolle(labels, st["wert"]) if st["art"] == "amt" else ART_TEXT[st["art"]],
            "gruender": st.get("gruender"),
            "von": st["von"] if daten else None, "bis": st["bis"] if daten else None,
            "ende_meldung": ende_meldung,
            # beendet: Ende mit Beleg A oder per Meldung. Ein Enddatum ohne Beleg zaehlt nicht.
            "beendet": beendet,
            # Wikidata nennt ein Ende, aber keine Quelle stuetzt es: nicht als laufend darstellen
            "ende_offen": bool(st.get("bis") and not daten and not ende_meldung),
            # aktuell: nur wenn eine junge Meldung die Rolle als aktuell beschreibt. Ein fehlendes
            # Enddatum in Wikidata reicht nicht (Messung 15.11.: alte Arbeitgeber ohne Enddatum).
            "aktuell": bool(laeuft and not beendet and st.get("bis") is None and b
                            and b.get("ende") == "nein" and b.get("datum", "") >= jung),
            "relevanz": len(mit_org),
            "beleg": beleg})
    return gezeigt, weg


def _jahr(z, jetzt):
    if not z:
        return ""
    d, prec = z
    try:
        dt = datetime.strptime(d.replace("-00", "-01"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return d[:4]
    if prec >= 11 and (jetzt - dt).days < 400:
        return dt.strftime("%d.%m.%Y")
    return d[:4]


def zeitangabe(s, jetzt, mit_link=False):
    """Kurze Zeitangabe ohne Behauptung, die kein Beleg traegt. "Beginn 2013" statt "seit 2013",
    weil ein fehlendes Enddatum nicht heisst, dass die Rolle noch laeuft."""
    teile = []
    if s["von"] or s["bis"]:
        von, bis = _jahr(s["von"], jetzt), _jahr(s["bis"], jetzt)
        teile.append(f"{von} bis {bis}" if von and bis else f"Beginn {von}" if von else f"Ende {bis}")
    if s["ende_meldung"]:
        e = s["ende_meldung"]
        d = _datum_de(e["datum"])
        if mit_link and e.get("url"):
            d = f'<a href="{html.escape(e["url"])}">{d}</a>'
        # Meldet die Meldung den Wechsel selbst, ist ihr Datum aussagekraeftig. Sonst nennt sie nur
        # eine fruehere Station (Test 15.11.: Kress bei Microsoft bis 2013, gemeldet am 12.11.2026).
        teile.append(f"Ende gemeldet am {d}" if e.get("neu", True) else f"früher, laut Meldung vom {d}")
    elif s["aktuell"]:
        teile.append("aktuell")
    elif s.get("ende_offen"):
        teile.append("beendet laut Wikidata, Zeitpunkt ohne Beleg")
    return ", ".join(teile)


_ART_ORDNUNG = {"gruendung": 0, "amt": 1, "arbeit": 2, "ausbildung": 3}


def _von_jahr(s):
    try:
        return int((s["von"] or ["0"])[0][:4])
    except ValueError:
        return 0


def _sortkey(s):
    return (_ART_ORDNUNG[s["art"]], s["beendet"], not s["aktuell"], -s["relevanz"], -_von_jahr(s))


def kopfzeile(stationen, jetzt):
    """Belegte Rollen in einer Zeile: hoechstens zwei Aemter und eine Gruendung."""
    teile = []
    aemter = sorted((s for s in stationen if s["art"] == "amt" and s["org"] and not s.get("ende_offen")),
                    key=lambda s: (s["beendet"], not s["aktuell"], -s["relevanz"], -_von_jahr(s)))
    for s in aemter[:2]:
        z = zeitangabe(s, jetzt)
        teile.append(f"{s['rolle']} bei {s['titel']}" + (f" ({z})" if z else ""))
    # Gruendung nur, wenn unsere Meldungen Person und Unternehmen zusammen nennen. Sonst stand bei
    # Elon Musk die Satirefirma Thud oben (einzige Gruendung mit Quelle, Messung 15.11.).
    gr = sorted((s for s in stationen if s["art"] == "gruendung" and s["relevanz"]), key=lambda s: -s["relevanz"])
    if gr:
        g = gr[0]
        teile.append(("Mitgründung" if (g.get("gruender") or 1) > 1 else "Gründung") + f" von {g['titel']}")
    return ("Belegte Rollen: " + ", ".join(teile)) if teile else ""


# ---------------------------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------------------------

_CSS = """
:root{--papier:#fff;--tinte:#16181b;--grau:#565c65;--linie:#dde2e8;--grund:#f0f4f8;--akzent:#0b6e88;
--serif:'Fraunces',Georgia,'Times New Roman',serif;--sans:'Work Sans',system-ui,-apple-system,sans-serif}
html.dark{--papier:#15181b;--tinte:#ecebe7;--grau:#a7acb3;--linie:#2a2e33;--grund:#0d0f11;--akzent:#55c3de}
*{box-sizing:border-box}
body{margin:0;background:var(--grund);color:var(--tinte);font:1.0625rem/1.65 var(--sans)}
a{color:var(--akzent)}
.fuss,main{max-width:46rem;margin:0 auto;padding:0 16px}
main{background:var(--papier);padding-top:28px;padding-bottom:36px;margin-top:76px;border-radius:4px}
.meta{font-size:.8125rem;color:var(--grau);text-transform:uppercase;letter-spacing:.04em}
h1{font:600 clamp(1.75rem,1.2rem + 2vw,2.5rem)/1.15 var(--serif);margin:.4rem 0 1rem;hyphens:none;overflow-wrap:break-word}
.anriss{font-size:1.1875rem;line-height:1.55;margin:0 0 1.25rem}
h2{font:600 1.3125rem var(--serif);margin:1.75rem 0 .5rem}
.wandel{border-left:3px solid var(--akzent);padding:.25rem 0 .25rem 1rem;margin:0 0 1.25rem}
.quelle{font-size:.9375rem;color:var(--grau)}
ul.weitere{list-style:none;padding:0;margin:0}
ul.weitere li{border-top:1px solid var(--linie);padding:.6rem 0}
ul.weitere a.t{color:var(--tinte);text-decoration:none;font-family:var(--serif);font-size:1.0625rem}
ul.weitere a.t:hover{color:var(--akzent)}
.zahl{font-variant-numeric:tabular-nums}
.hinweis{font-size:.8125rem;color:var(--grau);margin-top:2rem}
.fuss{display:flex;flex-wrap:wrap;gap:4px 14px;padding-top:18px;padding-bottom:32px;font-size:.8125rem;color:var(--grau)}
.fuss a{color:var(--grau)}
@media (min-width:1024px){html.kl-leiste-offen body{padding-left:240px}}
""".strip()

_THEME_JS = ("(function(){var s='auto';try{s=localStorage.getItem('ki_theme')||'auto';}catch(e){}"
             "var d=s==='dark'||(s!=='light'&&window.matchMedia&&"
             "matchMedia('(prefers-color-scheme: dark)').matches);"
             "if(d)document.documentElement.classList.add('dark');})();")
_ICONS = '<script src="/assets/ki-icons.js" defer></script>'
_KOPF = ('<script>window.KI_ROOT = "/";try{if(localStorage.getItem("ki_sidebar_open")==="1")'
         'document.documentElement.classList.add("kl-leiste-offen")}catch(e){}</script>\n'
         '<script src="/assets/ki-layout.js" defer></script>')
_FUSS = ('<footer class="fuss"><a href="/">ki-news.live</a><a href="/personen/">Personen</a>'
         '<a href="/dossiers.html">Dossiers</a><a href="/Archiv.html">Archiv</a>'
         '<a href="/Impressum.html">Impressum</a><a href="/Datenschutz.html">Datenschutz</a></footer>')


def _gerust(titel, beschreibung, pfad, index, koerper, ld=None):
    esc = html.escape
    robots = "index, follow" if index else "noindex, follow"
    teile = ["<!DOCTYPE html>", '<html lang="de">', "<head>", '<meta charset="utf-8"/>',
             '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
             f"<title>{esc(titel)} · KI News</title>",
             f'<meta name="description" content="{esc(beschreibung)}"/>',
             f'<meta name="robots" content="{robots}"/>',
             f'<link rel="canonical" href="{SITE}{pfad}"/>',
             '<link rel="icon" type="image/png" href="/s-logo.png"/>',
             '<meta property="og:type" content="profile"/>',
             f'<meta property="og:title" content="{esc(titel)}"/>',
             f'<meta property="og:description" content="{esc(beschreibung)}"/>',
             f'<meta property="og:url" content="{SITE}{pfad}"/>',
             '<meta property="og:site_name" content="KI News"/>',
             '<meta property="og:locale" content="de_DE"/>',
             '<link rel="stylesheet" href="/assets/ki-fonts.css"/>', _ICONS,
             f"<script>{_THEME_JS}</script>", f"<style>{_CSS}</style>"]
    if ld:
        teile.append('<script type="application/ld+json">' +
                     json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    teile += ["</head>", "<body>", _KOPF, "<main>"] + koerper + ["</main>", _FUSS, "</body>", "</html>", ""]
    return "\n".join(teile)


def _news_liste(eintraege):
    esc = html.escape
    li = []
    for n in eintraege:
        ziel = n.get("seite") or n.get("link") or ""
        belege = "/belege.html#link=" + urllib.parse.quote(n.get("link") or "", safe="")
        q = f" · {esc(n['source'])}" if n.get("source") else ""
        li.append(f'<li><a class="t" href="{esc(ziel)}">{esc(n.get("title") or "")}</a><br/>'
                  f'<span class="quelle">{_datum_de(_datum(n))}{q} · <a href="{esc(belege)}">Belege</a></span></li>')
    return '<ul class="weitere">' + "".join(li) + "</ul>"


def news_auswahl(treffer):
    """Neueste Meldungen, eine je Meldungsseite, Titeltreffer zuerst."""
    out, gesehen = [], set()
    for nur_titel in (True, False):
        for n, im_titel in treffer:
            if nur_titel and not im_titel:
                continue
            k = n.get("seite") or n.get("story_id") or n.get("link")
            if k in gesehen:
                continue
            gesehen.add(k)
            out.append(n)
            if len(out) >= NEWS_MAX:
                return sorted(out, key=_datum, reverse=True)
    return sorted(out, key=_datum, reverse=True)


def wandel_finden(treffer, jetzt):
    grenze = (jetzt - timedelta(days=WANDEL_TAGE)).strftime("%Y-%m-%d")
    for n, im_titel in treffer:
        if _datum(n) < grenze:
            break
        if im_titel and WANDEL_RX.search(n.get("title") or ""):
            return n
    return None


def personen_seite(p, d, index, jetzt):
    esc = html.escape
    pfad = f"/{ORDNER}/{p['id']}.html"
    st = d["stationen"]
    kopf = kopfzeile(st, jetzt)
    if not kopf:
        kopf = "Noch keine belegte Rolle. Die belegten Stationen stehen unten" if st else "Noch keine belegten Stationen"
    k = []
    k.append(f'<article><p class="meta">Person · Stand {_datum_de(d["stand"])}</p>')
    k.append(f"<h1>{esc(p['name'])}</h1>")
    k.append(f'<p class="anriss">{esc(kopf)}.</p>')
    w = d.get("wandel")
    if w:
        ziel = w.get("seite") or w.get("link") or ""
        k.append(f'<p class="wandel"><span class="meta">Hinweis zur Rolle</span><br/>'
                 f'Meldung vom {_datum_de(_datum(w))}: <a href="{esc(ziel)}">{esc((w.get("title") or "").rstrip("."))}</a>. '
                 f'Die Stationen unten können veraltet sein.</p>')
    if d["news"]:
        k.append("<h2>Warum gerade in den News</h2>")
        k.append(f'<p class="quelle zahl">{d["n7"]} Meldungen in 7 Tagen, {d["n30"]} in 30 Tagen.</p>')
        k.append(_news_liste(d["news"]))
    k.append("<h2>Stationen</h2>")
    if st:
        li = []
        for s in st:
            zeit = zeitangabe(s, jetzt, mit_link=True)
            rolle = s["rolle"]
            if s["art"] == "gruendung":
                rolle = "Mitgründung" if (s.get("gruender") or 1) > 1 else "Gründung"
            b = s["beleg"]
            blink = (f'<a href="{esc(b["url"])}" rel="noopener">{esc(b["text"])}</a>' if b.get("url")
                     else esc(b["text"]))
            kopfteil = (f"<strong>{esc(s['titel'])}</strong>" + (f" · {esc(rolle)}" if rolle and rolle != s["titel"] else ""))
            li.append(f'<li>{kopfteil}{" · " + zeit if zeit else ""}<br/>'
                      f'<span class="quelle">Beleg: {blink}</span></li>')
        k.append('<ul class="weitere">' + "".join(li) + "</ul>")
    else:
        k.append('<p class="quelle">Noch keine Station mit Beleg.</p>')
    if d["weg"]:
        k.append(f'<p class="quelle">Ohne Beleg weggelassen: {d["weg"]} Angaben aus Wikidata.</p>')
    perma = f"https://www.wikidata.org/w/index.php?title={p['qid']}&oldid={d['lastrevid']}"
    k.append("<h2>Woher die Angaben kommen</h2>")
    k.append('<p class="quelle">Die Stationen stammen aus '
             f'<a href="{esc(perma)}" rel="noopener">Wikidata</a> (frei nutzbar, CC0, Version vom '
             f'{_datum_de(d["wd_stand"] or "")}). Wir zeigen eine Angabe nur, wenn eine Quelle außerhalb der '
             'Wikipedia sie stützt oder wenn eine unserer Meldungen sie bestätigt. Diese Bestätigung prüft ein '
             'Sprachmodell am Meldungstext. Beginn und Ende stehen nur mit externer Quelle da. Familie, Wohnort, '
             'Vermögen und Geburtsdatum zeigen wir nicht. Etwas falsch? Schreiben Sie uns über das '
             '<a href="/Impressum.html">Impressum</a>.</p>')
    k.append("</article>")
    beschr = f"{p['name']}: {kopf}. Belegte Stationen und aktuelle Meldungen bei KI News."
    ld = {"@context": "https://schema.org", "@type": "ProfilePage", "inLanguage": "de",
          "mainEntity": {"@type": "Person", "name": p["name"],
                         "sameAs": [f"https://www.wikidata.org/wiki/{p['qid']}"]}}
    return _gerust(f"{p['name']}: Stationen und Meldungen", beschr[:200], pfad, index, k, ld)


def gesperrt_seite(p):
    pfad = f"/{ORDNER}/{p['id']}.html"
    k = ['<article><p class="meta">Person</p>', f"<h1>{html.escape(p['name'])}</h1>",
         '<p class="anriss">Diese Seite ist nicht mehr verfügbar.</p>',
         '<p class="quelle"><a href="/personen/">Zur Personenliste</a></p></article>']
    return _gerust(p["name"], "Diese Seite ist nicht mehr verfügbar.", pfad, False, k)


def uebersicht(daten, index, jetzt):
    esc = html.escape
    zeilen = sorted(daten, key=lambda d: (-d["n7"], -d["n30"], d["p"]["name"]))
    li = []
    for d in zeilen:
        p = d["p"]
        kopf = kopfzeile(d["stationen"], jetzt) or "Noch keine belegte Rolle"
        zuletzt = _datum_de(_datum(d["news"][0])) if d["news"] else ""
        z = f'<span class="zahl">{d["n7"]}</span> Meldungen in 7 Tagen, <span class="zahl">{d["n30"]}</span> in 30 Tagen'
        z += f", zuletzt am {zuletzt}" if zuletzt else ""
        w = " · neue Meldung zur Rolle" if d.get("wandel") else ""
        li.append(f'<li><a class="t" href="/{ORDNER}/{p["id"]}.html">{esc(p["name"])}</a><br/>'
                  f'<span class="quelle">{esc(kopf)}{w}</span><br/><span class="quelle">{z}</span></li>')
    k = ['<article><p class="meta">Personen</p>', "<h1>Wer gerade in den KI-News steht</h1>",
         '<p class="anriss">Kurze Lebensläufe der Personen, die in unseren Meldungen oft vorkommen. '
         'Jede Station hat einen Beleg. Sortiert nach Meldungen der letzten sieben Tage.</p>',
         '<ul class="weitere">' + "".join(li) + "</ul>",
         '<p class="hinweis">Die Liste pflegt die Redaktion von Hand. Aufgenommen werden Personen aus der '
         'Branche, die in ihrer Rolle öffentlich auftreten. Privatleute bekommen keine eigene Seite.</p>',
         "</article>"]
    return _gerust("Personen in den KI-News", "Kurze, belegte Lebensläufe der Personen, die in den KI-News "
                   "gerade oft vorkommen.", f"/{ORDNER}/", index, k)


def sitemap(pfade, jetzt):
    tag = jetzt.strftime("%Y-%m-%d")
    urls = "".join(f"<url><loc>{SITE}{p}</loc><lastmod>{tag}</lastmod></url>" for p in pfade)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')


# ---------------------------------------------------------------------------------------------
# Vorschlaege
# ---------------------------------------------------------------------------------------------

def vorschlaege(personen, meldungen, jetzt):
    grenze = (jetzt - timedelta(days=7)).strftime("%Y-%m-%d")
    abgl = [Abgleich(p) for p in personen]
    zahl = {}
    for n in meldungen:
        if _datum(n) < grenze:
            continue
        for m in VORSCHLAG_RX.finditer(n.get("title") or ""):
            name = m.group(1)
            if any(a.trifft(name) for a in abgl):
                continue
            zahl[name] = zahl.get(name, 0) + 1
    return sorted(((k, v) for k, v in zahl.items() if v >= VORSCHLAG_MIN), key=lambda x: -x[1])


# ---------------------------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------------------------

def _chip_eintrag(p, pfad=None):
    e = {"id": p["id"], "name": p["name"], "muster": p.get("muster") or [], "kurz": p.get("kurz") or [],
         "kontext": p.get("kontext") or "", "ausschluss": p.get("ausschluss") or []}
    if pfad:
        e["pfad"] = pfad
    else:
        e["fall"] = True
    return e


def erzeuge(base, jetzt=None):
    base = Path(base)
    jetzt = jetzt or _jetzt()
    ziel = base / ORDNER
    liste = _json_lesen(base / "personen.json", {})
    personen = [p for p in liste.get("personen") or [] if p.get("id") and p.get("name")]
    if not PERSONEN_AKTIV:
        _schreiben_wenn_neu(ziel / "index.json", json.dumps({"aktiv": False, "personen": []}) + "\n")
        log("Kill-Switch PERSONEN_AKTIV aus, nur index.json geschrieben")
        return
    index = jetzt.strftime("%Y-%m-%d") >= INDEX_AB
    cache = _json_lesen(ziel / "cache.json", {})
    wd = cache.setdefault("wikidata", {})
    labels = cache.setdefault("labels", {})
    cache_b = cache.setdefault("beleg_b", {})

    meldungen = meldungen_laden(base)
    treffer = treffer_sammeln(personen, meldungen)
    log(f"{len(meldungen)} Meldungen, {len(personen)} Personen in der Liste")

    seiten = [p for p in personen if p.get("schutz") == "oeffentlich" and p.get("qid")]
    # Wikidata: je Person hoechstens einmal am Tag, bei Ausfall bleibt der alte Stand
    faellig = [p for p in seiten if _alter_stunden((wd.get(p["qid"]) or {}).get("geholt", ""), jetzt) >= WD_ALTER_STUNDEN]
    for p in faellig:
        try:
            neu = wikidata_person(p["qid"])
            alt = wd.get(p["qid"]) or {}
            neu["gruendung"] = alt.get("gruendung", [])
            neu["geholt"] = _iso(jetzt)
            wd[p["qid"]] = neu
        except Exception as ex:
            log(f"Wikidata {p['qid']} ausgefallen: {type(ex).__name__} {getattr(ex, 'code', '')}")
    if faellig:
        try:
            gr = wikidata_gruendungen([p["qid"] for p in faellig])
            for p in faellig:
                if p["qid"] in wd:
                    wd[p["qid"]]["gruendung"] = gr.get(p["qid"], [])
        except Exception as ex:
            log(f"Wikidata-Abfrage Gruendungen ausgefallen: {type(ex).__name__} {getattr(ex, 'code', '')}")
        # Bezeichnungen einmal am Tag neu holen, damit Umbenennungen ankommen
        cache["labels"] = labels = {}
    alle_q = set()
    for e in wd.values():
        for s in e.get("stationen", []) + e.get("gruendung", []):
            alle_q.update(x for x in [s["wert"], s.get("org")] + s.get("stated", []) if x)
    try:
        labels_holen(alle_q, labels)
    except Exception as ex:
        log(f"Wikidata-Bezeichnungen ausgefallen: {type(ex).__name__}")

    quellen = Quellenpruefung(cache, jetzt)
    modell = Modellpruefung(cache, jetzt)
    if not modell.key:
        log("kein OPENROUTER_KEY oder MODELL_AKTIV aus: Beleg B nur aus dem Cache")
    h7 = (jetzt - timedelta(days=7)).strftime("%Y-%m-%d")
    h30 = (jetzt - timedelta(days=30)).strftime("%Y-%m-%d")

    daten, chips, pfade, geschrieben = [], [], [], 0
    for p in personen:
        schutz = p.get("schutz") or "oeffentlich"
        frei = bool(p.get("freigabe"))
        if schutz == "nur_fall":
            if frei:
                chips.append(_chip_eintrag(p))
            continue
        if schutz == "gesperrt":
            geschrieben += _schreiben_wenn_neu(ziel / f"{p['id']}.html", gesperrt_seite(p))
            continue
        e = wd.get(p.get("qid") or "")
        if not e:
            log(f"{p['name']}: noch keine Wikidata-Daten, Seite folgt im naechsten Lauf")
            continue
        t = treffer[p["id"]]
        roh = e.get("stationen", []) + e.get("gruendung", [])
        st, weg = stationen_belegen(p, roh, labels, t, quellen, modell, cache_b, jetzt)
        st.sort(key=_sortkey)
        d = {"p": p, "stationen": st, "weg": weg, "lastrevid": e.get("lastrevid"),
             "wd_stand": (e.get("modified") or "")[:10], "news": news_auswahl(t),
             "n7": sum(_datum(n) >= h7 for n, _ in t), "n30": sum(_datum(n) >= h30 for n, _ in t),
             "wandel": wandel_finden(t, jetzt)}
        neueste = max([_datum(n) for n in d["news"]] + [d["wd_stand"]])
        d["stand"] = neueste
        log(f"{p['name']}: {len(st)} Stationen belegt, {weg} weggelassen, {d['n7']} Meldungen in 7 Tagen"
            + (", Hinweis zur Rolle" if d["wandel"] else ""))
        if frei:
            text = personen_seite(p, d, index, jetzt)
            geschrieben += _schreiben_wenn_neu(ziel / f"{p['id']}.html", text)
            daten.append(d)
            chips.append(_chip_eintrag(p, f"/{ORDNER}/{p['id']}.html"))
            pfade.append(f"/{ORDNER}/{p['id']}.html")
        else:
            geschrieben += _schreiben_wenn_neu(ziel / "entwurf" / f"{p['id']}.html",
                                               personen_seite(p, d, False, jetzt))

    geschrieben += _schreiben_wenn_neu(ziel / "index.html", uebersicht(daten, index, jetzt))
    geschrieben += _schreiben_wenn_neu(ziel / "index.json", json.dumps(
        {"aktiv": True, "personen": chips}, ensure_ascii=False, separators=(",", ":")) + "\n")
    if index:
        geschrieben += _schreiben_wenn_neu(ziel / "sitemap.xml", sitemap([f"/{ORDNER}/"] + pfade, jetzt))

    vs = vorschlaege(personen, meldungen, jetzt)
    for name, n in vs[:10]:
        log(f"Personen-Vorschlag: {name} ({n} Titel in 7 Tagen, nicht in personen.json)")
    cache["vorschlaege"] = [{"name": k, "titel_7_tage": v} for k, v in vs[:20]]
    cache["stand"] = _iso(jetzt)
    geschrieben += _schreiben_wenn_neu(ziel / "cache.json",
                                       json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    log(f"fertig: {geschrieben} Dateien geschrieben, {quellen.abrufe} Quellen abgerufen, "
        f"{modell.aufrufe} Modellaufrufe ({modell.kosten:.4f} $), index={'ja' if index else 'nein'}")


if __name__ == "__main__":
    erzeuge(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
