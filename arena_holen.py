#!/usr/bin/env python3
"""LMArena-Ranglisten fuer die Modelle-Seite (30.09.26, Daniel: "Benchmarks, frei verfuegbar").

Quelle: Datensatz lmarena-ai/leaderboard-dataset auf Hugging Face, Split "latest",
Kategorie "overall", Lizenz CC BY 4.0 (Namensnennung: LMArena). Abgerufen ueber die
oeffentliche datasets-server-API (kein Schluessel). Gemessen 30.09.: ~3 s je Rangliste.

Ordnet die Arena-Namen ("claude-opus-4-6-high") den Modellen der Registry
("Claude Opus 4.6") zu und schreibt registry/arena.json. registry/ wird im Workflow
bereits committet. Fail-open: bei jedem Fehler bleibt die alte Datei stehen, Exit 0.

Aufruf: python3 arena_holen.py
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASIS = Path(__file__).resolve().parent
REGISTRY = BASIS / "registry" / "registry.json"
ZIEL = BASIS / "registry" / "arena.json"
API = "https://datasets-server.huggingface.co/rows"
DATENSATZ = "lmarena-ai/leaderboard-dataset"
# Arena-Konfiguration -> Anzeigename. text_style_control ist die Standard-Rangliste von lmarena.ai.
KATEGORIEN = {
    "text_style_control": "Text",
    "webdev": "Webdev",
    "vision": "Vision",
    "text_to_image": "Bild",
    "text_to_video": "Video",
    "agent": "Agenten",
}
MAX_SEKUNDEN = 90
_ZUSATZ = r"(?:high|max|low|medium|xhigh|thinking|preview|exp|experimental|latest|chat|instruct|beta\d*|\d+k)"


def normalisiere(name):
    """'claude-opus-4-6-high' und 'Claude Opus 4.6' -> 'claudeopus4.6'."""
    s = (name or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"(?<=\d)-(?=\d)", ".", s)                      # 4-6 -> 4.6
    s = re.sub(r"[-_ ]\d{8}\b|[-_ ]\d{4}-\d{2}-\d{2}\b", " ", s)  # Datumsstempel
    for _ in range(3):                                          # Zusaetze am Ende, auch mehrere
        s = re.sub(r"[-_ ]+" + _ZUSATZ + r"\s*$", "", s.strip())
    return re.sub(r"[^a-z0-9.]+", "", s)


def hole(url):
    letzter = None
    for versuch in range(3):
        try:
            anfrage = urllib.request.Request(url, headers={"User-Agent": "ki-news.live arena_holen"})
            with urllib.request.urlopen(anfrage, timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            letzter = e
            time.sleep(2 + versuch * 2)
    raise letzter


def rangliste(konfig, start):
    """Alle Zeilen der Kategorie 'overall' aus dem Split 'latest' (liegen vorne)."""
    zeilen, versatz = [], 0
    while versatz < 5000 and time.time() - start < MAX_SEKUNDEN:
        q = urllib.parse.urlencode({"dataset": DATENSATZ, "config": konfig, "split": "latest",
                                    "offset": versatz, "length": 100})
        daten = hole(API + "?" + q)
        seite = [z["row"] for z in daten.get("rows", [])]
        overall = [z for z in seite if z.get("category") == "overall"]
        zeilen += overall
        if (zeilen and not overall) or not seite:
            break
        versatz += 100
        if versatz >= daten.get("num_rows_total", 0):
            break
    return zeilen


def main():
    start = time.time()
    try:
        modelle = json.loads(REGISTRY.read_text(encoding="utf-8"))["modelle"]
    except Exception as e:  # noqa: BLE001
        print(f"arena_holen: registry.json nicht lesbar ({e}) - nichts geschrieben")
        return 0
    schluessel = {}
    for m in modelle:
        for kandidat in (m.get("n"), (m.get("s") or "").split("/")[-1]):
            k = normalisiere(kandidat)
            if k:
                schluessel.setdefault(k, set()).add(m["s"])

    ergebnis, kategorien, datum = {}, {}, ""
    for konfig, titel in KATEGORIEN.items():
        if time.time() - start > MAX_SEKUNDEN:
            print(f"arena_holen: Zeitbudget erreicht, {konfig} uebersprungen")
            break
        try:
            zeilen = rangliste(konfig, start)
        except Exception as e:  # noqa: BLE001
            print(f"arena_holen: {konfig} fehlgeschlagen ({e.__class__.__name__}) - uebersprungen")
            continue
        if not zeilen:
            continue
        datum = max(datum, max(str(z.get("leaderboard_publish_date") or "") for z in zeilen))
        treffer = 0
        for z in sorted(zeilen, key=lambda z: -(z.get("rating") or 0)):   # beste Variante gewinnt
            for slug in schluessel.get(normalisiere(z.get("model_name")), ()):
                eintrag = ergebnis.setdefault(slug, {})
                if titel in eintrag:
                    continue
                eintrag[titel] = {"rang": int(z.get("rank") or 0), "wert": round(float(z.get("rating") or 0)),
                                  "stimmen": int(z.get("vote_count") or 0), "arena": z.get("model_name")}
                treffer += 1
        kategorien[titel] = {"konfig": konfig, "modelle": len(zeilen), "zugeordnet": treffer}
        print(f"arena_holen: {titel}: {len(zeilen)} Arena-Modelle, {treffer} Registry-Modelle zugeordnet")

    if not ergebnis:
        print("arena_holen: keine Zuordnung - alte arena.json bleibt")
        return 0
    ZIEL.write_text(json.dumps({
        "_hinweis": "GENERIERT von arena_holen.py - nicht manuell editieren.",
        "quelle": "LMArena, Datensatz lmarena-ai/leaderboard-dataset (Hugging Face), Lizenz CC BY 4.0",
        "stand_arena": datum,
        "abgerufen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "kategorien": kategorien,
        "modelle": ergebnis,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"arena_holen: {len(ergebnis)} Modelle mit Arena-Werten, {time.time() - start:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
