#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layout_check.py: Prüft die öffentlichen Seiten im echten Browser.
site_check.py liest nur den Quelltext. Die Fehler vom 03.11.26 (Inhalt unter der Seitenleiste,
Links nur in einer Leiste, Entwicklertexte, leere Zukunftstage) waren dort alle grün.

  1. Obere Leiste und Seitenleiste sind da, haben dieselben Links und sehen auf jeder Seite gleich aus
  2. Die offene Seitenleiste verdeckt keinen Text, beim Laden und nach dem Klick, und fährt beim Laden nicht
     ein. Unter der oberen Leiste liegen nach dem Laden weder Text noch Kästen. Das geschlossene Menü
     wirft am Handy keinen Schatten
  3. Die Seite läuft nicht seitlich aus dem Fenster, kein Text wird ohne Auslassungszeichen abgeschnitten,
     keine Überschrift bricht mitten im Wort
  4. Die obere Leiste passt von 1024 bis 1440 px, ohne dass sich etwas überlappt
  5. Im sichtbaren Text stehen keine Entwicklertexte
  6. Wochen-Rückblick: keine abgeschnittenen Video-Labels, keine Tage in der Zukunft, keine Karten mit der
     grauen Standardfarbe als Akzent

Aufruf:   python tools/layout_check.py
Braucht:  pip install playwright && python -m playwright install chromium
Exit-Code 0 = alles ok, 1 = Fehler gefunden.
"""
import datetime, functools, http.server, os, re, sys, threading

from playwright.sync_api import sync_playwright

import seiten

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
errors = []
leisten_bild = {}

ENTWICKLERTEXT = re.compile(
    r"\b[\w-]+\.json\b|lokale[nrs]? (Daten|Datei|Volltext)|relative[nr]? (Pfad|lokale)|"
    r"Entity-Registry|Video-Card|Keine belastbare Zuordnung", re.I)
# Bekannt und noch offen (Stand 03.11.26). Wer eine dieser Seiten bereinigt, nimmt sie hier heraus.
ENTWICKLERTEXT_OFFEN = {"belege.html", "dossiers.html", "landkarte.html", "modelle.html", "stats.html", "suche.html"}

# Sichtbarer Text, der links von der offenen Leiste beginnt. Die Leisten selbst zählen nicht.
VERDECKT_JS = r"""() => {
  const leiste = document.getElementById('sidebar');
  const rechts = leiste ? leiste.getBoundingClientRect().right : 0;
  if (rechts < 100) return { rechts, treffer: [] };
  const treffer = [];
  const lauf = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (lauf.nextNode()) {
    const knoten = lauf.currentNode;
    if (!knoten.nodeValue.trim()) continue;
    const el = knoten.parentElement;
    if (!el || el.closest('#sidebar,#kl-nav,#sidebar-toggle,#sidebar-backdrop,#kl-ov,script,style,noscript')) continue;
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const bereich = document.createRange();
    bereich.selectNodeContents(knoten);
    const r = bereich.getBoundingClientRect();
    if (r.width && r.height && r.right > 0 && r.bottom > 0 && r.left < rechts - 1) {
      treffer.push(Math.round(rechts - r.left) + ' px: ' + knoten.nodeValue.trim().slice(0, 40));
    }
  }
  return { rechts, treffer };
}"""

# Sichtbarer Text und Kästen hinter der festen oberen Leiste, gemessen direkt nach dem Laden.
UNTER_NAV_JS = r"""() => {
  const nav = document.getElementById('kl-nav');
  if (!nav) return [];
  const unten = nav.getBoundingClientRect().bottom;
  const treffer = [];
  const lauf = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (lauf.nextNode()) {
    const knoten = lauf.currentNode;
    if (!knoten.nodeValue.trim()) continue;
    const el = knoten.parentElement;
    if (!el || el.closest('#kl-nav,#sidebar,#sidebar-toggle,#sidebar-backdrop,#kl-ov,script,style,noscript')) continue;
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const bereich = document.createRange();
    bereich.selectNodeContents(knoten);
    const r = bereich.getBoundingClientRect();
    if (r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < unten - 1) {
      treffer.push(Math.round(unten - r.top) + ' px: ' + knoten.nodeValue.trim().slice(0, 40));
    }
  }
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('#kl-nav,#sidebar,#sidebar-toggle,#sidebar-backdrop,#kl-ov')) continue;
    const st = getComputedStyle(el);
    if (st.position === 'fixed' || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const r = el.getBoundingClientRect();
    if (r.top >= unten - 1 || r.bottom <= unten || r.top < -40 || r.width < 40) continue;
    const rand = parseFloat(st.borderTopWidth) > 0 && !st.borderTopColor.endsWith(', 0)');
    const flaeche = !st.backgroundColor.endsWith(', 0)') && parseFloat(st.borderTopLeftRadius) > 0;
    if (rand || flaeche) treffer.push(Math.round(unten - r.top) + ' px: Kasten ' + String(el.className).slice(0, 30));
  }
  return treffer;
}"""

# Merkmale, die sich von Seite zu Seite nicht unterscheiden dürfen. Sie wandern sonst über die Stile der
# jeweiligen Seite in die Leisten, zum Beispiel über eine andere Zeilenhöhe oder a{text-decoration}.
LEISTEN_BILD_JS = r"""() => {
  const q = s => document.querySelector(s);
  const stil = (s, p) => { const e = q(s); return e ? getComputedStyle(e)[p] : null; };
  const seiten = q('#sidebar');
  return {
    'Höhe Menüzeile': q('#sidebar .sidebar-nav-link') ? Math.round(q('#sidebar .sidebar-nav-link').getBoundingClientRect().height) : null,
    'Höhe Seitenleiste': seiten ? seiten.scrollHeight : null,
    'Höhe obere Leiste': q('#kl-nav') ? Math.round(q('#kl-nav').getBoundingClientRect().height) : null,
    'Schrift oben': stil('#kl-toplinks a', 'fontSize'),
    'Unterstrich Marke': stil('#brand-link', 'textDecorationLine'),
    'Unterstrich Link oben': stil('#kl-toplinks a', 'textDecorationLine'),
    'Unterstrich Menüzeile': stil('#sidebar .sidebar-nav-link', 'textDecorationLine')
  };
}"""

SCHATTEN_JS = "() => { const s = document.getElementById('sidebar'); return s ? getComputedStyle(s).boxShadow : 'none'; }"

UEBERLAUF_JS = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"

# Text, der ohne Auslassungszeichen abgeschnitten wird. Screenreader-Text ist 1 px breit und zählt nicht.
GESCHNITTEN_JS = r"""() => {
  const treffer = [];
  const lauf = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (lauf.nextNode()) {
    const e = lauf.currentNode;
    if (e.closest('#sidebar,#kl-nav,#sidebar-toggle,#sidebar-backdrop,#kl-ov,script,style,noscript')) continue;
    if (e.clientWidth <= 1 || e.scrollWidth <= e.clientWidth + 1) continue;
    if (![...e.childNodes].some(k => k.nodeType === 3 && k.nodeValue.trim())) continue;
    if (!e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const c = getComputedStyle(e);
    if (c.overflowX !== 'hidden' && c.overflowX !== 'clip') continue;
    const blockig = ['block', 'inline-block', 'list-item', 'table-cell'].includes(c.display);
    if (c.textOverflow === 'ellipsis' && blockig && c.whiteSpace === 'nowrap') continue;
    treffer.push(e.scrollWidth + ' statt ' + e.clientWidth + ' px: ' + e.textContent.trim().slice(0, 40));
  }
  return treffer;
}"""

# Überschriften: Ein Wort bis 22 Zeichen muss in die Spalte passen. Längere dürfen umbrechen, sonst
# hinge das Ergebnis an einzelnen Wortungetümen in den Tagesdaten. Trennung ist dabei aus, weil der
# Browser im Test das Trennwörterbuch nicht immer hat.
WORTBRUCH_JS = r"""() => {
  const stil = document.createElement('style');
  stil.textContent = '*{hyphens:manual !important}';
  document.head.appendChild(stil);
  const treffer = [];
  for (const kopf of document.querySelectorAll('h1,h2,h3,h4,[class*="title"],[class*="label"]')) {
    if (kopf.closest('#sidebar,#kl-nav,#sidebar-backdrop,#kl-ov')) continue;
    if (!kopf.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const lauf = document.createTreeWalker(kopf, NodeFilter.SHOW_TEXT);
    while (lauf.nextNode()) {
      const knoten = lauf.currentNode;
      for (const m of knoten.nodeValue.matchAll(/[^\s\-/]+/g)) {
        if (m[0].length > 22) continue;
        const bereich = document.createRange();
        bereich.setStart(knoten, m.index);
        bereich.setEnd(knoten, m.index + m[0].length);
        const zeilen = new Set([...bereich.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top)));
        if (zeilen.size > 1) treffer.push(m[0]);
      }
    }
  }
  stil.remove();
  return treffer;
}"""

LEISTEN_JS = r"""() => {
  const sichtbar = a => getComputedStyle(a).display !== 'none';
  const ziel = a => a.getAttribute('href');
  const nav = document.getElementById('kl-nav');
  return {
    nav: !!nav && nav.getBoundingClientRect().height > 0,
    oben: [...document.querySelectorAll('#kl-toplinks a')].filter(sichtbar).map(ziel),
    seite: [...document.querySelectorAll('#sidebar .sidebar-nav-link')].map(ziel)
  };
}"""

PLATZ_JS = r"""() => {
  const rect = s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect() : null; };
  const marke = rect('#brand-link'), mitte = rect('#kl-toplinks'), rechts = rect('#kl-nav .kl-right');
  return { markeEnde: marke && marke.right, mitteStart: mitte && mitte.left, mitteEnde: mitte && mitte.right,
           rechtsStart: rechts && rechts.left, rechtsEnde: rechts && rechts.right, breite: innerWidth };
}"""

NAVIGATION = re.findall(r"\{ key: '[^']+',\s*label: '[^']+',\s*href: '([^']+)'",
                        open("assets/ki-layout.js", encoding="utf-8").read())

WOCHE_JS = r"""() => ({
  abgeschnitten: [...document.querySelectorAll('.px-video-label,.px-video-duration')]
    .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
  tage: [...document.querySelectorAll('.px-day')].map(e => e.id.replace('px-day-', '')),
  ohneVideoFigur: [...document.querySelectorAll('.px-video-figure')].filter(e => !e.querySelector('img,video')).length,
  grau: [...document.querySelectorAll('.px-focus-lead,.px-side-story,.px-story-card')]
    .filter(e => e.style.getPropertyValue('--px-story-color') === '#555555').length
})"""


class Leise(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Testserver(http.server.ThreadingHTTPServer):
    # Der Browser bricht beim Schließen einer Seite laufende Übertragungen ab. Das ist kein Fehler der Website.
    def handle_error(self, request, client_address):
        pass


def pruefe_verdeckt(page, seite, wann):
    erg = page.evaluate(VERDECKT_JS)
    if erg["treffer"]:
        errors.append("%s: %d Texte unter der Leiste (%s), z.B. %s"
                      % (seite, len(erg["treffer"]), wann, erg["treffer"][0]))


def pruefe_unter_nav(page, seite, wann):
    treffer = page.evaluate(UNTER_NAV_JS)
    if treffer:
        errors.append("%s: %d Texte hinter der oberen Leiste (%s), z.B. %s" % (seite, len(treffer), wann, treffer[0]))


def pruefe_ueberlauf(page, seite, wann):
    mehr = page.evaluate(UEBERLAUF_JS)
    if mehr > 1:
        errors.append("%s: läuft %d px seitlich aus dem Fenster (%s)" % (seite, mehr, wann))


def pruefe_text(page, seite, wann):
    geschnitten = page.evaluate(GESCHNITTEN_JS)
    if geschnitten:
        errors.append("%s: %d Texte abgeschnitten (%s), z.B. %s" % (seite, len(geschnitten), wann, geschnitten[0]))
    gebrochen = page.evaluate(WORTBRUCH_JS)
    if gebrochen:
        errors.append("%s: Überschrift bricht mitten im Wort (%s): %s" % (seite, wann, ", ".join(gebrochen[:4])))


def laden(browser, adresse, breite, offen):
    ctx = browser.new_context(viewport={"width": breite, "height": 900})
    ctx.add_init_script("try{localStorage.setItem('ki_sidebar_open','%s')}catch(e){}" % ("1" if offen else "0"))
    ctx.add_init_script("addEventListener('transitionrun',e=>{if(e.target.id==='sidebar')window.__leisteFaehrt=1},true)")
    # Nur eigene Dateien plus Chart.js (ohne das Skript haben die Diagramme auf stats.html die falsche
    # Breite): Analyse, Schriften und Videos von außen sollen das Ergebnis nicht beeinflussen.
    ctx.route(lambda url: not url.startswith(adresse) and "cdnjs.cloudflare.com" not in url,
              lambda route: route.abort())
    return ctx


def leisten_vergleichen():
    # Maßstab ist der häufigste Wert, damit eine einzelne Ausreißer-Seite als solche auffällt.
    for merkmal in next(iter(leisten_bild.values())):
        werte = {seite: bild[merkmal] for seite, bild in leisten_bild.items()}
        alle = list(werte.values())
        ueblich = max(set(alle), key=lambda wert: (alle.count(wert), str(wert)))
        for seite, wert in werte.items():
            if wert != ueblich:
                errors.append("%s: %s ist %s, auf den anderen Seiten %s" % (seite, merkmal, wert, ueblich))


def seite_pruefen(browser, adresse, seite):
    # Offen laden: Hier steht <main> beim Start des Layout-Skripts oft noch nicht im DOM.
    for breite in (1440, 1200, 1024):
        ctx = laden(browser, adresse, breite, True)
        page = ctx.new_page()
        page.goto(adresse + seite, wait_until="load")
        page.wait_for_timeout(600)
        pruefe_verdeckt(page, seite, "offen geladen, %d px" % breite)
        pruefe_unter_nav(page, seite, "offen geladen, %d px" % breite)
        pruefe_ueberlauf(page, seite, "offen geladen, %d px" % breite)
        pruefe_text(page, seite, "offen geladen, %d px" % breite)
        # Nur bei offener Leiste aussagekräftig: Geschlossen ist sie 0 px breit und alle Zeilen brechen um.
        if breite == 1440:
            leisten_bild[seite] = page.evaluate(LEISTEN_BILD_JS)
        if page.evaluate("() => !!window.__leisteFaehrt"):
            errors.append("%s: Die Seitenleiste fährt beim Laden ein (%d px)" % (seite, breite))
        ctx.close()

    # Geschlossen laden, dann per Klick öffnen und wieder schließen.
    ctx = laden(browser, adresse, 1440, False)
    page = ctx.new_page()
    page.goto(adresse + seite, wait_until="load")
    page.wait_for_timeout(600)
    pruefe_unter_nav(page, seite, "geschlossen, 1440 px")
    leisten = page.evaluate(LEISTEN_JS)
    if not leisten["nav"]:
        errors.append("%s: keine obere Leiste" % seite)
    if not leisten["seite"]:
        errors.append("%s: keine Seitenleiste" % seite)
    # Die Seitenleiste führt zusätzlich die Social-Links und die Browser-Demo, deshalb gegen NAV.
    fehlt = [ziel for ziel in NAVIGATION if ziel not in leisten["oben"] or ziel not in leisten["seite"]]
    if fehlt:
        errors.append("%s: Navigationspunkt fehlt in einer Leiste: %s" % (seite, ", ".join(fehlt)))
    pruefe_ueberlauf(page, seite, "geschlossen, 1440 px")
    pruefe_text(page, seite, "geschlossen, 1440 px")
    treffer = ENTWICKLERTEXT.search(page.evaluate("() => document.body.innerText"))
    if treffer and seite not in ENTWICKLERTEXT_OFFEN:
        errors.append("%s: Entwicklertext sichtbar: %s" % (seite, treffer.group(0)))
    if page.query_selector("#sidebar-toggle") and page.is_visible("#sidebar-toggle"):
        page.click("#sidebar-toggle")
        page.wait_for_timeout(450)
        pruefe_verdeckt(page, seite, "per Klick geöffnet")
        pruefe_ueberlauf(page, seite, "per Klick geöffnet")
        page.click("#sidebar-toggle")
        page.wait_for_timeout(450)
        pruefe_ueberlauf(page, seite, "per Klick geschlossen")
    ctx.close()

    # Handy und Tablet: Die Leiste ist hier ein Drawer und darf nichts verschieben.
    for breite in (375, 768):
        wann = "%d px" % breite
        ctx = laden(browser, adresse, breite, True)
        page = ctx.new_page()
        page.goto(adresse + seite, wait_until="load")
        page.wait_for_timeout(600)
        pruefe_ueberlauf(page, seite, wann)
        pruefe_text(page, seite, wann)
        pruefe_unter_nav(page, seite, wann)
        if page.evaluate(SCHATTEN_JS) != "none":
            errors.append("%s: Das geschlossene Menü wirft einen Schatten auf die Seite (%s)" % (seite, wann))
        ctx.close()


def obere_leiste_pruefen(browser, adresse):
    for seite in ("index.html", "woche.html"):
        for breite in (1024, 1279, 1280, 1440):
            ctx = laden(browser, adresse, breite, False)
            page = ctx.new_page()
            page.goto(adresse + seite, wait_until="load")
            page.wait_for_timeout(300)
            p = page.evaluate(PLATZ_JS)
            if p["mitteStart"] is not None and p["mitteEnde"] - p["mitteStart"] > 0:
                if p["markeEnde"] > p["mitteStart"] or p["mitteEnde"] > p["rechtsStart"]:
                    errors.append("%s bei %d px: Links überlappen sich in der oberen Leiste (%s)" % (seite, breite, p))
            if p["rechtsEnde"] is not None and p["rechtsEnde"] > p["breite"]:
                errors.append("%s bei %d px: obere Leiste läuft aus dem Fenster" % (seite, breite))
            ctx.close()


def woche_pruefen(browser, adresse):
    ctx = laden(browser, adresse, 1440, False)
    page = ctx.new_page()
    page.goto(adresse + "woche.html", wait_until="load")
    page.wait_for_selector(".px-focus-lead", timeout=30000)
    pruefe_text(page, "woche.html", "Meldungen geladen, 1440 px")
    erg = page.evaluate(WOCHE_JS)
    if erg["abgeschnitten"]:
        errors.append("woche.html: abgeschnittene Video-Labels: %s" % ", ".join(erg["abgeschnitten"][:4]))
    if erg["ohneVideoFigur"]:
        errors.append("woche.html: %d Video-Rahmen ohne Video" % erg["ohneVideoFigur"])
    if erg["grau"]:
        errors.append("woche.html: %d Karten mit der grauen Standardfarbe als Akzent" % erg["grau"])
    heute = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    zukunft = [tag for tag in erg["tage"] if tag > heute]
    if zukunft:
        errors.append("woche.html: Tage in der Zukunft: %s" % ", ".join(zukunft))
    ctx.close()


def main():
    handler = functools.partial(Leise, directory=ROOT)
    server = Testserver(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adresse = "http://127.0.0.1:%d/" % server.server_address[1]
    liste = seiten.oeffentliche_seiten()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for seite in liste:
            seite_pruefen(browser, adresse, seite)
        leisten_vergleichen()
        obere_leiste_pruefen(browser, adresse)
        woche_pruefen(browser, adresse)
        browser.close()
    server.shutdown()
    if errors:
        print("LAYOUT-FEHLER (%d):" % len(errors))
        for e in errors:
            print("  ✗", e)
        sys.exit(1)
    print("✓ Layout-Check bestanden: %d Seiten." % len(liste))


if __name__ == "__main__":
    main()
