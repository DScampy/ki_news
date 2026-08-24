# False-Merge-Audit-Scan (Entity-Heuristik)

Entstanden 12.–13.08.2026 als Nebenfund der 2.-Prüf-Agent-Offline-Simulation
(siehe `project_ki-news-shadow-registry-a9-fix.md`). Findet Storys im
`story_registry_shadow.json`, die vermutlich mehrere unterschiedliche
Ereignisse fälschlich in einer Story zusammengeführt haben.

**Ablauf:** lädt `entities.json` (29 kuratierte Firmen) + `story_registry_shadow.json`,
prüft pro Story mit ≥2 Titeln, ob es Titel-Paare mit disjunkten, aber beide
nicht-leeren Firmen-Entitäten-Sets gibt (Titel A nennt nur Firma X, Titel B
nennt nur Firma Y, keine Überschneidung → verdächtig).

**Ergebnis 13.08.2026:** Vollscan aller 593 aktiven Storys → 8 Kandidaten,
davon 7 nach Volltext-Artikel-Prüfung (WebFetch/WebSearch) als echte
False-Merges bestätigt (~1,2 % aller Storys, ~7,9 % der Storys mit ≥2 Titeln).
Betroffene IDs: st-02201, st-02204, st-02294, st-02304, st-02613, st-02642,
st-02663, st-02481 (letzterer nur durch manuelle Stichprobe, nicht durch
diesen Scan gefunden — siehe Einschränkung unten).

## Bekannte Einschränkungen — vor jeder Nutzung lesen

- **Bug 1 (in diesem Skript behoben):** Der Alias `\bmeta\b` in `entities.json`
  matcht NICHT "Metas neues Modell" — deutsches Genitiv-s bricht die
  Wortgrenze `\b`. Dieses Skript ergänzt automatisch eine `s?`-Variante für
  jeden Alias, der auf `\b` endet.
