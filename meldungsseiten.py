"""Meldungsseiten (28.10.26): eine statische Seite je Story, damit Google sie findet.

Ablage:   meldung/JJJJ-MM/<slug>.html, Register je Monat in meldung/JJJJ-MM/index.json
Sitemaps: meldung/JJJJ-MM/sitemap.xml (nur indexierbare Seiten),
          sitemap-meldungen.xml (Index ueber alle Monate),
          sitemap-news.xml (Google-News-Sitemap, letzte 48 h)

Regeln:
- Eine Seite je Story (story_id des Laufs), Vertreter = hoechster Score.
- Die Adresse bleibt stabil: Das Register merkt sich alle Links einer Story. Taucht
  einer davon spaeter wieder auf, wird dieselbe Seite aktualisiert statt neu angelegt.
- Seiten werden nie geloescht. Neu geschrieben wird nur, wenn sich der Inhalt aendert.
- Substanz-Regel: index nur mit Einordnung, Linie, Anriss oder >= 300 Zeichen Text,
  sonst noindex,follow (Seite bleibt erreichbar, Google listet sie nicht).
- "Weitere Meldungen" wird beim Anlegen festgehalten und spaeter nicht umgebaut,
  sonst aendern sich bei jedem Lauf alle Seiten.

Einziger Schreiber aller Dateien unter meldung/ und der beiden Sitemaps (I5).
Aufruf aus ki_news.py VOR dem Schreiben von news.json: setzt dort je Meldung das Feld
"seite" (Pfad der Meldungsseite), das Startseite und Listen verlinken.
Kill-Switch MELDUNGSSEITEN_AKTIV.
"""

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("ki_news.meldungen")

SITE = "https://ki-news.live"
ORDNER = "meldung"
NEWS_SITEMAP_STUNDEN = 48
SUBSTANZ_ZEICHEN = 300          # Zusammenfassung allein
SUBSTANZ_MIT_ANRISS = 250       # Zusammenfassung + Anriss
WEITERE_MAX = 5

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe",
                          "Ü": "ue", "ß": "ss"})


def _slug(text, max_len=70):
    s = (text or "").translate(_UMLAUTE).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rsplit("-", 1)[0]
    return s or "meldung"


def _zahl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _titel(n):
    t = (n.get("schlagzeile") or n.get("title") or "").strip()
    return t[:-1] if t.endswith(".") and not t.endswith("..") else t


def _links(n):
    return [l for l in (n.get("link"), n.get("link_verlag")) if l]


def _json_lesen(pfad, leer):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return leer


def _schreiben_wenn_neu(pfad, text):
    """True, wenn geschrieben wurde. Unveraenderte Dateien bleiben unangetastet."""
    try:
        if pfad.exists() and pfad.read_text(encoding="utf-8") == text:
            return False
    except Exception:
        pass
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8", newline="\n")
    return True


def _karten_nach_link(base):
    roh = _json_lesen(base / "cards.json", [])
    karten = roh if isinstance(roh, list) else roh.get("cards", [])
    out = {}
    for k in karten:
        links = k.get("links") or []
        if isinstance(links, str):
            links = [links]
        for l in links:
            out.setdefault(l, k)
    return out


def _recherche_nach_link(base):
    """Veroeffentlichte Recherche-Artikel (recherche_artikel.py) je Meldungslink."""
    out = {}
    for e in _json_lesen(base / "recherche" / "index.json", {}).values():
        if e.get("status") == "veroeffentlicht" and e.get("pfad"):
            for l in e.get("links") or []:
                out.setdefault(l, {"pfad": e["pfad"], "titel": e.get("titel") or "",
                                   "anriss": e.get("anriss") or "", "quellen": e.get("quellen") or ""})
    return out


def _linie_info(n, linien):
    k = n.get("linie")
    l = linien.get(k) if k and isinstance(linien, dict) else None
    if not l:
        return None
    d = l.get("dossier") if isinstance(l.get("dossier"), dict) else {}
    titel = (d.get("titel") or "").strip()
    if not titel:
        return None
    return {"titel": titel, "seit": l.get("seit") or "", "n": l.get("n") or ""}


def _substanz(n, karte, linie, recherche=None):
    if recherche:
        return True
    summary = n.get("summary") or ""
    anriss = n.get("anriss") or ""
    if (karte or {}).get("einordnung") or linie:
        return True
    if anriss and len(summary) + len(anriss) >= SUBSTANZ_MIT_ANRISS:
        return True
    return len(summary) >= SUBSTANZ_ZEICHEN


