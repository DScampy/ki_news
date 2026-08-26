import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os
import logging
import difflib
import webbrowser
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from time import sleep
from urllib.error import URLError, HTTPError
import html as _html

# ──────────────────────────────────────────────────────────────────────────
# SSR / Pre-Rendering für index.html
# ──────────────────────────────────────────────────────────────────────────
# Crawler & KI-Bots (GPTBot, ClaudeBot, PerplexityBot …) führen kein JavaScript
# aus. Diese Funktion schreibt die aktuellen News bei jedem Lauf als ECHTES HTML
# in index.html – in zwei markierte Bereiche. Das JS-Frontend bleibt unverändert;
# es ersetzt diese Bereiche im Browser wie bisher.
#   <!-- SSR:HERO:START --> … <!-- SSR:HERO:END -->
#   <!-- SSR:NEWS:START --> … <!-- SSR:NEWS:END -->
SSR_MAX = 24  # max. News-Karten im vorgerenderten HTML

# Deutsche Signalwoerter (14.08.26, portiert aus generate_news_cards.py'
# GERMAN_MARKERS/_looks_german() - dort seit 08.07.26 im Einsatz, um
# unuebersetzte Karten-Headlines abzufangen). Gleicher Fund hier: title_de
# ist bei fehlgeschlagener Uebersetzung schlicht der englische Original-
# Titel (Platzhalter aus summarize_news() wurde nie ueberschrieben) - das
# ging bisher UNGEPRUEFT in news.json und damit in Hero + Grid-Karten der
# Website (Fund 14.08.26: Lauf 05:01 UTC, "OpenAI is losing its second
# executive this week" lief englisch auf ki-news.live). Bewusst keine harte
# Sprach-ID-Bibliothek - reicht als Fangnetz gegen unuebersetzten Text.
# FIX 18.08.26: Die urspruengliche Liste stammt aus generate_news_cards.py, wo
# sie auf langen FLIESSTEXT laeuft. Am 14.08. wurde sie auf den kurzen title_de
# portiert - deutsche Nachrichtentitel sind telegrammartig und enthalten oft
# keinen einzigen Artikel. Ergebnis: 81 korrekt uebersetzte Titel wurden ueber
# Tage hinweg in JEDEM Lauf verworfen (438 Verwerfungen im Log vom 16.-18.08.).
# Marker-Heuristik skaliert nicht nach unten -> Liste erweitert + Entscheidung
# auf englische NEGATIV-Marker umgestellt (s. _looks_german unten).
GERMAN_MARKERS = [
    " der ", " die ", " das ", " und ", " ist ", " nicht ", " eine ",
    " einen ", " für ", " mit ", " auf ", " dass ", " wird ", " sich ",
    " kein ", " keine ", " ein ", " im ", " den ",
    # 18.08.26 ergaenzt - haeufig in verkuerzten Titeln, alle NICHT auch englisch:
    " von ", " zu ", " durch ", " über ", " nach ", " bei ", " als ",
    " auch ", " wie ", " werden ", " wurde ", " hat ", " sind ", " sein ",
    " seine ", " ihre ", " ihr ", " mehr ", " neue ", " neuen ", " neuer ",
    " gegen ", " ohne ", " vor ", " stellt ", " bringt ", " plant ",
    " laut ", " nun ", " uns ", " bis ", " dem ", " des ", " zur ", " zum ",
    # 26.08.26 ergaenzt - deutsche Schlagzeilen haben fast immer ein finites
    # Verb in der 3. Person, aber oft keinen Artikel ("Anthropic startet
    # Claude for Healthcare"). Genau diese Titel fielen bisher durch: kein
    # Marker griff, und im englischen Eigennamen stand ein ENGLISH_MARKER.
    # Alle folgenden sind KEINE englischen Woerter (geprueft).
    " startet ", " findet ", " statt ", " kommt ", " gibt ", " macht ",
    " zeigt ", " kauft ", " baut ", " nutzt ", " setzt ", " testet ",
    " meldet ", " warnt ", " liefert ", " bekommt ", " steigt ", " sinkt ",
    " senkt ", " oeffnet ", " schliesst ", " kostet ", " heisst ",
    " sowie ", " jetzt ", " schon ", " noch ", " damit ", " dabei ",
    " weil ", " wenn ", " aber ", " oder ", " diese ", " dieser ",
    " dieses ", " einem ", " eines ", " keinen ", " beim ", " vom ",
    " ins ", " zwei ", " drei ", " viele ", " eigene ", " eigenen ",
]

# Eindeutig ENGLISCHE Funktionswoerter. Bewusst NICHT enthalten: " in ", " an ",
# " so ", " was ", " will ", " man ", " wer " - die sind auch deutsch und haben
# in der Erprobung deutsche Titel faelschlich als englisch markiert.
ENGLISH_MARKERS = [
    " the ", " of ", " this ", " that ", " with ", " from ", " and ",
    " is ", " are ", " says ", " has ", " have ", " for ", " its ",
    " it ", " may ", " not ", " to ", " on ", " as ", " by ", " at ",
    " be ", " you ", " your ", " how ", " why ", " a ", " an ", " but ",
    " they ", " their ", " we ", " our ", " more ", " new ", " into ",
    " about ", " after ", " over ", " up ", " out ",
]

GERMAN_CHARS = frozenset("äöüÄÖÜß")

# Encoding-Bug (Fund 18.08.26): einzelne Modelle liefern LaTeX-Escapes statt
# Umlauten ('OpenAI l{"o}scht ...' statt 'loescht'). 25 Vorkommen im Log.
# Zentral beim Einlesen der Modell-Antwort reparieren, s. summarize_news().
_LATEX_UMLAUTS = {
    '{"o}': "ö", '{"O}': "Ö", '{"u}': "ü", '{"U}': "Ü",
    '{"a}': "ä", '{"A}': "Ä", '{\\ss}': "ß", "\\ss ": "ß ",
}


# Klammerlose Variante (Fund 19.08.26): 'ungesch"uzt' statt 'ungesch{"u}tzt'.
# Bewusst eng: nur zwischen zwei Kleinbuchstaben, sonst wuerden legitime
# Anfuehrungszeichen zerstoert (der "Ultrafast"-Modus bleibt unangetastet).
_LATEX_INLINE = re.compile(r'(?<=[a-zäöüß])"([oua])(?=[a-zäöüß])')
_INLINE_MAP = {"o": "ö", "u": "ü", "a": "ä"}


# ── Zentraler Artefakt-Filter (26.08.26) ─────────────────────────────────
# Aus der ox-Schleife (Lauf 240826_0435_en, Runde 12), von Hand nachgehaertet.
# 61/61 Testfaelle, 0 Fehlverwerfungen auf 16.578 echten Texten.
# Fallback bewusst permissiv: fehlt sanitize.py im Repo, laesst der Filter
# alles durch statt den Lauf mit ImportError zu killen -- derselbe Fehler wie
# beim registry_bau-Import am 21.08. soll sich nicht wiederholen.
try:
    from sanitize import ist_brauchbar as _sanitize_llm_output
except ImportError:            # pragma: no cover
    logging.getLogger(__name__).warning(
        "sanitize.py nicht gefunden - Artefakt-Filter inaktiv, Lauf geht weiter")
    def _sanitize_llm_output(text, original=None):
        return True


def _fix_latex_escapes(text: str) -> str:
    """LaTeX-Umlaut-Escapes durch echte Umlaute ersetzen. No-op wenn keine da."""
    t = text or ""
    if '"' in t:
        t = _LATEX_INLINE.sub(lambda m: _INLINE_MAP[m.group(1)], t)
    if "{" not in t and "\\ss" not in t:
        return t
    for esc, ch in _LATEX_UMLAUTS.items():
        t = t.replace(esc, ch)
    return t


# ── Statistische Sprach-ID (26.08.26) ────────────────────────────────────
# Warum ueberhaupt: das hier ist der VIERTE Anlauf auf dasselbe Problem
# (08.07., 14.08., 18.08., jetzt). Die drei vorherigen waren alle Wortlisten,
# und Wortlisten erkennen keine Sprache, sondern Funktionswoerter -- genau die
# fehlen in Tech-Schlagzeilen. Gemessen am 26.08. gegen die echte Funktion:
#   'Hack the North gibt Studenten 36 Stunden, um ambitionierte Ideen in
#    Demos umzusetzen.'                       -> verworfen, obwohl Deutsch
#   'Anthropic startet Claude for Healthcare' -> verworfen, obwohl Deutsch
#   'NVIDIA DLSS 4.5 Ray Reconstruction Tech Brings 2nd Gen Transformer'
#                                             -> durchgelassen, obwohl Englisch
# Also in BEIDE Richtungen falsch. py3langid ist eine reine Python-Portierung
# von langid.py: offline, kein API-Call, kein Modell-Download, rund 0.4 ms pro
# Titel. Auf 'de'/'en' eingeschraenkt, weil nur diese Unterscheidung zaehlt.
#
# Fehlt das Paket (lokaler Lauf ohne pip install), faellt die Funktion auf die
# alte Marker-Heuristik zurueck -- schlechter, aber der Lauf kippt nicht.
try:
    from py3langid.langid import LanguageIdentifier, MODEL_FILE as _LANGID_MODEL
    _LANGID = LanguageIdentifier.from_pickled_model(_LANGID_MODEL, norm_probs=True)
    _LANGID.set_languages(["de", "en"])
except Exception:          # pragma: no cover - nur ohne installiertes Paket
    _LANGID = None

# Schwelle offline kalibriert (26.08.26) gegen alle 3514 title_de aus
# summary-cache.json. Umlaut- und Marker-Regel fangen 3460 davon ab, nur 54
# erreichen langid ueberhaupt. Von diesen 54 werden bei >= 0.99 genau zwei
# verworfen ('The Progress Guest Chef Dinner', 'The Village Pub Winter
# Winemaker Dinner') - beide tatsaechlich unuebersetzt, also 0 Fehlverwerfungen.
# Bei 0.90 kaemen zwei ECHTE deutsche Titel dazu ('Google rollt Nano Banana AI
# in Earth aus' 0.939, 'KI-Experimentalprojekte Osaka September Meetup' 0.903).
# Deshalb 0.99 und nicht tiefer: ein faelschlich verworfener Artikel ist teurer
# als eine haessliche Kachel, und Regel 0 faengt den Hauptfall ohnehin exakt.
_LANGID_EN_SCHWELLE = 0.99


def _looks_german(text: str, original: str = None) -> bool:
    """True wenn der Text als Deutsch durchgehen darf.

    Reihenfolge (erste Regel gewinnt):
      1. Umlaut/ss vorhanden             -> deutsch
      2. deutsches Signalwort            -> deutsch
      3. py3langid sagt 'en' mit >= 0.99 -> nicht deutsch
      4. sonst                           -> deutsch (Zweifel zugunsten des
         Artikels); ohne py3langid greift hier die alte Marker-Heuristik

    `original` wird nur noch entgegengenommen, damit die Aufrufstelle nicht
    erneut angefasst werden muss, und BEWUSST nicht mehr ausgewertet:

    ZURUECKGEBAUT 26.08.26 abends, wenige Stunden nach dem Einbau. Die Idee war
    "title_de == unveraenderter Originaltitel heisst: nie uebersetzt worden" --
    exakt statt heuristisch, und der Test gegen 13 englische Titel gab 13/13.
    Der Test hatte nur eine Luecke: er enthielt keinen einzigen Artikel aus
    einer DEUTSCHEN Quelle. Bei heise, golem und t3n ist title_de == Original
    der Normalfall, weil da nichts zu uebersetzen ist. Ergebnis im Live-Lauf
    vom 26.08. 18:11 -- die Regel lief VOR der Umlaut-Pruefung und verwarf
    69 Artikel, davon 19 von 26 eindeutig deutschen Titeln nachgemessen
    ("Bosch baut humanoiden Roboter in Deutschland.", "KI aus Deutschland: Ein
    Foerdersystem, das Innovationen hemmt"). Alle 19 haetten Regel 1 oder 2
    bestanden.

    Lehre, damit das niemand neu erfindet: Identitaet sagt nichts ueber
    Sprache. Sie ist nur dann ein Hinweis auf eine fehlgeschlagene
    Uebersetzung, wenn das Original englisch ist -- und ob es das ist, muss
    ohnehin die Sprach-ID entscheiden. Die Regel war also im besten Fall
    ueberfluessig und im schlechtesten genau der Schaden, den sie verhindern
    sollte. Nachgemessen bringt sie an den Log-Daten vom 25./26.08. auch keinen
    Gewinn: die 7 tatsaechlich englischen Titel liegen alle bei langid-Wahr-
    scheinlichkeit 1.00 und fallen ohne sie genauso durch.
    """
    t = _fix_latex_escapes(text or "").strip()
    if not t:
        return True
    if any(c in GERMAN_CHARS for c in t):
        return True
    lower = f" {t.lower()} "
    if any(marker in lower for marker in GERMAN_MARKERS):
        return True
    if _LANGID is not None:
        try:
            lang, prob = _LANGID.classify(t)
        except Exception:
            return not any(marker in lower for marker in ENGLISH_MARKERS)
        return not (lang == "en" and prob >= _LANGID_EN_SCHWELLE)
    return not any(marker in lower for marker in ENGLISH_MARKERS)


def _ssr_fmt_date(d):
    """'2026-05-28' -> '28.05.2026'"""
    if not d:
        return ""
    p = str(d)[:10].split("-")
    return f"{p[2]}.{p[1]}.{p[0]}" if len(p) == 3 else _html.escape(str(d))


# Karten-/Flaggen-Symbol je Region. welt/sachsen sind Karten (mit Stadt-
# Punkten im SVG-Symbol selbst), alle anderen sind Flaggen (card-bg--flag).
_REGION_SYMBOL = {
    "welt":         ("map-welt", False),
    "sachsen":      ("map-sachsen", False),
    "europa":       ("flag-europa", True),
    "deutschland":  ("flag-deutschland", True),
    "oesterreich":  ("flag-oesterreich", True),
    "schweiz":      ("flag-schweiz", True),
}


def _card_bg_svg(n):
    """SVG-Hintergrund (Karte oder Flagge) fuer eine News-Kachel, je nach
    n['region']. Kein Feld/unbekannte Region -> keine Deko (leerer String),
    damit ein fehlendes region-Feld nie zu einem kaputten <use> fuehrt."""
    region = n.get("region")
    sym = _REGION_SYMBOL.get(region)
    if not sym:
        return ""
    symbol_id, is_flag = sym
    cls = "card-bg card-bg--flag" if is_flag else "card-bg"
    return f'<svg class="{cls}"><use href="assets/ki-maps.svg#{symbol_id}" width="100%" height="100%"/></svg>'


def _ssr_card(n):
    c = _html.escape(n.get("color") or "#1d9bf0", quote=True)
    src = _html.escape(n.get("source") or "")
    date = _ssr_fmt_date(n.get("date") or n.get("first_seen") or "")
    date_html = (
        f'<span class="text-[11px] font-mono ki-faint">· {date}</span>' if date else ""
    )
    score = n.get("score")
    score_html = (
        f'<span class="text-[10px] font-mono ki-faint" title="Score">{round(score)}</span>'
        if score else ""
    )
    return (
        # noreferrer am 22.08.26 ergaenzt, damit diese Kachel exakt dasselbe rel
        # setzt wie renderCard() in index.html -- die beiden erzeugen dieselbe
        # Kachel, einmal vorgerendert und einmal im Browser.
        f'<a href="{_html.escape(n.get("link") or "#", quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'class="ki-card ki-border border p-4 flex flex-col h-full transition-all">'
        f'{_card_bg_svg(n)}'
        f'<div class="card-scrim"></div>'
        f'<div class="card-content flex flex-col h-full">'
        f'<div class="flex items-center justify-between mb-4">'
        f'<span class="text-white px-2 py-0.5 font-source-tag text-source-tag rounded-sm uppercase" '
        f'style="background:{c}">{src}</span>'
        f'</div>'
        # Bottom-Anchor (04.07.26): margin-top:auto schiebt Titel+Text+Footer an
        # den Kachel-Boden, oben bleibt freie Zone fuer die Karten-/Flaggen-Deko
        # (Kacheln einer Grid-Reihe sind gleich hoch, Inhalte unterschiedlich).
        # flex-grow am <p> musste dafuer weg (frisst sonst den freien Raum).
        # Pendant in index.html renderCard() - immer zusammen aendern!
        f'<h4 class="font-headline-md ki-main mb-2 leading-snug" '
        f"style=\"font-family:'Space Grotesk',sans-serif;margin-top:auto\">{_html.escape(n.get('title') or '')}</h4>"
        f'<p class="text-on-surface-variant font-body-sm text-body-sm mb-6">'
        f"{_html.escape(n.get('summary') or '')}</p>"
        f'<div class="pt-4 ki-border border-t flex items-center justify-between">'
        f'<span class="text-[11px] font-mono uppercase" style="color:{c}">{src}</span>'
        f'<div style="display:flex;align-items:center;gap:6px">{date_html}{score_html}</div>'
        f'</div>'
        f'</div>'
        f'</a>'
    )


def inject_ssr(base_dir, news_json_data):
    """Schreibt Hero + News-Grid + JSON-LD als statisches HTML in index.html."""
    base_dir = Path(base_dir)
    index_path = base_dir / "index.html"
    if not index_path.exists():
        return  # Kein index.html in diesem Verzeichnis (z.B. lokal) – nichts zu tun.

    news = sorted(
        list(news_json_data.get("news") or []),
        key=lambda n: n.get("score", 0),
        reverse=True,
    )[:SSR_MAX]
    if not news:
        return

    stand = news_json_data.get("stand", "")

    # ── Hero (Top-Story) ──
    top = news[0]
    hero = (
        "<!-- SSR:HERO:START -->\n"
        '            <div class="c-text">\n'
        f'              <h2 id="c-title">{_html.escape(top.get("title") or "")}</h2>\n'
        f'              <p id="c-desc">{_html.escape(top.get("summary") or "")}</p>\n'
        "            </div>\n"
        "            <!-- SSR:HERO:END -->"
    )

    # ── JSON-LD ItemList ──
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Aktuelle KI-News",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": n.get("link") or "https://ki-news.live/",
                "name": n.get("title") or "",
            }
            for i, n in enumerate(news)
        ],
    }
    json_ld = json.dumps(item_list, ensure_ascii=False, indent=2)

    # ── News-Grid ──
    cards = "\n".join("        " + _ssr_card(n) for n in news)
    news_block = (
        "<!-- SSR:NEWS:START -->\n"
        '      <script type="application/ld+json" id="ssr-newslist">\n'
        f"{json_ld}\n"
        "      </script>\n"
        '      <div id="news-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">\n'
        f"{cards}\n"
        "      </div>\n"
        "      <!-- SSR:NEWS:END -->"
    )

    html_txt = index_path.read_text(encoding="utf-8")
    html_txt, n_hero = re.subn(
        r"<!-- SSR:HERO:START -->.*?<!-- SSR:HERO:END -->",
        lambda _m: hero, html_txt, flags=re.DOTALL,
    )
    html_txt, n_news = re.subn(
        r"<!-- SSR:NEWS:START -->.*?<!-- SSR:NEWS:END -->",
        lambda _m: news_block, html_txt, flags=re.DOTALL,
    )
    # Stand-Label-Default (vor JS-Hydration)
    html_txt = re.sub(
        r'(<span id="stand-label"[^>]*>)[^<]*(</span>)',
        lambda m: f"{m.group(1)}Stand: {_html.escape(stand)}{m.group(2)}",
        html_txt,
    )

    if n_hero and n_news:
        index_path.write_text(html_txt, encoding="utf-8")
        logger.info("SSR: index.html aktualisiert (%d News, Stand %s)", len(news), stand)
    else:
        logger.warning("SSR: Marker fehlen (hero=%d, news=%d) – index.html unveraendert", n_hero, n_news)

def inject_admin_posts(base_dir, news_json_data):
    """Aktualisiert den eingebetteten #news-data Block in admin-posts.html."""
    base_dir = Path(base_dir)
    admin_path = base_dir / "admin-posts.html"
    if not admin_path.exists():
        return
    payload = json.dumps(news_json_data, ensure_ascii=False, indent=2)
    html_txt = admin_path.read_text(encoding="utf-8")
    html_txt, n = re.subn(
        r'(<script type="application/json" id="news-data">).*?(</script>)',
        lambda m: f"{m.group(1)}\n{payload}\n{m.group(2)}",
        html_txt, flags=re.DOTALL,
    )
    if n:
        admin_path.write_text(html_txt, encoding="utf-8")
        logger.info("SSR: admin-posts.html aktualisiert (Stand %s)", news_json_data.get("stand",""))
    else:
        logger.warning("SSR: #news-data Marker in admin-posts.html fehlt – unveraendert")

# -------------------------
# Dashboard-Config + Post-Cache
# -------------------------
def load_dashboard_config(base_dir):
    """Lädt dashboard_config.json (featured_links + blocked_links)."""
    path = Path(base_dir) / "dashboard_config.json"
    if not path.exists():
        return {"featured_links": [], "blocked_links": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"featured_links": [], "blocked_links": []}

def load_post_cache(base_dir):
    """Lädt post-cache.json – gespeicherte LLM-Texte pro Artikel-Link."""
    path = Path(base_dir) / "post-cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def load_summary_cache(base_dir):
    """Laedt summary-cache.json - gespeicherte Uebersetzungen (title_de/summary)
    pro Artikel-Link. Laufzeit-Fix (02.07.26): summarize_news() hat bisher bei
    JEDEM Lauf ALLE ~200+ Artikel neu uebersetzt (~55 LLM-Batches, gemessen
    47 min Wartezeit pro Lauf). title_de/summary sind pro Link stabil - einmal
    uebersetzen reicht. Nur echte LLM-Erfolge werden gecacht (kein Fallback),
    damit englische Titel nicht zementiert werden."""
    path = Path(base_dir) / "summary-cache.json"
    if not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # Einmal-Purge (04.07.26): Muse-Spark-Titel wurde trotz Eigennamen-Regel
    # generisch uebersetzt ("...eines neuen KI-Modells mit erweiterten
    # Codierungsfaehigkeiten"); title_de ist pro Link stabil und wuerde sich
    # nie selbst heilen. Eintrag verwerfen -> naechster Lauf uebersetzt neu
    # (mit verschaerfter Regel). Nach ein paar Tagen ersatzlos entfernbar.
    _poisoned = "eines neuen KI-Modells mit erweiterten Codierungsf"
    cache = {k: v for k, v in cache.items()
             if _poisoned not in (v.get("title_de") or "")}
    return cache