- **Bug 2 (nur lokaler Workaround, NICHT in `entities.json` geändert):**
  Firmen wie "Intel" und "Kimi/Moonshot" fehlen in den 29 kuratierten
  Entitäten. Das Skript ergänzt sie testweise nur für den Scan
  (`DEFAULT_EXTRA_ENTITIES`). Bei neuen Fehlermustern ggf. weitere Firmen
  dort ergänzen — nicht automatisch in die produktive `entities.json`
  schreiben (die Datei wird laut eigenem Header "manuell per
  GitHub-Web-Upload" gepflegt).
- **Strukturelle blinde Stelle (nicht durch mehr Entitäten behebbar):**
  Merges von zwei verschiedenen Produkten derselben Firma (z. B. 3
  verschiedene Kimi-Modelle in einer Story) sind für diese firmen-basierte
  Heuristik unsichtbar, weil beide Titel dieselbe Firmen-Entität matchen.
  Das war Fall st-02481 — nur durch manuelle Stichprobe gefunden. Die reale
  Fehlerquote liegt also vermutlich über den gemessenen ~1,2 %.
- **False Positives möglich:** Ein Ereignis kann legitim aus zwei
  Firmen-Perspektiven beschrieben werden (z. B. Täter + Opfer eines Hacks)
  und trotzdem dieselbe Story sein. Jeder Treffer MUSS vor einer
  Registry-Korrektur per Volltext-Artikel verifiziert werden, nicht blind
  übernommen werden. Bekanntes Beispiel: st-02576 (OpenAI/Hugging-Face-Hack)
  wurde geflaggt, war aber bei Prüfung ein korrekter Merge.
- **Log-Retention-Lücke:** `ki_news.log` deckt nur ~2 Tage ab. Root-Cause
  (welcher Pass — 1/2/3 — hat den Merge erzeugt?) lässt sich für Funde, die
  erst Tage später auffallen, nicht mehr rekonstruieren. Offener Punkt,
  siehe `project_ki-news-shadow-registry-a9-fix.md`.

## Code

Liegt daneben als `false_merge_scan.py`.

## Verwendung als wöchentlicher Scheduled Task

Läuft als eigener Cowork-Scheduled-Task (siehe `create_trigger`, wöchentlich,
Prompt referenziert diese Datei). Der Task lädt `entities.json` +
`story_registry_shadow.json` aus dem lokalen `Projekte/ki-news`-Ordner (oder
frisch von GitHub, falls lokal stale — siehe
`feedback_ki-news-lokaler-ordner-live-aktuell.md`), führt den Scan aus,
verifiziert die Top-Kandidaten per WebFetch/WebSearch und meldet das Ergebnis
an Daniel (Push/E-Mail + Log-Zeile in `project-status-log.md`). Er korrigiert
NICHTS automatisch in der Registry — jede Korrektur läuft über die normale
"Plan zeigen → warten → dann handeln"-Regel.

---

## Nachtrag 24.08.2026 — warum diese Dateien jetzt im Repo liegen

Der wöchentliche Cloud-Task kam am 24.08. nicht an die KIVault-Dateien (kein Desktop
verbunden) und hat die Heuristik **aus der Aufgabenbeschreibung nachgebaut**. Deshalb
liegen Skript und Doku ab jetzt hier im Repo — über `git clone` immer erreichbar.

### Was der Nachbau anders machte

Gemessen am selben Bestand (506 Storys, Stand 24.08. 10:12):

| | Original | Nachbau des Cloud-Tasks |
|---|---|---|
| Kandidaten | 6 | 11 |
| davon echte False Merges | 6 | 9 |
| Falsch-Positive | **0** | 2 |

Beide Verfahren finden dieselben sechs Kernfälle. Der Nachbau findet drei weitere
echte (`st-03211`, `st-03421`, `st-03555`), fängt sich dafür zwei Falsch-Positive ein.
**Das ist kein schlechterer Nachbau, sondern ein anderer Arbeitspunkt** — mehr Recall,
weniger Präzision. Für ein Audit, dessen Treffer ohnehin einzeln per Volltext geprüft
werden, ist das vertretbar.

Die drei Zusatzfunde zeigen die in den Einschränkungen genannte strukturelle Lücke:
bei `st-03421` überschneiden sich die Firmen-Sets (Google und Marvell kommen in zwei
Titeln vor), das disjunkt-Kriterium greift also nicht — obwohl ein separater
Fractile/Anthropic-Deal hineingemischt wurde.

### Die Metrik, die nicht verloren gehen darf

Der Cloud-Task meldete **9/493 = 1,8 %** gegen eine Baseline von 1,2 %. Dieser Nenner
ist irreführend: von 506 Storys haben nur **67** überhaupt mehr als einen Artikel, die
restlichen 439 können per Definition kein False Merge sein.

```
gegen alle Storys:        9 / 506  =  1,8 %
gegen gemergte Storys:    9 /  67  = 13,4 %   <- die aussagekräftige Zahl
```

Das Skript gibt `stories_with_multi_titles` genau dafür aus. Die Baseline vom 13.08.
lautet entsprechend **7,9 %**, nicht 1,2 % — beide Zahlen stehen oben in dieser Datei.

**Und: 7 gegen 9 Fälle ist kein Trend.** z = 0,88, weit unter der Auffälligkeitsschwelle.
Solange die Fallzahlen einstellig sind und die Methode wechselt, ist jeder
Wochenvergleich Rauschen. Die absolute Quote melden, keinen Trend behaupten.

### Was ein False Merge tatsächlich anrichtet

Die Registry läuft weiter im **Schattenbetrieb**. Ihre einzige Live-Wirkung ist
`link_to_story_map()` für den Entity-Graphen. Dort entstehen dadurch **keine falschen
Kanten** — Entitäten aus verschiedenen Artikeln werden nie verbunden, gezählt wird pro
Artikel über Titel+Summary. Es entsteht **Untererfassung**: von den 20 Artikeln der
neun Fälle werden 11 durch den `seen_stories`-Skip gar nicht gezählt.

Keine Karte, kein Telegram-Post, keine Website-Story ist betroffen.

### Obsolet seit 23.08.

`DEFAULT_EXTRA_ENTITIES` ergänzte testweise Intel und Kimi/Moonshot, weil sie in den
29 kuratierten Entitäten fehlten. Seit `entities.json` v2 (71 Entitäten) sind beide
regulär enthalten — der Workaround schadet nicht, ist aber überflüssig.
