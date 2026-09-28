#!/usr/bin/env python3
"""Pruefliste zu den Entwuerfen (28.09.26, Gate fuer Auftrag 5).

Schreibt je Entwurf eine Seite artikel/entwurf/pruefliste-<id>.html (noindex,
nicht verlinkt): jede Aussage und jede Zahl, die im Entwurf steht, mit dem
Quellen-Link, gegen den Daniel sie pruefen kann.

Was automatisch geprueft wird (nur Hinweis, ersetzt die Pruefung nicht):
- Release-Zitate: steht der Satz woertlich im Text der offiziellen Seite?
- Zahlen in Pipeline-Texten (Zusammenfassungen, Titel): steht dieselbe Zahl im
  Quell-Titel? Die Zusammenfassung ist von der Pipeline formuliert, darum muss
  sie gegen den Artikel selbst geprueft werden.

Aufruf: python3 tools/pruefliste.py [--dossiers 3] [--releases 3] [--ohne-netz]
"""
import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import dossier_automat as da  # noqa: E402
import release_automat as ra  # noqa: E402
import hersteller_feed as hf  # noqa: E402

ZIEL = BASE / "artikel" / "entwurf"
ZAHL = re.compile(r"\d+(?:[.,]\d+)*")


def _e(s):
    return html.escape(re.sub(r"\s+", " ", str(s or "")).strip().replace("—", "-").replace("–", "-"), quote=True)


def zahlen(text):
    return [z for z in ZAHL.findall(text or "") if not re.fullmatch(r"0|1", z)]


