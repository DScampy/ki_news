#!/usr/bin/env python3
"""Deckungspruefung der Einordnungen (28.09.26, Trockenlauf).

Anlass: Teaser "der ehemalige US-Praesident Trump" - falsch, Trump ist amtierend.
Das Skript prueft Titel und Zusammenfassung (die "Einordnung" der Pipeline) jeder
Meldung gegen den Quelltext des Artikels und gegen eine kleine, gepflegte Liste
von Aemtern. Es aendert nichts: weder news.json noch ki_news.py. Ergebnis ist
eine Trefferliste zum Nachpruefen.

Pruefungen je Meldung:
  AMT      Person aus AEMTER mit falschem Zusatz (z.B. "ehemalig" bei amtierend).
           Gilt auch ohne Quelltext, weil die Liste selbst die Referenz ist.
  ZUSATZ   "ehemalig/frueher/designiert/kuenftig/scheidend..." steht in der
           Einordnung, aber keine Entsprechung im Quelltext.
  ZAHL     Zahl in der Einordnung, die im Quelltext nicht vorkommt.
  DATUM    Wochentag oder Monatsname, der im Quelltext nicht vorkommt.
  PERSON   Rolle + Name (z.B. "CEO Dario Amodei"): Name oder Rolle fehlt im Quelltext.

Quelltext: full_text aus news.json, sonst die Verlagsseite (link_verlag, dann
link; Google-News-Weiterleitungen werden nicht aufgeloest). Unter 600 Zeichen
gilt ein Quelltext als nicht verfuegbar (Paywall, Blockade).

Aufruf: python3 tools/deckungspruefung.py [--n 50] [--ohne-netz] [--aus DATEI]
Ausgabe: _vorschau/deckung/treffer.html und treffer.json (nicht fuer main).
"""
import argparse
import html
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AUS = BASE / "_vorschau" / "deckung"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MIN_QUELLTEXT = 600

# Gepflegte Aemterliste. Stand 28.09.2026. Nur Aemter, bei denen der Stand sicher
# ist; bei Wechseln hier nachtragen. status: "amtierend" oder "ehemalig".
AEMTER = [
    {"name": "Donald Trump", "muster": r"(?:Donald\s+)?Trump", "amt": "US-Präsident", "status": "amtierend", "seit": "20.01.2025"},
    {"name": "JD Vance", "muster": r"(?:JD|J\.\s?D\.)\s+Vance|Vance", "amt": "US-Vizepräsident", "status": "amtierend", "seit": "20.01.2025"},
    {"name": "Joe Biden", "muster": r"(?:Joe\s+)?Biden", "amt": "US-Präsident", "status": "ehemalig", "bis": "20.01.2025"},
    {"name": "Kamala Harris", "muster": r"(?:Kamala\s+)?Harris", "amt": "US-Vizepräsidentin", "status": "ehemalig", "bis": "20.01.2025"},
    {"name": "Friedrich Merz", "muster": r"(?:Friedrich\s+)?Merz", "amt": "Bundeskanzler", "status": "amtierend", "seit": "06.05.2025"},
    {"name": "Olaf Scholz", "muster": r"(?:Olaf\s+)?Scholz", "amt": "Bundeskanzler", "status": "ehemalig", "bis": "06.05.2025"},
    {"name": "Ursula von der Leyen", "muster": r"(?:Ursula\s+)?von der Leyen", "amt": "EU-Kommissionspräsidentin", "status": "amtierend", "seit": "2019"},
    {"name": "Xi Jinping", "muster": r"Xi(?:\s+Jinping)?\b", "amt": "Staatspräsident Chinas", "status": "amtierend", "seit": "2013"},
    {"name": "Sam Altman", "muster": r"(?:Sam\s+)?Altman", "amt": "CEO von OpenAI", "status": "amtierend", "seit": "2019"},
    {"name": "Dario Amodei", "muster": r"(?:Dario\s+)?Amodei", "amt": "CEO von Anthropic", "status": "amtierend", "seit": "2021"},
    {"name": "Sundar Pichai", "muster": r"(?:Sundar\s+)?Pichai", "amt": "CEO von Google/Alphabet", "status": "amtierend", "seit": "2015"},
    {"name": "Satya Nadella", "muster": r"(?:Satya\s+)?Nadella", "amt": "CEO von Microsoft", "status": "amtierend", "seit": "2014"},
    {"name": "Jensen Huang", "muster": r"(?:Jensen\s+)?Huang", "amt": "CEO von Nvidia", "status": "amtierend", "seit": "1993"},
]

