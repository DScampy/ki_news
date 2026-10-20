#!/usr/bin/env python3
"""Pruefbericht fuer "Die 5 des Tages" (21.10.26, Daniel: "messen statt Standbilder anschauen").

Laeuft im Workflow direkt nach die5_video.py. Prueft, was sich messen laesst:
  1. Vorlage (Playwright, gleiche Seite wie die Aufnahme): je Meldung mitten im Abschnitt
     - Bildquelle (Meldungsbild / Kartenmotiv / eigenes Motiv) und ob das Bild wirklich geladen ist
     - Textblock im freien Platz (nicht in der Bedienzone unten 150 px / rechts 48 px)
     - Zusammenfassung per Notbremse ausgeblendet?
     - Schrift Inter geladen, keine Fehler in der Konsole
     dazu je Meldung ein Beleg-Bild out/die5-pruef-N.jpg
  2. MP4 (ffprobe): 1080 x 1920, Tonspur da, Laenge passt zur Tonspur
  3. Sync: Sprechpausen in der MP3 (silencedetect) gegen die Startzeiten im JSON
  4. Bildfehler: schwarze Strecken (blackdetect) und ob das Video je Meldung wirklich wechselt
     (Graustufen-Bild mitten in jeder Meldung gegen das der naechsten; freezedetect taugt hier
     nicht, der langsame Bild-Zoom aendert von Bild zu Bild zu wenig)
  5. --online: Feed parst, MP3-Adresse antwortet 200 und Groesse = length im Feed

Ausgabe: out/pruefung.json, out/pruefung.txt (eine Zeile, geht in die Telegram-Beschriftung),
pro Befund eine ::warning:: im Log. Exit immer 0: ein Befund ist eine Warnung, kein Abbruch.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SYNC_GRENZE = 0.25      # s, Abweichung Startzeit JSON gegen Ende der Sprechpause
BEDIEN_UNTEN, BEDIEN_RECHTS, BREITE, HOEHE = 150, 48, 420, 747

DOM_JS = r"""
const { chromium } = require('playwright');
const [,, html, ausDir] = process.argv;
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox', '--disable-web-security'] });
  const ctx = await b.newContext({ viewport: { width: %(B)d, height: %(H)d }, deviceScaleFactor: 1 });
  const p = await ctx.newPage(); const fehler = [];
  p.on('console', m => { if (m.type() === 'error') fehler.push(m.text().slice(0, 160)); });
  p.on('pageerror', e => fehler.push(String(e).slice(0, 160)));
  await p.goto('file://' + html.replace(/\\/g, '/') + '?rec=1', { waitUntil: 'networkidle', timeout: 60000 });
  await p.evaluate(() => document.fonts.ready);
  const schrift = await p.evaluate(() => document.fonts.check("800 25px Inter"));
  const n = await p.evaluate(() => (window.DIE5_SEGS || []).filter(s => s.art === 'meldung').length);
  const meldungen = [];
  for (let i = 0; i < n; i++) {
    const r = await p.evaluate(i => {
      const s = window.DIE5_SEGS.filter(s => s.art === 'meldung')[i];
      const t = s.start + 0.6 * (s.ende - s.start); window.KI_RENDER_AT(t);
      const box = s.el.getBoundingClientRect();
      let quelle = 'keins', geladen = false, sicht = 0;
      if (s.bildEl) { quelle = s.bild_art || 'meldung'; geladen = s.img.complete && s.img.naturalWidth > 0; sicht = +s.bildEl.style.opacity; }
      else if (s.motiv) { quelle = 'motiv'; geladen = true; sicht = +s.motiv.style.opacity; }
      return { nr: s.nr, t: +t.toFixed(2), quelle, geladen, sicht: +sicht.toFixed(2),
               block: { oben: Math.round(box.top), unten: Math.round(box.bottom), rechts: Math.round(box.right) },
               block_sicht: +(+s.el.style.opacity).toFixed(2),
               zf_weg: !!(s.zf && s.zf.style.display === 'none'), zf_da: !!s.zf };
    }, i);
    await p.screenshot({ path: ausDir + '/die5-pruef-' + r.nr + '.jpg', type: 'jpeg', quality: 80 });
    meldungen.push(r);
  }
  console.log(JSON.stringify({ schrift, fehler, meldungen }));
  await b.close();
})().catch(e => { console.log(JSON.stringify({ absturz: String(e).slice(0, 300) })); process.exit(0); });
""" % {"B": BREITE, "H": HOEHE}


def _lauf(cmd, timeout=180, eingabe=None):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, input=eingabe)


def dom_pruefen(html: Path, out: Path):
    r = _lauf(["node", "-", str(html.resolve()), str(out.resolve())], timeout=300, eingabe=DOM_JS)
    zeile = next((z for z in reversed(r.stdout.splitlines()) if z.startswith("{")), "")
    return json.loads(zeile) if zeile else {"absturz": (r.stderr or "keine Ausgabe")[-300:]}


def mp4_pruefen(mp4: Path):
    r = _lauf(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
               "-of", "json", str(mp4)])
    d = json.loads(r.stdout or "{}")
    video = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"breite": video.get("width"), "hoehe": video.get("height"),
            "ton": any(s.get("codec_type") == "audio" for s in d.get("streams", [])),
            "dauer": round(float(d.get("format", {}).get("duration", 0)), 2)}


def pausen_enden(mp3: Path):
    r = _lauf(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp3), "-af",
               "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"])
    return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]


def bildfehler(mp4: Path, zeiten):
    r = _lauf(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-vf",
               "blackdetect=d=0.5:pix_th=0.02:pic_th=0.995", "-an", "-f", "null", "-"], timeout=300)
    bilder = []
    for t in zeiten:
        g = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1",
                            "-s", "64x114", "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True, timeout=60)
        bilder.append(g.stdout)
    unterschied = [round(sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a)), 1)
                   for a, b in zip(bilder, bilder[1:]) if a and b]
    return {"schwarz": len(re.findall(r"black_start:", r.stderr)), "wechsel": unterschied}


def feed_pruefen(feed: Path):
    try:
        item = ET.parse(feed).getroot().find("channel/item")
        enc = item.find("enclosure")
        url, laenge = enc.get("url"), int(enc.get("length"))
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.status, "groesse_ok": int(r.headers.get("Content-Length", -1)) == laenge,
                    "url": url}
    except Exception as e:
        return {"fehler": str(e)[:200]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--online", action="store_true", help="Feed und MP3-Adresse pruefen")
    ap.add_argument("--feed", default="morgenlage.xml")
    a = ap.parse_args(argv)
    out = Path(a.out)
    ablauf = sorted(out.glob("morgenlage-????-??-??.json"))
    if not ablauf:
        print("pruefen: kein morgenlage-*.json - nichts zu pruefen.")
        return 0
    ablauf = ablauf[-1]
    datum = ablauf.stem.split("-", 1)[1]
    daten = json.loads(ablauf.read_text(encoding="utf-8"))
    mp3, mp4, html = ablauf.with_suffix(".mp3"), out / f"die5-{datum}.mp4", out / f"die5-{datum}.html"
    befunde, bericht = [], {"datum": datum}

    # 1. Vorlage
    dom = dom_pruefen(html, out) if html.exists() else {"absturz": "HTML fehlt"}
    bericht["vorlage"] = dom
    meld = dom.get("meldungen") or []
    if dom.get("absturz"):
        befunde.append("Vorlagen-Pruefung abgestuerzt: " + dom["absturz"][:120])
    if dom.get("schrift") is False:
        befunde.append("Schrift Inter nicht geladen")
    for f in dom.get("fehler") or []:
        befunde.append("Konsole: " + f)
    for m in meld:
        if not m["geladen"]:
            befunde.append(f"Meldung {m['nr']}: Bild ({m['quelle']}) nicht geladen")
        if m["block"]["unten"] > HOEHE - BEDIEN_UNTEN + 2 or m["block"]["rechts"] > BREITE - BEDIEN_RECHTS + 2:
            befunde.append(f"Meldung {m['nr']}: Text ragt in die Bedienzone ({m['block']})")
        if m["block"]["oben"] < 90:
            befunde.append(f"Meldung {m['nr']}: Text reicht bis unter die Kopfzeile ({m['block']['oben']} px)")
        elif m["quelle"] != "keins" and m["block"]["oben"] < 240:
            # Bild/Motiv geht bis 400 px, eingeplant ist Text ab 300 px
            befunde.append(f"Meldung {m['nr']}: Text überdeckt das Bild stark (ab {m['block']['oben']} px)")
        if m["zf_weg"]:
            befunde.append(f"Meldung {m['nr']}: Zusammenfassung zu lang, ausgeblendet")
        if m["block_sicht"] < 0.95:
            befunde.append(f"Meldung {m['nr']}: Text mitten im Abschnitt nicht voll sichtbar ({m['block_sicht']})")
    quellen = {}
    for m in meld:
        quellen[m["quelle"]] = quellen.get(m["quelle"], 0) + 1

    # 2. MP4
    if mp4.exists():
        v = mp4_pruefen(mp4)
        bericht["mp4"] = v
        if (v["breite"], v["hoehe"]) != (1080, 1920):
            befunde.append(f"MP4 hat {v['breite']}x{v['hoehe']}")
        if not v["ton"]:
            befunde.append("MP4 ohne Tonspur")
        if abs(v["dauer"] - daten["dauer"]) > 2.0:
            befunde.append(f"MP4 {v['dauer']} s, Ton {daten['dauer']} s")
        bf = bildfehler(mp4, [m["t"] for m in meld])
        bericht["bildfehler"] = bf
        if bf["schwarz"]:
            befunde.append(f"{bf['schwarz']} schwarze Strecke(n)")
        for i, u in enumerate(bf["wechsel"]):
            if u < 3:   # mittlere Abweichung je Bildpunkt (0-255); echte Wechsel liegen weit darueber
                befunde.append(f"Video wechselt zwischen Meldung {i + 1} und {i + 2} kaum ({u})")
    else:
        befunde.append("MP4 fehlt")

    # 3. Sync
    enden = pausen_enden(mp3) if mp3.exists() else []
    abw = []
    for s in daten["segmente"][1:]:
        if enden:
            abw.append(round(min((abs(s["start"] - e) for e in enden)), 3))
    sync_max = max(abw) if abw else None
    bericht["sync"] = {"abweichungen": abw, "max": sync_max}
    if sync_max is None:
        befunde.append("Sync nicht messbar (keine Sprechpausen gefunden)")
    elif sync_max > SYNC_GRENZE:
        befunde.append(f"Sync: Abweichung bis {sync_max:.2f} s")

    # 5. Feed online
    if a.online:
        fd = feed_pruefen(Path(a.feed))
        bericht["feed"] = fd
        if fd.get("fehler") or fd.get("status") != 200 or not fd.get("groesse_ok"):
            befunde.append(f"Feed/MP3 online nicht in Ordnung: {fd}")

    bericht["befunde"] = befunde
    teile = [f"Bilder {sum(m['geladen'] for m in meld)}/{len(meld)}"
             + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(quellen.items())) + ")" if quellen else "")]
    if sync_max is not None:
        teile.append(f"Sync max. {sync_max:.2f} s")
    teile.append("ok" if not befunde else f"{len(befunde)} Befund(e)")
    zeile = "Prüfung: " + " · ".join(teile)
    (out / "pruefung.json").write_text(json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "pruefung.txt").write_text(zeile + "\n", encoding="utf-8")
    print(zeile)
    for b in befunde:
        print(f"::warning::die5-Pruefung: {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