def _norm(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip().lower()


def zeile(nr, art, aussage, links, hinweis="", ohne_link="kein Link"):
    zs = zahlen(aussage)
    link_html = "<br>".join(f'<a href="{_e(l)}" target="_blank" rel="noopener noreferrer">{_e(t)} ↗</a>'
                         for t, l in links if l) or (f'<span class="warn">{ohne_link}</span>' if ohne_link == "kein Link" else _e(ohne_link))
    return (f'<tr><td class="nr">{nr}</td><td class="art">{_e(art)}</td><td>{_e(aussage)}'
            + (f'<div class="z">Zahlen: {", ".join(_e(z) for z in zs)}</div>' if zs else "")
            + f'</td><td>{link_html}</td><td class="hw">{hinweis}</td>'
            '<td class="ok"><label><input type="checkbox"> geprüft</label></td></tr>')


def seite(titel, entwurf_datei, zeilen, hinweis):
    stand = datetime.now().strftime("%d.%m.%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Prüfliste: {_e(titel)}</title>
<style>
:root{{--bg:#fff;--fg:#14171a;--mut:#5b6670;--line:#dfe3e7;--acc:#0a7ea4;--warn:#b54708;--okbg:#e8f6ee}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1419;--fg:#e7e9ea;--mut:#8b98a5;--line:#2f3336;--acc:#1d9bf0;--warn:#f79009;--okbg:#10291c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1200px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 6px}} p{{margin:0 0 12px;color:var(--mut)}}
a{{color:var(--acc);overflow-wrap:anywhere}}
table{{width:100%;border-collapse:collapse}} td,th{{border-top:1px solid var(--line);padding:8px 6px;vertical-align:top;text-align:left}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}}
.nr{{color:var(--mut);width:28px}} .art{{font-size:12px;color:var(--mut);width:130px}} .hw{{font-size:13px;width:190px}}
.z{{font:12px ui-monospace,monospace;color:var(--mut);margin-top:4px}} .warn{{color:var(--warn)}} .gut{{color:#12805c}}
tr:has(input:checked){{background:var(--okbg)}}
@media(max-width:760px){{table,tbody,tr,td{{display:block}} thead{{display:none}} tr{{border-top:1px solid var(--line);padding:8px 0}} td{{border:0;padding:3px 0;width:auto!important}}}}
</style></head><body><main>
<h1>Prüfliste: {_e(titel)}</h1>
<p>Entwurf: <a href="{_e(entwurf_datei)}">{_e(entwurf_datei)}</a> · erstellt {stand} · Automatische Zusammenstellung, nicht veröffentlicht.</p>
<p>{hinweis}</p>
<table><thead><tr><th>#</th><th>Art</th><th>Aussage im Entwurf</th><th>Quelle</th><th>Automatischer Hinweis</th><th></th></tr></thead>
<tbody>
{chr(10).join(zeilen)}
</tbody></table>
</main></body></html>
"""


def zahl_hinweis(text, vergleich):
    zs = zahlen(text)
    if not zs:
        return ""
    fehlt = [z for z in zs if z not in (vergleich or "")]
    if not fehlt:
        return '<span class="gut">Zahlen stehen auch im Quell-Titel</span>'
    return f'<span class="warn">nicht im Quell-Titel: {", ".join(_e(z) for z in fehlt)} (im Artikel prüfen)</span>'


def dossier_liste(lid, d):
    z, nr = [], 0

    def add(*a):
        nonlocal nr
        nr += 1
        z.append(zeile(nr, *a))

    alle = [(q["quelle"] or "Quelle", q["link"]) for e in d["ereignisse"] for q in e["quellen"][:1]]
    add("Titel (Pipeline)", d["titel"], alle[:3], "Oberbegriff der Pipeline, muss von allen Meldungen gedeckt sein")
    if d["worum"]:
        add("Worum es geht (Pipeline)", d["worum"], alle[:3], "hat die Deckungsprüfung der Pipeline passiert")
    add("Einleitung (gezählt)", da.einleitung(d), [], '<span class="gut">aus Zählwerten gebaut, kein Sprachmodell</span>',
        "berechnet aus den Zeilen unten")
    for e in d["ereignisse"]:
        haupt = [(q["quelle"] or "Quelle", q["link"]) for q in e["quellen"] if q["link"]]
        titel_quelle = " ".join(q["titel"] for q in e["quellen"])
        add(f"Meldung {da._datum_kurz(e['datum'])}: Titel", e["titel"], haupt[:1],
            "Titel wie im Feed" + ("" if not zahlen(e["titel"]) else " · " + zahl_hinweis(e["titel"], titel_quelle)))
        if e["zusammenfassung"]:
            add(f"Meldung {da._datum_kurz(e['datum'])}: Zusammenfassung", e["zusammenfassung"], haupt[:4],
                "von der Pipeline formuliert, gegen den Artikel prüfen"
                + ("" if not zahlen(e["zusammenfassung"]) else "<br>" + zahl_hinweis(e["zusammenfassung"], titel_quelle)))
    return z


def release_liste(b, seite_text):
    r = b["r"]
    z, nr = [], 0
    # gleiche Absatz-Aufbereitung wie der Automat, sonst trennen entfernte Link-Tags die Saetze
    norm_seite = _norm(" ".join(ra.absaetze(seite_text))) if seite_text else ""

    def add(*a):
        nonlocal nr
        nr += 1
        z.append(zeile(nr, *a))

    offiziell = [(f"Ankündigung {r['hersteller']}", r["url"])]
    add("Eckdaten", f"Hersteller: {r['hersteller']} · Modell: {r['modell']} · Angekündigt: {da._datum_lang(r['datum'])}",
        offiziell, "aus hersteller.json (Feed des Herstellers), Datum auf der Seite prüfen")
    for art, liste in (("Zitat", b["zitate"]), ("Zahlen-Satz", b["zahlen"])):
        for s in liste:
            if not norm_seite:
                hw = '<span class="warn">Seite nicht gelesen, Text aus dem Feed</span>'
            elif _norm(s)[:120] in norm_seite:
                hw = '<span class="gut">wörtlich auf der Seite gefunden</span>'
            else:
                hw = '<span class="warn">nicht wörtlich gefunden, prüfen</span>'
            add(art, s, offiziell, hw)
            if s in b["de"]:
                add(f"{art} (Übersetzung)", b["de"][s], offiziell, "maschinell übersetzt, Zahlen gegen Original geprüft")
    for a in b["berichte"]:
        q = [(a.get("source") or "Quelle", a.get("link"))]
        add("Bericht: Titel", a.get("title"), q, "Titel wie im Feed")
        if a.get("summary"):
            add("Bericht: Zusammenfassung", a["summary"], q,
                "von der Pipeline formuliert, gegen den Artikel prüfen"
                + ("" if not zahlen(a["summary"]) else "<br>" + zahl_hinweis(a["summary"], a.get("title"))))
    return z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dossiers", type=int, default=3)
    ap.add_argument("--releases", type=int, default=3)
    ap.add_argument("--ohne-netz", action="store_true", help="offizielle Seiten nicht laden")
    a = ap.parse_args()

    news = da._lade("news.json", {})
    archiv = da._lade("archive.json", [])
    linien = news.get("linien") or {}
    karten = da.KartenIndex(da._lade("cards.json", []))
    nach_link, nach_story = {}, {}
    for art in list(archiv) + list(news.get("news") or []):
        if isinstance(art, dict) and art.get("link"):
            nach_link[art["link"]] = art
    for art in nach_link.values():
        k = da.story_schluessel(art)
        if k:
            nach_story.setdefault(k, []).append(art)
    ids = [lid for lid, l in linien.items()
           if len(l.get("e") or []) >= da.MIN_EREIGNISSE and (l.get("dossier") or {}).get("titel")]
    ids.sort(key=lambda lid: -len(linien[lid]["e"]))
    for lid in ids[: a.dossiers]:
        d = da.baue_linie(lid, linien[lid], nach_link, nach_story, karten)
        zeilen = dossier_liste(lid, d)
        ziel = ZIEL / f"pruefliste-linie-{lid}.html"
        ziel.write_text(seite(d["titel"], f"linie-{lid}.html", zeilen,
                              "Jede Zeile ist eine Aussage aus dem Dossier-Entwurf. Titel und Zusammenfassungen stammen "
                              "aus der Pipeline, Zählwerte sind berechnet."), encoding="utf-8")
        print(f"  {ziel.relative_to(BASE)}  {len(zeilen)} Aussagen")

    releases = json.loads((BASE / "hersteller.json").read_text(encoding="utf-8")).get("releases") or []
    for r in releases[: a.releases]:
        seite_text = ""
        if not a.ohne_netz:
            try:
                seite_text = hf._get(r["url"], timeout=25)
            except Exception:
                seite_text = ""
        b = ra.baue_release(r, news.get("news") or [], archiv, None)
        if not b["gelesen"]:
            seite_text = ""
        s = ra.slug(r["modell"]) + "-was-es-kann"
        zeilen = release_liste(b, seite_text)
        ziel = ZIEL / f"pruefliste-release-{s}.html"
        ziel.write_text(seite(f"{r['modell']}: was es kann", f"release-{s}.html", zeilen,
                              "Zitate und Zahlen-Sätze sind wörtlich von der offiziellen Seite übernommen; "
                              "Berichte kommen aus dem KI-News-Feed."), encoding="utf-8")
        print(f"  {ziel.relative_to(BASE)}  {len(zeilen)} Aussagen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