# Zusaetze, die eine Zeitform/Rolle behaupten -> Entsprechungen im Quelltext
ZUSAETZE = {
    r"ehemalig\w*|früher\w*|einstig\w*|Ex-\w+|Alt-\w+": r"former|ex-|previous|previously|once|ehemalig|früher|einstig|erstwhile|past",
    r"designiert\w*|gewählt\w*|künftig\w*|angehend\w*": r"designate|elect\b|incoming|future|nominee|nominated|designiert|gewählt|künftig",
    r"scheidend\w*|bisherig\w*|abgesetzt\w*|zurückgetreten\w*": r"outgoing|departing|resign|stepp(?:ed|ing) down|ousted|fired|scheidend|zurückgetreten",
    r"amtierend\w*|derzeitig\w*|aktuell\w* (?:US-)?Präsident\w*": r"current|sitting|incumbent|amtierend|derzeitig",
}
FALSCH_BEI_AMTIEREND = r"ehemalig\w*|früher\w*|einstig\w*|Ex-|Alt-|designiert\w*|(?:neu\s+)?gewählt\w*|künftig\w*|scheidend\w*|abgewählt\w*"
FALSCH_BEI_EHEMALIG = r"amtierend\w*|derzeitig\w*|aktuell\w*|scheidend\w*"

ROLLEN = {
    r"CEO|Chef\w*|Geschäftsführer\w*|Vorstandschef\w*|Konzernchef\w*": r"ceo|chief executive|chef|head|boss|leader|geschäftsführer|vorstand",
    r"Gründer\w*|Mitgründer\w*|Co-Gründer\w*": r"founder|co-founder|cofounder|gründer",
    r"Präsident\w*|Vizepräsident\w*": r"president|präsident",
    r"Minister\w*|Ministerin": r"minister|secretary",
    r"Kanzler\w*": r"chancellor|kanzler",
    r"Forscher\w*|Wissenschaftler\w*": r"research|scientist|forscher|wissenschaftler|professor",
}
ROLLE_NAME = re.compile(r"\b(" + "|".join(ROLLEN) + r")\s+(?:(?:des|der|von|bei)\s+[\w.-]+\s+)?"
                        r"((?:[A-ZÄÖÜ][\w'-]+)(?:\s+[A-ZÄÖÜ][\w'-]+){1,2})")

WOCHENTAGE = {"Montag": "monday", "Dienstag": "tuesday", "Mittwoch": "wednesday", "Donnerstag": "thursday",
              "Freitag": "friday", "Samstag": "saturday", "Sonntag": "sunday"}
MONATE = {"Januar": "january|jan", "Februar": "february|feb", "März": "march|mar", "April": "april|apr",
          "Mai": "may", "Juni": "june|jun", "Juli": "july|jul", "August": "august|aug", "September": "september|sep",
          "Oktober": "october|oct", "November": "november|nov", "Dezember": "december|dec"}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000).decode("utf-8", errors="replace")


