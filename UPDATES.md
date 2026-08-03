# Update-Befehle

Diese Konfiguration trennt Änderungen am GitHub-Repository von Updates der
Flake-Inputs. Alle Befehle erkennen `nyx` oder `aether` automatisch. Das erwartete
Remote ist `https://github.com/madebycli/nix-config.git` oder
`git@github.com:madebycli/nix-config.git`. Zurück zur [README](README.md).

## Übersicht

| Befehl | Wirkung |
|---|---|
| `config-update` | Neue Konfigurationsdateien von GitHub holen, bauen und aktivieren |
| `system-update` | Alle Flake-Inputs aktualisieren, bauen und aktivieren |
| `system-update base` | Nur Nixpkgs und CachyOS-Kernel aktualisieren |
| `system-update packages` | Nur Nixpkgs und damit die normalen Systempakete aktualisieren |
| `system-update kernel` | Nur den CachyOS-Kernel-Input aktualisieren |
| `system-update desktop` | Home Manager, Mango, Noctalia und Noctalia-Greeter aktualisieren |
| `system-rollback` | Auf die vorherige NixOS-Systemgeneration wechseln |

## Input-Gruppen

### Alles

```text
nixpkgs
home-manager
nix-cachyos-kernel
mango
noctalia
noctalia-greeter
```

### Base

```text
nixpkgs
nix-cachyos-kernel
```

Dieser Modus aktualisiert **nicht** die eigenen Git-Revisionen von Mango,
Noctalia, Noctalia-Greeter oder Home Manager.

### Packages

```text
nixpkgs
```

### Kernel

```text
nix-cachyos-kernel
```

### Desktop

```text
home-manager
mango
noctalia
noctalia-greeter
```

## Ablauf von `system-update`

1. Host und zuletzt verwendetes Desktopprofil erkennen.
2. Prüfen, ob GitHub eine neuere Konfiguration enthält.
3. Eine Sicherung der aktuellen `flake.lock` anlegen.
4. Einmalig das sudo-Passwort abfragen und den sudo-Zeitstempel aktiv halten.
5. Nur die ausgewählten Flake-Inputs aktualisieren.
6. `nixos-rebuild build` ausführen.
7. Nur nach erfolgreichem Build automatisch `nixos-rebuild switch` ausführen.
8. TRIM für den nächsten Neustart vormerken.
9. Die getestete `flake.lock` automatisch committen und pushen, sofern Git-Identität und Git-Zustand dies sicher erlauben.

Schlägt das Input-Update oder der Build fehl, wird die vorherige `flake.lock`
automatisch wiederhergestellt. Andere lokale Dateien werden nicht verändert.

Enthält GitHub eine neuere Konfiguration, stoppt `system-update` mit dem Hinweis,
zuerst `config-update` auszuführen.

## Rollback

```bash
system-rollback
```

Der Befehl verwendet:

```bash
sudo nixos-rebuild switch --rollback
```

Damit werden das laufende System und der Boot-Standard auf die vorherige
NixOS-Systemgeneration gesetzt. Das Repository und die `flake.lock` bleiben
unverändert. Nach einem Kernel- oder Initrd-Rollback sollte der Rechner neu
gestartet werden.

## Erstmalige Aktivierung der Befehle

Auf einem bereits eingerichteten Rechner:

```bash
config-update
```

Danach stehen `system-update` und `system-rollback` direkt im Terminal zur
Verfügung.
