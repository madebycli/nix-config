# Nix-Wartungsbefehle

Diese Konfiguration trennt neue GitHub-Konfigurationscommits, Flake-Input-Updates,
persönliche Nix-Profile und NixOS-Systemgenerationen. Alle Befehle erkennen
`nyx` oder `aether` automatisch. Zurück zur [README](README.md).

## Übersicht

| Befehl | Wirkung |
|---|---|
| `config-update` | Neue Konfigurationscommits holen, bauen und aktivieren |
| `nix-help` | Alle eigenen Befehle und Beispiele anzeigen |
| `nix-status [--online]` | System-, Store-, Git- und Profilübersicht |
| `nix-updates [MODUS] [--full]` | Updates in einer temporären Repositorykopie prüfen |
| `nix-refresh [MODUS]` | Ausgewählte Quellen aktualisieren, bauen und sicher aktivieren |
| `nix-generations` | NixOS-Systemgenerationen anzeigen oder vergleichen |
| `nix-clean [1-20]` | Aktuelle Generation plus gewünschte Backup-Anzahl behalten |
| `nix-optimize` | Identische Store-Dateien deduplizieren, ohne Generationen zu löschen |
| `nix-rollback` | Auf die vorherige Systemgeneration wechseln |

Die alten Programme `system-update` und `system-rollback` existieren nicht mehr
und werden nicht als Alias weitergeleitet.

## Update-Gruppen

| Modus | Flake-Inputs | Persönliches `nix profile` |
|---|---|---|
| `nix-refresh` | alle unten aufgeführten Inputs | `upgrade --all --refresh` |
| `nix-refresh base` | `nixpkgs`, `nix-cachyos-kernel` | `upgrade --all --refresh` |
| `nix-refresh packages` | `nixpkgs` | `upgrade --all --refresh` |
| `nix-refresh kernel` | `nix-cachyos-kernel` | unverändert |
| `nix-refresh desktop` | `home-manager`, `mango`, `noctalia`, `noctalia-greeter` | unverändert |
| `nix-refresh profiles` | keine System-Flakes | `upgrade --all --refresh` |

Der vollständige Modus umfasst:

```text
nixpkgs
home-manager
nix-cachyos-kernel
mango
noctalia
noctalia-greeter
```

`desktop` aktualisiert ausschließlich Home Manager und die drei Desktopquellen.
Nixpkgs und der CachyOS-Kernel bleiben dabei auf ihren aktuellen Revisionen.

## Vorschau mit `nix-updates`

```bash
nix-updates
nix-updates base
nix-updates desktop
nix-updates profiles
nix-updates --full
```

Für Flake-Updates wird das lokale Repository in ein temporäres Verzeichnis
kopiert. Nur dort wird eine neue `flake.lock` erzeugt. Angezeigt werden je Input
Datum und kurzer Commit-Hash. Die echte Lockdatei bleibt unverändert.

`--full` baut zusätzlich die mögliche neue System-Closure, aktiviert sie jedoch
nicht. Anschließend zeigt `nix store diff-closures` Paket-, Versions- und
Größenunterschiede gegenüber `/run/current-system`.

Persönliche Profilpakete werden mit folgendem Dry Run geprüft:

```bash
nix profile upgrade --all --refresh --dry-run
```

## Sicherer Ablauf von `nix-refresh`

1. Host, Repository und zuletzt verwendetes Desktopprofil erkennen.
2. Remote und Git-Verhältnis zu GitHub prüfen.
3. Bei neueren GitHub-Konfigurationscommits auf `config-update` verweisen.
4. Aktuelle `flake.lock` in einem Zeitstempel-Backup sichern.
5. Nur die Inputs des ausgewählten Modus mit `--refresh` aktualisieren.
6. Das vollständige NixOS-Profil bauen.
7. Ausschließlich nach erfolgreichem Build switchen.
8. TRIM für den nächsten Neustart vormerken.
9. In den Modi `all`, `base` und `packages` persönliche Profilpakete mit
   `nix profile upgrade --all --refresh` aktualisieren.
10. Eine getestete geänderte Lockdatei committen und pushen, sofern Git-Zustand
    und Identität dies sicher erlauben.

Schlägt Input-Auflösung oder Build vor der Aktivierung fehl, wird die vorherige
`flake.lock` automatisch wiederhergestellt. Ein späteres Profilupdate ist eine
separate Transaktion; dessen Fehler macht den bereits erfolgreichen NixOS-Switch
nicht rückgängig.

## Systemgenerationen

```bash
nix-generations
nix-generations --last 10
nix-generations --diff 20 21
```

Eine Systemgeneration ist ein durch `nixos-rebuild` erzeugter Systemstand, der
im Bootmenü und für Rollbacks verfügbar sein kann. `--diff` vergleicht die beiden
Closures mit `nix store diff-closures`.

## Aufräumen

```bash
nix-clean                  # aktuell + fünf Backups
nix-clean 1                # aktuell + ein Backup
nix-clean 10               # aktuell + zehn Backups
nix-clean --dry-run 5
nix-clean list
```

Erlaubt sind 1 bis 20 Backups. Der Standardwert ist fünf; zusammen mit der
aktuell laufenden Generation bleiben damit höchstens sechs Generationen.

Vor dem Löschen prüft `nix-clean`, dass laufendes System und Boot-Standard
identisch sind und dass die laufende Generation die neueste ist. Danach werden
nur die ausdrücklich angezeigten Generationen aus dem Systemprofil entfernt,
das Bootmenü neu erzeugt und unerreichbare Store-Pfade durch Garbage Collection
freigegeben. Repository, Hardwaredateien und persönliche Dateien werden nicht
verändert.

Die wöchentliche automatische Garbage Collection entfernt keine Generationen
mehr anhand einer 30-Tage-Regel. Die Anzahl wird bewusst mit `nix-clean`
gesteuert.

## Store-Optimierung und Rollback

```bash
nix-optimize
nix-rollback
```

`nix-optimize` führt `sudo nix-store --optimise -vv` aus und misst den Store vor
und nach der Deduplizierung. Es löscht keine Generationen.

`nix-rollback` verwendet `sudo nixos-rebuild switch --rollback`. Repository und
Lockdatei bleiben unverändert. Nach einem Kernel- oder Initrd-Rollback sollte der
Rechner neu gestartet werden.

## Aktivierung auf einem vorhandenen Rechner

```bash
config-update
```

Nach erfolgreichem Build und Switch stehen die neuen `nix-*`-Programme direkt
im Terminal zur Verfügung. `nix-help` zeigt die komplette Übersicht.