def save_summary_cache(base_dir, cache):
    """Speichert summary-cache.json, bereinigt Eintraege aelter als 30 Tage
    (Artikel leben max. 10 Tage im Archiv, 30 ist grosszuegig)."""
    cutoff = (datetime.now(BERLIN) - timedelta(days=30)).strftime("%Y-%m-%d")
    pruned = {link: data for link, data in cache.items()
              if data.get("generated_at", "9999") >= cutoff}
    path = Path(base_dir) / "summary-cache.json"
    try:
        path.write_text(json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("summary-cache.json: %d Eintraege gespeichert", len(pruned))
    except Exception as e:
        logger.exception("Fehler beim Schreiben summary-cache.json: %s", e)

def save_post_cache(base_dir, cache):
    """Speichert post-cache.json, bereinigt Einträge älter als 90 Tage."""
    cutoff = (datetime.now(BERLIN) - timedelta(days=90)).strftime("%Y-%m-%d")
    pruned = {link: data for link, data in cache.items()
              if data.get("generated_at", "9999") >= cutoff}
    path = Path(base_dir) / "post-cache.json"
    try:
        path.write_text(json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("post-cache.json: %d Eintraege gespeichert", len(pruned))
    except Exception as e:
        logger.exception("Fehler beim Schreiben post-cache.json: %s", e)

# -------------------------
# Logging
# -------------------------
LOG_PATH = Path("ki_news.log")
_fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
_fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
_fh.setFormatter(_fmt)
logger = logging.getLogger("ki_news")
logger.setLevel(logging.INFO)
logger.addHandler(_fh)
logger.propagate = False  # Kein Doppel-Logging durch Root-Logger

# -------------------------
# Zeitzone
# -------------------------
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = timezone(timedelta(hours=2))

# -------------------------
# Keys
# -------------------------
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
if not OPENROUTER_KEY:
    cfg = Path.home() / "Documents" / "Projekte" / "ki-news" / "config.txt"
    if cfg.exists():
        try:
            OPENROUTER_KEY = cfg.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Fehler beim Lesen config.txt: %s", e)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "9096438").strip()
GROQ_CHAT_KEY = os.environ.get("GROQ_CHAT_KEY", "").strip()

# -------------------------
# Konfiguration
# -------------------------
# Kurzwörter (ki, ai, llm, gpt) brauchen Wort-Grenzen – sonst matched "Kinostart", "marketing" etc.
# Längere Begriffe (openai, chatgpt, anthropic...) sind sicher als Substring.
KI_KEYWORDS_WORD = {
    # Nur als ganzes Wort matchen (Regex \b...\b)
    "ki", "ai", "llm", "gpt",
}
KI_KEYWORDS_SUBSTR = {
    # Substring-Match ok – lang genug um keine Fehlalarme zu erzeugen
    # Bug-Fix (14.07.26): "model" ENTFERNT - "modell" ist im Deutschen ein
    # generisches Wort (Apple Pencil, Auto, Geschaeftsmodell...), keine
    # KI-spezifische Signatur. "model" matchte als Substring sogar in "modell"
    # und liess so einen Apple-Pencil-Stift-Artikel durch den KI-Relevanzfilter
    # (Fall 14.07.: "...ein neues Modell" -> als "wichtig" gelabelt, obwohl
    # kein KI-Bezug). "sprachmodell" bleibt - das IST spezifisch genug.
    "kunstliche", "künstliche", "intelligenz", "claude",
    "chatgpt", "openai", "google", "meta ai", "agent", "nvidia",
    "anthropic", "gemini", "mistral", "deepseek", "roboter", "automation",
    "sprachmodell", "chatbot", "machine learning", "neural", "generativ",
}

def _is_ki_relevant(title: str) -> bool:
    """Prüft ob ein Titel KI-relevant ist – mit Wortgrenzen für Kurzkürzel."""
    t = title.lower()
    # Substr-Check (unkritische, lange Keywords)
    if any(k in t for k in KI_KEYWORDS_SUBSTR):
        return True
    # Wort-Grenze-Check für ki / ai / llm / gpt
    if any(re.search(r'\b' + re.escape(k) + r'\b', t) for k in KI_KEYWORDS_WORD):
        return True
    return False

# -------------------------
# Wochenzusammenfassungen (Roundups) erkennen
# -------------------------
# Caschy "Immer wieder sonntags KW NN", Heise "Fotonews der Woche", The Batch (weekly)
# usw. Diese Titel sind Multi-Thema und wirken im Clustering als Keyword-Magnet, der
# unzusammenhaengende Artikel kuenstlich in einen Cluster zieht (aufgeblaehter Score) –
# ausserdem sind es keine Breaking-News. Wir trennen sie ab: sie bleiben als Material
# in news.json -> "roundups", landen aber nicht in der News-Liste/Startseite/Breaking.
_ROUNDUP_PATTERN = re.compile(
    r'immer wieder sonntags'
    r'|fotonews der woche'
    r'|\bKW\s?\d{1,2}\b'
    r'|wochenr(ü|ue)ckblick'
    r'|week in review|this week in|the week in ai'
    r'|weekly (recap|roundup|digest|wrap)'
    r'|news der woche|das war die woche'
    # Evergreen-Tracker (z.B. TechCrunch "The Complete List of 2026 Tech
    # Layoffs") sind keine Wochenzusammenfassung, aber dasselbe Grundproblem:
    # Multi-Themen-Sammelartikel ohne konkretes Einzelereignis, der als
    # Keyword-Magnet Cluster aufbläht und ohne Namen/Specifics als Breaking-
    # Karte nichtssagend wirkt. Beobachtet: "Die fortlaufende Liste: große
    # Entlassungen..." rutschte durch, weil kein "week"/"KW"-Muster passte.
    r'|the (complete|full|ongoing|running) list|layoff tracker|\btracker\b'
    r'|fortlaufende liste|laufend aktualisiert',
    re.I,
)
_ROUNDUP_SOURCES = {"The Batch"}

def _is_roundup(news_item) -> bool:
    """True wenn der Eintrag eine Wochenzusammenfassung ist (Titel-Muster oder Quelle)."""
    if news_item.get("source") in _ROUNDUP_SOURCES:
        return True
    return bool(_ROUNDUP_PATTERN.search(news_item.get("title", "")))

def _is_ad(news_item) -> bool:
    """Werbung/Sponsored erkennen – z.B. Golem 'Anzeige: ...'. Nur Titel, die DAMIT
    ANFANGEN, damit echte News wie 'Immobilienanzeigen' nicht getroffen werden."""
    t = (news_item.get("title", "") or "").strip().lower()
    return (t.startswith("anzeige:") or t.startswith("anzeige ")
            or t.startswith("[anzeige]") or t.startswith("sponsored")
            or t.startswith("werbung:"))

FEEDS = [
    # Deutsch
    ("The Decoder", "https://the-decoder.de/feed/"),
    ("Heise",       "https://www.heise.de/newsticker/heise.rdf"),
    # Regional Sachsen, via Google News RSS (kein eigener KI-Feed vorhanden -
    # +KI im Query filtert grob vor, regional_score() filtert danach nochmal).
    # Quelle/Idee: Daniel, 26.06.26 (Zukunftsblog = Sächs. Staatsministerium f.
    # Wirtschaft; live getestet, beide liefern echte KI-relevante Treffer).
    ("Zukunftsblog Sachsen",  "https://news.google.com/rss/search?q=site:smwa.sachsen.de+KI&hl=de&gl=DE&ceid=DE:de"),
    ("Sächsische Zeitung KI", "https://news.google.com/rss/search?q=site:saechsische.de+KI&hl=de&gl=DE&ceid=DE:de"),
    ("Golem",       "https://rss.golem.de/rss.php?feed=RSS2.0"),
    ("Caschy Blog", "https://stadt-bremerhaven.de/feed/"),
    # Englisch – AI-spezifische Feeds bevorzugt
    ("TechCrunch AI",  "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Ars Technica",   "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Wired",          "https://wired.com/feed/rss"),
    ("The Verge",      "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("CNBC", 		"https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("SiliconAngle",   "https://siliconangle.com/feed"),
    # 22.08.26: Direktfeed gab in 10 von 10 Laeufen HTTP 403 -- TechRepublic
    # sperrt GitHub-Actions-IPs grundsaetzlich. Der Umweg ueber Google News
    # funktioniert (live geprueft: 101 Eintraege), genau wie bei Bloomberg,
    # WSJ, Reuters und FT weiter oben, die aus demselben Grund so eingebunden
    # sind.
    ("TechRepublic",   "https://news.google.com/rss/search?q=site:techrepublic.com+AI&hl=en&gl=US&ceid=US:en"),
    # Paywall-Quellen via Google News RSS
    ("Reuters AI",   "https://news.google.com/rss/search?q=site:reuters.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("Bloomberg AI", "https://news.google.com/rss/search?q=site:bloomberg.com+AI&hl=en&gl=US&ceid=US:en"),
    ("WSJ AI",       "https://news.google.com/rss/search?q=site:wsj.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("FT AI",        "https://news.google.com/rss/search?q=site:ft.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("Economist AI", "https://news.google.com/rss/search?q=site:economist.com+artificial+intelligence&hl=en&gl=US&ceid=US:en"),
    ("CNet", 		"https://www.cnet.com/rss/all/"),
    ("MIT", 		"https://www.technologyreview.com/feed/"),
    ("NYT Technology",  "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("OpenAI",         "https://openai.com/blog/rss.xml"),
    # Kuratiert – bereits AI-spezifisch, kein KI-Filter nötig
    ("AlignedNews",    "https://alignednews.com/feed"),
    # Primärquellen – Lab-Announcements direkt (via Olshansk/rss-feeds, stündlich aktualisiert)
    ("Anthropic News",     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml"),
    ("Anthropic Research", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml"),
    ("Meta AI Blog",       "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml"),
    ("Google AI Blog",     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_google_ai.xml"),
    ("xAI News",           "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_xainews.xml"),
    ("Mistral News",       "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_mistral.xml"),
    ("The Batch",          "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_the_batch.xml"),
    # Hardware / AI-Hardware (Computex, AI-Laptops, Server)
    ("WCCFtech",           "https://wccftech.com/feed/"),
    # Kuratiertes Signal, kein eigener RSS-Feed, aber ueber Google News site:-Suche
    # erreichbar (Fund 01.07.26, Daniel): Digg (Relaunch) aggregiert, was fuehrende
    # AI/Tech-Koepfe auf X teilen (@ylecun, @levie, @nathanbenaich ua.) - fing die
    # Fable-5-Jailbreak-Abschaltung frueher als die Presse-Feeds.
    ("Digg AI",             "https://news.google.com/rss/search?q=site:digg.com+AI&hl=en&gl=US&ceid=US:en"),
    # Chinesische Labs (Luecke geschlossen 17.07.26, Anlass: Kimi K3 fehlte komplett
    # in Top Storys, siehe Kontext-Chat). GitHub-Releases-Ansatz getestet und verworfen:
    # MoonshotAI/zai-org/QwenLM nutzen kein GitHub-Release-Feature, nur deepseek-ai
    # hat einen einzelnen archivarischen Tag (nicht als laufender Kanal geeignet).
    # Kill-Switch: <2 wirklich neue (nicht schon anderweitig abgedeckte) Storys/Woche
    # nach 7 Tagen -> Zeilen wieder raus.
    ("China AI Labs",  "https://news.google.com/rss/search?q=%22Moonshot+AI%22+OR+%22DeepSeek%22+OR+%22Alibaba+Qwen%22+OR+%22Zhipu+AI%22+OR+%22GLM-5%22+OR+%22MiniMax%22&hl=en&gl=US&ceid=US:en"),
    ("Qwen Blog",      "https://qwenlm.github.io/blog/index.xml"),  # nativer Hugo-RSS-Feed, verifiziert 17.07.26
    ("Kimi Blog",      "https://news.google.com/rss/search?q=site:kimi.com/blog&hl=en&gl=US&ceid=US:en"),  # kein natives RSS an kimi.com/blog, echte Quelle verifiziert (K3-Post datiert 14.07.26)
]

# News, die an den LLM fuer Posts/Einordnungen gehen.
# 02.07.26: 3 -> 5, damit jede der 5 Top-Karten der Startseite eine
# Scampy-Einordnung bekommt (Daniels Feedback: "nicht jede News oben hat
# eine Analyse"). Kosten sind mit dem Summary-Cache vernachlaessigbar.
# Nebenwirkung, bewusst akzeptiert: bis zu 5 statt 3 Telegram-Nachrichten
# pro Lauf mit neuen Stories. Der alte Hinweis "mehr = generischer
# Fuelltext" galt fuer einen einzelnen Prompt mit vielen News - ask_llm
# bekommt weiterhin nur die UNCACHED Stories (meist 1-2 pro Lauf).
MAX_LLM_NEWS = 5

MODELLE = [
    # Free-Modelle – Gemma zuerst (empirisch: llama/hermes dauerhaft auf 429)
    "google/gemma-4-31b-it:free",                      # Gemma 4 31B – zuverlässigster Free-Slot
    "google/gemma-4-26b-a4b-it:free",                  # Gemma 4 26B Fallback
    # 14.08.26: meta-llama/llama-3.3-70b-instruct:free und
    # nousresearch/hermes-3-llama-3.1-405b:free entfernt - Live-Check gegen
    # OpenRouter /api/v1/models (14.08.26) zeigt: beide :free-Varianten
    # existieren nicht mehr im Katalog, nur noch die bezahlten IDs ohne
    # ":free"-Suffix. Jeder Aufruf lieferte seit mind. 12.08. durchgehend
    # HTTP 404 (kein Rate-Limit, echtes Modell-Ende) - reiner Zeitverlust
    # pro Batch. Siehe ki_news.log 12.-14.08.
    # 14.08.26: neue Free-Modelle nach Live-Check gegen den echten OpenRouter-
    # Katalog + echtem Testaufruf im Produktions-Batch-Format (4 Items,
    # max_tokens=1500) hinzugefuegt. gpt-oss-20b lief im Test sofort sauber
    # (JSON vollstaendig, 4/4 ids, echtes Deutsch). Die vier Nemotron-Modelle
    # brauchten dafuer den reasoning:{enabled:false}-Schalter in
    # _call_llm_api() (sonst verbrennen sie das ganze Token-Budget im
    # unsichtbaren Denkprozess und liefern nie die Antwort) - siehe Kommentar
    # dort. Alle 5 danach live verifiziert: vollstaendiges 4/4-JSON, deutsch.
    # 22.08.26: openai/gpt-oss-20b:free ENTFERNT. Es war bis zum 21.08. der
    # Arbeitspferd-Slot (die meisten "Batch N OK mit ..."-Zeilen im Log liefen
    # darueber), ist seitdem aber aus dem OpenRouter-Katalog verschwunden --
    # Live-Abgleich gegen /api/v1/models am 22.08.: nicht mehr vorhanden.
    # Danach 63x HTTP 404 + 52x leere Antwort + 7x 429 in einem Log-Fenster,
    # zusammen rund 135 Fehlaufrufe. Sein Wegfall ist auch die Ursache dafuer,
    # dass Uebersetzungen scheiterten und Artikel still verworfen wurden.
    # 26.08.26 NEU, live im Produktions-Batch-Format vermessen (4 Titel,
    # max_tokens=1500, derselbe Prompt-Aufbau wie summarize_news):
    #   minimax/minimax-m3:free                2.9s  4/4  sauberes Deutsch
    #   nvidia/nemotron-3-ultra-550b-a55b:free 3.1s  4/4  sauberes Deutsch (reasoning:false)
    # Beide vor gemma einzusortieren waere falsch -- gemma ist im Zweifel
    # besser im Deutschen; sie stehen hier als erste ECHTE Auffangstufe, weil
    # gemma/glm im Messfenster 25.-26.08. zu ueber 90% auf 429 liefen.
    # Ebenfalls im selben Test durchgefallen, deshalb NICHT aufgenommen:
    #   dots-studio/dots-3-note-preview:free   1500 Tokens verbrannt, Antwort leer
    #   thinkingmachines/inkling(-small):free  HTTP 403 (kein Zugang mit diesem Key)
    #   minimax/minimax-m2.7:free              4/4, aber 22.9s -- zu langsam als Free-Slot
    "minimax/minimax-m3:free",                          # 26.08. gemessen: 2.9s, 4/4, 1M Kontext
    "nvidia/nemotron-3-ultra-550b-a55b:free",           # 26.08. gemessen: 3.1s, 4/4, mit reasoning:false
    "z-ai/glm-5.2:free",                                # 22.08.26 neu im Katalog, 256k Kontext
    "nvidia/nemotron-3-super-120b-a12b:free",           # 22.08. live nachgetestet: 4/4 sauberes Deutsch
    # 26.08.26 ENTFERNT: nvidia/nemotron-3-nano-30b-a3b:free und
    # nvidia/nemotron-nano-9b-v2:free. Beide seit dem 22.08. nicht mehr im
    # OpenRouter-Katalog (live gegen /api/v1/models geprueft) - im Log-Fenster
    # 25.-26.08. zusammen 104x HTTP 404, kein einziger Treffer. modell_check.py
    # hat sie in JEDEM CI-Lauf gemeldet, aber der Schritt laeuft mit
    # continue-on-error und ohne --streng: der Befund stand nur in der
    # Actions-Ausgabe, die niemand liest. Siehe Workflow-Aenderung vom 26.08.
    # 26.08.26 abends ENTFERNT: nvidia/nemotron-3.5-lightning:free.
    # Bilanz ueber zwei Log-Fenster: 25./26.08. 52x "Expecting value: line 1
    # column 1" (= leere/kaputte Antwort), 26.08. nach dem Umbau nochmal 10x
    # derselbe Fehler. In Summe 62 Versuche, NULL erfolgreiche Batches. Der
    # reasoning:false-Schalter greift, es liefert trotzdem nichts. Steht nur
    # noch als Latenz in der Kaskade.
    # Ebenfalls beobachtet, aber (noch) drin: nvidia/nemotron-3-ultra-550b-a55b:free.
    # Im Einzeltest 3.1s und 4/4, im Produktionslauf vom 26.08. nur 1 Treffer
    # bei 10 Versuchen (4x leerer Content, 3x abgeschnittener JSON-String,
    # 2x Sprachmix). Lehre fuer den naechsten Modelltausch: ein Einzelaufruf
    # sagt wenig, weil er weder Rate-Limit noch Lastspitze sieht. Erst nach
    # einem vollen Tag beurteilen, nicht nach einem Nachmittag.
    # stealth/ox-alpha (22.08.26): anonymes Testmodell bei OpenRouter, gratis
    # bei 1M Kontext. Live geprueft, Ergebnis gemischt:
    #   Uebersetzung (1500 Tokens): 4/4, sauberes Deutsch -- aber 24,5 Sekunden.
    #                               Zum Vergleich: gemini-lite 2,3s, qwen 3,7s.
    #   Scoring (150 Tokens):       LEER, 150 Tokens im Reasoning verbraucht.
    #   reasoning:{enabled:false}:  HTTP 400 "Reasoning is mandatory for this
    #                               endpoint and cannot be disabled."
    # Deshalb ABSICHTLICH als LETZTES Free-Modell und NICHT in MODELLE_POSTS:
    # dort laufen die 150-Token-Aufrufe von score_cluster_llm, und der Schalter,
    # der die Nemotrons rettet, greift hier nicht.
    # Zwei Dinge im Blick behalten: Stealth-Modelle verschwinden ohne Ankuendigung
    # (genau das ist gpt-oss-20b:free am 21.08. passiert), und der Anbieter ist
    # anonym -- was hier an Prompts hingeht, sind oeffentliche Schlagzeilen,
    # nichts Vertrauliches. Faellt es weg, greift einfach der naechste Eintrag.
    # 26.08.26 abends ENTFERNT: stealth/ox-alpha ist aus dem Katalog
    # verschwunden (modell_check.py meldet es als TOT, live gegen
    # /api/v1/models geprueft) - im Nachmittagslauf 10x HTTP-Fehler, 0 Treffer.
    # Genau die Lebensdauer, die der Kommentar oben vorhergesagt hat: vier
    # Tage. Stealth-Slots sind Leihgaben, keine Infrastruktur.
    # Kostenpflichtige Anker - nur wenn alle Free-Modelle 429 oder leer liefern.
    # 22.08.26 im Batch-Format live vermessen (4 Artikel, max_tokens=1500):
    #   qwen3.7-flash          $0.03/$0.13 je 1M   3.7s   4/4 sauber
    #   gemini-2.5-flash-lite  $0.10/$0.40 je 1M   2.3s   4/4 sauber
    #   llama-3.3-70b-instruct $0.10/$0.32 je 1M          bisheriger Anker
    # qwen zuerst: rund dreimal billiger als llama bei gleicher Qualitaet.
    # Hochgerechnet auf vier Laeufe taeglich liegt der Monatspreis bei etwa
    # $0.40 (qwen) bzw. $1.20 (gemini-lite) -- die teureren Gemini-3.x-Modelle
    # koennen dasselbe, kosten aber das Zehnfache und sind hier nicht noetig.
    # 26.08.26: qwen/qwen3.7-flash ENTFERNT. Der Kommentar vom 22.08. oben
    # sagt, es liefere bei 1500 Tokens sauber -- das Log widerlegt das:
    # 44x "leerer Content (Reasoning-Budget aufgebraucht?)" im Fenster
    # 25.-26.08., kein einziger Treffer. Das sind BEZAHLTE Aufrufe ohne
    # jedes Ergebnis, im Uebersetzungs-Pfad mit vollem 1500-Token-Budget.
    # Das reasoning:{enabled:false}-Gegenmittel greift nur fuer nvidia/.
    # Wieder aufnehmen erst nach erneuter Live-Messung, nicht auf Verdacht.
    "google/gemini-2.5-flash-lite",                     # Haupt-Anker: 26 von 44 erfolgreichen Batches (25.-26.08.)
    "meta-llama/llama-3.3-70b-instruct",               # bisheriger Anker
    "google/gemma-3-27b-it",                            # Letzter Fallback
]

# NEU: Separate Modellliste für Post-Generierung
# Gemma-4-31b schreibt bessere deutsche Posts als Llama – empirisch aus Logs bestätigt.
# Reihenfolge bewusst anders als MODELLE: Gemma zuerst, Llama als Fallback.
MODELLE_POSTS = [
    "google/gemma-4-31b-it:free",                      # Beste Posts-Qualität (DE-Format, Scampy-6)
    "google/gemma-4-26b-a4b-it:free",                  # Gemma-Fallback
    # 14.08.26: :free-IDs von llama-3.3-70b-instruct/hermes-3-405b entfernt,
    # siehe Begruendung bei MODELLE oben - identischer Befund (100% 404).
    # gpt-oss-20b ergaenzt (live getestet, siehe MODELLE oben) - die Nemotron-
    # Modelle bewusst NICHT hier: diese Liste bedient auch score_cluster_llm
    # mit nur 150 Tokens Budget, dort noch nicht gegen reasoning:false getestet.
    # 22.08.26: gpt-oss-20b:free entfernt, Begruendung bei MODELLE oben.
    # Nemotron bleibt auch hier draussen -- diese Liste bedient score_cluster_llm
    # mit nur 150 Tokens Budget, und dort verbrennen Reasoning-Modelle alles.
    #
    # qwen/qwen3.7-flash steht aus genau demselben Grund NICHT hier, obwohl es
    # in MODELLE der billigste Anker ist. Nachgemessen am 22.08. im echten
    # 150-Token-Pfad: Antwort leer, completion_tokens=152, davon
    # reasoning_tokens=150 -- das gesamte Budget im unsichtbaren Denken
    # verbraucht, wie bei den Nemotrons. Bei 1500 Tokens (MODELLE) liefert es
    # dagegen sauber. Hier waere es ein BEZAHLTER Aufruf ohne jedes Ergebnis.
    # Der reasoning:{enabled:false}-Schalter greift nur fuer nvidia/-Modelle,
    # siehe _call_llm_api().
    #
    # gemini-2.5-flash-lite dagegen im selben Test: '85' nach 2 Tokens, 1.2s,
    # reasoning_tokens=0. Passt.
    "google/gemini-2.5-flash-lite",                     # 150-Token-Pfad live geprueft
    "meta-llama/llama-3.3-70b-instruct",               # bisheriger Paid-Anker, ebenfalls geprueft
    "google/gemma-3-27b-it",                            # Letzter Fallback
]

# 429-Circuit-Breaker (02.07.26): gemma-4-31b:free ist praktisch dauerhaft
# rate-limited, wurde aber von JEDEM Batch erneut zuerst probiert - Messung
# (Log 02.07., 05:00-Lauf): 47 von 55 Minuten Laufzeit waren 429-Fehlversuche
# plus Latenz der Fallback-Modelle. Nach N aufeinanderfolgenden 429 desselben
# Modells wird es fuer den REST DES LAUFS uebersprungen (in-memory, kein State).
_MODEL_429_STREAK = {}
_MODEL_429_LIMIT = 3

# ── Lauf-Bilanz (26.08.26) ───────────────────────────────────────────────
# Warum: die Modellliste ist zwischen dem 21. und 25.08. lautlos zerfallen --
# sieben von zwoelf Eintraegen lieferten nichts mehr, ein einziges Modell
# (gemini-2.5-flash-lite) trug 26 von 44 erfolgreichen Batches. Sichtbar war
# das nur, wenn man 532 Batch-Zeilen im Log auszaehlt. Genau das hat niemand
# getan, und die Degradation lief fuenf Tage. Diese eine Zeile am Laufende
# macht daraus einen Blick:
#   BILANZ: Batches 12/9 OK | Traeger: gemini-2.5-flash-lite 7x, ... | Guard verwarf 3 Artikel
# Faustregel fuer den taeglichen Check: traegt EIN Modell mehr als die Haelfte
# der Batches, ist die Liste schon halb tot -- unabhaengig davon, ob im Log
# eine Exception steht.
_BATCH_VERSUCHE = 0
_BATCH_OK = {}          # modell -> Anzahl erfolgreicher Batches
_GUARD_VERWORFEN = 0    # Artikel, die der Sprach-Guard aus news.json geworfen hat

def _model_blocked(model):
    return _MODEL_429_STREAK.get(model, 0) >= _MODEL_429_LIMIT

def _model_note_429(model):
    _MODEL_429_STREAK[model] = _MODEL_429_STREAK.get(model, 0) + 1
    if _MODEL_429_STREAK[model] == _MODEL_429_LIMIT:
        logger.warning("Modell %s: %dx 429 in Folge - wird fuer den Rest des Laufs uebersprungen",
                       model, _MODEL_429_LIMIT)

def _model_note_ok(model):
    _MODEL_429_STREAK[model] = 0

# NEU: Ollama – lokaler Provider (wird automatisch erkannt, GitHub Actions ignoriert das)
# Setup: https://ollama.ai → `ollama pull gemma3:27b` oder `ollama pull gemma2:27b`
# Wenn OLLAMA_HOST gesetzt ist UND ein Server antwortet, werden Ollama-Modelle
# an ERSTER Stelle in MODELLE_POSTS eingefügt (kein Rate-Limit, kostenlos).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODELS_POSTS = [
    "ollama/gemma3:27b",    # Beste Qualität lokal
    "ollama/gemma2:27b",    # Fallback
    "ollama/llama3.3:70b",  # Llama lokal
]

def _detect_ollama_models():
    """Prüft welche Ollama-Modelle lokal verfügbar sind. Gibt [] zurück wenn kein Server."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
            available = {m["name"].split(":")[0] for m in data.get("models", [])}
            matched = []
            for om in OLLAMA_MODELS_POSTS:
                name = om.replace("ollama/", "").split(":")[0]
                if name in available:
                    matched.append(om)
            if matched:
                logger.info("Ollama verfügbar – %d Modelle: %s", len(matched), matched)
            return matched
    except Exception:
        return []  # Kein Ollama-Server – kein Problem

SOURCE_COLORS = {
    "The Decoder": "#1d9bf0",
    "TechCrunch AI": "#ff6b35",
    "Ars Technica": "#16a34a",
    "MIT Tech Review": "#dc2626",
    "Heise": "#ca8a04",
}

THREAD_LABELS = ["Hook", "Kontext", "Kaskade", "Gruselig", "Konsequenz", "Fazit"]

# -------------------------
# NEU: Story-Scoring & Clustering
# -------------------------

# Quellen-Prestige: höhere Zahl = glaubwürdiger / reichweitenstärker
SOURCE_PRESTIGE = {
    "Bloomberg":      5,
    "The Decoder":    5,
    "TechCrunch AI":  5,
    "Heise":          5,
    "Ars Technica":   5,
    "Wired":          5,
    "The Verge":      5,
    "Golem":          5,
    "SiliconAngle":   5,
    "TechRepublic":   5,
    "Caschy Blog":    5,
    "CNet":	      5,
    "CNBC":           5,
    "NYT Technology":  5,
    # Gizmodo entfernt (blockiert GitHub Actions)
    # Primärquellen (direkt vom Hersteller) – höher gewichtet als Media
    "Anthropic News":     10,
    "Anthropic Research": 10,
    "Meta AI Blog":       10,
    "Google AI Blog":     10,
    "xAI News":           10,
    "Mistral News":       10,
    "OpenAI":             10,
    "The Batch":          5,
}

# Wichtigkeits-Keywords → Punktebonus
# Tuple: (keyword, punkte)
IMPORTANCE_KEYWORDS = [
    # Mega-Events (15 Punkte) – echte Nachricht, nicht nur ein Update
    ("ban", 15), ("banned", 15), ("verboten", 15), ("lawsuit", 15), ("klage", 15),
    ("billion", 15), ("milliard", 15), ("fired", 15), ("entlassen", 15),
    ("merger", 15), ("acqui", 15), ("übernimmt", 15), ("shutdown", 15),
    ("regulation", 15), ("gesetz", 15), ("verbot", 15),
    ("valuation", 15), ("bewertung", 15),
    # Neue Modelle / Fähigkeiten – KERN einer KI-News-Seite, höher als Finanzierung.
    # Bug-Fix (14.07.26): nackte "model"/"modell"-Treffer entfernt - zu generisch
    # (matcht Apple Pencil, Autos, Geschaeftsmodelle...), s. Kommentar bei
    # KI_KEYWORDS_SUBSTR. Die verbleibenden Begriffe sind spezifisch genug, um
    # echte Modell-Launches ohne Fehlalarme zu erkennen.
    ("open-weight", 12), ("open weight", 12),
    ("state-of-the-art", 12), ("outperforms", 10), ("übertrifft", 8), ("beats", 8),
    ("open source", 10), ("open-source", 10),
    # Wichtige Ereignisse (10 Punkte)
    ("launch", 10), ("release", 10), ("veröffentlicht", 10), ("vorgestellt", 10),
    ("unveils", 10), ("introduces", 8), ("einführung", 8),
    ("breakthrough", 10), ("durchbruch", 10), ("opens", 8), ("patent", 10),
    # Finanzierung ENTSCHÄRFT: kleine Seed/Series-A-Runden sind Nebengeräusch.
    # Nur große Runden bleiben über "billion"/"valuation" oben. "million" entfernt
    # (war Haupttreiber für No-Name-Startup-Rauschen vor Modell-News).
    ("funding round", 5), ("raises $", 5), ("funding", 3), ("investment", 5), ("raises", 3),
    # Interessante Entwicklungen (5 Punkte)
    ("study", 5), ("studie", 5), ("research", 5), ("warnt", 5),
    ("kritik", 5), ("erstmals", 5), ("kostenlos", 5),
]


# -------------------------
# Release-Signatur (Fix 18.08.26, V2)
# -------------------------
# score_cluster() ist der Tuersteher fuer die LLM-Bewertung (pick_top_news:
# nur die Top-N nach Legacy-Score bekommen einen LLM-Call). Seit dem
# 14.07.-Fix, der "model"/"modell" als zu generisch entfernte, gibt es kein
# Signal mehr fuer "hier erscheint ein neues Modell". Eine Hersteller-
# Ankuendigung am Tag 0 hat 1 Quelle -> ~25 Punkte -> unter der Schwelle.
# Gemessen an archive.json (08.-18.08.): 105 Artikel auf base_score 25,
# darunter 12 echte Launches ("Claude Opus 5 wird vorgestellt" = Rang 114/155).
#
# Der Bonus ist KEIN Ranking, sondern ein Kandidatenfilter: er oeffnet die
# Tuer zur LLM-Bewertung. Ein Fehltreffer kostet einen LLM-Call, keine
# Sichtbarkeit — das LLM stuft ihn danach selbst zurueck.
#
# Bewusst NICHT wieder eingefuehrt: nacktes "model"/"modell". Die Signatur
# verlangt ein Release-Verb UND (Modellfamilie ODER Herstellerquelle) —
# der Apple-Pencil-Fehlalarm vom 14.07. erfuellt das nicht.

FIRST_PARTY_SOURCES = {
    "OpenAI", "Anthropic News", "Anthropic Research", "Meta AI Blog",
    "xAI News", "Mistral News", "Qwen Blog", "Kimi Blog",
    "Google AI Blog", "DeepMind",
}

# Trennbare Verben als Satzklammer suchen, NICHT mit fester Wortdistanz:
# "xAI stellt Grok Build vor" hat zwei Woerter dazwischen, "Google stellt das
# neue Gemini 3.7 Flash Modell fuer Programmierung und KI-Agenten vor" acht.
RELEASE_TRENNBAR = re.compile(
    r"(stellt\b.*\bvor\b|führt\b.*\bein\b|bringt\b.*\b(heraus|auf den markt)\b)", re.I)

RELEASE_DIREKT = re.compile(
    r"(vorgestellt|vorstellung von|veröffentlicht|veroeffentlicht|eingeführt|"
    r"launcht|launches|unveils|introduc\w+|debuts|releases?|ist da|is here|"
    r"jetzt verfügbar|now available|ab sofort verfügbar|angekündigt|startet)", re.I)

MODELL_FAMILIEN = re.compile(
    r"\b(gpt|claude|gemini|llama|mistral|qwen|deepseek|grok|kimi|glm|opus|"
    r"sonnet|haiku|muse|sora|veo|imagen|flux|nova|command|phi|falcon|voxtral|"
    r"nemotron|daybreak|mai-code|seedance|minimax)\b", re.I)

# An echten Fehltreffern kalibriert: trotz Release-Verb kein Produkt-Launch.
KEIN_LAUNCH = re.compile(
    r"(preisgestaltung|preise|preis|abrechnung|tarif|"
    r"forschungsartikel|forschungsagenda|technische blogs|whitepaper|"
    r"bösartig|angriff|schwachstelle|sicherheitsvorfall|"
    r"einheit|abteilung|team|stellt\s+\S+\s+ein\b|einstellung|"
    r"meetup|hackathon|summit|konferenz|webinar)", re.I)

# Hersteller-Case-Studies: Marketing im Nachrichtenkanal. Greift unabhaengig
# davon, ob der Satz mit "Wie" beginnt. Partnerschafts- und Kooperations-
# meldungen bekommen bewusst KEINEN Malus — die sind oft echte News.
CASE_STUDY = re.compile(
    r"(wie\s+\S+.*(nutzt|verwendet|transformiert|optimiert|einsetzt)|"
    r"case study|customer story|erfahrungsbericht|customer journey|"
    r"\b(optimiert|transformiert|automatisiert|beschleunigt)\b.*"
    r"\bmit\s+(chatgpt|claude|gemini|copilot|mistral|grok)\b)", re.I)

RELEASE_BONUS = 20
CASE_STUDY_MALUS = -10


def _release_signal(all_titles: str, sources=()) -> int:
    """Punkte fuer 'hier erscheint ein neues Modell/Produkt'.

    all_titles ist lowercase (kommt aus score_cluster), sources ist die Menge
    der Quellennamen im Cluster.
    """
    if CASE_STUDY.search(all_titles):
        return CASE_STUDY_MALUS
    if KEIN_LAUNCH.search(all_titles):
        return 0
    if not (RELEASE_TRENNBAR.search(all_titles) or RELEASE_DIREKT.search(all_titles)):
        return 0
    if MODELL_FAMILIEN.search(all_titles):
        return RELEASE_BONUS
    if any(s in FIRST_PARTY_SOURCES for s in sources):
        return RELEASE_BONUS
    return 0


# Malus-Keywords → Punkteabzug (senkt Score, filtert nicht hart aus)
# Tuple: (keyword, punkte)
PENALTY_KEYWORDS = [
    # Heise-Selbstvermarktung
    ("webinar", -30), ("academy", -30), ("online-kurs", -25), ("anmeldung", -20),
    ("schulung", -25), ("zertifikat", -20), ("workshop", -15),
    # Gaming / Hardware ohne KI-Relevanz
    ("gaming", -20), ("esports", -30), ("playstation", -30), ("xbox", -30),
    ("nintendo", -30), ("benchmark", -5), (" fps", -20), ("game pass", -30),
    ("grafikkarte test", -20), ("monitor test", -20),
    # Gaming/Entertainment-Genre (Spiele-News ohne echte KI-Relevanz, z.B.
    # "Fantasy-Spiel mit KI-NPCs"). Senkt den Score, filtert nicht hart raus.
    ("open-world", -15), ("open world", -15), ("fantasy", -15), (" rpg", -15),
    ("videospiel", -15), ("video game", -15), ("videogame", -15),
    ("dungeon", -15), ("spieler", -10), ("zähmen", -10),
    # Deals / Commerce
    (" sale", -20), ("deal:", -20), ("discount", -20), ("angebot:", -20),
    ("best buy", -25), ("preis fällt", -15),
    # Gerüchte ohne Substanz
    ("rumor:", -10), ("leak:", -10), ("leaked:", -10), ("könnte kommen", -10),
    # Persoenliche Reaktions-/Meinungs-Posts statt echter News (typisch fuer
    # X-Aggregatoren wie AlignedNews: "Scoble Reacts to...", "X Promotes Y...").
    # Senkt Score, filtert nicht hart raus - falls doch mal wichtig genug.
    ("reacts to", -15), ("promotes", -20), ("offers $", -10),
    ("aligned news", -30),
    # Veranstaltungswerbung (Fund 22.08.26): vier "AI Tinkerers"-Meldungen zu
    # verschiedenen Staedten (Munich, Wellington, Osaka, Seattle) und eine
    # Peking-Barmeldung standen gleichzeitig im Bestand. Der KI-Keyword-Filter
    # greift korrekt -- es SIND KI-Themen -- aber es sind Einladungen, keine
    # Nachrichten. "meetup" steht bereits in KEIN_LAUNCH, das verhindert nur
    # den Release-Bonus und senkt den Score nicht.
    # Eng gefasst (Nachschaerfung 22.08.26 nach Pruefung): die erste Fassung
    # hatte "teilnahme an", "meetup" und "tickets" allein stehen. Das haette
    # echte Nachrichten getroffen -- "EU-Kommission bestaetigt Teilnahme an
    # KI-Sicherheitsgipfel", "Support-Tickets werden von KI beantwortet",
    # "Meetup-Plattform integriert KI-Empfehlungen". Jetzt matchen nur noch
    # Formulierungen, die als Einladung nicht misszuverstehen sind.
    ("ai tinkerers", -30), ("nehmen sie an", -25), ("nehmen sie am", -25),
    ("rsvp", -30), ("jetzt anmelden", -25),
    ("teilnahme an ai ", -25), ("teilnahme am meetup", -25),
    ("meetup in ", -25), ("tickets sichern", -20), ("jetzt tickets", -20),
]

# Score-Labels für Telegram-Log und news.json
# Schwellen angehoben (04.07.26, Backtest 21.06.-01.07. gegen archive.json):
# episch>=40 gab je nach Tag 3-25% "BREAKING" (instabil, entwertet den Begriff),
# >=55 liefert stabil 0-6/Tag - selbst an den Cluster-Inflationstagen 22.-25.06.
# ACHTUNG: Frontend-Pendants in index.html (scoreToLevel, scoreBadge) fuehren
# dieselben Schwellen hartkodiert - immer zusammen aendern!
SCORE_LABELS = [
    (55, "🔥 episch"),
    (35, "⚡ wichtig"),
    (0,  "📰 normal"),
]

# Firmen-Namensvarianten, die im Cluster-Matching als zwei verschiedene
# Firmen erscheinen, obwohl es dieselbe ist (Kurzname vs. offizieller Name).
# Fund 26.06.: "ON Semiconductor" (CNBC) und "Onsemi" (SiliconAngle) teilten
# bei derselben Synaptics-Uebernahme nur 1 Keyword ("synaptics") -> Cluster-
# Schwelle (>=2) verfehlt, zwei Karten fuer eine Story. Liste bei Bedarf
# erweitern (gleiches Pattern wie SACHSEN_KW).
COMPANY_ALIASES = {
    "onsemi": "on semiconductor",
}


def _normalize_company_aliases(text):
    t = text.lower()
    for alias, canonical in COMPANY_ALIASES.items():
        t = re.sub(rf"\b{re.escape(alias)}\b", canonical, t)
    return t


def _title_keywords(title):
    """Extrahiert bedeutsame Wörter aus einem Titel (min. 4 Zeichen, keine Stopwörter)."""
    STOPWORDS = {
        "die", "der", "das", "ein", "eine", "und", "oder", "mit", "von", "für",
        "auf", "in", "an", "bei", "zu", "ist", "sind", "hat", "wird", "nach",
        "the", "a", "an", "of", "in", "to", "for", "on", "with", "and", "or",
        "is", "are", "new", "its", "their", "by", "as", "at", "from", "that",
        "this", "was", "has", "have", "will", "über", "nach", "beim", "auch",
        # Generische Finanz-/Füllwörter: clusterten unzusammenhängende Startup-/Finanz-
        # Meldungen zu einem Müll-Cluster zusammen (z.B. alle "X sammelt Y Millionen").
        "million", "millionen", "milliarde", "milliarden", "dollar", "euro", "startup",
        "startups", "prozent", "percent", "raises", "funding", "sammelt", "series",
    }
    words = re.findall(r'\b\w{4,}\b', _normalize_company_aliases(title))
    return {w for w in words if w not in STOPWORDS}

# Tokens für Bigram-Bildung: inkl. Zahlen/Versionen (z.B. "2.5", "gpt"), min. 3 Zeichen.
_BIGRAM_STOP = {
    "die","der","das","ein","eine","und","oder","mit","von","für","fur","auf","im","in",
    "den","des","dem","zu","ist","sind","wie","sich","the","a","an","of","to","for","on",
    "with","and","or","is","are","new","its","their","by","as","at","from","that","this",
    "million","millionen","milliarde","milliarden","dollar","euro","startup","startups",
    "prozent","percent","raises","funding","sammelt","series",
}

def _title_tokens(title):
    return [w for w in re.findall(r'[a-z0-9äöüß\.]{3,}', _normalize_company_aliases(title)) if w not in _BIGRAM_STOP]

def _title_bigrams(title):
    """Gemeinsame 2-Wort-Phrasen – ein distinktiverer Cluster-Anker als Einzelwörter."""
    t = _title_tokens(title)
    return set(zip(t, t[1:]))

# Token, das in <= so vielen Titeln vorkommt, gilt als distinktiv (Produkt-/Eigenname).
CLUSTER_RARE_DF_MAX = 3
# Harter Deckel gegen Schneeball-Cluster (03.07.26): mehr Artikel nimmt ein
# Cluster nicht auf. Grosse echte Stories sind davon kaum betroffen (die
# groesste reale Story am 03.07. hatte 6 Artikel), Transitiv-Ketten schon.
CLUSTER_MAX_SIZE = 8

def _recent_story_anchors(existing_archive, days=3):
    """Cross-Run-Duplikat-Fix (13.07.26): cluster_news() vergleicht bisher NUR
    Artikel, die im SELBEN Pipeline-Lauf gleichzeitig frisch im RSS-Fenster
    liegen. Berichten mehrere Outlets zeitlich verteilt (verschiedene Laeufe,
    4x/Tag) ueber dasselbe Ereignis, landet jedes im eigenen Cluster - keins
    sieht je die anderen. Fund 13.07.: Apple-vs-OpenAI-Klage lief als 5
    separate Karten (The Decoder/TechCrunch/Caschy/Wired/NYT), 13 Artikel
    insgesamt, obwohl die Titel massiv Vokabular teilen ("Apple verklagt
    OpenAI wegen ... Diebstahls von ... Geheimnissen").

    Liefert die letzten `days` Tage aus archive.json als "Anker"-Pseudo-
    Mitglieder fuer cluster_news(): sie nehmen an der GLEICHEN Keyword/Bigram-
    Pruefung teil wie frische Artikel. Matcht ein frischer Artikel gegen einen
    Anker, landet er in dessen Cluster und erbt darueber automatisch die
    Story-Historie (first_seen/base_score kommen ueber den bestehenden
    history-Mechanismus - der Anker-Link ist ja bereits ein history-Eintrag).
    Anker werden NIE selbst als news.json-Zeile ausgegeben (s. Filter am Ende
    von cluster_news() und die _anchor-Checks bei der Repraesentanten-Wahl)."""
    if not existing_archive:
        return []
    anchors, seen = [], set()
    for entry in existing_archive:
        link = entry.get("link")
        if not link or link in seen:
            continue
        if _days_since(entry.get("first_seen") or entry.get("date")) > days:
            continue
        seen.add(link)
        anchors.append({
            "title": entry.get("title", ""),
            "source": entry.get("source", ""),
            "link": link,
            "_anchor": True,
        })
    return anchors


def cluster_news(alle_news, anchors=None):
    """
    Gruppiert ähnliche Artikel zu Stories. Ein Artikel kommt in einen Cluster, wenn er
    entweder 2+ Einzel-Keywords mit ihm teilt ODER eine gemeinsame 2-Wort-Phrase (Bigram)
    hat, in der mindestens ein Token distinktiv (selten) ist.

    Das zweite Kriterium fängt Fälle wie "Seedance 2.5" / "ByteDance Seedance", wo nur EIN
    starkes Stichwort geteilt wird (2-Keyword-Schwelle verfehlt), OHNE generische Phrasen
    wie "Millionen Dollar" zu unzusammenhängenden Clustern zu verketten (beide Tokens dort
    sind häufig → kein distinktives Token → kein Merge).

    anchors (optional): Pseudo-Mitglieder aus _recent_story_anchors() - Story-Titel
    der letzten Tage, die bei der Merge-Pruefung mitspielen (Cross-Run-Duplikat-Fix,
    13.07.26), aber nie selbst als eigenstaendiger Artikel zurueckgegeben werden.

    Gibt Liste von Clusters zurück (jeder Cluster = Liste von Artikeln).
    """
    combined = list(anchors or []) + list(alle_news)
    # Dokumentfrequenz NUR ueber alle_news (heutiger frischer Batch), NICHT ueber
    # combined. Testfund (13.07.26): mit Ankern in der df-Zaehlung "altern" die
    # Kern-Begriffe einer wiederkehrenden Story (z.B. "apple"/"openai"/"verklagt")
    # nach 3-4 Anker-Treffern ueber CLUSTER_RARE_DF_MAX und gelten dann als "nicht
    # mehr distinktiv" - die Story kann sich selbst nicht mehr weiter verschmelzen,
    # genau umgekehrt zur Absicht. Die Distinktivitaets-Schwelle soll nur vor
    # Ueberhaeufigkeit IM HEUTIGEN Batch schuetzen (Schneeball-Fix-Zweck), nicht
    # vor der eigenen Story-Historie.
    df = Counter()
    for item in alle_news:
        for w in set(_title_tokens(item["title"])):
            df[w] += 1

    # Schneeball-Fix (03.07.26): Vorher wurde gegen die VEREINIGUNG aller
    # Cluster-Keywords verglichen, die mit jedem Mitglied WUCHS - in einem
    # KI-Feed (fast jeder Titel enthaelt openai/google/ki/agenten) frass sich
    # ein Cluster transitiv durch den Feed. Vorfall heute 17:00: EIN Cluster
    # mit 22 Artikeln (Google-ADK-Tutorial + Microsoft-Invest + Claude Science),
    # Cluster-Score 77 an alle vererbt -> 61 von 183 News "episch"/BREAKING.
    # Jetzt: (a) Matching gegen JEDES Mitglied einzeln (keine wachsende Union),
    # (b) von 2+ geteilten Keywords muss mind. 1 DISTINKTIV sein (df-Schwelle,
    # dieselbe Regel wie beim Bigram-Kriterium), (c) harter Groessendeckel.
    # Simulation auf den 183 News vom 03.07.: groesster Cluster 11 -> 6, und
    # der 6er ist die echte OpenAI-5%-Story; SpaceX/Anthropic-Samsung bleiben
    # korrekt zusammen, Themen-Ketten zerfallen.
    clusters = []  # je {"items": [...], "sigs": [(kw, bg) pro Mitglied]}
    for item in combined:
        kw = _title_keywords(item["title"])
        bg = _title_bigrams(item["title"])
        merged = False
        for cluster in clusters:
            if len(cluster["items"]) >= CLUSTER_MAX_SIZE:
                continue
            for m_kw, m_bg in cluster["sigs"]:
                shared_kw = kw & m_kw
                kw_match = (len(shared_kw) >= 2
                            and any(df[w] <= CLUSTER_RARE_DF_MAX for w in shared_kw))
                shared_bg = bg & m_bg
                strong_bg = any(df[a] <= CLUSTER_RARE_DF_MAX or df[b] <= CLUSTER_RARE_DF_MAX
                                for (a, b) in shared_bg)
                if kw_match or strong_bg:
                    cluster["items"].append(item)
                    cluster["sigs"].append((kw, bg))
                    merged = True
                    break
            if merged:
                break
        if not merged:
            clusters.append({"items": [item], "sigs": [(kw, bg)]})
    # Anker-only Cluster (kein frischer Artikel hat gematcht) sind fuer DIESEN
    # Lauf irrelevant - keine neue Entwicklung, nichts auszugeben. Anker dienen
    # nur als Matching-Ziel, nie als eigenstaendiges Ergebnis.
    return [c["items"] for c in clusters if any(not it.get("_anchor") for it in c["items"])]

def score_cluster(cluster):
    """
    Berechnet Relevanz-Score für einen Story-Cluster.
    Formel: Multi-Quellen-Bonus + Prestige-Bonus + Wichtigkeits-Keywords
    """
    unique_sources = len({item["source"] for item in cluster})
    # Mehrere Quellen = wichtige Story (Kern-Signal) – max. 4 gewertet (Deckel gegen Google-Dominanz)
    source_score = min(unique_sources, 4) * 15

    # Höchstes Prestige im Cluster zählt
    prestige_score = max(SOURCE_PRESTIGE.get(item["source"], 3) for item in cluster)

    # Keywords aus allen Titeln im Cluster prüfen
    all_titles = " ".join(item["title"].lower() for item in cluster)
    kw_score = sum(pts for kw, pts in IMPORTANCE_KEYWORDS if kw in all_titles)
    penalty_score = sum(pts for kw, pts in PENALTY_KEYWORDS if kw in all_titles)

    release_score = _release_signal(all_titles, {item["source"] for item in cluster})

    total = source_score + prestige_score + kw_score + penalty_score + release_score
    if release_score:
        # 20.08.26 bewusst auf INFO (nicht debug): der Loglevel steht auf INFO,
        # sonst laesst sich nach dem Upload nicht unterscheiden, ob der Bonus
        # nicht greift oder nur nicht durchschlaegt. Nach der Verifikation
        # wieder auf logger.debug zuruecksetzen - ca. 3 Zeilen pro Lauf.
        logger.info("score_cluster: Release-Signatur %+d - %s", release_score, all_titles[:70])
    label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
    return total, label

# -------------------------
# NEU: Hybrid-Scoring (24.06. Backtest-Session)
# LLM bewertet Substanz/Einordnungs-Spannung/Abdeckungsluecke (0-65), ein
# deterministisches Keyword-Gate bewertet Regional-Bezug (0-35) - NICHT die
# LLM, weil sich im Backtest gezeigt hat dass die LLM sich Regional-Punkte
# "ausdenkt" (z.B. Sakana/Japan-Story bekam 18 Phantompunkte D-A-CH-Bezug,
# obwohl der Prompt das explizit verbot). Regional-Bezug ist reines Pattern-
# Matching, das macht eine Liste zuverlaessiger als ein LLM-Urteil.
#
# score_cluster_llm() wird der FUEHRENDE Score (treibt pick_top_news-Sortierung
# und damit Dashboard/Telegram/Cron). score_cluster() (Keyword-System oben)
# bleibt als Fallback: schlaegt der LLM-Call fehl (Timeout/429/Parse-Fehler),
# wird automatisch auf den alten Score zurueckgefallen - die Pipeline blockiert
# nie wegen eines LLM-Ausfalls.
#
# Staedte-/Begriffsliste ist ein Erstwurf, kein Dorf-Vollkatalog. "sachsen"
# selbst ist in der Liste, faengt also auch Orte ohne eigenen Eintrag ab,
# SOFERN der Artikeltext das Bundesland nennt (in deutschen Regionalmeldungen
# fast immer der Fall). Liste bei Bedarf erweitern.
# -------------------------
SACHSEN_KW = [
    "sachsen", "sächsisch", "saechsisch", "dresden", "leipzig", "chemnitz",
    "zwickau", "görlitz", "goerlitz", "freiberg", "bautzen", "plauen",
    "pirna", "meißen", "meissen", "torgau", "annaberg",
]
DACH_KW = [
    "deutschland", "österreich", "oesterreich", "schweiz", "berlin", "münchen",
    "muenchen", "hamburg", "frankfurt", "köln", "koeln", "stuttgart",
    "düsseldorf", "duesseldorf", "wien", "zürich", "zuerich", "bundestag",
    "bundesregierung", "bsi", "bafin",
]
EU_KW = [
    "eu-kommission", "european commission", "europäische union", "european union",
    "brüssel", "brussels", "ai act", "dsgvo", "gdpr", "eu-parlament",
]

def regional_score(text):
    """Deterministisches Regional-Gate, KEIN LLM-Urteil. Sachsen > D-A-CH > EU.
    Kein Treffer -> 0, keine Ausnahme (Plausibilitaets-Spekulation zaehlt nicht)."""
    t = (text or "").lower()
    if any(k in t for k in SACHSEN_KW):
        return 33
    if any(k in t for k in DACH_KW):
        return 22
    if any(k in t for k in EU_KW):
        return 4
    return 0

# Karten-/Flaggen-Hintergrund fuer News-Kacheln (02.07.26). Getrennt von
# regional_score(): der Score/das Ranking darf sich NICHT aendern, nur die
# Kartendeko soll feiner aufloesen (eigene Flagge fuer AT/CH statt Sammel-
# Deutschland-Flagge, von Daniel bestaetigt 02.07.26). ACHTUNG: AT_KW/CH_KW
# sind KEINE Teilmengen von DACH_KW mehr — die Staedte unten stehen bewusst
# NICHT in DACH_KW, damit der Score unveraendert bleibt. Ein Basel-Artikel
# bekommt also die CH-Flagge, aber weiterhin 0 Regional-Bonus.
# "bern" fehlt BEWUSST: Substring-Matching wuerde "Übernahme"/"übernimmt"
# treffen -> jeder Uebernahme-Artikel bekaeme die CH-Flagge. "berner" ist safe.
AT_KW = ["österreich", "oesterreich", "wien", "graz", "linz", "salzburg", "innsbruck"]
CH_KW = ["schweiz", "zürich", "zuerich", "basel", "genf", "berner", "lausanne"]


def classify_region(text):
    """Region fuer die Karten-/Flaggen-Deko der News-Kachel.
    Reihenfolge wie regional_score(): Sachsen > AT/CH > Deutschland > EU > Welt.
    Rueckgabewerte: sachsen | oesterreich | schweiz | deutschland | europa | welt.
    """
    t = (text or "").lower()
    if any(k in t for k in SACHSEN_KW):
        return "sachsen"
    if any(k in t for k in AT_KW):
        return "oesterreich"
    if any(k in t for k in CH_KW):
        return "schweiz"
    if any(k in t for k in DACH_KW):
        return "deutschland"
    if any(k in t for k in EU_KW):
        return "europa"
    return "welt"

# Scoring-Fix (02.07.26), zwei Aenderungen am Prompt:
# (a) Kriterium 1 verlangt jetzt KI als KERN-Thema (Fall: Sony-Kopfhoerer-
#     Firmware-Update kam mit Score 44 in die Top-Raenge - der LLM bewertete
#     Substanz/Spannung, ohne je zu fragen, ob das ueberhaupt KI-News ist).
# (b) Kriterium 3 hiess "Abdeckungs-Luecke" und gab 0 Punkte, sobald das Thema
#     in den recent_titles vorkam - das BESTRAFTE Follow-ups grosser Storys
#     aktiv (Fable-5-Relaunch: je laenger die Saga in den Titeln stand, desto
#     tiefer wurde jede NEUE Entwicklung dazu gestuft - genau falsch herum).
#     Jetzt: Statuswechsel/neue Entwicklung in bekanntem Thema zaehlt voll,
#     nur substanzlose Wiederholung faellt auf 0.
LLM_SCORE_PROMPT = """Du bewertest KI-News fuer ScampyKI, einen deutschsprachigen, \
skeptischen KI-Newskanal (kein Hype, echte Einordnung statt Pressemitteilung).
Bewerte den folgenden Artikel nach drei Kriterien (Regional-Bezug wird NICHT von dir \
bewertet, das macht ein separater deterministischer Check):

1. Substanz statt Ankuendigung (0-30): Aendert sich real etwas (neue Faehigkeit, \
echtes Limit, messbarer Effekt)? Reine PR ohne Inhalt = 0. WICHTIG: Ist KI/AI nicht \
das ZENTRALE Thema des Artikels, sondern nur Randnotiz oder Marketing-Etikett \
(z.B. Gadget-Firmware, Gaming-Hardware, Consumer-Deals), maximal 5 Punkte. Gleiches \
Limit fuer Tutorials/Anleitungen/How-tos und Produktblog-Marketing ohne \
Nachrichtenereignis (es wird erklaert oder beworben, aber nichts ist PASSIERT, \
z.B. "Baue ein Multi-Agenten-Team mit Tool X"), auch wenn KI das Kern-Thema ist.
2. Einordnungs-Spannung (0-20): Gibt es einen Widerspruch oder eine eigene These \
zu bilden (Hype vs. Realitaet, Gewinner/Verlierer)?
3. Neuigkeitswert (0-15): Volle Punkte wenn (a) das Thema in den "bereits \
abgedeckten Themen" unten NICHT vorkommt ODER (b) es eine ECHTE NEUE ENTWICKLUNG \
zu einem bekannten Thema ist - ein Statuswechsel zaehlt immer als neu (gesperrt -> \
wieder freigegeben, angekuendigt -> veroeffentlicht, Geruecht -> bestaetigt, \
Klage eingereicht -> Urteil). 0 Punkte NUR, wenn der Artikel dieselbe Meldung \
ohne neue Substanz wiederholt.

Bereits abgedeckte Themen der letzten 3 Tage (Titel):
{recent_titles}

Artikel:
Titel: {title}
Zusammenfassung: {summary}

Antworte NUR mit JSON, keine Erklaerung davor/danach. score ist die Summe der drei \
Kriterien, also 0-65:
{{"score": <0-65>, "begruendung": "<1 Satz>"}}"""

def score_cluster_llm(cluster, recent_titles):
    """
    Hybrid-Score: LLM bewertet Substanz/Spannung/Abdeckungsluecke (0-65),
    regional_score() addiert den deterministischen Regional-Bonus (0-35).
    Gibt (None, None) zurueck wenn der LLM-Call fehlschlaegt -> Aufrufer
    faellt dann auf score_cluster() (Keyword-System) zurueck.
    """
    if not OPENROUTER_KEY:
        return None, None
    # Anker (Cross-Run-Duplikat-Fix, 13.07.26) duerfen nie als Titel-Quelle
    # dienen - sie sind alte, bereits archivierte Artikel, kein frischer Inhalt.
    rep = next((it for it in cluster if not it.get("_anchor")), cluster[0])
    title = rep.get("title", "")
    summary = " ".join(i.get("title", "") for i in cluster)[:600]
    prompt = LLM_SCORE_PROMPT.format(
        recent_titles="\n".join(f"- {t}" for t in recent_titles[:15] if t) or "(keine)",
        title=title,
        summary=summary,
    )
    messages = [{"role": "user", "content": prompt}]
    for modell in MODELLE_POSTS:
        if _model_blocked(modell):
            continue
        try:
            antwort = _call_llm_api(modell, messages, max_tokens=150, timeout=30)
            raw = (antwort or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`").replace("json", "", 1).strip()
            parsed = json.loads(raw)
            llm_part = int(parsed.get("score", 0))
            reg_part = regional_score(title + " " + summary)
            # Scoring-Fix (02.07.26): Multi-Source-Bonus deterministisch addieren.
            # Vorher floss die Anzahl unabhaengiger Quellen - das staerkste
            # "das ist eine Nachricht"-Signal - NUR in den Legacy-Fallback ein;
            # im fuehrenden LLM-Score wurden 10 berichtende Outlets und ein
            # einzelner Blogpost identisch behandelt (Fable-5-Relaunch-Fall).
            # Deckel bei 4 Quellen wie in score_cluster() (Google-Duplikate).
            src_part = min(len({i.get("source") for i in cluster}), 4) * 8
            total = max(0, min(100, llm_part + reg_part + src_part))
            label = next((lbl for threshold, lbl in SCORE_LABELS if total >= threshold), "📰 normal")
            _model_note_ok(modell)
            return total, label
        except Exception as e:
            if getattr(e, "code", None) == 429:
                _model_note_429(modell)
            logger.warning("score_cluster_llm: %s fehlgeschlagen (%s) - naechstes Modell", modell, e)
            continue
    return None, None

def _recent_titles_from_archive(existing_archive, days=3, limit=15):
    """Titel der letzten N Tage aus archive.json - Kontext fuer die
    Abdeckungs-Luecke-Bewertung. Liest nur, schreibt nichts zurueck."""
    if not existing_archive:
        return []
    heute = datetime.now(BERLIN).date()
    titles = []
    for item in existing_archive:
        try:
            d = datetime.strptime(str(item.get("date", ""))[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if 0 <= (heute - d).days <= days:
            titles.append(item.get("title", ""))
    return titles[-limit:]

def pick_top_news(alle_news, n=3, history=None, featured_links=None, existing_archive=None, already_sent=None):
    """
    Wählt die n wichtigsten Artikel nach Clustering + Scoring.
    Statt blindem [:3] aus der Feed-Reihenfolge.
    Gibt je einen repräsentativen Artikel pro Top-Cluster zurück.

    history (link -> {first_seen, base_score}) optional: wenn gesetzt, wird nach
    dem ZEIT-VERFALLENEN Score sortiert – identisch zur Dashboard-Sortierung,
    damit Telegram und Dashboard dieselben Top-Storys zeigen.
    """
    history = history or {}
    featured_links = set(featured_links or [])
    # Cross-Run-Duplikat-Fix (13.07.26) - WIEDER DEAKTIVIERT (13.07.26, selber
    # Abend): live Fehlverschmelzung beobachtet (Microsoft/Copilot-Meldung
    # zog sich 7 fremde Anker rein, nur weil "microsoft"+"openai" im kleinen
    # frischen Tagesbatch faelschlich distinktiv wirkten - s. Notizen bei
    # _recent_story_anchors()). Df-Berechnung braucht eine Paar-Haeufigkeit
    # statt Einzeltoken-Pruefung, bevor das wieder scharf geschaltet wird.
    # anchors=None -> Verhalten wie vor dem 13.07., unveraendert sicher.
    clusters = cluster_news(alle_news, None)
    recent_titles = _recent_titles_from_archive(existing_archive)

    # Legacy-Score (Keyword-System) zuerst fuer ALLE Cluster - dient als
    # (a) Auswahlkriterium, welche Cluster ueberhaupt einen teuren LLM-Call
    #     bekommen (nur die aussichtsreichsten Kandidaten), und
    # (b) Fallback-Wert, falls der LLM-Call fuer einen Kandidaten fehlschlaegt.
    legacy_results = [score_cluster(cluster) for cluster in clusters]
    # 19.08.26: von 10 auf 13 angehoben. Die Release-Signatur bringt ~3,4
    # zusaetzliche Kandidaten pro Lauf durch die Tuer - ohne diese Anhebung
    # wuerden sie andere Storys aus der LLM-Bewertung verdraengen.
    LLM_SCORE_CANDIDATES = 13
    candidate_order = sorted(
        range(len(clusters)), key=lambda i: legacy_results[i][0], reverse=True
    )[:LLM_SCORE_CANDIDATES]
    candidate_set = set(candidate_order)

    # Jeden Cluster bewerten: fuehrender Score = Hybrid-LLM-Score (Substanz/
    # Spannung/Abdeckungsluecke per LLM + Regional-Bonus per Keyword-Gate).
    # Schlaegt der LLM-Call fehl ODER ist der Cluster kein Top-Kandidat,
    # wird auf score_cluster() (Keyword-System) zurueckgefallen.
    scored = []
    for idx, cluster in enumerate(clusters):
        legacy_score, legacy_label = legacy_results[idx]
        llm_score, llm_label = (
            score_cluster_llm(cluster, recent_titles) if idx in candidate_set else (None, None)
        )
        if llm_score is not None:
            score, label, score_source = llm_score, llm_label, "llm"
        else:
            score, label, score_source = legacy_score, legacy_label, "legacy_fallback"

        # Ältesten first_seen im Cluster als Story-Alter (Member ohne History erben ihn).
        cluster_histories = [history[item["link"]] for item in cluster if item.get("link") in history]
        oldest_first_seen = min((h["first_seen"] for h in cluster_histories), default=_today_iso())
        # Anzeige-Score eines Artikels – GENAU wie news_list/Frontend ihn berechnen
        # (decay_score auf base_score + History-Heilung). Dadurch wählen wir denselben
        # Repräsentanten (höchster Score, nicht höchstes Prestige) und dieselbe Top-
        # Reihenfolge, die die deduplizierte Startseite zeigt. Folge: der für eine Story
        # generierte Teaser hängt immer an genau der Karte, die oben angezeigt wird.
        def _display_score(m, _score=score, _oldest=oldest_first_seen):
            h = history.get(m.get("link", ""))
            if h:
                fs = h["first_seen"]
            elif m.get("source") in ALWAYS_KI_RELEVANT_SOURCES:
                # Bug-Fix (01.07.26): Primaerquellen (Lab-Blogs direkt) erben nie das
                # Cluster-Alter sekundaerer Berichterstattung - eine eigene Ankuendigung
                # des Labors ist per Definition eine frische Entwicklung, kein Rehash
                # einer alten Story (Fall: Anthropics "Redeploying Fable 5" clusterte
                # mit einem 3 Tage alten, laengst verfallenen Sekundaerartikel und wurde
                # dadurch nie Repraesentant der eigenen Story).
                fs = _today_iso()
            else:
                fs = _oldest
            base = max(h["base_score"], _score) if h and h["base_score"] <= HEAL_THRESHOLD else _score
            return decay_score(base, fs)
        # Anker (Cross-Run-Duplikat-Fix) duerfen nie Repraesentant werden - sie
        # sind alte, bereits archivierte Artikel ohne frischen Inhalt fuer die
        # Karte. cluster_news() garantiert mind. 1 Nicht-Anker pro Cluster.
        rep = max((m for m in cluster if not m.get("_anchor")), key=_display_score)
        eff_score = _display_score(rep)
        # Featured-Boost aus dashboard_config.json (mit Zeitverfall)
        if featured_links:
            cluster_links = {item.get("link", "") for item in cluster}
            if rep.get("link", "") in featured_links or cluster_links & featured_links:
                fs = history.get(rep.get("link", ""), {}).get("first_seen", _today_iso())
                days_old = _days_since(fs)
                boost = 60 if days_old == 0 else 30 if days_old == 1 else 15 if days_old == 2 else 0
                eff_score += boost
        scored.append({
            "rep": rep,
            "score": score,
            "eff_score": eff_score,
            "label": label,
            "score_legacy": legacy_score,
            "label_legacy": legacy_label,
            "score_source": score_source,
            "sources_count": len({i["source"] for i in cluster}),
            "members": cluster,   # NEU: alle Artikel im Cluster für Story-Mapping
        })

    # Nach verfallenem Score absteigend sortieren (bei Gleichstand: roher Score)
    scored.sort(key=lambda x: (x["eff_score"], x["score"]), reverse=True)

    # Bug-Fix (26.06.26): already_sent (z.B. telegram_state.json sent_links)
    # nur HIER anwenden - bei der finalen Top-n-Auswahl fuer Telegram/LLM -
    # NICHT vorher beim Scoring (s. Kommentar am Call-Standort in main()).
    # Jeder Cluster wurde oben unabhaengig vom Sent-Status bewertet (eff_score
    # inkl. Featured-Boost bleibt fuer score_map/news.json erhalten), hier
    # werden nur bereits gesendete Reps von den n sichtbaren Telegram-Plaetzen
    # verdraengt, damit frische Stories durchkommen statt staendig wiederholt
    # derselben 3 Top-Score-Cluster zu weichen.
    already_sent = already_sent or set()
    if already_sent:
        frisch = [item for item in scored if item["rep"].get("link", "") not in already_sent]
        top = frisch[:n] if frisch else scored[:n]
    else:
        top = scored[:n]
    for item in top:
        logger.info(
            "[Scoring] %s | %s | Score: %d (akt. %d, Quelle: %s, Legacy: %d) | Quellen: %d",
            item["label"], item["rep"]["title"][:60], item["score"], item["eff_score"],
            item["score_source"], item["score_legacy"], item["sources_count"]
        )

    # NEU: link → Story-Metadaten (für news.json-Anreicherung)
    # Jeder Artikel erbt story_id, story_cluster_score und story_article_count seines Clusters.
    # Damit kann die Podcast-Logik Artikel nach Story-Gewicht gruppieren statt nach Einzel-Score.
    # score_source ("llm"/"legacy_fallback") + story_score_legacy bleiben als Vergleichswerte
    # sichtbar in news.json/archive.json, damit man den Hybrid-Score gegen das alte
    # Keyword-System nachvollziehen kann.
    link_to_cluster_info = {}
    for cluster_idx, item in enumerate(scored):
        story_id = f"s{cluster_idx:03d}"
        article_count = len(item.get("members", []))
        for member in item.get("members", []):
            lnk = member.get("link", "")
            if lnk:
                link_to_cluster_info[lnk] = {
                    "story_id":            story_id,
                    "story_cluster_score": item["score"],
                    "story_label":         item["label"],
                    "story_article_count": article_count,
                    "story_score_legacy":  item["score_legacy"],
                    "story_score_source":  item["score_source"],
                }

    # Bug 26.06.: eff_score (= score + Decay + Featured-Boost) wurde bisher NUR
    # lokal zum Sortieren/Top-n-Auswaehlen benutzt und ging beim Return verloren -
    # news.json bekam den UNGEBOOSTETEN "score". Folge: ein gepinnter Artikel
    # gewann seinen Platz in der Telegram-/Dashboard-Top-Liste (wo eff_score
    # zaehlt), aber generate_news_cards.py (liest nur news.json/"score") sah den
    # Boost nie und sortierte die Story trotz Pin nach hinten. Jetzt wird
    # eff_score mit zurueckgegeben, news.json uebernimmt ihn als raw_score.
    return [item["rep"] for item in top], {
        item["rep"]["link"]: {
            "score": item["score"], "eff_score": item["eff_score"], "label": item["label"],
            "score_legacy": item["score_legacy"], "score_source": item["score_source"],
        }
        for item in scored
    }, link_to_cluster_info

# -------------------------
# Score-Verfall (Zeit-Decay)
# -------------------------
# Jeder Artikel verliert pro Tag seit Erst-Erfassung Punkte, Untergrenze 0.
# So sinken alte Stories automatisch nach unten und machen Platz für Neues.
SCORE_DECAY_PER_DAY = 5
SCORE_FLOOR = 0
# Bug-Fix (13.07.26): History-Heilung war bedingungslos max(alt, neu) - dachte
# nur an den Ursprungsfall (faelschlich als 0 archivierte Member sollen sich
# ausheilen koennen), heilte aber symmetrisch JEDEN einmaligen Score-Ausreisser
# nach oben permanent fest (Fall: OnlyFans-Story bekam einmalig base_score 78,
# jede folgende Neuberechnung kam auf ~32, wurde aber via max() 16 Tage lang
# verworfen). Heilung jetzt nur noch erlaubt, wenn der alte Wert nahe 0 war -
# der dokumentierte Ursprungsfall. Alles darueber: frischer Score gewinnt immer.
HEAL_THRESHOLD = 5
MAX_AGE_DAYS = 5  # Artikel älter als 5 Tage werden aus news.json entfernt (Start-/Artikelseite)
# Abschlag fuer Cluster-Member, die NICHT der Repraesentant ihrer Story sind.
# Sie erben den Story-Cluster-Score minus diesen Wert, damit der Repraesentant
# oben bleibt, die Story aber als Block zusammensteht (statt dass Member auf 0 fallen).
CLUSTER_MEMBER_MALUS = 10

def _today_iso():
    return datetime.now(BERLIN).strftime("%Y-%m-%d")

def _days_since(date_str):
    """Volle Tage zwischen date_str (YYYY-MM-DD) und heute. Robust gegen Müll."""
    if not date_str:
        return 0
    try:
        d0 = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0
    today = datetime.now(BERLIN).date()
    return max(0, (today - d0).days)

def _recall_relevant_from_archive(alle_news, existing_archive, featured_links):
    """Holt Artikel zurueck, die aus dem frischen RSS-Fenster (fetch_feed nimmt nur
    die letzten ~20 Items pro Feed) rausgescrollt sind, aber noch sichtbar bleiben
    sollen.

    Fund 26.06.: ein gepinnter, NUR EINEN TAG alter Sachsen-Artikel (Heise) ist
    komplett aus news.json verschwunden - nicht weil MAX_AGE_DAYS ihn purgte
    (1 Tag << 5 Tage), sondern weil alle_news JEDEN Lauf komplett frisch aus
    fetch_feed() aufgebaut wird (keine Verbindung zu archive.json). Heises
    generischer Newsticker (alle Themen, nicht nur KI) hat ihn binnen Stunden aus
    den letzten 20 RSS-Items rausgedrueckt. Ab da: kein Pin, kein Score, kein
    Boost kann mehr greifen, weil der Artikel nie wieder in alle_news landet.

    Zwei Gruppen werden aus archive.json zurueckgeholt, solange sie innerhalb von
    MAX_AGE_DAYS liegen:
    - featured_links (manuell gepinnt)
    - regional_score(title) > 0 (Sachsen/D-A-CH-Prioritaet) - Daniel: gerade WEIL
      das selten ist (oft nur 1 Quelle), darf es nicht nach ein paar Stunden im
      generischen Feed-Rauschen untergehen, sondern soll die vollen ~5 Tage
      sichtbar bleiben (mindestens 2, ist hier durch MAX_AGE_DAYS automatisch
      erfuellt).
    """
    present = {n.get("link") for n in alle_news if n.get("link")}
    by_link, seen = [], set()
    for n in existing_archive or []:
        link = n.get("link")
        if not link or link in seen:
            continue
        seen.add(link)
        by_link.append(n)

    featured_set = set(featured_links or [])
    recalled = []
    for entry in by_link:
        link = entry.get("link")
        if link in present:
            continue
        age = _days_since(entry.get("first_seen") or entry.get("date"))
        if age > MAX_AGE_DAYS:
            continue
        if link in featured_set or regional_score(entry.get("title", "")) > 0:
            recalled.append(entry)
    return recalled


def decay_score(base_score, first_seen):
    """
    Deterministischer Verfall: score = max(0, base_score - 5 * Tage_seit_Erfassung).

    Bewusst NICHT kumulativ (kein „-5 pro Lauf“): der GitHub-Action-Cron kann
    mehrmals täglich laufen – ein Abzug pro Lauf würde Artikel je nach Laufzahl
    unterschiedlich stark bestrafen. Aus base_score + first_seen neu zu rechnen
    ist idempotent und liefert bei jedem Lauf denselben, korrekten Wert.
    """
    try:
        base = int(base_score)
    except (ValueError, TypeError):
        base = 0
    decayed = base - SCORE_DECAY_PER_DAY * _days_since(first_seen)
    return max(SCORE_FLOOR, decayed)

def _cap_inflated_base_scores(entries):
    """Einmal-Migration (04.07.26): Die Schneeball-Cluster-Inflation vom 03.07.
    hat base_scores bis 77 in archive.json eingefroren (und ueber die History-
    Heilung max(hist, raw) auch AELTERE Links mit hochgezogen). Mit Decay -5/Tag
    verstopfen diese Alt-Eintraege die Startseiten-Sortierung noch ~10 Tage und
    tragen dabei frisch berechnete NIEDRIGE Labels (Zahl alt, Label neu ->
    Karte mit Score 52 ohne Badge, wirkt unsortiert). Kappung auf 54 = knapp
    unter der neuen episch-Schwelle 55. Idempotent, betrifft nur Eintraege bis
    einschliesslich 03.07. - kann nach dem 14.07.26 ersatzlos entfernt werden."""
    for e in entries:
        try:
            if str(e.get("first_seen", ""))[:10] <= "2026-07-03" and float(e.get("base_score", 0)) > 54:
                e["base_score"] = 54
        except (TypeError, ValueError):
            continue

def build_history_map(*archive_lists):
    """
    Baut link -> {first_seen, base_score} aus vorhandenen Archiv-Einträgen.
    Quelle der Wahrheit für „wann zum ersten Mal gesehen“ + „Ausgangs-Score“.
    Ältere Archive ohne diese Felder werden tolerant migriert (Fallback auf date/score).
    """
    hist = {}
    for lst in archive_lists:
        for n in (lst or []):
            link = n.get("link")
            if not link:
                continue
            first_seen = n.get("first_seen") or n.get("date") or _today_iso()
            base_score = n.get("base_score")
            if base_score is None:
                base_score = n.get("score", 0)
            prev = hist.get(link)
            entry = {"first_seen": first_seen, "base_score": base_score}
            if "image" in n:
                entry["image"] = n.get("image") or ""
            # Frühestes Datum gewinnt (echtes Erst-Sichten)
            if prev is None or str(first_seen) < str(prev["first_seen"]):
                # Bild aus dem vorherigen Eintrag retten, falls neuer keins hat
                if prev and "image" in prev and "image" not in entry:
                    entry["image"] = prev["image"]
                hist[link] = entry
            else:
                if base_score and not prev.get("base_score"):
                    prev["base_score"] = base_score
                if "image" in entry and "image" not in prev:
                    prev["image"] = entry["image"]
    return hist

def apply_decay_to_entries(entries):
    """Rechnet score für eine Liste von Einträgen neu (in-place) aus base_score+first_seen."""
    for n in entries:
        if not isinstance(n, dict):
            continue
        fs = n.get("first_seen") or n.get("date")
        bs = n.get("base_score")
        if bs is None:
            bs = n.get("score", 0)
            n["base_score"] = bs
        if not n.get("first_seen"):
            n["first_seen"] = fs or _today_iso()
        n["score"] = decay_score(bs, n["first_seen"])
    return entries


# -------------------------
# Feeds
# -------------------------
def http_get_with_retry(url, headers=None, timeout=10, retries=3, backoff=2):
    # Realistischer Browser-UA – reduziert 403/Throttling bei Medien-Seiten
    default_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    headers = headers or {
        "User-Agent": default_ua,
        "Accept": "application/rss+xml,application/xml,*/*"
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (HTTPError, URLError) as e:
            if hasattr(e, 'code') and e.code == 403:
                # 403 = Feed blockiert GitHub Actions IPs → kein Retry, sofort aufgeben
                logger.warning("HTTP Fehler %s: %s (Versuch %d/%d) – Feed blockiert, überspringe", url, e, attempt, retries)
                break
            logger.warning("HTTP Fehler %s: %s (Versuch %d/%d)", url, e, attempt, retries)
            sleep(backoff * attempt)
        except Exception as e:
            logger.exception("Unerwarteter Fehler %s: %s", url, e)
            break
    return None

# Volltext-Capture fuer den Chat-Bot (Fund 08.07.26): der Bot-Kontext bestand
# bisher NUR aus der RSS-Kurz-Summary (siehe summarize_news) - selbst bei
# Nicht-Paywall-Quellen wurde nie der Artikel-Volltext geholt. Ausloeser: Frage
# zur Saechsische-Zeitung-Betrugskarte, die der Bot nicht beantworten konnte.
# Bewusst NUR fuer die Top-5 nach Score (nicht alle ~30 Feeds) - haelt Scrape-
# Last und rechtliches Risiko (Volltext-Reproduktion fremder Inhalte) klein.
_FULLTEXT_MAX_CHARS = 2000

def _extract_readable_text(raw_html):
    """Grobe Volltext-Extraktion, reines stdlib (kein requests/BeautifulSoup -
    der GitHub-Actions-Workflow installiert dafuer nichts). Kein Anspruch auf
    saubere Artikel-Extraktion (Nav/Footer/Kommentare koennen mit drin sein) -
    Zweck ist "mehr Substanz fuer den Chat-Bot", nicht Archivqualitaet."""
    if not raw_html:
        return ""
    try:
        text = raw_html.decode("utf-8", errors="replace") if isinstance(raw_html, bytes) else raw_html
    except Exception:
        return ""
    text = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = text.strip()
    return text[:_FULLTEXT_MAX_CHARS]

def fetch_full_text(url):
    """Liefert (full_text, paywalled)-Tupel. paywalled=True heisst: Fetch
    fehlgeschlagen ODER Ausbeute verdaechtig duenn (Paywall-Teaser-Symptom) -
    der Bot soll dann ehrlich 'nur Teaser verfuegbar' sagen statt zu raten."""
    if not url:
        return "", True
    raw = http_get_with_retry(url, timeout=12, retries=1)
    if not raw:
        return "", True
    text = _extract_readable_text(raw)
    # Heuristik: ein echter Artikel liefert deutlich mehr als ein paar Zeilen
    # Teaser/Cookie-Banner. Schwelle bewusst niedrig gehalten (lieber ein
    # duenner Volltext als False-Positive "paywalled" bei kurzen News-Blurbs).
    if len(text) < 200:
        return text, True
    return text, False

# Quellen, die per Definition NUR KI-Themen posten (Labor-Blogs, kuratierte
# KI-News-Aggregatoren) - der _is_ki_relevant()-Titelfilter ist hier nicht nur
# ueberfluessig, sondern schaedlich (siehe Bug-Fix-Kommentar in fetch_feed()).
ALWAYS_KI_RELEVANT_SOURCES = {
    "AlignedNews", "Anthropic News", "Anthropic Research", "OpenAI",
    "Meta AI Blog", "Google AI Blog", "xAI News", "Mistral News",
}

# Generische Hochvolumen-Newsticker (alle IT-Themen, nicht nur KI) brauchen ein
# tieferes Scan-Fenster als spezialisierte AI-Feeds, siehe Kommentar in fetch_feed().
DEEP_SCAN_SOURCES = {"Heise", "Golem", "NYT Technology", "CNet", "TechRepublic"}

# Bug-Fix (02.07.26): Atom-Feeds (z.B. The Verge) deklarieren einen XML-Namespace -
# ElementTree-Tags heissen dann "{http://www.w3.org/2005/Atom}entry", und
# root.iter("entry") findet NICHTS. Folge: The Verge lieferte seit Einfuehrung
# still 0 Artikel (kein Log, weil nur ParseError geloggt wurde; verifiziert
# 02.07.26: Feed hat 10 Entries, alter Code fand 0). Die Helfer hier vergleichen
# nur den lokalen Tag-Namen, egal ob RSS (item) oder Atom (entry), mit/ohne Namespace.
def _tag_local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def _first_child_text(el, name):
    for ch in el:
        if _tag_local(ch.tag) == name:
            return (ch.text or "").strip()
    return ""

def fetch_feed(name, url):
    # The Decoder braucht mehr Zeit – Server langsam für GitHub Actions IPs
    timeout = 20 if "the-decoder" in url else 12
    raw = http_get_with_retry(url, timeout=timeout, retries=2, backoff=3)
    if not raw:
        logger.error("[%s] Kein Inhalt erhalten.", name)
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning("[%s] XML ParseError: %s", name, e)
        return []

    items = []
    # Namespace-agnostisch: findet RSS-<item> UND Atom-<entry> (auch mit Namespace),
    # siehe Bug-Fix-Kommentar bei _tag_local() oben.
    candidates = [el for el in root.iter() if _tag_local(el.tag) in ("item", "entry")]
    if not candidates:
        logger.warning("[%s] Feed geparst, aber 0 Items/Entries gefunden (Formatwechsel?)", name)
    # Tiefer in den Feed schauen (war 10): aktive Feeds wie TechCrunch haben 15-20
    # Items, wichtige Modell-News stehen oft erst ab Position 11.
    # Bug-Fix (01.07.26): 20 reicht bei generischen Hochvolumen-Newstickern (Heise,
    # Golem, ...) nicht - die posten ueber ALLE IT-Themen, nicht nur KI. Fund: die
    # Heise-Story zu Claude Sonnet 5 / Fable-5-Wiederfreigabe stand auf Position
    # 51 von 159 im Feed (nur ~10h alt, aber Heise postet ~5 Items/Stunde ueber
    # alle Themen) - fiel komplett aus dem 20er-Fenster, kam nie bei
    # _is_ki_relevant() an. Fuer diese Quellen tiefer scannen.
    scan_depth = 60 if name in DEEP_SCAN_SOURCES else 20
    for item in candidates[:scan_depth]:
        title = _first_child_text(item, "title")
        link = _first_child_text(item, "link")
        if not link:
            # Atom: <link href="..."/> (ggf. mehrere; rel="alternate" oder ohne rel bevorzugen)
            for ch in item:
                if _tag_local(ch.tag) == "link" and ch.get("href") and ch.get("rel") in (None, "alternate"):
                    link = ch.get("href", "").strip()
                    break
        # Bug-Fix (01.07.26): Quellen, die AUSSCHLIESSLICH KI-Themen posten (Labor-
        # Blogs), wurden trotzdem durch _is_ki_relevant() gefiltert - der Titel allein
        # reicht dem Wortfilter oft nicht (z.B. Anthropics eigener Post "Redeploying
        # Fable 5" enthaelt weder "AI"/"KI" noch "Claude"/"Anthropic" im Titel und
        # fiel deshalb komplett raus, obwohl es die Story war, die den ganzen Anlass
        # fuer diese Session ausgeloest hat).
        # Google-News-Titel bei Digg haengen " - Digg" an (Google-News-Konvention fuer
        # site:-Suchen) - fuer alle anderen Google-News-Quellen (Reuters/Bloomberg/...)
        # kein Problem, weil deren site-Name selten am Titelende landet, bei "Digg" schon.
        if name == "Digg AI" and title.endswith(" - Digg"):
            title = title[: -len(" - Digg")].strip()
        if title and (name in ALWAYS_KI_RELEVANT_SOURCES or _is_ki_relevant(title)):
            items.append({"title": title, "link": link, "source": name})
    # War [:3] – das warf ~70% der relevanten News pro Feed weg (The Decoder liefert
    # 10 KI-relevante, nur 3 kamen durch). Höher = bessere Abdeckung neuer Modelle,
    # das Scoring + der Zeit-Verfall sortieren die Masse danach.
    # Bug-Fix (01.07.26): dieselbe Deckelung wie oben - bei DEEP_SCAN_SOURCES reicht
    # 8 nicht, wenn im tieferen Fenster mehr als 8 KI-relevante Treffer liegen (an
    # Tagen mit viel KI-News verdraengen die 8 neuesten sonst aeltere, aber noch
    # relevante Treffer wie die Sonnet-5/Fable-5-Story).
    output_cap = 15 if name in DEEP_SCAN_SOURCES else 8
    return items[:output_cap]

# -------------------------
# Vorschaubilder (og:image) – serverseitig für externe Links / X-Posts
# -------------------------
# X-Posts (und andere externe Links) liefern kein eigenes Vorschaubild im RSS.
# Wir holen das og:image / twitter:image einmalig beim Lauf und speichern es in
# news.json + archive.json, damit die Karten im Frontend ein Standbild zeigen –
# ganz ohne dass der Browser des Besuchers das Drittanbieter-HTML laden muss.
_OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']', re.I),
]

def fetch_og_image(url):
    """Holt das og:image / twitter:image einer URL. Gibt absolute URL oder '' zurück."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        raw = http_get_with_retry(url, timeout=10, retries=1, backoff=2)
        if not raw:
            return ""
        # Nur den <head> durchsuchen reicht und ist schnell.
        # Bug-Fix (02.07.26): raw ist BYTES, die _OG_PATTERNS sind str-Regexes -
        # pat.search(bytes) wirft TypeError, der vom breiten except unten still
        # geschluckt wurde. Folge: fetch_og_image() hat seit Einfuehrung IMMER ""
        # zurueckgegeben (verifiziert: 0 von 955 archive.json-Eintraegen mit Bild).
        # Fix: erst dekodieren, dann matchen.
        head = raw[:200000].decode("utf-8", errors="replace")
        for pat in _OG_PATTERNS:
            m = pat.search(head)
            if m:
                img = (m.group(1) or "").strip()
                if not img:
                    continue
                # Schema-relative oder Pfad-relative URLs absolut machen
                if img.startswith("//"):
                    img = "https:" + img
                elif img.startswith("/"):
                    from urllib.parse import urlparse
                    p = urlparse(url)
                    img = f"{p.scheme}://{p.netloc}{img}"
                if img.startswith(("http://", "https://")):
                    return img
    except Exception as e:
        logger.debug("og:image-Abruf fehlgeschlagen für %s: %s", url, e)
    return ""

def resolve_preview_image(link, history_entry):
    """
    Liefert das Vorschaubild für einen Link. Nutzt den Cache (history_entry aus
    archive.json) und holt nur dann neu, wenn noch keins gespeichert ist – das
    spart HTTP-Abrufe bei jedem Lauf. Leerer String = kein Bild gefunden.
    """
    if history_entry and "image" in history_entry:
        # Schon einmal versucht (auch wenn Ergebnis leer war) → nicht erneut abrufen
        return history_entry.get("image") or ""
    return fetch_og_image(link)

# -------------------------
# X-Beiträge: Vorschaubild serverseitig holen (kein CORS-Problem)
# -------------------------
def _tweet_id_from_url(url):
    m = re.search(r"status(?:es)?/(\d+)", url or "")
    return m.group(1) if m else ""

def fetch_tweet_image(tweet_id):
    """
    Holt das Vorschaubild eines X-Beitrags über die CORS-freie fxtwitter-API.
    Serverseitig (GitHub-Action) – im Gegensatz zum Browser kein CORS-Block.
    Gibt eine pbs.twimg.com-Bild-URL zurück oder '' wenn keins gefunden.
    """
    if not tweet_id:
        return ""
    try:
        raw = http_get_with_retry(f"https://api.fxtwitter.com/status/{tweet_id}", timeout=10, retries=1)
        if not raw:
            return ""
        d = json.loads(raw)
        t = (d or {}).get("tweet") or {}
        m = t.get("media") or {}
        photos = m.get("photos") or []
        if photos and photos[0].get("url"):
            return photos[0]["url"]
        videos = m.get("videos") or []
        if videos and videos[0].get("thumbnail_url"):
            return videos[0]["thumbnail_url"]
        allm = m.get("all") or []
        if allm:
            return allm[0].get("thumbnail_url") or allm[0].get("url") or ""
        author = t.get("author") or {}
        if author.get("avatar_url"):
            return author["avatar_url"]
    except Exception as e:
        logger.debug("Tweet-Bild (fx) fehlgeschlagen %s: %s", tweet_id, e)
    return ""

def fetch_tweet_data(tweet_url):
    """
    Holt die vollen Daten eines X-Beitrags über die freie fxtwitter-API
    (Autor, Text, Likes/Retweets/Views) statt nur das Vorschaubild.
    Grundlage fuer den "Was X dazu sagt"-Reaktionsblock (Community-Pulse,
    Idee aus dem HuggingNews-Vergleich 12.07.26 - kein X-API-Abo noetig).
    Gibt {} zurueck wenn nichts gefunden wurde.
    """
    tweet_id = _tweet_id_from_url(tweet_url)
    if not tweet_id:
        return {}
    try:
        raw = http_get_with_retry(f"https://api.fxtwitter.com/status/{tweet_id}", timeout=10, retries=1)
        if not raw:
            return {}
        d = json.loads(raw)
        t = (d or {}).get("tweet") or {}
        if not t:
            return {}
        author = t.get("author") or {}
        return {
            "url": tweet_url,
            "author_name": author.get("name", ""),
            "author_handle": author.get("screen_name", ""),
            "author_avatar": author.get("avatar_url", ""),
            "text": t.get("text", ""),
            "likes": t.get("likes", 0),
            "retweets": t.get("retweets", 0),
            "views": t.get("views", 0),
        }
    except Exception as e:
        logger.debug("Tweet-Daten (fx) fehlgeschlagen %s: %s", tweet_id, e)
    return {}

def update_media_xpost_images(base_dir):
    """Ergänzt fehlende Vorschaubilder der X-Beiträge in media.json (serverseitig)."""
    path = base_dir / "media.json"
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    xposts = data.get("xposts") or []
    changed = False
    for x in xposts:
        if not isinstance(x, dict) or x.get("image"):
            continue
        img = fetch_tweet_image(_tweet_id_from_url(x.get("url", "")))
        if img:
            x["image"] = img
            changed = True
            logger.info("X-Vorschaubild ergänzt: %s", x.get("url", ""))
    if changed:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("media.json: X-Vorschaubilder aktualisiert")
        except Exception as e:
            logger.exception("Fehler beim Schreiben media.json: %s", e)

# -------------------------
# LLM – Zusammenfassungen (alle News, fuer Dashboard links)
# -------------------------
def summarize_news(alle_news, summary_cache=None):
    result = {i: {"title_de": n["title"], "summary": ""} for i, n in enumerate(alle_news)}
    if not OPENROUTER_KEY:
        logger.info("Kein OPENROUTER_KEY: Ueberspringe Zusammenfassungen.")
        return result

    # Laufzeit-Fix (02.07.26): bereits uebersetzte Artikel (per Link) aus dem
    # Cache bedienen, nur NEUE Artikel gehen an den LLM. Siehe load_summary_cache().
    pending = []
    for i, n in enumerate(alle_news):
        c = (summary_cache or {}).get(n.get("link", ""))
        if c and c.get("title_de"):
            result[i] = {"title_de": c["title_de"], "summary": c.get("summary", "")}
        else:
            pending.append(i)
    if summary_cache is not None:
        logger.info("Summary-Cache: %d von %d Artikeln aus Cache, %d neu zu uebersetzen",
                    len(alle_news) - len(pending), len(alle_news), len(pending))
    if not pending:
        return result

    # Kleinere Batches: je weniger News pro Call, desto seltener verwechselt das
    # LLM, welcher uebersetzte Titel zu welcher id gehoert (siehe Anker-Check unten).
    batch_size = 4
    url = "https://openrouter.ai/api/v1/chat/completions"

    # Placeholder-Erkennung: LLMs kopieren manchmal den Beispieltext aus dem Prompt
    PLACEHOLDER_PATTERNS = {
        "kurzer deutscher titel", "kurznews", "kurze meldung", "titel auf deutsch",
        "deutsche zusammenfassung", "news zusammenfassung", "hier der titel",
        "zusammenfassung hier", "titel hier", "schlagzeile", "beispieltitel",
    }
    def _is_placeholder(title: str) -> bool:
        t = title.lower().strip()
        return len(t) < 8 or any(p in t for p in PLACEHOLDER_PATTERNS)

    # Bekannte KI-Firmen-/Produktnamen - bewusst klein und kuratiert, KEINE
    # generische Grossschreibungs-Erkennung wie bei topic_keywords/entity_words
    # in generate_news_cards.py: im Deutschen wird jedes Substantiv grossgeschrieben,
    # eine Blacklist generischer Nomen waere hier so lang wie das halbe Vokabular.
    # Dient nur dem Content-Blending-Check unten - bei neuen wiederkehrenden
    # Faellen (andere Firma/Produkt wird vermischt) ergaenzen.
    _KNOWN_AI_ENTITIES = {
        "openai", "anthropic", "google", "deepmind", "meta", "microsoft",
        "samsung", "spacex", "tencent", "xai", "nvidia", "apple", "amazon",
        "chatgpt", "claude", "gemini", "codex", "reflection", "mistral",
        "perplexity", "groq", "cohere", "stability", "midjourney", "alibaba",
        "baidu", "huawei", "ibm", "salesforce", "oracle", "tesla",
    }

    def _entities_in(text: str) -> set:
        t = (text or "").lower()
        return {e for e in _KNOWN_AI_ENTITIES if e in t}

    # Sprachreinheit: title_de/summary sollen reines Deutsch sein. Beobachtet:
    # "AlpSemi收集 19,5 Millionen Dollar" - chinesische Zeichen aus der
    # Original-Quelle (oder einem mehrsprachigen Modell-Output) landeten
    # unuebersetzt im deutschen Titel. CJK-Unicode-Block reicht als Heuristik,
    # da deutsche Texte naturgemaess keine CJK-Zeichen enthalten.
    # 19.08.26 um Kyrillisch erweitert: im Summary eines Eintrags vom 16.08.
    # stand "war fast ein Jahr lang senderстви" - der Guard griff nicht, weil
    # er nur CJK/Kana/Hangul kannte.
    _CJK_PATTERN = re.compile(r'[一-鿿぀-ヿ가-힣Ѐ-ӿ]')

    def _has_foreign_script(text: str) -> bool:
        return bool(_CJK_PATTERN.search(text or ""))

    def _anchor_ok(src_echo: str, orig_title: str) -> bool:
        """Prueft ob das vom LLM zurueckgegebene src_title wirklich zum Original-
        Artikel an diesem Index gehoert. So faellt auf, wenn das Modell title_de
        an die falsche id gehaengt hat (Titel verrutscht -> falscher Link)."""
        if not src_echo or not orig_title:
            return False
        a = src_echo.lower().strip()
        b = orig_title.lower().strip()
        if not a:
            return False
        # Schneller Treffer: Anfang stimmt ueberein (Modell soll Originalanfang kopieren)
        if a[:18] in b or b[:18] in a:
            return True
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.5

    # Batches laufen ueber die PENDING-Indizes (Cache-Fix 02.07.26) - lokale
    # Batch-id 1..N wird ueber batch_indices auf den globalen Index abgebildet.
    for batch_start in range(0, len(pending), batch_size):
        globals()["_BATCH_VERSUCHE"] = globals()["_BATCH_VERSUCHE"] + 1
        batch_indices = pending[batch_start:batch_start + batch_size]
        batch = [alle_news[gi] for gi in batch_indices]
        news_text = "\n".join([f"{i+1}. {n['title']} (via {n['source']})" for i, n in enumerate(batch)])
        prompt = f"""Du bist ein deutschsprachiger KI-News-Redakteur.
Uebersetze und fasse JEDE der folgenden News auf Deutsch zusammen.
Antworte AUSSCHLIESSLICH mit einem JSON-Array – kein Text davor oder danach, keine Backticks, kein Markdown.

Format (ersetze Inhalt mit echten Werten fuer jede News):
[{{"id": 1, "src_title": "die ersten Woerter des ORIGINAL-Titels exakt kopiert", "title_de": "Echter deutscher Titel der News", "summary": "2-3 Saetze: was ist passiert und warum relevant fuer KI-Interessierte."}}, ...]

Wichtig:
- src_title MUSS die ersten Woerter des jeweiligen Original-Titels WORTWOERTLICH (unveraendert, gleiche Sprache) kopieren – das dient der Zuordnung
- title_de MUSS eine echte Uebersetzung GENAU DIESES Originaltitels sein
- Falls der Original-Titel einen Firmen-, Produkt- oder Personennamen enthaelt, MUSS title_de diesen Namen ebenfalls enthalten – ein Titel ohne das eigentliche Subjekt ("KI-Startup sammelt Millionen" statt "Baseten sammelt Millionen") ist nutzlos. Das gilt AUCH fuer Produkt-/Modellnamen aus mehreren Woertern ("Muse Spark", "Claude Sonnet 5"): den Namen WOERTLICH uebernehmen, NIEMALS durch einen Gattungsbegriff ersetzen - "Meta plant neues KI-Modell mit besseren Coding-Faehigkeiten" statt "Meta kuendigt Muse Spark an" ist ein FEHLER, denn Leser suchen nach genau diesem Namen
- title_de und summary AUSSCHLIESSLICH auf Deutsch, keine Zeichen aus anderen Schriftsystemen (z.B. chinesische/japanische/koreanische Zeichen) uebernehmen, auch wenn der Original-Titel mehrsprachig ist
- title_de MUSS ein Aussagesatz sein, KEINE Frage (kein Fragezeichen, keine Frageform wie "Hat X sich...?"). Falls der Original-Titel selbst eine Frage oder reine Spekulation ist, in eine Aussage mit Unsicherheits-Marker umformulieren (z.B. "moeglicherweise", "laut Bericht") statt die Frage zu uebernehmen – das gilt nur fuer die Formulierung, nicht als Grund den Artikel zu verwerfen
- title_de MUSS GENAU EIN Satz sein (genau EIN Satzzeichen . oder ! am Ende, sonst nichts) – KEIN zweiter Satz mit weiteren Erlaeuterungen ("...ins Auge gefasst. Dies koennte..."). Alles ueber den Kern-Fakt Hinausgehende (Einordnung, Kontext, Vermutungen zur Bedeutung) gehoert in summary, NIEMALS in title_de. Card-Rendering nutzt title_de als feste Kachel-Ueberschrift – ein zweisaetziger Titel sprengt das Layout.
- Jede id muss vorkommen (1 bis {len(batch)})
- Nur das JSON-Array zurueckgeben, sonst nichts

News:
{news_text}"""

        for modell in MODELLE:
            if _model_blocked(modell):
                continue
            try:
                data = json.dumps({
                    "model": modell,
                    "messages": [{"role": "user", "content": prompt}],
                    # 1500 statt vormals 900: bei batch_size=4 muss das Modell pro
                    # Item src_title (volle Kopie des Originaltitels) + title_de +
                    # summary unterbringen. 900/4 = 225 Tokens/Item war an der
                    # Grenze - beobachtetes Symptom in Live-Karten: title_de/summary
                    # brechen mitten im Satz ab ("SpaceX unterzeichnet"), JSON bleibt
                    # aber syntaktisch gueltig, daher faengt die ID-/Anker-Pruefung
                    # das nicht ab (siehe Vollstaendigkeits-Check unten).
                    "max_tokens": 1500
                }).encode()
                req = urllib.request.Request(url, data=data, headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://ki-news.live/",
                    "X-Title": "KI News Dashboard"
                })
                with urllib.request.urlopen(req, timeout=60) as r:
                    _roh = json.loads(r.read())
                    # HIER entstand das 'NoneType' object has no attribute
                    # 'strip' aus dem Log (4x, 21.08.): Reasoning-Modelle
                    # liefern HTTP 200 mit content=null, wenn das Token-Budget
                    # im unsichtbaren Denken aufgebraucht wird. Dieser Pfad ruft
                    # die API direkt auf, nicht ueber _call_llm_api() -- der
                    # Guard dort half hier also nicht. Sauber als Fehlschlag
                    # behandeln statt mit einer Meldung abzubrechen, die nach
                    # Programmierfehler aussieht.
                    antwort = (((_roh.get("choices") or [{}])[0].get("message")
                                or {}).get("content") or "").strip()
                    if not antwort:
                        raise ValueError(
                            "leerer Content (Reasoning-Budget aufgebraucht?)")
                    antwort = antwort.replace("```json", "").replace("```", "").strip()
                    summaries = json.loads(antwort)

                    # Validierung: kleinere/free Modelle liefern bei Batch-Uebersetzungen
                    # manchmal doppelte oder ausserhalb-des-Bereichs ids zurueck. Ohne
                    # Check landet ein title_de am FALSCHEN Artikel-Index - derselbe
                    # uebersetzte Titel-Text taucht dann bei einem anderen Artikel (anderer
                    # Link/Quelle) auf. Passt zum beobachteten Symptom wiederkehrender
                    # "falscher" Stories im Archiv (z.B. Wired-Eintraege mit Claude-Code-
                    # Preis-Titel, obwohl Link auf ein anderes Thema zeigt). Im Zweifel:
                    # ganzen Batch verwerfen, naechstes Modell versuchen, statt mit
                    # unsicherer Zuordnung weiterzumachen.
                    seen_ids = set()
                    ids_valid = True
                    for item in summaries:
                        iid = item.get("id")
                        if not isinstance(iid, int) or not (1 <= iid <= len(batch)) or iid in seen_ids:
                            ids_valid = False
                            break
                        seen_ids.add(iid)
                    if not ids_valid:
                        logger.warning(
                            "Batch %d: %s lieferte doppelte/ungueltige ids - Batch verworfen, naechstes Modell",
                            batch_start // batch_size + 1, modell
                        )
                        continue

                    # Anker-Pruefung: title_de + summary werden zusammen generiert und
                    # bleiben gepaart - aber das LLM haengt sie manchmal an die falsche
                    # id. Dann landet eine in sich stimmige Uebersetzung am falschen
                    # Artikel-Index (= falscher Link/Quelle). Die ID-Pruefung oben faengt
                    # das NICHT, weil die id formal gueltig bleibt. Wir lassen das Modell
                    # den Originaltitel zurueckgeben (src_title) und verifizieren, dass er
                    # zum Artikel an diesem Index passt. Bei Mismatch: ganzen Batch
                    # verwerfen statt falsche Zuordnung durchzulassen.
                    anchors_ok = True
                    for item in summaries:
                        gi = batch_indices[item["id"] - 1]
                        if not _anchor_ok(item.get("src_title", ""), alle_news[gi]["title"]):
                            anchors_ok = False
                            break
                    if not anchors_ok:
                        logger.warning(
                            "Batch %d: %s Anker-Mismatch (Titel verrutscht) - Batch verworfen, naechstes Modell",
                            batch_start // batch_size + 1, modell
                        )
                        continue

                    # Vollstaendigkeits-Pruefung: bei knappem max_tokens bricht das
                    # Modell manchmal das LETZTE Feld eines Items mitten im Gedanken
                    # ab, bleibt dabei aber JSON-valide - weder ID- noch Anker-Pruefung
                    # faengt das ab, weil beide nur auf Index-Verrutschen pruefen, nicht
                    # auf Vollstaendigkeit. Symptom beobachtet in Live-Karten: title_de
                    # "SpaceX unterzeichnet" (kein Satzende), summary endet ohne
                    # Satzzeichen mitten im Wort. Heuristik: title_de braucht >=3 Woerter
                    # (deutsche Kurznews-Titel sind praktisch nie kuerzer), summary muss
                    # auf Satzzeichen enden.
                    completeness_ok = True
                    for item in summaries:
                        # WICHTIG: gegen den REPARIERTEN Text pruefen, nicht gegen den
                        # rohen. _fix_latex_escapes() macht aus f{"u}r ein "für" -- wer
                        # vorher prueft, verwirft Texte, die sich reparieren lassen.
                        # (Belegt am 26.08.: beide LaTeX-Reste in archive.json vom
                        # 16.08. werden von _fix_latex_escapes vollstaendig geheilt.)
                        t = _fix_latex_escapes(item.get("title_de") or "").strip()
                        s = _fix_latex_escapes(item.get("summary") or "").strip()
                        # Zentraler Artefakt-Filter (26.08.26). Faengt das Muster hinter
                        # drei der letzten vier Produktionsfehler: Padding-Token,
                        # Refusals, Meta-Geschwaetz, Roh-JSON, HTML, Sprachmix,
                        # Emoji-/Wort-Spam, abgebrochene Texte. Alle Schwellen liegen
                        # bewusst weit vom echten Bestand entfernt -- siehe sanitize.py.
                        if (t and not _sanitize_llm_output(t)) or \
                           (s and not _sanitize_llm_output(s)):
                            completeness_ok = False
                            break
                        if t and len(t.split()) < 3:
                            completeness_ok = False
                            break
                        # Fund 06.07.26 (Daniels Karten-Screenshots): title_de kam manchmal
                        # als 2-Satz-Mini-Absatz zurueck ("...ins Auge gefasst. Dies koennte
                        # eine strategische Partnerschaft..."). generate_news_cards.py rendert
                        # title_de als feste Kachel-Ueberschrift - eine ueberlange 2-Satz-
                        # Headline sprengt dort das Flexbox-Layout und verdraengt den
                        # kompletten "Was ist passiert"-Block. Hier an der Wurzel abfangen:
                        # title_de darf nur EIN Satzende-Zeichen enthalten.
                        if t and len(re.findall(r"[.!?]", t)) > 1:
                            completeness_ok = False
                            break
                        if s and s[-1] not in ".!?\"'”":
                            completeness_ok = False
                            break
                        if _has_foreign_script(t) or _has_foreign_script(s):
                            completeness_ok = False
                            break
                    if not completeness_ok:
                        logger.warning(
                            "Batch %d: %s lieferte unvollstaendigen/fremdsprachigen Text (max_tokens-Abschnitt oder Sprachmix) - Batch verworfen, naechstes Modell",
                            batch_start // batch_size + 1, modell
                        )
                        continue

                    # Content-Blending-Check: src_title sagt uns das WIRKLICHE Thema
                    # des Artikels an diesem Index (durch Anker-Pruefung oben schon
                    # verifiziert). Wenn die summary NUR bekannte KI-Entitaeten nennt,
                    # die im Original-Thema gar nicht vorkommen, hat das Modell
                    # vermutlich Inhalte zweier verschiedener Artikel im selben Batch
                    # vermischt (beobachtet: Titel "OpenAI startet", Text faktisch ueber
                    # Anthropic). Anders als der Anchor-Check (Index verrutscht) bleibt
                    # hier der Index korrekt - nur der Inhalt selbst ist vermischt.
                    # Bewusst nur auf das kuratierte Namens-Set begrenzt (siehe oben),
                    # sonst zu viele False Positives durch legitime Konkurrenz-Vergleiche.
                    blending_ok = True
                    for item in summaries:
                        title_entities   = _entities_in(item.get("src_title", ""))
                        summary_entities = _entities_in(item.get("summary", ""))
                        if title_entities and summary_entities and not (title_entities & summary_entities):
                            blending_ok = False
                            break
                    if not blending_ok:
                        logger.warning(
                            "Batch %d: %s vermischt vermutlich Inhalte verschiedener Artikel (Entitaeten in summary passen nicht zum Thema) - Batch verworfen, naechstes Modell",
                            batch_start // batch_size + 1, modell
                        )
                        continue

                    for item in summaries:
                        global_index = batch_indices[item["id"] - 1]
                        raw_title = _fix_latex_escapes(item.get("title_de", ""))
                        # Placeholder-Schutz: falls LLM Beispieltext zurückgibt → Original behalten
                        title_de = raw_title if raw_title and not _is_placeholder(raw_title) \
                                   else alle_news[global_index]["title"]
                        result[global_index] = {
                            "title_de": title_de,
                            "summary": _fix_latex_escapes(item.get("summary", ""))
                        }
                        # Nur ECHTE LLM-Erfolge cachen (kein Placeholder-Fallback),
                        # sonst wuerde ein englischer Originaltitel zementiert.
                        link = alle_news[global_index].get("link", "")
                        if link and summary_cache is not None and raw_title and not _is_placeholder(raw_title):
                            summary_cache[link] = {
                                "title_de": title_de,
                                "summary": _fix_latex_escapes(item.get("summary", "")),
                                "generated_at": _today_iso(),
                            }
                    logger.info("Zusammenfassungen Batch %d OK mit %s", batch_start // batch_size + 1, modell)
                    _model_note_ok(modell)
                    globals()["_BATCH_OK"][modell] = globals()["_BATCH_OK"].get(modell, 0) + 1
                    break
            except HTTPError as e:
                if e.code == 429:
                    _model_note_429(modell)
                    logger.warning("Batch %d: %s Rate-Limit (429) – naechstes Modell",
                                   batch_start // batch_size + 1, modell)
                else:
                    logger.warning("Batch %d mit %s fehlgeschlagen: HTTP %s",
                                   batch_start // batch_size + 1, modell, e.code)
                continue
            except Exception as e:
                logger.warning("Batch %d mit %s fehlgeschlagen: %s",
                               batch_start // batch_size + 1, modell, e)
                continue
    return result

# -------------------------
# NEU: Einheitlicher LLM-Aufruf (OpenRouter + Ollama)
# -------------------------
def _call_llm_api(model, messages, max_tokens, timeout=90):
    """
    Ruft OpenRouter oder einen lokalen Ollama-Server auf.
    Modell-Prefix 'ollama/' → Ollama, alles andere → OpenRouter.
    Wirft HTTPError(429) bei Rate-Limit, Exception bei anderen Fehlern.
    """
    if model.startswith("ollama/"):
        ollama_model = model[7:]  # "ollama/gemma3:27b" → "gemma3:27b"
        url = f"{OLLAMA_HOST}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
    else:
        if not OPENROUTER_KEY:
            raise ValueError("Kein OPENROUTER_KEY gesetzt")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ki-news.live/",
            "X-Title": "KI News Dashboard",
        }
        ollama_model = model

    payload = {
        "model": ollama_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    # Reasoning-Schalter (14.08.26, Live-Test gegen die echte OpenRouter-API):
    # nvidia/nemotron-*:free-Modelle sind standardmaessig "Reasoning"-Modelle -
    # sie verbrauchen das GESAMTE max_tokens-Budget fuer unsichtbares Nachdenken
    # (completion_tokens_details.reasoning_tokens) und liefern bei unserem eng
    # bemessenen Budget (1500 fuer 4-Item-Batch, nur 150 fuer score_cluster_llm)
    # NIE die eigentliche Antwort - JSON leer/kaputt. Erst reasoning:{enabled:
    # false} schaltet das ab, live getestet: alle 4 Nemotron-Free-Modelle liefern
    # danach sauberes JSON. ACHTUNG: Nicht global setzen - openai/gpt-oss-*
    # (bereits im Einsatz, z.B. JUDGE_MODELLE) antwortet auf denselben Parameter
    # mit HTTP 400 "Reasoning is mandatory for this endpoint and cannot be
    # disabled." Deshalb bewusst nur fuer nvidia/-Modelle gesetzt.
    if ollama_model.startswith("nvidia/"):
        payload["reasoning"] = {"enabled": False}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        antwort = json.loads(r.read())
    inhalt = ((antwort.get("choices") or [{}])[0].get("message") or {}).get("content")
    # Leerer Content trotz HTTP 200: Reasoning-Modelle verbrennen bei knappem
    # Budget das ganze max_tokens im unsichtbaren Denken und liefern
    # content=null. Die beiden Aufrufer hier (score_cluster_llm, ask_llm) waren
    # dagegen schon abgesichert -- die NoneType-Meldungen im Log kamen aus dem
    # direkten API-Aufruf in summarize_news(), der jetzt ebenfalls prueft.
    # Trotzdem sinnvoll: eine Logzeile mit Modellnamen macht sichtbar, WELCHES
    # Modell leer liefert, statt es nur als anonymen Batch-Fehler zu zaehlen.
    if not inhalt:
        logger.warning("%s lieferte HTTP 200 mit leerem Content "
                       "(Reasoning-Budget aufgebraucht?) - gilt als Fehlschlag",
                       ollama_model)
        return ""
    return inhalt

# -------------------------
# LLM – Posts Scampy-6
# Bekommt nur MAX_LLM_NEWS Items – mehr = Fuelltext
# -------------------------
def ask_llm(top_news, n=None):
    if not OPENROUTER_KEY:
        fallback = ""
        for i in range(1, 4):
            fallback += f"TEASER {i}: Keine LLM-Verbindung – kein OPENROUTER_KEY.\n"
            for j in range(1, 7):
                fallback += f"THREAD {i}-{j}: Kein Key.\n"
            fallback += f"ERKLAERUNG {i}: Kein Key.\n"
        return fallback

    news_text = "\n".join([f"- {n['title']} (via {n['source']})" for n in top_news])

    system = """Du bist @ScampyKI, ein sachlicher aber neugieriger KI-Beobachter aus Deutschland.
Dein Stil: direkt, menschlich, keine Floskeln, keine Ausrufezeichen, kein "Sie".
Du ziehst den Leser rein – jeder Satz endet mit einer kleinen Spannung die zum naechsten zieht.
Du erklaerst was eine News WIRKLICH bedeutet – die Erkenntnis, nicht das Ereignis.
Du schreibst immer auf Deutsch, auch wenn die Quelle englisch ist.
Du erfindest keine Fakten."""

    n = n or len(top_news)
    # 02.07.26: Format-Block dynamisch fuer n Posts generieren - war vorher fest
    # auf 3 Posts kodiert und haette bei n=5 (MAX_LLM_NEWS-Erhoehung) dem Modell
    # ein widerspruechliches Beispiel gezeigt.
    format_block = "\n".join(
        f"TEASER {i}: [Text]\n"
        + "\n".join(f"THREAD {i}-{j}: [Text]" for j in range(1, 7))
        + f"\nERKLAERUNG {i}: [Text]"
        for i in range(1, n + 1)
    )
    user = f"""Schreibe GENAU {n} Posts – einen pro News. Nicht mehr, nicht weniger.

TEASER-Regeln:
- Beginne mit der Erkenntnis, nicht mit dem Ereignis
- Hook + Flip: erst die ueberraschende Wahrheit, dann die Konsequenz
- Maximal 265 Zeichen (Emojis zaehlen als 2)
- Kein Ausrufezeichen, kein Promotional Content
- Ende: (via Quellenname)

THREAD-Regeln – Scampy-6-Struktur:
THREAD X-1 Hook: Sofort rein, kein Anlauf, die Erkenntnis als erster Satz
THREAD X-2 Kontext: Historischer Rahmen + konkrete Zahlen
THREAD X-3 Kaskade: Was das Schritt fuer Schritt konkret bedeutet
THREAD X-4 Gruselig: Was daran beunruhigend oder faszinierend ist
THREAD X-5 Konsequenz: Was das fuer echte Menschen heute bedeutet
THREAD X-6 Fazit: Ein Gedanke der nachhallt – endet mit einer persoenlichen Frage an den Leser
Jeder Thread-Teil: mindestens 180, maximal 265 Zeichen. Kurze Antworten sind Fehler.

ERKLAERUNG (die "Scampy-Einordnung" auf der Website): zwei bis drei VOLLSTAENDIGE,
einfache Saetze, 90 bis 200 Zeichen. Stell dir vor, ein Kollege auf Arbeit ohne
KI-Vorwissen fragt dich in der Pause, was das bedeutet - erklaere es ihm so, dass
er es versteht, ohne sich dumm zu fuehlen, und weiss, warum es ihn betrifft (oder
ehrlich: dass es ihn nicht betrifft). Alltagssprache, gern ein Vergleich aus dem
Arbeitsleben, konkrete Zahlen. Keine Spitznamen fuer Laender/Behoerden, kein
Fachjargon, keine dramatische Zuspitzung. Beispiel fuer den Ton: "Die KI schreibt
jetzt Code, den man frueher einem Entwickler fuer 500 Euro am Tag gegeben haette.
Fuer grosse Firmen heisst das sparen, fuer Entwickler heisst das umdenken." KEINE
abgehackten Halbsaetze, kein Satz der mitten im Gedanken aufhoert.

Format – EXAKT so, keine Abweichungen:
{format_block}

News (genau diese {n}, je eine pro Post):
{news_text}"""

    # NEU: Ollama-Modelle an erster Stelle wenn lokal verfügbar
    ollama_available = _detect_ollama_models()
    modell_liste = ollama_available + MODELLE_POSTS

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    for modell in modell_liste:
        if _model_blocked(modell):
            continue
        try:
            # 02.07.26: max_tokens skaliert mit n (war fest 3600 fuer 3 Posts -
            # 5 volle Posts a 8 Segmente waeren sonst mitten im Text abgeschnitten
            # worden; die Vollstaendigkeits-Symptome kennen wir von summarize_news).
            antwort = _call_llm_api(modell, messages, max_tokens=min(1200 * n, 6000), timeout=120)
            if not antwort:
                logger.warning("Posts: %s liefert leeren Content – naechstes Modell", modell)
                continue
            logger.info("Posts OK mit Modell: %s", modell)
            _model_note_ok(modell)
            return antwort
        except HTTPError as e:
            if e.code == 429:
                _model_note_429(modell)
                logger.warning("Posts: %s Rate-Limit (429) – naechstes Modell", modell)
            else:
                logger.warning("Posts: %s fehlgeschlagen: HTTP %s", modell, e.code)
            continue
        except Exception as e:
            logger.warning("Posts: %s fehlgeschlagen: %s", modell, e)
            continue
    logger.error("Posts: Kein Modell verfuegbar – alle Fallbacks erschoepft")
    return "Fehler: Kein Modell verfuegbar"

# -------------------------
# Parsing
# -------------------------
def parse_posts(posts_raw):
    """Parst die LLM-Posts in ein Dict {post_nummer: {...}}.

    Frueher eine Liste in Ausgabe-Reihenfolge: gab das Modell TEASER 2 vor TEASER 1
    aus, verband das spaetere zip() in main() News 1 mit Post 2. Jetzt wird die
    Nummer aus 'TEASER N:' extrahiert und als Schluessel genutzt – Reihenfolge egal.
    """
    lines = posts_raw.strip().splitlines()
    result = {}
    current_idx = None
    current = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        upper = line.upper()

        m_teaser = re.match(r'TEASER\s+(\d+)\s*:', upper)
        if m_teaser:
            if current is not None and current_idx is not None:
                result[current_idx] = current
            current_idx = int(m_teaser.group(1))
            current = {"teaser": line.split(":", 1)[1].strip(), "thread": [], "erklaerung": ""}
        elif re.match(r'THREAD\s+\d+-\d+\s*:', upper):
            if current is not None:
                current["thread"].append(line.split(":", 1)[1].strip())
        elif re.match(r'ERKLAERUNG\s+\d+\s*:', upper):
            if current is not None:
                current["erklaerung"] = line.split(":", 1)[1].strip()

    if current is not None and current_idx is not None:
        result[current_idx] = current

    return result

# -------------------------
# Telegram – plain text, keine Labels
# Du teilst den Thread selbst ein beim Posten auf X
# -------------------------
def _sanitize_for_telegram(text):
    """Entfernt Zeichen die Telegram HTTP 400 verursachen."""
    # Telegram mag keine ungepaarten < > & Zeichen ohne parse_mode
    # Einfachste Loesung: plain text ohne parse_mode, aber < > & ersetzen
    text = text.replace("&", "und").replace("<", "(").replace(">", ")")
    return text

def _telegram_send_chunk(text, max_retries=3, delay=5):
    text = _sanitize_for_telegram(text)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    logger.info("Telegram: Chunk gesendet (Versuch %d)", attempt)
                    return True
                logger.warning("Telegram API ok=false: %s", resp)
        except Exception as e:
            logger.warning("Telegram Fehler (Versuch %d): %s", attempt, e)
        sleep(delay)
    return False

def _x_intent_url(text):
    """X mit vorbefuelltem Post-Text oeffnen (ein Tap vom Ticker zum Posting)."""
    return "https://x.com/intent/post?text=" + urllib.parse.quote(text or "", safe="")

def _telegram_send_message(text, buttons=None, max_retries=3, delay=5):
    """Einzelnachricht mit HTML-Formatierung + optionalen Inline-Buttons.
    Faellt bei HTML-Parse-Fehlern automatisch auf plain text zurueck."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(1, max_retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    return True
                logger.warning("Telegram API ok=false: %s", resp)
                if "parse" in str(resp.get("description", "")).lower():
                    # HTML-Problem -> naechster Versuch ohne parse_mode
                    payload.pop("parse_mode", None)
                    payload["text"] = _sanitize_for_telegram(text)[:4000]
        except Exception as e:
            logger.warning("Telegram Fehler (Versuch %d): %s", attempt, e)
        sleep(delay)
    return False

def send_telegram_stories(stories, score_map=None, detailliert=False):
    """Eine Nachricht PRO neuer Story: Label + fetter Titel + Teaser +
    Erklaerung, Buttons 'Auf X posten' (Intent-Link) und 'Artikel'.
    detailliert=True (wenige neue Storys, Schwelle beim Aufrufer): Die ERSTE
    Story der Liste (= hoechster Score) bekommt den kompletten Thread-Entwurf
    angehaengt. Vorher (bis 04.07.26) nur bei GENAU 1 neuer Story - dadurch war
    der Analyse-Ausbau bei Nachrichtenflaute praktisch verschwunden."""
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False
    score_map = score_map or {}

    def esc(t):
        return _html.escape(t or "", quote=False)

    ok_all = True
    for _story_idx, (n, p) in enumerate(stories):
        label = score_map.get(n.get("link", ""), {}).get("label", "")
        teile = [f"{label} <b>{esc(n.get('title', ''))}</b>".strip()]
        if p.get("teaser"):
            teile += ["", esc(p["teaser"])]
        if p.get("erklaerung"):
            teile += ["", f"<i>{esc(p['erklaerung'])}</i>"]
        if detailliert and _story_idx == 0 and p.get("thread"):
            teile += ["", "<b>Thread-Entwurf:</b>"]
            teile += [f"{i}/ {esc(tweet)}" for i, tweet in enumerate(p["thread"], 1)]
        buttons_row = []
        if p.get("teaser"):
            buttons_row.append({"text": "Auf X posten", "url": _x_intent_url(p["teaser"])})
        if n.get("link"):
            buttons_row.append({"text": "Artikel", "url": n["link"]})
        ok = _telegram_send_message("\n".join(teile), [buttons_row] if buttons_row else None)
        ok_all = ok and ok_all
        sleep(1)  # Telegram-Rate-Limit schonen
    return ok_all

def send_telegram(parsed):
    if not TELEGRAM_TOKEN:
        logger.warning("Kein Telegram Token. Ueberspringe Versand.")
        return False

    teile = ["KI News fuer @ScampyNews24_bot\n"]
    for i, p in enumerate(parsed, 1):
        teile.append(f"--- Post {i} ---")
        teile.append(p["teaser"])
        if p.get("erklaerung"):
            teile.append(f"({p['erklaerung']})")
        teile.append("")

    nachricht = "\n".join(teile).strip()

    chunks = []
    if len(nachricht) <= 4000:
        chunks = [nachricht]
    else:
        current_chunk = ""
        for zeile in teile:
            candidate = (current_chunk + "\n" + zeile).strip()
            if len(candidate) > 4000:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = zeile
            else:
                current_chunk = candidate
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

    success = all(_telegram_send_chunk(chunk) for chunk in chunks)
    if not success:
        logger.error("Telegram: Mindestens ein Chunk fehlgeschlagen.")
    return success

# -------------------------
# HTML
# -------------------------
def create_html(alle_news, parsed, summaries):
    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

    news_html = ""
    for i, n in enumerate(alle_news):
        farbe = SOURCE_COLORS.get(n["source"], "#555")
        summary = summaries.get(i, {})
        title_de = summary.get("title_de", n["title"])
        summary_text = summary.get("summary", "")
        news_html += f'''
        <div class="news-item" onclick="toggleNews(this)">
            <div class="news-header">
                <span class="source-badge" style="background:{farbe}">{n["source"]}</span>
                <span class="news-title">{title_de}</span>
                <span class="news-arrow">&#9662;</span>
            </div>
            <div class="news-expand">
                {f'<p class="news-summary">{summary_text}</p>' if summary_text else ""}
                <a href="{n["link"]}" target="_blank" onclick="event.stopPropagation()">&#8594; Artikel lesen</a>
            </div>
        </div>'''

    posts_html = ""
    for i, p in enumerate(parsed, 1):
        teaser = p["teaser"]
        erklaerung = p.get("erklaerung", "")
        thread = p.get("thread", [])
        zeichen = len(teaser)
        zahl_farbe = "#16a34a" if zeichen <= 265 else "#dc2626"

        quelle_name = ""
        quelle_farbe = "#555"
        if "(via " in teaser:
            try:
                quelle_name = teaser.split("(via ")[-1].rstrip(")").strip()
                quelle_farbe = next(
                    (v for k, v in SOURCE_COLORS.items() if k.lower() in quelle_name.lower()), "#555"
                )
            except Exception:
                quelle_name = ""

        thread_html = ""
        if thread:
            n_parts = len(thread)
            thread_parts_html = ""
            for j, t in enumerate(thread, 1):
                label = THREAD_LABELS[j - 1] if j - 1 < len(THREAD_LABELS) else str(j)
                t_zeichen = len(t)
                t_farbe = "#16a34a" if t_zeichen <= 265 else "#dc2626"
                thread_parts_html += f'''
                <div class="thread-part">
                    <div class="thread-meta">
                        <span class="thread-nr">{j}/{n_parts} {label}</span>
                        <span class="thread-zeichen" style="color:{t_farbe}">{t_zeichen}/265</span>
                    </div>
                    <p class="thread-text" id="thread{i}-{j}">{t}</p>
                    <button class="btn-copy-sm" onclick="copyPost(\'thread{i}-{j}\', this)">Kopieren</button>
                </div>'''

            thread_html = f'''
            <div class="thread-toggle" onclick="toggleThread(this)">&#9658; Thread anzeigen ({n_parts} Teile)</div>
            <div class="thread-section" style="display:none">
                {thread_parts_html}
            </div>'''

        posts_html += f'''
        <div class="post-card">
            <div class="post-meta">
                <span class="post-nr">Post {i}</span>
                <span class="post-zeichen" style="color:{zahl_farbe}">{zeichen}/265</span>
            </div>
            <p class="post-text" id="teaser{i}">{teaser}</p>
            {f'<p class="post-erklaerung">{erklaerung}</p>' if erklaerung else ""}
            {f'<span class="post-quelle" style="background:{quelle_farbe}">{quelle_name}</span>' if quelle_name else ""}
            <div class="post-actions">
                <button class="btn-copy" onclick="copyPost(\'teaser{i}\', this)">Kopieren</button>
                <a href="https://x.com/intent/tweet?text={{}}"
                   onclick="this.href=\'https://x.com/intent/tweet?text=\'+encodeURIComponent(document.getElementById(\'teaser{i}\').textContent)"
                   target="_blank" class="btn-x">Posten</a>
            </div>
            {thread_html}
        </div>'''

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KI News Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, Arial, sans-serif; background: #0a0a0a; color: #e7e9ea; min-height: 100vh; }}
        .header {{ background: #000; border-bottom: 1px solid #2f3336; padding: 14px 24px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 10; }}
        .header h1 {{ color: #1d9bf0; font-size: 18px; font-weight: 700; }}
        .header-stats {{ margin-left: auto; display: flex; gap: 20px; }}
        .stat {{ text-align: center; }}
        .stat-zahl {{ font-size: 18px; font-weight: 700; color: #1d9bf0; }}
        .stat-label {{ font-size: 10px; color: #536471; text-transform: uppercase; letter-spacing: 0.5px; }}
        .datum {{ color: #536471; font-size: 12px; margin-left: 16px; }}
        .layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; max-width: 1200px; margin: 0 auto; min-height: calc(100vh - 57px); }}
        .panel {{ padding: 20px; }}
        .panel-left {{ border-right: 1px solid #2f3336; }}
        .panel-title {{ color: #536471; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; padding-bottom: 12px; border-bottom: 1px solid #2f3336; margin-bottom: 4px; }}
        .news-item {{ border-bottom: 1px solid #1a1a1a; cursor: pointer; transition: background 0.15s; border-radius: 6px; }}
        .news-item:hover {{ background: #111; }}
        .news-item.open {{ background: #111; border: 1px solid #2f3336; margin: 4px 0; }}
        .news-header {{ padding: 12px 8px; display: flex; align-items: flex-start; gap: 8px; }}
        .news-title {{ color: #e7e9ea; font-size: 14px; line-height: 1.4; flex: 1; }}
        .news-arrow {{ color: #536471; font-size: 12px; margin-top: 2px; flex-shrink: 0; transition: transform 0.2s; }}
        .news-item.open .news-arrow {{ transform: rotate(180deg); color: #1d9bf0; }}
        .source-badge {{ color: white; font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 10px; white-space: nowrap; margin-top: 2px; flex-shrink: 0; }}
        .news-expand {{ display: none; padding: 0 8px 14px 8px; }}
        .news-item.open .news-expand {{ display: block; }}
        .news-summary {{ font-size: 13px; color: #94a3b8; line-height: 1.5; margin-bottom: 10px; }}
        .news-expand a {{ color: #1d9bf0; font-size: 13px; font-weight: 600; text-decoration: none; }}
        .news-expand a:hover {{ text-decoration: underline; }}
        .post-card {{ background: #111; border: 1px solid #2f3336; border-radius: 14px; padding: 16px; margin: 10px 0; transition: border-color 0.2s; }}
        .post-card:hover {{ border-color: #1d9bf0; }}
        .post-meta {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .post-nr {{ color: #1d9bf0; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }}
        .post-zeichen {{ font-size: 11px; font-weight: 700; }}
        .post-text {{ font-size: 15px; line-height: 1.5; color: #e7e9ea; margin-bottom: 6px; }}
        .post-erklaerung {{ font-size: 12px; color: #536471; margin-bottom: 8px; font-style: italic; }}
        .post-quelle {{ display: inline-block; color: white; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; margin-bottom: 10px; }}
        .post-actions {{ display: flex; gap: 8px; margin-top: 10px; }}
        .btn-copy, .btn-x {{ padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; transition: opacity 0.2s; border: none; }}
        .btn-copy {{ background: #2f3336; color: #e7e9ea; }}
        .btn-copy:hover {{ opacity: 0.8; }}
        .btn-x {{ background: #1d9bf0; color: white; }}
        .btn-x:hover {{ opacity: 0.8; }}
        .copied {{ background: #16a34a !important; }}
        .thread-toggle {{ color: #536471; font-size: 12px; cursor: pointer; margin-top: 12px; padding: 8px 0 0 0; border-top: 1px solid #1a1a1a; user-select: none; transition: color 0.2s; }}
        .thread-toggle:hover {{ color: #1d9bf0; }}
        .thread-section {{ margin-top: 8px; }}
        .thread-part {{ background: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 10px; padding: 10px 12px; margin: 6px 0; }}
        .thread-meta {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .thread-nr {{ color: #536471; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }}
        .thread-zeichen {{ font-size: 10px; font-weight: 700; }}
        .thread-text {{ font-size: 14px; line-height: 1.5; color: #e7e9ea; margin-bottom: 8px; }}
        .btn-copy-sm {{ padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 700; cursor: pointer; background: #1a1a1a; color: #94a3b8; border: 1px solid #2f3336; transition: opacity 0.2s; }}
        .btn-copy-sm:hover {{ opacity: 0.8; }}
        @media (max-width: 700px) {{
            .layout {{ grid-template-columns: 1fr; }}
            .panel-left {{ border-right: none; border-bottom: 1px solid #2f3336; }}
        }}
    </style>
    <script>
        function toggleNews(el) {{ el.classList.toggle('open'); }}
        function toggleThread(btn) {{
            const section = btn.nextElementSibling;
            const isOpen = section.style.display !== 'none';
            section.style.display = isOpen ? 'none' : 'block';
            const n = section.querySelectorAll('.thread-part').length;
            btn.innerHTML = isOpen
                ? '&#9658; Thread anzeigen (' + n + ' Teile)'
                : '&#9660; Thread ausblenden';
        }}
        function copyPost(id, btn) {{
            navigator.clipboard.writeText(document.getElementById(id).textContent);
            const orig = btn.textContent;
            btn.textContent = 'Kopiert';
            btn.classList.add('copied');
            setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 2000);
        }}
    </script>
</head>
<body>
    <div class="header">
        <h1>KI News</h1>
        <div class="header-stats">
            <div class="stat"><div class="stat-zahl">{len(alle_news)}</div><div class="stat-label">News</div></div>
            <div class="stat"><div class="stat-zahl">{len(parsed)}</div><div class="stat-label">Posts</div></div>
            <div class="stat"><div class="stat-zahl">{len(set(n['source'] for n in alle_news))}</div><div class="stat-label">Quellen</div></div>
        </div>
        <span class="datum">Stand: {datum}</span>
    </div>
    <div class="layout">
        <div class="panel panel-left">
            <div class="panel-title">Aktuelle KI-News</div>
            {news_html}
        </div>
        <div class="panel panel-right">
            <div class="panel-title">Post-Vorschlaege fuer @ScampyKI</div>
            {posts_html}
        </div>
    </div>
</body>
</html>"""

    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"

    if proj_dir.exists():
        # Lokal: nur ki_news.html schreiben – index.html ist die Tailwind-Seite, nie überschreiben
        pfad_lokal = str(proj_dir / "ki_news.html")
        try:
            Path(pfad_lokal).write_text(html, encoding="utf-8")
            logger.info("HTML geschrieben: ki_news.html")
        except Exception as e:
            logger.exception("Fehler beim Schreiben HTML: %s", e)
        return pfad_lokal
    else:
        # GitHub Actions: Posts-HTML als ki_news.html, index.html (Tailwind-Dashboard) NICHT anfassen
        pfad = "ki_news.html"
        try:
            Path(pfad).write_text(html, encoding="utf-8")
            logger.info("HTML geschrieben: %s", pfad)
        except Exception as e:
            logger.exception("Fehler beim Schreiben HTML: %s", e)
        return pfad

# -------------------------
# Entity-Graph (Phase 2, 16.07.26) — kumulativer, unsichtbarer Daten-Step
# -------------------------
def update_entity_graph(base_dir, news_items, link_to_story=None):
    """Schreibt graph.json kumulativ fort: Knoten = kuratierte Entitäten aus
    entities.json, Kanten = Ko-Okkurrenzen zweier Entitäten in Titel+Summary
    desselben Artikels. Zählt über Läufe hinweg weiter (kumulativ), auch wenn
    Artikel längst aus archive.json (10 Tage) herausgealtert sind.

    Vertragsregeln (ki-news-architektur-vertrag):
    - entities.json wird NUR GELESEN — kuratierte Registry, Pflege manuell
      per GitHub-Web-Upload (wie dashboard_config.json). Fehlt sie: Skip + WARN.
    - graph.json hat genau EINEN Schreiber: diese Funktion (Invariante I5).
      GENERIERTE Datei — nie manuell editieren (Invariante I6).
    - Idempotent über "seen"-Delta-State: jeder Artikel-Link wird genau einmal
      gezählt, egal wie oft ein Lauf wiederholt wird. seen wird nach 30 Tagen
      geprunt — ungefährlich, weil archive.json/news.json nur max. 10 Tage
      alte Artikel liefern, ein Link also nie nach >30 Tagen wiederkommt.
    - Fehler blockieren NIE die Pipeline (Invariante I8): nur Log, kein Raise.
    - Unsichtbar: kein SSR, kein Frontend-Bezug, reiner Datenaufbau.

    link_to_story (11.08.2026, erste Live-Nutzung der Shadow-Registry):
    optionale {link: story_id}-Map aus story_registry_shadow.link_to_story_map().
    Wenn vorhanden, wird pro STORY (nicht mehr pro Link) höchstens einmal
    gezählt — verhindert, dass dieselbe reale Meldung über mehrere Quellen-
    Links (Cross-Source-Duplikate, von der Registry erkannt) die Kanten-
    Gewichte künstlich vervielfacht. Fail-safe additiv: fehlt die Map oder
    kennt sie einen Link nicht, verhält sich der Code exakt wie vorher
    (Dedup rein über den Link). Bewusst NUR die Zähllogik hier betroffen —
    kein SSR/Frontend-Bezug, also weiterhin "unsichtbar" im Sinne des
    Vertrags oben; das ist der von Daniel gewünschte erste Schritt (Graph-
    Datenqualität), noch keine sichtbare Graph-Feature auf der Website.
    """
    ENTITY_SEEN_MAX_DAYS = 30
    link_to_story = link_to_story or {}
    try:
        base = Path(base_dir)
        ent_path = base / "entities.json"
        graph_path = base / "graph.json"
        if not ent_path.exists():
            logger.warning("entities.json fehlt - Entity-Graph-Step uebersprungen")
            return
        registry = json.loads(ent_path.read_text(encoding="utf-8")).get("entities", [])
        meta, comp = {}, []   # id -> Registry-Eintrag | Liste (id, kompiliertes Pattern)
        for e in registry:
            try:
                comp.append((e["id"], re.compile("|".join(e["aliasse"]), re.I)))
                meta[e["id"]] = e
            except Exception:
                logger.warning("entities.json: Eintrag %r unbrauchbar, uebersprungen", e.get("id"))
        if not comp:
            logger.warning("entities.json: keine brauchbaren Eintraege - Step uebersprungen")
            return

        # Bestehenden Graph laden (kumulativer Zustand); unlesbar -> Neustart bei 0
        nodes, edges, seen, seen_stories = {}, {}, {}, {}
        if graph_path.exists():
            try:
                g = json.loads(graph_path.read_text(encoding="utf-8"))
                nodes = {n["id"]: n for n in g.get("nodes", []) if n.get("id")}
                edges = {(ed["source"], ed["target"]): ed
                         for ed in g.get("edges", []) if ed.get("source") and ed.get("target")}
                if isinstance(g.get("seen"), dict):
                    seen = g["seen"]
                if isinstance(g.get("seen_stories"), dict):
                    seen_stories = g["seen_stories"]
            except Exception:
                logger.exception("graph.json unlesbar - Graph startet neu bei 0")

        today = datetime.now(BERLIN).strftime("%Y-%m-%d")
        new_articles = 0
        story_dupes_skipped = 0
        for it in news_items:
            link = it.get("link")
            if not link or link in seen:
                continue
            seen[link] = today
            sid = link_to_story.get(link)
            if sid:
                if sid in seen_stories:
                    # Eine andere Quelle derselben Registry-Story hat diese
                    # Entitaeten in einem frueheren Lauf schon gezaehlt.
                    story_dupes_skipped += 1
                    continue
                seen_stories[sid] = today
            text = f"{it.get('title', '')} {it.get('summary', '')}"
            found = [eid for eid, pat in comp if pat.search(text)]
            if not found:
                continue
            new_articles += 1
            for eid in found:
                n = nodes.get(eid)
                if n is None:
                    n = {"id": eid, "count": 0, "first_seen": today}
                    nodes[eid] = n
                # typ/gehoert_zu bei jedem Lauf aus der Registry auffrischen,
                # damit Kuratierungs-Aenderungen in entities.json durchschlagen
                n["typ"] = meta[eid].get("typ")
                n["gehoert_zu"] = meta[eid].get("gehoert_zu")
                n["count"] = int(n.get("count", 0)) + 1
                n["last_seen"] = today
            for i, a in enumerate(found):
                for b in found[i + 1:]:
                    key = tuple(sorted((a, b)))
                    ed = edges.get(key)
                    if ed is None:
                        ed = {"source": key[0], "target": key[1], "count": 0, "first_seen": today}
                        edges[key] = ed
                    ed["count"] = int(ed.get("count", 0)) + 1
                    ed["last_seen"] = today

        # seen-Delta-State prunen (Datei waechst sonst unbegrenzt)
        seen = {k: v for k, v in seen.items() if _days_since(v) <= ENTITY_SEEN_MAX_DAYS}
        seen_stories = {k: v for k, v in seen_stories.items() if _days_since(v) <= ENTITY_SEEN_MAX_DAYS}

        out = {
            "_hinweis": "GENERIERT von ki_news.py (update_entity_graph) - NICHT manuell editieren. Kuratierung laeuft ueber entities.json.",
            "stand": datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M"),
            "nodes": sorted(nodes.values(), key=lambda n: -int(n.get("count", 0))),
            "edges": sorted(edges.values(), key=lambda e: -int(e.get("count", 0))),
            "seen": seen,
            "seen_stories": seen_stories,
        }
        graph_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("graph.json aktualisiert: %d Knoten, %d Kanten (+%d neue Artikel mit Entitaeten, "
                    "%d Cross-Source-Duplikate per Story-Registry uebersprungen)",
                    len(nodes), len(edges), new_articles, story_dupes_skipped)
    except Exception as e:
        logger.exception("Entity-Graph-Step fehlgeschlagen (Pipeline laeuft weiter): %s", e)


# -------------------------
# Main
# -------------------------
def main():
    logger.info("Starte KI News Lauf")
    alle_news = []
    for name, url in FEEDS:
        try:
            items = fetch_feed(name, url)
            alle_news.extend(items)
            logger.info("[%s] %d relevante News", name, len(items))
        except Exception as e:
            logger.exception("Fehler beim Feed %s: %s", name, e)

    seen = set()
    unique_news = []
    for n in alle_news:
        if n.get("link") and n["link"] not in seen:
            seen.add(n["link"])
            unique_news.append(n)
    alle_news = unique_news

    # Wochenzusammenfassungen (Roundups) abtrennen, BEVOR geclustert/bewertet wird.
    # Sonst wirken sie als Keyword-Magnet und blaehen Cluster-Scores auf. Sie bleiben
    # als Material erhalten (news.json -> "roundups"), erscheinen aber nicht in der
    # News-Liste, auf der Startseite oder in der Breaking-Karte.
    roundup_items = [n for n in alle_news if _is_roundup(n)]
    alle_news     = [n for n in alle_news if not _is_roundup(n)]
    if roundup_items:
        logger.info("%d Wochenzusammenfassung(en) abgetrennt (Material, nicht sichtbar)", len(roundup_items))

    # Werbung/Sponsored ('Anzeige: ...') komplett raus – kein Material, keine Anzeige.
    _before_ads = len(alle_news)
    alle_news = [n for n in alle_news if not _is_ad(n)]
    if _before_ads != len(alle_news):
        logger.info("%d Werbung/Anzeige-Eintraege entfernt", _before_ads - len(alle_news))

    if not alle_news:
        logger.info("Keine KI-News gefunden.")
        return

    # Bug 26.06.: gepinnte/regionale Artikel aus archive.json zurueckholen, falls sie
    # aus dem frischen RSS-Fenster rausgescrollt sind (siehe Docstring der Funktion).
    # Muss VOR summarize_news() passieren, damit recallte Items ganz normal mit-
    # zusammengefasst, mit-geclustert und mit-bewertet werden - kein Sonderpfad danach.
    _early_cfg_base = (Path.home() / "Documents" / "Projekte" / "ki-news")
    _early_cfg_base = _early_cfg_base if _early_cfg_base.exists() else Path(".")
    _early_featured_links = load_dashboard_config(_early_cfg_base).get("featured_links", [])
    _early_archive = []
    try:
        _early_arch_path = _early_cfg_base / "archive.json"
        if _early_arch_path.exists():
            _early_archive = json.loads(_early_arch_path.read_text(encoding="utf-8"))
    except Exception:
        _early_archive = []
    recalled_items = _recall_relevant_from_archive(alle_news, _early_archive, _early_featured_links)
    if recalled_items:
        logger.info(
            "%d Artikel aus archive.json zurueckgeholt (Pin/regional, aus RSS-Fenster gescrollt): %s",
            len(recalled_items), [r.get("title", "")[:50] for r in recalled_items],
        )
        alle_news.extend(recalled_items)
        seen_links_recall = set()
        _dedup_after_recall = []
        for n in alle_news:
            if n.get("link") and n["link"] not in seen_links_recall:
                seen_links_recall.add(n["link"])
                _dedup_after_recall.append(n)
        alle_news = _dedup_after_recall

    logger.info("%d KI-News gefunden (gesamt, ohne Roundups)", len(alle_news))

    # Zusammenfassungen fuer alle News (Dashboard links)
    # Laufzeit-Fix (02.07.26): Cache pro Link - nur neue Artikel gehen an den LLM.
    _summary_cache = load_summary_cache(_early_cfg_base)
    summaries = summarize_news(alle_news, _summary_cache)
    save_summary_cache(_early_cfg_base, _summary_cache)

    # Link->Summary-Map: summaries ist nach dem ORIGINAL-Index gekeyt. Der
    # blocked_links-Filter weiter unten weist alle_news aber NEU zu (kuerzere Liste)
    # -> danach passt summaries.get(i) nicht mehr zu alle_news[i] (Titel/Summary
    # verrutschen gegen Link/Quelle). Wir merken uns die Zuordnung per LINK, bevor
    # gefiltert wird, und richten summaries nach dem Filter wieder am Index aus.
    _summary_by_link = {
        alle_news[i].get("link"): summaries.get(i, {})
        for i in range(len(alle_news))
        if alle_news[i].get("link")
    }

    # Link->Titel-DE-Map: sofort aufgebaut, bevor blocked_links die alle_news-Indizes verschiebt.
    # Wird fuer Telegram benoetigt (send_telegram_stories nutzt n['title'] direkt).
    _title_de_by_link = {
        alle_news[i].get("link"): summaries.get(i, {}).get("title_de") or alle_news[i]["title"]
        for i in range(len(alle_news))
        if alle_news[i].get("link")
    }

    # ── Score-Verfall-Historie früh laden, damit Telegram-Auswahl UND Dashboard
    #    nach demselben (verfallenen) Score ranken → identische Top-Storys ──────
    heute = _today_iso()
    proj_dir = Path.home() / "Documents" / "Projekte" / "ki-news"
    _archive_base = proj_dir if proj_dir.exists() else Path(".")
    _existing_archive = []
    try:
        _arch_path = _archive_base / "archive.json"
        if _arch_path.exists():
            _existing_archive = json.loads(_arch_path.read_text(encoding="utf-8"))
    except Exception:
        _existing_archive = []
    _cap_inflated_base_scores(_existing_archive)  # Einmal-Migration 04.07.26, s. Funktion
    history = build_history_map(_existing_archive)

    # Cluster-Membership-Map: link → ältester first_seen im Cluster (Story-Alter-Fix)
    # Verhindert dass neue Artikel über bekannte Storys mit frischem Datum auftauchen.
    # Cross-Run-Duplikat-Fix (13.07.26) - WIEDER DEAKTIVIERT, s. Kommentar bei
    # der zweiten cluster_news()-Aufrufstelle in pick_top_news() oben.
    _clusters = cluster_news(alle_news, None)
    link_to_cluster_age = {}
    for cl in _clusters:
        cl_histories = [history[item["link"]] for item in cl if item.get("link") in history]
        if cl_histories:
            oldest = min(h["first_seen"] for h in cl_histories)
            for item in cl:
                if item.get("link"):
                    link_to_cluster_age[item["link"]] = oldest

    # Dashboard-Config laden (featured + blocked links)
    _cfg_base = proj_dir if proj_dir.exists() else Path(".")
    dash_cfg = load_dashboard_config(_cfg_base)
    featured_links = dash_cfg.get("featured_links", [])
    blocked_links  = set(dash_cfg.get("blocked_links", []))
    if blocked_links:
        before = len(alle_news)
        alle_news = [n for n in alle_news if n.get("link") not in blocked_links]
        logger.info("Blocked-Filter: %d News entfernt", before - len(alle_news))

    # summaries nach dem Filter wieder am (neuen) Index ausrichten – per Link, damit
    # create_html und die news.json-Karten (beide nutzen summaries.get(i)) garantiert
    # zum jeweiligen alle_news[i] passen. Idempotent wenn nichts geblockt wurde.
    summaries = {
        i: _summary_by_link.get(n.get("link", ""), {"title_de": n["title"], "summary": ""})
        for i, n in enumerate(alle_news)
    }

    # Bug-Fix (26.06.26), KORRIGIERT (selber Tag, 2. Versuch): bereits per
    # Telegram verschickte Links sollen die MAX_LLM_NEWS=3-Plaetze nicht
    # blockieren (dominante Mega-Stories halten ihren Score stundenlang, der
    # alte Dedup-Check kam erst NACH der Top-3-Auswahl -> alle 3 Plaetze
    # "verbraucht", frische/gepinnte Artikel kamen nie durch).
    # ERSTER Versuch (s.u. als Kommentar zur Erinnerung) hat _alle_news_fuer_
    # topnews VOR pick_top_news() gefiltert - das war falsch: pick_top_news()
    # berechnet eff_score (inkl. Featured-Boost) fuer ALLE Cluster und gibt
    # das ueber score_map an news.json weiter (s. Kommentar bei eff_score
    # oben in pick_top_news). Wer hier rausgefiltert wird, bekommt nie einen
    # eff_score-Eintrag - genau das hat den gepinnten Heise-Polizeigesetz-
    # Artikel getroffen (war schon einmal getelegramt, fiel komplett aus dem
    # Scoring raus, news.json bekam wieder den ungeboosteten Rohscore).
    # Fix jetzt: alle_news bleibt UNGEFILTERT fuer pick_top_news (volles
    # Scoring fuer jeden Artikel bleibt erhalten), der Sent-Filter wirkt erst
    # INNERHALB von pick_top_news beim Befuellen der finalen Top-n-Liste
    # (siehe Parameter already_sent dort) - score_map/link_to_cluster_info
    # bleiben unangetastet fuer alle Artikel.
    _tg_sent_links_early = set()
    try:
        _tg_sent_links_early = set(
            json.loads(Path("telegram_state.json").read_text(encoding="utf-8")).get("sent_links", {}).keys()
        )
    except Exception:
        pass

    # NEU: Top-3 nach (verfallenem) Scoring wählen statt blindem [:3]
    top_news, score_map, link_to_cluster_info = pick_top_news(
        alle_news, n=MAX_LLM_NEWS, history=history, featured_links=featured_links,
        existing_archive=_existing_archive, already_sent=_tg_sent_links_early,
    )
    logger.info("%d News an LLM uebergeben (nach Scoring)", len(top_news))

    # Post-Cache laden – LLM nur für noch nicht analysierte Stories aufrufen
    post_cache = load_post_cache(_cfg_base)
    heute_str  = _today_iso()
    uncached   = [n for n in top_news if n.get("link") not in post_cache]
    cached     = [n for n in top_news if n.get("link") in post_cache]
    if uncached:
        posts_raw       = ask_llm(uncached, n=len(uncached))
        parsed_new_dict = parse_posts(posts_raw)  # {nummer: {...}}
        logger.info("%d neue Posts geparst, %d aus Cache", len(parsed_new_dict), len(cached))
        for idx, news_item in enumerate(uncached, start=1):
            link = news_item.get("link", "")
            p = parsed_new_dict.get(idx, {"teaser": "", "erklaerung": "", "thread": []})
            # Zuordnungs-Guard (03.07.26): Der Teaser MUSS laut Prompt mit
            # "(via Quellenname)" enden - das ist ein Fingerabdruck, WORUEBER
            # das LLM wirklich geschrieben hat. Passt er nicht zur Quelle der
            # News an Position idx, hat das LLM die Nummerierung verwuerfelt
            # (Vorfall 03.07.: OpenAI-Headline bekam den Mistral-Teaser und
            # der Fehler wurde dann auch noch gecacht). Mismatch -> Post
            # verwerfen und NICHT cachen: naechster Lauf generiert neu.
            # Besser keine Einordnung als eine falsche.
            _teaser = p.get("teaser", "")
            _via = ""
            if "(via " in _teaser:
                _via = _teaser.rsplit("(via ", 1)[-1].rstrip(")").strip()
            _src = (news_item.get("source") or "").strip()
            if _via and _src and _via.lower() != _src.lower():
                logger.warning(
                    "Post-Zuordnung verworfen: TEASER %d nennt '(via %s)', News-Quelle ist aber '%s' (%s)",
                    idx, _via, _src, link,
                )
                continue
            # Qualitaets-Gate (03.07.26 abends, OpenRouter-Brownout): Der Prompt-
            # Vertrag verlangt "(via Quelle)" am Ende UND deutschen Text. Der
            # Brownout lieferte drei Sorten Muell, die der via-Check oben NICHT
            # faengt: Token-Salat ohne via ("Anth helpers uidPolicy Cain..."),
            # englische Teaser mit korrektem via (CNBC-Fall) und Sprachmix.
            # Regel: kein "(via " = Formatbruch; kein einziges deutsches
            # Funktionswort im ganzen Teaser = keine deutsche Antwort. Ein
            # echter deutscher Teaser (>=100 Zeichen) ohne der/die/das/und/...
            # existiert praktisch nicht.
            if _teaser:
                _fmt_ok = "(via " in _teaser
                # Wortliste erweitert (03.07. 21:18): "Zuckerberg enttaeuscht
                # VON KI-Entwicklung, interne Kritik BEI Meta" wurde als
                # nicht-deutsch verworfen - von/bei/als/... fehlten. Nur
                # Woerter ohne englische Doppelbedeutung ("am" fehlt bewusst:
                # engl. "I am").
                _de_ok = bool(re.search(
                    r"\b(der|die|das|den|dem|des|ein|eine|und|für|fuer|mit|auf|ist|sind|wird|werden|nicht|mehr|jetzt|sich"
                    r"|von|bei|als|aus|zum|zur|im|um|dass|kein|keine|noch|nur|auch|schon|gegen|ohne|wenn|wie)\b",
                    _teaser.lower()))
                # Reparatur statt Verwurf (14.08.26, Fund: 05:14-Lauf verwarf
                # alle 5 Posts von meta-llama/llama-3.3-70b-instruct - Text
                # war inhaltlich einwandfrei deutsch, das Modell hatte nur den
                # "(via Quelle)"-Formatvertrag ignoriert). Ist der Teaser
                # nachweislich deutsch (_de_ok) und NUR das via-Suffix fehlt,
                # selbst anhaengen statt den ganzen Post wegzuwerfen. Ist der
                # Teaser gar nicht deutsch (wie am selben 14.08.-Lauf bei den
                # 2 Faellen mit englischem Original-Titel), bleibt Verwerfen
                # richtig - das laesst sich nicht reparieren, nur neu
                # generieren (naechster Lauf).
                if not _fmt_ok and _de_ok and _src:
                    _teaser = f"{_teaser.rstrip()} (via {_src})"
                    p["teaser"] = _teaser
                    logger.info(
                        "Post repariert (Qualitaets-Gate): fehlendes '(via Quelle)' ergaenzt -> %r (%s)",
                        _teaser[:60], link,
                    )
                    _fmt_ok = True
                if not _fmt_ok or not _de_ok:
                    logger.warning(
                        "Post verworfen (Qualitaets-Gate): via_ok=%s deutsch_ok=%s teaser=%r (%s)",
                        _fmt_ok, _de_ok, _teaser[:60], link,
                    )
                    continue
            if link:
                post_cache[link] = {
                    "teaser":      p.get("teaser", ""),
                    "erklaerung":  p.get("erklaerung", ""),
                    "thread":      p.get("thread", []),
                    "generated_at": heute_str,
                }
        save_post_cache(_cfg_base, post_cache)
    else:
        logger.info("Alle %d Top-Stories aus Post-Cache (keine LLM-Kosten)", len(top_news))

    # Posts in Reihenfolge der Top-News zusammenbauen
    parsed = [
        {
            "teaser":     post_cache.get(n.get("link",""), {}).get("teaser", ""),
            "erklaerung": post_cache.get(n.get("link",""), {}).get("erklaerung", ""),
            "thread":     post_cache.get(n.get("link",""), {}).get("thread", []),
        }
        for n in top_news
    ]
    logger.info("%d Posts bereit", len(parsed))

    # ── Telegram-Delta: nur NEUE Top-Storys senden, 1 Nachricht pro Story ──
    tg_state_file = Path("telegram_state.json")
    tg_sent = {}
    try:
        tg_sent = json.loads(tg_state_file.read_text(encoding="utf-8")).get("sent_links", {})
    except Exception:
        pass
    # p.get("teaser")-Filter (03.07.26): Stories ohne (oder mit verworfenem,
    # siehe Zuordnungs-Guard oben) Post NICHT als Headline-Stummel senden -
    # sonst steht der Link in tg_sent und die Story bekommt NIE eine richtige
    # Nachricht. Zurueckhalten -> naechster Lauf generiert den Post neu und
    # sendet dann komplett.
    neue_stories = [
        ({**n, "title": _title_de_by_link.get(n.get("link"), n["title"])}, p)
        for n, p in zip(top_news, parsed)
        if n.get("link") and n["link"] not in tg_sent and p.get("teaser")
    ]
    if not neue_stories:
        logger.info("Telegram: keine neuen Top-Storys – Versand uebersprungen.")
    elif send_telegram_stories(neue_stories, score_map, detailliert=(len(neue_stories) <= 3)):
        jetzt = datetime.now(BERLIN).isoformat()
        for n, _ in neue_stories:
            tg_sent[n["link"]] = jetzt
        if len(tg_sent) > 60:  # State begrenzen: nur die 60 juengsten Links
            tg_sent = dict(sorted(tg_sent.items(), key=lambda kv: kv[1])[-60:])
        try:
            tg_state_file.write_text(
                json.dumps({"sent_links": tg_sent, "stand": jetzt}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("telegram_state.json nicht schreibbar: %s", e)

    # ── news.json schreiben (fuer Dashboard + Archiv) ──────────────────────
    def write_json_file(path_obj, data):
        try:
            path_obj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("JSON geschrieben: %s", path_obj)
        except Exception as e:
            logger.exception("Fehler beim Schreiben %s: %s", path_obj, e)

    datum = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

    # News-Liste mit deutschen Titeln + Zusammenfassungen aufbauen
    # NEU: score + label aus score_map ergänzen, dann Zeit-Verfall anwenden
    news_list = []
    for i, n in enumerate(alle_news):
        s = summaries.get(i, {})
        link = n.get("link", "")
        # Sprach-Guard (14.08.26): title_de ist bei fehlgeschlagener Uebersetzung
        # schlicht der unveraenderte englische Original-Titel (Platzhalter aus
        # summarize_news(), nie ueberschrieben - siehe Kommentar bei
        # GERMAN_MARKERS oben). Bisher ging das ungeprueft in news.json und damit
        # in Hero + Grid-Karten der Website. Artikel NICHT in diesem Lauf
        # anzeigen (kein card_sent/archive-Eintrag hier, s. update_archive()
        # weiter unten) - taucht automatisch wieder auf, sobald ein spaeterer
        # Lauf die Uebersetzung schafft. Analog zu generate_news_cards.py's
        # SKIP-Logik, damit Website und Cards konsistent filtern.
        _title_de_check = s.get("title_de", n.get("title", ""))
        # 26.08.26: Originaltitel wird mitgegeben, aber von _looks_german()
        # bewusst nicht mehr ausgewertet - Begruendung im Docstring dort
        # (deutsche Quellen liefern title_de == Original als Normalfall).
        if _title_de_check and not _looks_german(_title_de_check, n.get("title", "")):
            globals()["_GUARD_VERWORFEN"] = globals()["_GUARD_VERWORFEN"] + 1
            logger.warning(
                "news.json: Artikel uebersprungen, Titel wirkt unuebersetzt/nicht Deutsch "
                "(%r) - ki_news.py-Uebersetzung fehlgeschlagen, naechster Lauf versucht es erneut. (%s)",
                _title_de_check[:60], link,
            )
            continue
        cluster_info = link_to_cluster_info.get(link, {})
        scoring = score_map.get(link, {})
        # Befund 1: score_map enthaelt nur den Cluster-Repraesentanten. Ein Nicht-rep-
        # Member stand bisher mit raw_score 0 da -> die Story zerfiel im Ranking und der
        # Member rutschte ans Ende, obwohl er zur selben (oft wichtigen) Story gehoert.
        # Fix (Variante B): Member erbt den Story-Cluster-Score minus Abschlag, damit der
        # rep oben bleibt, die Story aber als Block zusammensteht. Der 7-Tage-Verfall
        # raeumt das Thema danach ohnehin auf 0.
        if "score" in scoring:
            # eff_score (inkl. Featured-Boost) bevorzugen, falls vorhanden - sonst
            # faellt ein gepinnter Artikel im persistierten Score auf den
            # ungeboosteten Wert zurueck (siehe Kommentar oben in pick_top_news).
            raw_score = scoring.get("eff_score", scoring["score"])  # Cluster-Repraesentant
        else:
            cscore = cluster_info.get("story_cluster_score", 0)
            raw_score = max(0, cscore - CLUSTER_MEMBER_MALUS) if cscore else 0
        # Schon mal gesehen? Dann ursprüngliches Datum behalten.
        # Neuer Artikel einer bekannten Story? Cluster-Alter erben → kein Score-Revival.
        hist = history.get(link)
        if hist:
            first_seen = hist["first_seen"]
        elif n.get("source") in ALWAYS_KI_RELEVANT_SOURCES:
            # Bug-Fix (01.07.26): siehe Kommentar bei _display_score() in pick_top_news -
            # dieselbe Logik hier fuer den finalen news.json-Score noetig, sonst wuerde
            # der Repraesentant zwar korrekt gewaehlt, aber der Decay trotzdem auf dem
            # alten Cluster-Alter rechnen.
            first_seen = heute
        else:
            first_seen = link_to_cluster_age.get(link, heute)
        # History-Heilung: frueher faelschlich als 0 archivierte Member duerfen ausheilen,
        # wenn ihr Cluster jetzt einen echten Score hat. Ohne max() bliebe base_score
        # wegen hist dauerhaft 0 (Selbstvergiftung ueber archive.json).
        # Bug-Fix (13.07.26): nur noch heilen wenn alter Wert <= HEAL_THRESHOLD war -
        # sonst frisst ein einmaliger Score-Ausreisser sich fuer die gesamte
        # Lebensdauer der Story fest (s. Kommentar bei HEAL_THRESHOLD oben).
        base_score = max(hist["base_score"], raw_score) if hist and hist["base_score"] <= HEAL_THRESHOLD else raw_score
        # Vorschaubild (og:image) – aus Cache oder einmalig serverseitig holen
        preview_img = resolve_preview_image(link, hist)
        title_de = s.get("title_de", n["title"])
        summary_de = s.get("summary", "")
        entry = {
            "title":      title_de,
            "summary":    summary_de,
            "link":       link,
            "source":     n.get("source", ""),
            "color":      SOURCE_COLORS.get(n.get("source", ""), "#555"),
            "image":      preview_img,                     # Vorschaubild für die Karte
            # Karten-/Flaggen-Hintergrund (02.07.26): bewusst der DEUTSCHE Text
            # (title_de/summary_de) — der Score nutzt den Originaltext, die
            # Keywords sind aber deutsch, daher trifft die Deko hier besser.
            # Score-Region und Deko-Region KOENNEN dadurch abweichen (ok, Deko
            # ist rein visuell und aendert kein Ranking).
            "region":     classify_region(title_de + " " + summary_de),
            "base_score": base_score,                      # Ausgangs-Score (verfällt nie)
            "score":      decay_score(base_score, first_seen),  # aktueller, verfallener Score
            "label":      cluster_info.get("story_label", scoring.get("label", "📰 normal")),  # NEU: aus Cluster, nicht Einzel-Artikel
            "first_seen": first_seen,                      # Erst-Erfassung (Basis für Verfall)
            "date":       first_seen,                      # date = Erst-Erfassung (für Sortierung/Anzeige)
            # NEU: Story-Cluster-Felder – alle Artikel einer Story teilen dieselbe story_id
            "story_id":            cluster_info.get("story_id", ""),
            "story_cluster_score": cluster_info.get("story_cluster_score", 0),
            "story_article_count": cluster_info.get("story_article_count", 1),
        }
        news_list.append(entry)

    # Volltext-Capture Top-5 fuer Chat-Bot-Kontext (Fund 08.07.26, siehe
    # fetch_full_text()-Kommentar oben). Lauf-Zeit-Kosten: max. 5 sequenzielle
    # HTTP-Fetches mit kurzem Timeout - im Rahmen des bestehenden Job-Budgets.
    # Diagnose-Logging (Fund 09.07.26): Lauf 2026-07-09T08:31:49Z zeigte nur 1 von
    # 5 Top-Storys mit full_text in news.json, OHNE jede "Volltext-Fetch
    # fehlgeschlagen"/"HTTP Fehler"-Zeile im Log - die bisherigen except-Faelle
    # decken das nicht ab. INFO-Zeile pro Versuch (vor+nach), um beim naechsten
    # Lauf zu sehen ob die Schleife ueberhaupt 5x durchlaeuft.
    _top5_for_fulltext = sorted(news_list, key=lambda n: -(n.get("score") or 0))[:5]
    logger.info("Volltext-Capture: %d Kandidaten (Top-5 nach Score)", len(_top5_for_fulltext))
    for _i, _entry in enumerate(_top5_for_fulltext):
        _link = _entry.get("link", "")
        logger.info("Volltext-Capture [%d/%d] Start: %s", _i + 1, len(_top5_for_fulltext), _link)
        try:
            _entry["full_text"], _entry["paywalled"] = fetch_full_text(_link)
            logger.info(
                "Volltext-Capture [%d/%d] OK: %d Zeichen, paywalled=%s, %s",
                _i + 1, len(_top5_for_fulltext),
                len(_entry["full_text"]), _entry["paywalled"], _link,
            )
        except Exception as e:
            logger.warning("Volltext-Fetch fehlgeschlagen fuer %s: %s", _link, e)
            _entry["full_text"], _entry["paywalled"] = "", True

    # Artikel älter als MAX_AGE_DAYS aus news.json entfernen
    news_list = [
        n for n in news_list
        if _days_since(n.get("first_seen")) <= MAX_AGE_DAYS
    ]

    # Bug-Fix (26.06.26): news_list hatte bis hier KEINE definierte Reihenfolge –
    # sie folgte 1:1 alle_news, also der Reihenfolge, in der fetch_feed() die
    # Quellen abgearbeitet hat. Auf der Archiv-Seite (Archiv.html) wird diese
    # Reihenfolge 1:1 als Anzeige-Reihenfolge übernommen (kein Sort im Frontend),
    # dadurch standen dort scheinbar zufällige/alte Artikel "ganz oben" – es war
    # schlicht die Quellen-Verarbeitungsreihenfolge, nie Score oder Datum.
    # Fix: explizit nach first_seen sortieren, neueste zuerst.
    news_list.sort(key=lambda n: n.get("first_seen", ""), reverse=True)

    # Analyse-Fix (04.07.26): Posts nicht mehr NUR fuer die aktuellen top_news
    # exportieren. Seit dem already_sent-Fix (26.06.) verdraengt der Sent-Filter
    # bereits getelegramte Top-Storys aus top_news - deren Posts fehlten dann in
    # news.json, der Hero (Top-5 nach SCORE) fand keinen Link-Match mehr und die
    # "Analyse anzeigen"-Sektion verschwand ausgerechnet bei den grossen Storys.
    # Jetzt: Kandidaten = Top-15 nach Score + top_news + featured; Posts kommen
    # aus dem post_cache (reiner Cache-Lookup, keine LLM-Kosten). Jeder Post
    # traegt weiterhin Link + story_id, Frontend matcht exakt per Link.
    _post_link_cands = [n.get("link", "") for n in
                        sorted(news_list, key=lambda x: -(x.get("score") or 0))[:15]]
    _post_link_cands += [tn.get("link", "") for tn in top_news]
    _post_link_cands += list(featured_links or [])
    posts_list = []
    _pl_seen = set()
    for _lnk in _post_link_cands:
        if not _lnk or _lnk in _pl_seen:
            continue
        _pl_seen.add(_lnk)
        _pc = post_cache.get(_lnk, {})
        if not _pc.get("teaser"):
            continue
        posts_list.append({
            "teaser":     _pc.get("teaser", ""),
            "erklaerung": _pc.get("erklaerung", ""),
            "thread":     _pc.get("thread", []),
            "link":       _lnk,
            "story_id":   link_to_cluster_info.get(_lnk, {}).get("story_id", ""),
        })

    # Roundups als separates Feld – Material zum Abgleich, nicht in der News-Liste.
    # Frontend und Breaking-Karte lesen nur "news" und ignorieren dieses Feld.
    roundups_list = []
    for n in roundup_items:
        link = n.get("link", "")
        h = history.get(link)
        fs = h["first_seen"] if h else heute
        roundups_list.append({
            "title":      n.get("title", ""),
            "link":       link,
            "source":     n.get("source", ""),
            "date":       fs,
            "first_seen": fs,
        })

    news_json_data = {
        "stand":    datum,
        "news":     news_list,
        "posts":    posts_list,
        "roundups": roundups_list,
    }

    if proj_dir.exists():
        write_json_file(proj_dir / "news.json", news_json_data)
    else:
        write_json_file(Path("news.json"), news_json_data)

    # ── SSR / Pre-Rendering: aktuelle News als echtes HTML in index.html ──
    # (für Crawler & KI-Bots, die kein JavaScript ausführen)
    try:
        inject_ssr(proj_dir if proj_dir.exists() else Path("."), news_json_data)
    except Exception as e:
        logger.exception("SSR-Injektion fehlgeschlagen: %s", e)
    try:
        inject_admin_posts(proj_dir if proj_dir.exists() else Path("."), news_json_data)
    except Exception as e:
        logger.exception("Admin-Posts SSR fehlgeschlagen: %s", e)

    # ── archive.json kumulativ schreiben ──────────────────────────────────
    def update_archive(base_dir):
        archive_path = base_dir / "archive.json"
        try:
            if archive_path.exists():
                existing = json.loads(archive_path.read_text(encoding="utf-8"))
            else:
                existing = []
        except Exception:
            existing = []

        _cap_inflated_base_scores(existing)  # Einmal-Migration 04.07.26, s. Funktion

        # Scoring-Fix (02.07.26): base_score-Heilung erreicht jetzt auch das
        # ARCHIV. Vorher heilte nur news.json (max(hist, raw) dort), aber
        # bestehende Archiv-Eintraege behielten ihren alten base_score fuer
        # immer - eine am Tag 0 schlecht bewertete Story (z.B. Fable-5-Relaunch
        # am 28.06.: base 5, weil Cluster fragmentiert + Primaerquelle gefiltert)
        # blieb im Archiv/in der Statistik dauerhaft vergiftet, und
        # build_history_map() las den giftigen Wert bei jedem Lauf neu ein.
        healed_by_link = {n["link"]: n for n in news_list if n.get("link")}
        for entry in existing:
            h = healed_by_link.get(entry.get("link"))
            if not h:
                continue
            try:
                if float(h.get("base_score", 0)) > float(entry.get("base_score", 0)):
                    entry["base_score"] = h["base_score"]
                    if h.get("label"):
                        entry["label"] = h["label"]
            except (TypeError, ValueError):
                pass

        seen_links = {n["link"] for n in existing if n.get("link")}
        new_entries = [n for n in news_list if n.get("link") and n["link"] not in seen_links]
        # Neuestes vorne
        merged = new_entries + existing
        # Bug-Fix (26.06.26): Cap war bisher eine feste Anzahl (2000 Eintraege),
        # KEIN Zeit-Cutoff. Bei steigender Publishing-Rate waechst die Datei in
        # MB/Tag, und "10 Tage" war nie wirklich das Kriterium. Daniels Wunsch:
        # explizit 10 Tage. Fix: nach first_seen filtern statt nach Anzahl
        # abzuschneiden. ARCHIVE_MAX_AGE_DAYS bewusst getrennt von MAX_AGE_DAYS
        # (gilt fuer news.json/Startseite, 5 Tage) - das Archiv soll laenger
        # vorhalten als die Startseite, aber nicht unbegrenzt wachsen.
        ARCHIVE_MAX_AGE_DAYS = 10
        merged = [
            n for n in merged
            if _days_since(n.get("first_seen")) <= ARCHIVE_MAX_AGE_DAYS
        ]
        # Sicherheits-Cap bleibt zusaetzlich bestehen (falls an einem Tag
        # ungewoehnlich viele Artikel durchlaufen) - 2000 ist jetzt ein reines
        # Notfall-Limit, kein normales Verhalten mehr.
        merged = merged[:2000]
        # NEU: Score-Verfall auf das GANZE Archiv neu anwenden, damit auch alte
        # Einträge in der Statistik-Seite über die Zeit absinken (idempotent aus
        # base_score + first_seen). Migriert alte Einträge ohne diese Felder.
        apply_decay_to_entries(merged)
        try:
            archive_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("archive.json aktualisiert: %d Eintraege gesamt (Score-Verfall angewandt)", len(merged))
        except Exception as e:
            logger.exception("Fehler beim Schreiben archive.json: %s", e)

    if proj_dir.exists():
        update_archive(proj_dir)
    else:
        update_archive(Path("."))

    # ── Story-Registry SHADOW-MODE (20.07.26): loggt "haette angedockt" +
    #    fuehrt Story-Merges (Pass 1-3). Veraendert NICHTS am Kern-Pipeline-
    #    Output (Scoring/Karten/Telegram unberuehrt) - Kill-Switch = diesen
    #    Block entfernen. Details/Vertrag: story_registry_shadow.py.
    #    11.08.2026: laeuft jetzt VOR dem Entity-Graph-Schritt (statt danach),
    #    damit dessen Story-Zuordnung fuer den heutigen Lauf schon steht, wenn
    #    update_entity_graph() sie unten liest (link_to_story_map).
    try:
        from story_registry_shadow import update_story_registry_shadow, JUDGE_MODELLE
        update_story_registry_shadow(proj_dir if proj_dir.exists() else Path("."),
                                     news_list, cluster_news, _call_llm_api, JUDGE_MODELLE)
    except Exception as e:
        logger.exception("Shadow-Registry uebersprungen (Pipeline unbeeinflusst): %s", e)

    # ── Entity-Graph kumulativ fortschreiben (Phase 2, 16.07.26) ──────────
    # 11.08.2026: erste tatsaechliche LIVE-Nutzung der Shadow-Registry (bisher
    # reiner Logger). link_to_story_map() ist read-only, fail-safe (leeres
    # dict bei jedem Fehler -> update_entity_graph faellt automatisch auf sein
    # bisheriges Link-only-Verhalten zurueck, siehe Docstring dort). Kill-
    # Switch fuer NUR diesen Schritt: link_to_story wieder auf None setzen.
    try:
        from story_registry_shadow import link_to_story_map
        _link_to_story = link_to_story_map(proj_dir if proj_dir.exists() else Path("."))
    except Exception as e:
        logger.info("link_to_story_map nicht verfuegbar (%s) - Entity-Graph zaehlt wie bisher pro Link", e)
        _link_to_story = None
    update_entity_graph(proj_dir if proj_dir.exists() else Path("."), news_list, link_to_story=_link_to_story)

    # ── X-Beiträge: fehlende Vorschaubilder serverseitig ergänzen ──────────
    update_media_xpost_images(proj_dir if proj_dir.exists() else Path("."))

    # ── hashtags/hashtags.json aktualisieren ──────────────────────────────
    def update_hashtags(base_dir):
        """Extrahiert Hashtags aus Quellen + News-Titeln und mergt in hashtags.json."""
        hashtag_dir = base_dir / "hashtags"
        hashtag_path = hashtag_dir / "hashtags.json"
        try:
            hashtag_dir.mkdir(exist_ok=True)
            if hashtag_path.exists():
                existing_data = json.loads(hashtag_path.read_text(encoding="utf-8"))
                existing_tags = set(existing_data.get("tags", []))
            else:
                existing_tags = set()
        except Exception:
            existing_tags = set()

        # Basis-Tags aus Quellen
        source_tags = {
            "The Decoder": "#TheDecoder",
            "TechCrunch AI": "#TechCrunch",
            "Ars Technica": "#ArsTechnica",
            "MIT Tech Review": "#MITTechReview",
            "Heise": "#Heise",
        }
        # Keyword-Tags aus Nachrichtentiteln generieren
        keyword_map = {
            "openai": "#OpenAI", "chatgpt": "#ChatGPT", "gpt": "#GPT",
            "claude": "#Claude", "anthropic": "#Anthropic",
            "gemini": "#Gemini", "google": "#Google",
            "meta ai": "#MetaAI", "llama": "#Llama",
            "mistral": "#Mistral", "deepseek": "#DeepSeek",
            "nvidia": "#Nvidia", "gemma": "#Gemma",
            "agent": "#AIAgent", "llm": "#LLM",
            "roboter": "#Robotik", "automation": "#Automation",
            "sicherheit": "#AISafety", "datenschutz": "#Datenschutz",
        }
        new_tags = set()
        for n in alle_news:
            title_lower = n["title"].lower()
            # Quellen-Tag
            src_tag = source_tags.get(n.get("source", ""))
            if src_tag:
                new_tags.add(src_tag)
            # Keyword-Tags aus Titel
            for kw, tag in keyword_map.items():
                if kw in title_lower:
                    new_tags.add(tag)

        # Immer vorhandene Basis-Tags
        base_tags = {"#KI", "#AI", "#AINews", "#KünstlicheIntelligenz", "#LLM"}
        merged = sorted(base_tags | existing_tags | new_tags)

        try:
            hashtag_path.write_text(
                json.dumps({"tags": merged}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info("hashtags.json aktualisiert: %d Tags", len(merged))
        except Exception as e:
            logger.exception("Fehler beim Schreiben hashtags.json: %s", e)

    if proj_dir.exists():
        update_hashtags(proj_dir)
    else:
        update_hashtags(Path("."))

    # ── HTML generieren ───────────────────────────────────────────────────────
    pfad = create_html(alle_news, parsed, summaries)

    # ── Modell-Registry fortschreiben (21.08.26) ──────────────────────────
    #    Fuettert das Registry-Panel in Archiv.html: Zuordnung Artikel ->
    #    Modell/Anbieter plus die vier Facetten je Artikel. Ohne diesen
    #    Schritt veralteten die Zuordnungen mit jedem Lauf um einen Tag und
    #    mussten von Hand nachgezogen werden.
    #
    #    Bewusst die letzte Handlung des Laufs: news.json steht seit 3307,
    #    Telegram lief bei 3102, hier kann nichts mehr kaputtgehen.
    #    Kill-Switch = diesen Block entfernen; die Website faellt dann auf den
    #    zuletzt gepushten Registry-Stand zurueck und bleibt bedienbar.
    #
    #    Auch SystemExit wird gefangen: die Bausteine unter registry_bau/ sind
    #    Kommandozeilenwerkzeuge und melden Fehler mit `raise SystemExit`, das
    #    ein blosses `except Exception` durchlaesst.
    try:
        from registry_bau.lauf import registry_schritt
        registry_schritt(proj_dir if proj_dir.exists() else Path("."), logger)
    except (Exception, SystemExit) as e:
        logger.exception("Registry-Schritt uebersprungen (Pipeline unbeeinflusst): %s", e)

    # ── Lauf-Bilanz (26.08.26, Begruendung bei _BATCH_VERSUCHE oben) ──────
    # Eine Zeile, aus der der taegliche Check ablesen kann, ob die
    # Modellliste noch traegt - ohne 500 Batch-Zeilen auszuzaehlen.
    try:
        _ok_gesamt = sum(_BATCH_OK.values())
        _traeger = ", ".join(
            "%s %dx" % (m, c) for m, c in sorted(_BATCH_OK.items(), key=lambda kv: -kv[1])
        ) or "keiner"
        logger.info(
            "BILANZ: Batches %d versucht / %d OK | Traeger: %s | Sprach-Guard verwarf %d Artikel | Sprach-ID: %s",
            _BATCH_VERSUCHE, _ok_gesamt, _traeger, _GUARD_VERWORFEN,
            "py3langid" if _LANGID is not None else "FALLBACK Wortlisten (py3langid fehlt)",
        )
        # Mindest-Stichprobe 8 (nachgebessert 26.08.26 abends): die erste
        # Fassung warnte schon bei "1 von 1" und "3 von 5". Bei so wenigen
        # Batches ist ein dominierendes Modell keine Aussage, sondern Zufall -
        # eine Warnung, die bei jedem ruhigen Lauf angeht, wird genauso
        # ueberlesen wie die stumme Actions-Ausgabe des Modell-Waechters.
        # Zusaetzlich von >50% auf >=70% angehoben: dass EIN Free-Slot die
        # Mehrheit traegt, ist bei acht Modellen mit Rate-Limit normal.
        if _ok_gesamt >= 8 and max(_BATCH_OK.values()) >= _ok_gesamt * 0.7:
            _top = max(_BATCH_OK.items(), key=lambda kv: kv[1])
            logger.warning(
                "BILANZ-WARNUNG: %s traegt %d von %d erfolgreichen Batches - die Modellliste "
                "ist halb tot. modell_check.py pruefen und Free-Slots nachbesetzen.",
                _top[0], _top[1], _ok_gesamt,
            )
    except Exception as e:      # Bilanz darf den Lauf nie kippen
        logger.warning("Bilanz-Zeile fehlgeschlagen: %s", e)

    logger.info("KI News Lauf abgeschlossen.")


# -------------------------
# Entry Point
# -------------------------
if __name__ == "__main__":
    main()