def _datum_de(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return iso or ""


_CSS = """
:root{--papier:#fff;--tinte:#16181b;--grau:#565c65;--linie:#dde2e8;--grund:#f0f4f8;--akzent:#0b6e88;
--serif:'Fraunces',Georgia,'Times New Roman',serif;--sans:'Work Sans',system-ui,-apple-system,sans-serif}
html.dark{--papier:#15181b;--tinte:#ecebe7;--grau:#a7acb3;--linie:#2a2e33;--grund:#0d0f11;--akzent:#55c3de}
*{box-sizing:border-box}
body{margin:0;background:var(--grund);color:var(--tinte);font:1.0625rem/1.65 var(--sans)}
a{color:var(--akzent)}
.kopf,.fuss,main{max-width:46rem;margin:0 auto;padding:0 16px}
.kopf{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-top:18px;padding-bottom:14px;border-bottom:1px solid var(--linie)}
.marke{font:600 1.25rem var(--serif);color:var(--tinte);text-decoration:none}
.nav a{margin-left:14px;font-size:.9375rem;color:var(--grau);text-decoration:none}
main{background:var(--papier);padding-top:28px;padding-bottom:36px;margin-top:20px;border-radius:4px}
.meta{font-size:.8125rem;color:var(--grau);text-transform:uppercase;letter-spacing:.04em}
h1{font:600 clamp(1.75rem,1.2rem + 2vw,2.5rem)/1.15 var(--serif);margin:.4rem 0 1rem;hyphens:none;overflow-wrap:break-word}
.anriss{font-size:1.1875rem;line-height:1.55;margin:0 0 1.25rem}
figure{margin:0 0 1.25rem}
figure img,video{width:100%;height:auto;border-radius:4px;display:block;background:var(--linie)}
h2{font:600 1.3125rem var(--serif);margin:1.75rem 0 .5rem}
.einordnung{border-left:3px solid var(--akzent);padding:.25rem 0 .25rem 1rem}
.linie{border-top:1px solid var(--linie);border-bottom:1px solid var(--linie);padding:.75rem 0;margin:1.5rem 0}
.quelle{font-size:.9375rem;color:var(--grau)}
ul.weitere{list-style:none;padding:0;margin:0}
ul.weitere li{border-top:1px solid var(--linie);padding:.6rem 0}
ul.weitere a{color:var(--tinte);text-decoration:none;font-family:var(--serif);font-size:1.0625rem}
ul.weitere a:hover{color:var(--akzent)}
.hinweis{font-size:.8125rem;color:var(--grau);margin-top:2rem}
.fuss{padding-top:18px;padding-bottom:32px;font-size:.8125rem;color:var(--grau)}
.fuss a{color:var(--grau);margin-right:14px}
@media (max-width:480px){.nav a{margin-left:10px}.nav a.weg{display:none}}
""".strip()

# Gleiche Einstellung wie die Startseite (localStorage ki_theme: auto/light/dark).
_THEME_JS = ("(function(){var s='auto';try{s=localStorage.getItem('ki_theme')||'auto';}catch(e){}"
             "var d=s==='dark'||(s!=='light'&&window.matchMedia&&"
             "matchMedia('(prefers-color-scheme: dark)').matches);"
             "if(d)document.documentElement.classList.add('dark');})();")


def _seite(e, n, karte, linie, weitere, recherche=None):
    esc = html.escape
    titel = e["titel"]
    url = SITE + e["pfad"]
    anriss = (n.get("anriss") or "").strip()
    summary = (n.get("summary") or "").strip()
    desc = (anriss or summary or titel)[:200]
    quelle = n.get("source") or "Quelle"
    q_link = n.get("link_verlag") or n.get("link") or ""
    bild = n.get("image_local_gross") or n.get("image_local") or ""
    einordnung = ((karte or {}).get("einordnung") or "").strip()
    video = (karte or {}).get("mp4_url") or ""
    poster = (karte or {}).get("poster_url") or ""
    robots = "index, follow, max-image-preview:large" if e["index"] else "noindex, follow"

    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": titel[:110],
        "description": desc,
        "inLanguage": "de",
        "datePublished": e["veroeffentlicht"],
        "dateModified": e["geaendert"],
        "mainEntityOfPage": url,
        "author": {"@type": "Person", "name": "Daniel S.", "alternateName": "Scampy",
                   "url": SITE + "/", "sameAs": ["https://twitter.com/ScampyKI"]},
        "publisher": {"@type": "Organization", "name": "KI News", "url": SITE + "/",
                      "logo": {"@type": "ImageObject", "url": SITE + "/s-logo.png"}},
    }
    if bild:
        ld["image"] = [bild]
    if q_link:
        ld["isBasedOn"] = q_link
    ld_txt = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")

    teile = [
        "<!DOCTYPE html>",
        '<html lang="de">',
        "<head>",
        '<meta charset="utf-8"/>',
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
        f"<title>{esc(titel)} · KI News</title>",
        f'<meta name="description" content="{esc(desc)}"/>',
        f'<meta name="robots" content="{robots}"/>',
        f'<link rel="canonical" href="{url}"/>',
        '<link rel="icon" type="image/png" href="/s-logo.png"/>',
        '<meta property="og:type" content="article"/>',
        f'<meta property="og:title" content="{esc(titel)}"/>',
        f'<meta property="og:description" content="{esc(desc)}"/>',
        f'<meta property="og:url" content="{url}"/>',
        '<meta property="og:site_name" content="KI News"/>',
        '<meta property="og:locale" content="de_DE"/>',
        f'<meta property="article:published_time" content="{e["veroeffentlicht"]}"/>',
    ]
    if bild:
        teile += [f'<meta property="og:image" content="{esc(bild)}"/>',
                  '<meta name="twitter:card" content="summary_large_image"/>']
    teile += [
        '<meta name="twitter:site" content="@ScampyKI"/>',
        '<link rel="stylesheet" href="/assets/ki-fonts.css"/>',
        f"<script>{_THEME_JS}</script>",
        f"<style>{_CSS}</style>",
        f'<script type="application/ld+json">{ld_txt}</script>',
        "</head>",
        "<body>",
        '<header class="kopf"><a class="marke" href="/">KI News</a>'
        '<nav class="nav"><a href="/">Startseite</a><a href="/dossiers.html">Dossiers</a>'
        '<a class="weg" href="/Archiv.html">Archiv</a></nav></header>',
        "<main>",
        "<article>",
        f'<p class="meta">{esc(quelle)} · <time datetime="{e["datum"]}">{_datum_de(e["datum"])}</time></p>',
        f"<h1>{esc(titel)}</h1>",
    ]
    if anriss:
        teile.append(f'<p class="anriss">{esc(anriss)}</p>')
    if video:
        p = f' poster="{esc(poster)}"' if poster else ""
        teile.append(f'<figure><video controls playsinline preload="none"{p}>'
                     f'<source src="{esc(video)}" type="video/mp4"/></video></figure>')
    elif bild:
        teile.append(f'<figure><img src="{esc(bild)}" alt="{esc(titel)}" loading="lazy"/></figure>')
    if summary and summary != anriss:
        teile.append(f"<p>{esc(summary)}</p>")
    if einordnung:
        teile += ["<h2>Einordnung</h2>", f'<p class="einordnung">{esc(einordnung)}</p>']
    if linie:
        z = f" · {esc(str(linie['n']))} Meldungen" if linie.get("n") else ""
        s = f"Seit {_datum_de(linie['seit'])}" if linie.get("seit") else "Laufende Entwicklung"
        teile.append(f'<p class="linie"><span class="meta">Teil einer Entwicklung</span><br/>'
                     f'<a href="/dossiers.html">{esc(linie["titel"])}</a><br/>'
                     f'<span class="quelle">{s}{z}</span></p>')
    if recherche:
        z = f" aus {esc(str(recherche['quellen']))} Quellen" if recherche.get("quellen") else ""
        teile.append(f'<p class="linie"><span class="meta">Hintergrund{z}</span><br/>'
                     f'<a href="{esc(recherche["pfad"])}">{esc(recherche["titel"])}</a><br/>'
                     f'<span class="quelle">{esc(recherche["anriss"])}</span></p>')
    if q_link:
        auch = [q for q in (n.get("dub_quellen") or []) if isinstance(q, str) and q != quelle]
        a = f" Auch berichtet von: {esc(', '.join(auch))}." if auch else ""
        teile.append(f'<p class="quelle">Originalquelle: <a href="{esc(q_link)}" rel="noopener" '
                     f'target="_blank">{esc(quelle)}</a>.{a}</p>')
    teile.append("</article>")
    if weitere:
        teile.append("<h2>Weitere Meldungen</h2>")
        teile.append('<ul class="weitere">' + "".join(
            f'<li><a href="{esc(w["pfad"])}">{esc(w["titel"])}</a></li>' for w in weitere) + "</ul>")
    teile += [
        '<p class="hinweis">Zusammenfassung aus der englischsprachigen Originalquelle, '
        'automatisch übersetzt und von KI News ausgewählt.</p>',
        "</main>",
        '<footer class="fuss"><a href="/">ki-news.live</a><a href="/Impressum.html">Impressum</a>'
        '<a href="/Datenschutz.html">Datenschutz</a></footer>',
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(teile)


def _inhalt_hash(n, karte, linie, titel, index, recherche=None):
    teile = [titel, n.get("anriss") or "", n.get("summary") or "", n.get("source") or "",
             n.get("link_verlag") or n.get("link") or "", n.get("image_local_gross") or
             n.get("image_local") or "", (karte or {}).get("einordnung") or "",
             (karte or {}).get("mp4_url") or "", json.dumps(linie, sort_keys=True),
             ",".join(n.get("dub_quellen") or []), str(index)]
    if recherche:                         # ohne Recherche bleibt der Hash wie bisher
        teile.append(json.dumps(recherche, sort_keys=True))
    return hashlib.sha1("\x1f".join(teile).encode("utf-8")).hexdigest()[:12]


def _sitemaps(base, register, jetzt):
    xmlns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    monate = sorted(register)
    for m in monate:
        urls = [e for e in register[m].values() if e.get("index")]
        zeilen = ['<?xml version="1.0" encoding="UTF-8"?>', f"<urlset {xmlns}>"]
        for e in sorted(urls, key=lambda x: x["pfad"]):
            zeilen.append(f"  <url><loc>{SITE}{e['pfad']}</loc>"
                          f"<lastmod>{e['geaendert'][:10]}</lastmod></url>")
        zeilen += ["</urlset>", ""]
        _schreiben_wenn_neu(base / ORDNER / m / "sitemap.xml", "\n".join(zeilen))

    idx = ['<?xml version="1.0" encoding="UTF-8"?>', f"<sitemapindex {xmlns}>"]
    for m in monate:
        lm = max((e["geaendert"][:10] for e in register[m].values()), default=jetzt[:10])
        idx.append(f"  <sitemap><loc>{SITE}/{ORDNER}/{m}/sitemap.xml</loc>"
                   f"<lastmod>{lm}</lastmod></sitemap>")
    idx += ["</sitemapindex>", ""]
    _schreiben_wenn_neu(base / "sitemap-meldungen.xml", "\n".join(idx))

    grenze = (datetime.fromisoformat(jetzt) - timedelta(hours=NEWS_SITEMAP_STUNDEN)).isoformat()
    frisch = [e for m in monate for e in register[m].values()
              if e.get("index") and e["veroeffentlicht"] >= grenze]
    news = ['<?xml version="1.0" encoding="UTF-8"?>',
            f'<urlset {xmlns} xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">']
    for e in sorted(frisch, key=lambda x: x["veroeffentlicht"], reverse=True)[:1000]:
        news.append(
            f"  <url><loc>{SITE}{e['pfad']}</loc><news:news><news:publication>"
            "<news:name>KI News</news:name><news:language>de</news:language>"
            f"</news:publication><news:publication_date>{e['veroeffentlicht']}"
            f"</news:publication_date><news:title>{html.escape(e['titel'])}</news:title>"
            "</news:news></url>")
    news += ["</urlset>", ""]
    _schreiben_wenn_neu(base / "sitemap-news.xml", "\n".join(news))
    return len(frisch)


def erzeuge(base_dir, news_json_data, jetzt=None):
    base = Path(base_dir)
    jetzt = jetzt or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    heute = jetzt[:10]
    news = [n for n in (news_json_data.get("news") or []) if n.get("link") and n.get("title")]
    linien = news_json_data.get("linien") or {}
    karten = _karten_nach_link(base)
    recherchen = _recherche_nach_link(base)

    # Alle vorhandenen Monatsregister laden (klein: ein Eintrag je Story).
    register = {}
    ordner = base / ORDNER
    if ordner.exists():
        for d in ordner.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}", d.name):
                register[d.name] = _json_lesen(d / "index.json", {})
    nach_link = {l: (m, s) for m, reg in register.items() for s, e in reg.items()
                 for l in e.get("links", [])}

    # Storys des Laufs: Vertreter = hoechster Score, alle Links der Story merken.
    storys = {}
    for n in news:
        storys.setdefault(n.get("story_id") or n["link"], []).append(n)
    reihe = []
    for glieder in storys.values():
        rep = max(glieder, key=lambda x: _zahl(x.get("score")))
        links = [l for g in glieder for l in _links(g)]
        karte = next((karten[l] for l in links if l in karten), None)
        recherche = next((recherchen[l] for l in links if l in recherchen), None)
        reihe.append((rep, links, karte, glieder, recherche))
    reihe.sort(key=lambda t: _zahl(t[0].get("score")), reverse=True)

    neu = geaendert = 0
    eintraege = []
    # Eine Seite gehoert je Lauf genau einer Story (29.10.26). Vorher landeten ueber einen alten
    # gemeinsamen Link drei Storys auf der Gemini-4-Carbon-Seite, die schwaechste (Score 18)
    # schrieb zuletzt und ueberschrieb den Inhalt. Reihe ist nach Score sortiert: die staerkste
    # Story behaelt die Seite, die anderen bekommen eine eigene.
    vergeben = set()
    for rep, links, karte, glieder, recherche in reihe:
        titel = _titel(rep)
        linie = _linie_info(rep, linien)
        index = _substanz(rep, karte, linie, recherche)
        treffer = next((nach_link[l] for l in links if l in nach_link and nach_link[l] not in vergeben), None)
        if treffer:
            monat, slug = treffer
            e = register[monat][slug]
        else:
            datum = (rep.get("first_seen") or rep.get("date") or heute)[:10]
            monat = datum[:7]
            reg = register.setdefault(monat, {})
            slug = basis = _slug(titel)
            i = 2
            while slug in reg:
                slug, i = f"{basis}-{i}", i + 1
            e = reg[slug] = {
                "pfad": f"/{ORDNER}/{monat}/{slug}.html",
                "datum": datum,
                # Erstveroeffentlichung: heute = jetzt, sonst das Datum des ersten Auftauchens
                "veroeffentlicht": jetzt if datum == heute else f"{datum}T06:00:00+00:00",
                "geaendert": jetzt,
                "links": [],
                "weitere": None,
            }
            neu += 1
        # Links ziehen mit ihrer Story um: bei einer anderen Seite austragen, sonst landet die
        # Story im naechsten Lauf wieder dort (und bekaeme jedes Mal eine neue Seite).
        for l in links:
            alt = nach_link.get(l)
            if alt and alt != (monat, slug):
                ae = register[alt[0]][alt[1]]
                ae["links"] = [x for x in ae["links"] if x != l]
            nach_link[l] = (monat, slug)
        e["links"] = sorted(set(e["links"]) | set(links))
        vergeben.add((monat, slug))
        for g in glieder:                 # Startseite und Listen verlinken hierauf
            g["seite"] = e["pfad"]
        h = _inhalt_hash(rep, karte, linie, titel, index, recherche)
        if e.get("h") != h:
            if e.get("h"):
                e["geaendert"] = jetzt
                geaendert += 1
            e["h"] = h
        e["titel"], e["index"] = titel, index
        eintraege.append((e, rep, karte, linie, recherche))

    # "Weitere Meldungen": beim ersten Anlegen festschreiben (indexierbare Storys des Laufs).
    indexierbar = [e for e, *_ in eintraege if e["index"]]
    for e, *_ in eintraege:
        if e["weitere"] is None:
            e["weitere"] = [w["pfad"] for w in indexierbar if w is not e][:WEITERE_MAX]
    nach_pfad = {e["pfad"]: e for reg in register.values() for e in reg.values()}

    geschrieben = 0
    for e, rep, karte, linie, recherche in eintraege:
        weitere = [nach_pfad[p] for p in e["weitere"] if p in nach_pfad]
        datei = base / e["pfad"].lstrip("/")
        if _schreiben_wenn_neu(datei, _seite(e, rep, karte, linie, weitere, recherche)):
            geschrieben += 1

    for m, reg in register.items():
        _schreiben_wenn_neu(ordner / m / "index.json",
                            json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    frisch = _sitemaps(base, register, jetzt)
    logger.info("Meldungsseiten: %d Storys, %d neu, %d geaendert, %d Dateien geschrieben, "
                "%d indexierbar, %d in der News-Sitemap",
                len(eintraege), neu, geaendert, geschrieben, len(indexierbar), frisch)
    return {"storys": len(eintraege), "neu": neu, "geschrieben": geschrieben,
            "indexierbar": len(indexierbar), "news_sitemap": frisch}
