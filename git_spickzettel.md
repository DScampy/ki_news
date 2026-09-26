# Git Spickzettel – @CScampy

## Täglich

```bash
git status                    # Was hat sich geändert?
git add .                     # Alles für Commit vorbereiten
git commit -m "Beschreibung"  # Änderungen speichern
git push                      # Auf GitHub hochladen
git pull                      # Von GitHub herunterladen
```

\---

## Wenn git push abgelehnt wird

GitHub hat Änderungen die du lokal nicht hast (z.B. GitHub Actions hat gepusht):

```bash
git pull --rebase             # GitHub-Stand holen + eigene Commits drauf
git push                      # Jetzt funktioniert es
```

\---

## Wenn du lokale Änderungen hast die noch nicht committed sind

```bash
git stash                     # Lokale Änderungen kurz weglegen
git pull                      # GitHub-Stand holen
git stash pop                 # Eigene Änderungen wieder drauf
git add .
git commit -m "Beschreibung"
git push
```

\---

## Wenn du Mist gebaut hast

```bash
# Letzte Änderungen an einer Datei rückgängig (noch nicht committed):
git checkout -- ki\\\_news.py

# Letzten Commit rückgängig (Änderungen bleiben erhalten):
git reset --soft HEAD\\\~1

# Datei aus Commit rauswerfen (versehentlich hinzugefügt):
git rm --cached dateiname.txt
git commit -m "Datei entfernt"
```

\---

## Wenn dein lokaler Stand der richtige ist (GitHub überschreiben)

Nur wenn du sicher bist dass lokal alles stimmt und GitHub falsch liegt:

```bash
git push --force              # GitHub-Stand wird überschrieben – kein Zurück
```

⚠️ Vorsicht: GitHub Actions Commits gehen dabei verloren.

\---

## Das blaue Fenster mit dem `:`

Git zeigt lange Ausgaben im sogenannten Pager an. Einfach:

* `q` drücken → Beenden
* Pfeiltasten → Scrollen
* `/suchbegriff` → Suchen

\---

## Vim – wenn ein blauer Editor aufgeht

Passiert bei `git merge` oder `git commit` ohne `-m`. Vim ist gewöhnungsbedürftig:

```
ESC drücken
:wq   → speichern und beenden
:q!   → beenden ohne speichern
```

Einmalig auf Notepad umstellen – dann nie wieder Vim:

```bash
git config --global core.editor notepad
```

\---

## Aufräumen

```bash
# Versehentlich erstellte Dateien löschen (wie cd, copy, git):
git rm cd copy git
git commit -m "Muell entfernt"
git push

# Sehen was in einem Commit war:
git log --oneline             # Kurze Übersicht aller Commits
git show abc1234              # Details zu einem Commit
```

\---

## Was bedeuten die Fehlermeldungen?

|Fehler|Bedeutung|Lösung|
|-|-|-|
|`rejected (non-fast-forward)`|GitHub ist weiter als du|`git pull --rebase` dann push|
|`rejected (fetch first)`|Gleiche Sache|`git pull` dann push|
|`Your local changes would be overwritten`|Lokale Änderungen blockieren pull|`git stash` → pull → `stash pop`|
|`LF will be replaced by CRLF`|Windows/Linux Zeilenenden|Harmlos, ignorieren|

\---

## .gitignore – was nie auf GitHub soll

```
config.txt          # API Keys
\\\*.pyc               # Python Cache
\\\_\\\_pycache\\\_\\\_/
```

\---

*Erstellt April 2026*

