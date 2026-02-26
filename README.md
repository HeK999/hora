# hora

`hora` ist ein CLI für BrightSign-Setups. Es findet Videos, lässt ein Main-Video wählen und generiert passende `autorun.brs`-Dateien für Main + Clients.

## Voraussetzungen

- macOS
- Python 3.10+
- `pipx`
- Zugriff auf das private GitHub-Repository

## Installation (Team)

SSH:

```bash
pipx install "git+ssh://git@github.com/HeK999/hora.git@main"
```

HTTPS (Fallback):

```bash
pipx install "git+https://github.com/HeK999/hora.git@main"
```

Danach ist `hora` direkt im PATH verfügbar.

## Updates

```bash
pipx upgrade hora
```

`hora` prüft bei jedem Start den Stand von `main` und zeigt bei Abweichung eine Warnung mit diesem Update-Befehl.

## Migration von lokalen Symlinks

Falls bisher ein lokaler Symlink verwendet wurde (z. B. `/usr/local/bin/hora -> .../hora.py`):

```bash
rm /usr/local/bin/hora
pipx install "git+ssh://git@github.com:HeK999/hora.git@main"
```

## Nutzung

Im gewünschten Projektordner:

```bash
hora
```

Optionen:

- `--skip-update-check` überspringt den Start-Update-Check
- `--version` zeigt die installierte Version

Alternativ per Environment-Variable:

```bash
HORA_SKIP_UPDATE_CHECK=1 hora
```

Debug-Ausgaben des Update-Checks:

```bash
HORA_DEBUG_UPDATE_CHECK=1 hora
```
