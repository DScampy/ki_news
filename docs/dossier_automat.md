# Dossier-Automat (Auftrag 5, Dossier-Teil + Auftrag 7.1 Chronoskop)

`dossier_automat.py` macht aus den Entwicklungslinien in `news.json` (`linien`, erzeugt von
`ki_news.py` / `_linien_dossiers()`) Dossier-Artikel im Chronoskop-Layout.

## Was drinsteht, und woher

| Teil | Quelle |
|---|---|
| Titel | `linien[id].dossier.titel` (von der Pipeline geprüft); Linien ohne geprüften Titel werden übersprungen |
| Einleitungssatz | aus Zählwerten gebaut (Anzahl Meldungen, Quellen, Zeitraum), **kein Sprachmodell** |
| „Worum es geht“ | `dossier.worum`, nur wenn die Pipeline ihn durch ihre Deckungsprüfung gelassen hat |
| Ereignisse | `linien[id].e`: Titel, Datum, Quelle, Link, Zusammenfassung |
| Belege je Ereignis | Artikel aus `news.json`/`archive.json` desselben Clusters (Story-ID + Erfassungstag + Cluster-Kennwerte, weil die Story-ID je Lauf neu vergeben wird) plus `dub_quellen` |
| News-Karte (MP4) | `cards.json`, gleiche Zuordnung wie `klCardFor()` (Link, dann Titel-Präfix) |
| Befund / Nur Anriss | Befund = mindestens eine Quelle mit Volltext (`full_text`, keine Paywall) |
| Abseits | `dossier.abseits` (Jev-Prüfung der Pipeline) |
| Dossier-Lücke | mehr als 3 Tage zwischen zwei Ereignissen |

Hype-Wörter (revolutionär, bahnbrechend, …) werden **gemeldet**, aber in Quelltexten nicht umgeschrieben.

## Ablage und Freigabe

- Entwurf: `artikel/entwurf/linie-<id>.html`, `noindex`, nicht in Navigation, Sitemap oder Feeds.
- Freigabe: Linien-ID in `dossiers_freigabe.json` unter `freigegeben` eintragen. Der nächste Lauf schreibt
  `artikel/dossier-<id>.html` (indexierbar, weiterhin als „Automatische Zusammenstellung“ gekennzeichnet)
  und ergänzt `sitemap.xml`.

## Aufruf

```
python3 dossier_automat.py --dry-run        # nur Liste + Hype-Funde
python3 dossier_automat.py --max 3          # die 3 größten Linien als Entwurf
python3 dossier_automat.py --linie d33805d3 # eine bestimmte Linie
```

## Gate vor dem Zeitplan

Noch **nicht** im Workflow. Erst wenn Daniel 3 Entwürfe gegen die Quellen geprüft hat (0 erfundene
Aussagen), kommt ein Schritt nach `ki_news.py` in `.github/workflows/ki_news.yml` dazu.