def text_aus_html(seite):
    s = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", seite)
    teile = []
    for m in re.finditer(r'(?is)<meta[^>]+(?:property|name)=["\'](?:og:title|og:description|description)["\'][^>]+content=["\']([^"\']+)', s):
        teile.append(m.group(1))
    m = re.search(r"(?is)<title>(.*?)</title>", s)
    if m:
        teile.append(m.group(1))
    teile += re.findall(r"(?is)<(?:p|h1|h2|li|figcaption)[^>]*>(.*?)</(?:p|h1|h2|li|figcaption)>", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", " ".join(teile)))
    return re.sub(r"\s+", " ", t).strip()


def quelltext(meldung, netz):
    ft = meldung.get("full_text")
    if isinstance(ft, str) and len(ft) >= MIN_QUELLTEXT:
        return ft, "full_text"
    if not netz:
        return "", "ohne Netz"
    for url in (meldung.get("link_verlag"), meldung.get("link")):
        if not url or "news.google.com" in url:
            continue
        try:
            t = text_aus_html(_get(url))
        except Exception as e:
            return "", f"Abruf fehlgeschlagen ({type(e).__name__})"
        if len(t) >= MIN_QUELLTEXT:
            return t, url
        return "", "Quelltext zu kurz (Paywall/Blockade?)"
    return "", "nur Google-News-Link"


def _zahl_varianten(z):
    roh = z.replace(" ", "")
    v = {roh, roh.replace(",", "."), roh.replace(".", ","), roh.replace(".", "")}
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", roh):  # 1.000 -> 1,000 / 1000
        v |= {roh.replace(".", ","), roh.replace(".", "")}
    return v


def _zahlen(text):
    out = []
    for m in re.finditer(r"(?<![\w.-])\d+(?:[.,]\d+)*(?![\w-])", text):
        z = m.group(0).rstrip(".,")
        if len(z) == 1:  # einstellige Zahlen sind fast immer Aufzaehlung/Artikel
            continue
        out.append(z)
    return out


def _saetze(text):
    return re.split(r"(?<=[.!?])\s+", text)


def pruefe(meldung, quelle):
    einordnung = " ".join(x for x in (meldung.get("title"), meldung.get("summary")) if x)
    q = (quelle or "").lower()
    treffer = []

    # AMT: gegen die Liste, unabhaengig vom Quelltext
    for amt in AEMTER:
        for satz in _saetze(einordnung):
            for m in re.finditer(amt["muster"], satz):
                vorher = satz[max(0, m.start() - 70): m.start()]
                falsch = FALSCH_BEI_AMTIEREND if amt["status"] == "amtierend" else FALSCH_BEI_EHEMALIG
                # Zusatz muss direkt vor dem Namen stehen (hoechstens 2 Woerter dazwischen),
                # sonst springt "der ehemalige Praesident Trump trifft Amodei" auf Amodei ueber
                f = re.search(r"(?i)(?:^|\W)(" + falsch + r")\s+(?:[\w.-]+\s+){0,2}$", vorher)
                if f:
                    quelle_auch = ""
                    if q:
                        entspr = next((v for k, v in ZUSAETZE.items() if re.fullmatch(k, f.group(1), re.I)), None)
                        # nur direkt am Namen (z.B. "president-elect Donald Trump", "former President Trump")
                        nahe = " ".join(q[max(0, m2.start() - 40): m2.end() + 12]
                                        for m2 in re.finditer(amt["muster"], q, re.I))
                        if entspr and re.search(entspr, nahe):
                            quelle_auch = " Der Quelltext enthaelt denselben Zusatz: Quelle evtl. alt, Datum pruefen."
                    treffer.append({"art": "AMT", "stelle": satz.strip(),
                                    "befund": f'"{f.group(1)}" vor {amt["name"]}, laut Liste {amt["status"]} '
                                              f'({amt["amt"]}, {"seit " + amt["seit"] if amt.get("seit") else "bis " + amt.get("bis", "")}).'
                                              + quelle_auch})
                elif amt["status"] == "ehemalig" and re.search(r"(?i)(Präsident|Kanzler|Vizepräsident)\w*\s+(?:\w+\s+)?$", vorher) \
                        and not re.search(r"(?i)ehemalig|früher|einstig|Ex-|Alt-", vorher):
                    treffer.append({"art": "AMT", "stelle": satz.strip(),
                                    "befund": f'{amt["name"]} mit Amtstitel ohne "ehemalig", laut Liste {amt["amt"]} bis {amt.get("bis")}'})

    if not q:
        return treffer

    # ZUSATZ
    for muster, entspr in ZUSAETZE.items():
        for m in re.finditer(r"(?<![\w-])(" + muster + r")", einordnung):
            if not re.search(entspr, q):
                satz = next((s for s in _saetze(einordnung) if m.group(1) in s), einordnung)
                treffer.append({"art": "ZUSATZ", "stelle": satz.strip(),
                                "befund": f'"{m.group(1)}" ohne Entsprechung im Quelltext'})

    # ZAHL
    gemeldet = set()
    for z in _zahlen(einordnung):
        if z in gemeldet:
            continue
        if not any(v in q for v in _zahl_varianten(z)):
            gemeldet.add(z)
            satz = next((s for s in _saetze(einordnung) if z in s), einordnung)
            treffer.append({"art": "ZAHL", "stelle": satz.strip(), "befund": f"{z} nicht im Quelltext"})

    # DATUM
    for de, en in list(WOCHENTAGE.items()) + list(MONATE.items()):
        if re.search(r"\b" + de + r"\b", einordnung) and not re.search(r"\b(?:" + en + r"|" + de.lower() + r")\b", q):
            satz = next((s for s in _saetze(einordnung) if de in s), einordnung)
            treffer.append({"art": "DATUM", "stelle": satz.strip(), "befund": f'"{de}" nicht im Quelltext'})

    # PERSON: Rolle + Name
    for m in ROLLE_NAME.finditer(einordnung):
        rolle, name = m.group(1), m.group(2)
        nachname = name.split()[-1].lower()
        if nachname not in q:
            treffer.append({"art": "PERSON", "stelle": m.group(0), "befund": f"{name} nicht im Quelltext"})
            continue
        entspr = next((v for k, v in ROLLEN.items() if re.fullmatch(k, rolle)), None)
        if entspr and not re.search(entspr, q):
            treffer.append({"art": "PERSON", "stelle": m.group(0), "befund": f'Rolle "{rolle}" ohne Entsprechung im Quelltext'})
    return treffer


def lade_meldungen(n, datei):
    if datei:
        daten = json.loads(Path(datei).read_text(encoding="utf-8"))
        liste = daten.get("news") if isinstance(daten, dict) else daten
    else:
        liste = json.loads((BASE / "news.json").read_text(encoding="utf-8")).get("news") or []
    # Dubletten bleiben drin: ihre Zusammenfassungen sind in Dossiers und Quellenlisten sichtbar
    liste = [a for a in liste if isinstance(a, dict) and a.get("link")]
    liste.sort(key=lambda a: (str(a.get("first_seen") or a.get("date") or ""), float(a.get("score") or 0)), reverse=True)
    return liste[:n]


def bericht_html(ergebnis, stand, n):
    e = lambda s: html.escape(str(s or ""), quote=True)
    zeilen = []
    for r in ergebnis:
        if not r["treffer"]:
            continue
        for t in r["treffer"]:
            zeilen.append(f'<tr class="a-{t["art"].lower()}"><td><b>{t["art"]}</b></td><td>{e(t["befund"])}<div class="st">{e(t["stelle"])}</div></td>'
                          f'<td><a href="{e(r["link"])}" target="_blank" rel="noopener noreferrer">{e(r["quelle"])} ↗</a>'
                          f'<div class="st">{e(r["datum"])} · Quelltext: {e(r["quelltext"])}</div></td></tr>')
    ohne = [r for r in ergebnis if not r["quelltext_ok"]]
    return f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Deckungsprüfung</title><style>
:root{{--bg:#fff;--fg:#14171a;--mut:#5b6670;--line:#dfe3e7;--acc:#0a7ea4;--amt:#fde8e8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1419;--fg:#e7e9ea;--mut:#8b98a5;--line:#2f3336;--acc:#1d9bf0;--amt:#3a1616}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}} main{{max-width:1100px;margin:0 auto;padding:24px 16px}}
a{{color:var(--acc);overflow-wrap:anywhere}} table{{width:100%;border-collapse:collapse}} td,th{{border-top:1px solid var(--line);padding:8px 6px;vertical-align:top;text-align:left}}
.st{{font-size:13px;color:var(--mut);margin-top:3px}} tr.a-amt{{background:var(--amt)}} p{{color:var(--mut)}}
@media(max-width:760px){{table,tbody,tr,td{{display:block}} thead{{display:none}} tr{{border-top:1px solid var(--line);padding:8px 0}} td{{border:0;padding:2px 0}}}}
</style></head><body><main>
<h1>Deckungsprüfung (Trockenlauf)</h1>
<p>{stand} · {n} Meldungen geprüft · {len(zeilen)} Treffer · {len(ohne)} ohne Quelltext (dort nur die Ämter-Prüfung).
Nichts wurde geändert. Treffer sind Hinweise, keine Urteile: Zahlen können im Quelltext anders geschrieben stehen.</p>
<table><thead><tr><th>Art</th><th>Befund / Stelle in der Einordnung</th><th>Quelle</th></tr></thead><tbody>
{chr(10).join(zeilen)}
</tbody></table></main></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--ohne-netz", action="store_true")
    ap.add_argument("--aus", help="andere news.json/archive.json")
    a = ap.parse_args()
    meldungen = lade_meldungen(a.n, a.aus)
    with ThreadPoolExecutor(max_workers=8) as ex:
        quellen = list(ex.map(lambda m: quelltext(m, not a.ohne_netz), meldungen))
    ergebnis = []
    for m, (q, herkunft) in zip(meldungen, quellen):
        ergebnis.append({"titel": m.get("title"), "link": m.get("link"), "quelle": m.get("source"),
                         "datum": m.get("first_seen") or m.get("date"), "quelltext": herkunft if q else herkunft,
                         "quelltext_ok": bool(q), "treffer": pruefe(m, q)})
    AUS.mkdir(parents=True, exist_ok=True)
    stand = datetime.now().strftime("%d.%m.%Y %H:%M")
    (AUS / "treffer.json").write_text(json.dumps({"stand": stand, "ergebnis": ergebnis}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (AUS / "treffer.html").write_text(bericht_html(ergebnis, stand, len(meldungen)), encoding="utf-8")
    zaehl = {}
    for r in ergebnis:
        for t in r["treffer"]:
            zaehl[t["art"]] = zaehl.get(t["art"], 0) + 1
    print(f"deckungspruefung: {len(meldungen)} Meldungen, {sum(r['quelltext_ok'] for r in ergebnis)} mit Quelltext, "
          f"Treffer: {zaehl or 'keine'}")
    for r in ergebnis:
        for t in r["treffer"]:
            print(f"  [{t['art']}] {t['befund']}  <- {r['quelle']}: {(r['titel'] or '')[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
