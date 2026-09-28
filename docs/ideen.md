# Ideen-Liste

Ideen, die bewusst noch nicht gebaut werden. Pro Idee: was es wäre und was es bräuchte.

## Erzähler-Labor (Auftrag 7.8, Entwurf `_prototypen/idee_erzaehler_labor/` auf Branch `prototypen/bunny`)

Eine Bühne, auf der zwei echte Meldungen (aus `news.json` oder `archive.json`) nebeneinanderstehen und sichtbar wird, was sie verbindet: gemeinsame Entitäten, Quellen, Regionen, Themen oder Zeitraum. Das zeigt, wie Geschichten zusammenhängen, ohne eine neue Tatsachenbehauptung aufzustellen.
Nötig wären: eine belastbare Verbindungslogik aus vorhandenen Daten (Entitäten über `entities.json`, Cluster über Link, Tag und Cluster-Kennwerte, weil die `story_id` je Lauf neu vergeben wird) und eine klare Kennzeichnung, dass nur Überschneidungen gezeigt werden und keine Kausalität. Dazu klare Grenzen für jeden erzählenden Text: ohne Sprachmodell nur Vorlagen aus den Datenfeldern; mit Sprachmodell nur über eine Deckungsprüfung wie bei den Linien-Dossiers.
