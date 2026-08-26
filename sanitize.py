# -*- coding: utf-8 -*-
"""Zentraler Filter fuer kaputte LLM-Ausgaben -- Einbau-Fassung.

Herkunft: ox-Schleife, Lauf lauf_sanitize_240826_0435_en, Runde 12
          (61/61 Testfaelle, 29/29 Artefakte, 0 von 15.391 Texten verworfen).

Was gegenueber der Schleifen-Fassung von Hand geaendert wurde (26.08.2026),
jede Aenderung am Bestand gemessen, nicht geschaetzt:

  1. Truncation-Schwelle 300 -> 400 Zeichen.
     Der laengste echte Text ohne Satzendzeichen im Gesamtkorpus (16.578) ist
     265 Zeichen lang. Der Testfall K18 ist 501. Bei 300 lag die Grenze 35
     Zeichen ueber dem echten Maximum -- dieselbe Art knapper Grenze, die den
     <pad>-Fall vom 20.08. durchgelassen hat (9 Woerter, Grenze bei 8).
     400 liegt in der Mitte: 135 Zeichen Luft nach unten, 101 nach oben.

  2. Sprachmisch-Schwelle 3 -> 4 verschiedene englische Funktionswoerter.
     Echtes Maximum im Korpus: 2. Testfall K25: 7. Bei 3 war die Marge genau
     ein Wort. Bei 4 sind es zwei nach unten und drei nach oben.

  3. LaTeX-Muster [a-z]"[uoa][a-z] ergaenzt (aus den Parallelloesungen
     lauf_sanitize_230826_2145_de / _240826_1412_en uebernommen).
     Runde 12 faengt {"u}, aber nicht die Form ungesch"uzt. Beide Formen
     stehen live auf ki-news.live im Artikel ueber Anthropics Bio-Waffen-
     Filter -- der Fall ist echt, nicht konstruiert.

Kill-Switch: Verwirft der Filter im Betrieb mehr als etwa 1 % der Ausgaben,
ist etwas falsch -- gemessene Rate auf 16.578 echten Texten ist 0,012 %
(2 Texte, beide echte LaTeX-Artefakte). Dann NICHT die Schwellen nachziehen,
sondern die verworfenen Texte ansehen: die Grenzen liegen bewusst weit weg
vom echten Bestand, ein Anstieg bedeutet neue Daten, keine zu scharfe Regel.
"""
import json
import re
import unicodedata

_PAD_TOKENS = [
    "<pad>", "<|endoftext|>", "</s>", "<|im_end|>", "<|end|>",
    "<|user|>", "<|assistant|>", "[pad]",
]

_REFUSAL_STARTS = (
    "as an ai language model",
    "i'm sorry",
    "i am sorry",
    "es tut mir leid",
)

_META_PREFIXES = (
    "hier ist die deutsche übersetzung",
    "hier ist die deutsche uebersetzung",
    "übersetzung:",
    "uebersetzung:",
    "assistant:",
    "titel:",
    "[titel]",
    "de:",
)

# englische Funktionswoerter fuer die Sprachmisch-Pruefung (K25)
_EN_FUNC = re.compile(
    r"\b(and|the|to|of|with|from|that|this|company|plans|appeal|decision)\b"
)
# deutsche Indikatoren: Umlaute/ss oder haeufige deutsche Woerter
_DE_INDICATOR = re.compile(
    r"[äöüßÄÖÜ]|\b(die|der|das|und|ist|eine|einen|einer|gegen|von|mit|für|ueber|über)\b"
)

# --- Schwellen an einer Stelle, damit sie nachpruefbar bleiben -------------
# Alle Margen am Gesamtbestand von 16.578 echten Texten gemessen (26.08.2026).
# Die knappste Regel ist Nummer 9 (Listenmarker, Marge 1) -- wenn hier je etwas
# faelschlich verworfen wird, ist es mit hoher Wahrscheinlichkeit die.
_MAX_LEN_OHNE_SATZENDE = 400   # echtes Maximum: 265  -> Marge 135
_MIN_EN_WOERTER = 4            # echtes Maximum:   2  -> Marge   2
_MIN_EMOJI = 4                 # echtes Maximum:   0  -> Marge   4
_MIN_WORTWIEDERHOLUNG = 4      # 5 gleiche Woerter am Stueck; echtes Max: 2


def ist_brauchbar(text, original=None):
    """True, wenn der Text als Titel/Kurzfassung auf der Website erscheinen darf."""
    if not isinstance(text, str):
        return False
    t = text.strip()
    if not t:
        return False

    low = t.lower()

    # 1) Padding / Spezialtokens
    for tok in _PAD_TOKENS:
        if tok in low:
            return False
    if re.search(r"\[\s*pad\s*\]", low):
        return False

    # 2) Replacement Characters
    if "\ufffd" in t:
        return False

    # 3) LaTeX-Umlaut-Escapes
    if re.search(r'\{"[aAeEoOuU]\}', t):
        return False
    if re.search(r"\{\\ss\}", t):
        return False
    if re.search(r'\\["`\'^~]\s*[aAeEiIoOuU]', t):
        return False
    if re.search(r'\\"[aAeEiIoOuU]', t):
        return False
    # ergaenzt: Form ohne Klammern, z.B. ungesch"uzt / au"ser
    if re.search(r'[a-zA-Z]"[uoaUOA][a-z]', t):
        return False

    # 4) Refusals
    for r in _REFUSAL_STARTS:
        if low.startswith(r):
            return False

    # 5) Meta-Chatter
    for p in _META_PREFIXES:
        if low.startswith(p):
            return False
    if re.search(r"\n+hinweis:", low):
        return False
    if re.search(r"\n+(?:anmerkung|note|bemerkung)\s*:", low):
        return False
    if t.startswith("```") or t.endswith("```"):
        return False
    if t.startswith("{") and t.endswith("}"):
        try:
            json_obj = json.loads(t)
            if isinstance(json_obj, dict):
                return False
        except Exception:
            pass
    if "{{" in t and "}}" in t:
        return False
    if re.search(r"\|\s*(?:sprache|lang|länge|laenge)\s*:", low):
        return False

    # 6) HTML-Tags / Entities
    if re.search(r"<(?:p|br|div|span)\b[^>]*/?>", low):
        return False
    if re.search(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]{2,8});", t):
        return False

    # 6b) Sprachmischung (K25)
    if _DE_INDICATOR.search(t):
        en_hits = set(m.group(1).lower() for m in _EN_FUNC.finditer(t))
        if len(en_hits) >= _MIN_EN_WOERTER:
            return False

    # 7) Wortwiederholungs-Spam (K19)
    if re.search(r"\b(\w+)\b(?:[\s,.]*\b\1\b){%d,}" % _MIN_WORTWIEDERHOLUNG,
                 t, re.IGNORECASE):
        return False

    # 8) Emoji-Spam (K26)
    emoji_count = sum(
        1 for ch in t
        if unicodedata.category(ch) == "So" and ord(ch) > 0x2000
    )
    if emoji_count >= _MIN_EMOJI:
        return False

    # 9) Nummerierte Liste (K24)
    if len(re.findall(r"(?:^|\s{2,})\d{1,2}\.\s+\S", t)) >= 2:
        return False

    # 10) Abbruch mitten im Text
    if len(t) > _MAX_LEN_OHNE_SATZENDE and \
       not re.search(r"[.!?…](?:\s|$)|[.:!?]$|[»”\"]$", t):
        return False

    return True


# Name, unter dem der Filter in ki_news.py und add_reactions.py eingebunden wird
_sanitize_llm_output = ist_brauchbar
