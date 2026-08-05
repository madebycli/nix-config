#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  ""|--help|-h|help) ;;
  *)
    printf 'Fehler: nix-help akzeptiert keine Argumente.\n' >&2
    exit 2
    ;;
esac

cat <<'HELP'
NixOS-Werkzeuge dieser Konfiguration

  config-update              Konfigurationscommits holen, bauen und aktivieren

  nix-status                 Lokale System-, Store- und Git-Übersicht
  nix-status --online        Zusätzlich den GitHub-Stand prüfen

  nix-updates                Alle Flake- und Profilupdates unverbindlich prüfen
  nix-updates base           Nixpkgs und CachyOS-Kernel prüfen
  nix-updates packages       Nixpkgs und Profilpakete prüfen
  nix-updates kernel         Nur den CachyOS-Kernel prüfen
  nix-updates desktop        Home Manager, Mango, Noctalia und Greeter prüfen
  nix-updates profiles       Nur persönliche Nix-Profilpakete prüfen
  nix-updates --full         Neue System-Closure bauen und Paketversionen vergleichen

  nix-refresh                Alle Flake-Inputs aktualisieren, bauen und switchen;
                             danach persönliche Profilpakete aktualisieren
  nix-refresh base           Nixpkgs und CachyOS-Kernel plus Profilpakete
  nix-refresh packages       Nixpkgs plus Profilpakete
  nix-refresh kernel         Nur CachyOS-Kernel
  nix-refresh desktop        Home Manager, Mango, Noctalia und Greeter
  nix-refresh profiles       Nur persönliche Nix-Profilpakete

  nix-generations            Alle NixOS-Systemgenerationen anzeigen
  nix-generations --last 10  Nur die letzten zehn anzeigen
  nix-generations --diff A B Paketunterschiede zwischen Generation A und B

  nix-clean                  Aktuelle Generation plus fünf Backups behalten
  nix-clean 10               Aktuelle Generation plus zehn Backups behalten
  nix-clean --dry-run 5      Nur anzeigen, was entfernt würde
  nix-clean list             Generationen anzeigen, nichts löschen

  nix-optimize               Identische Dateien im Nix Store deduplizieren
  nix-rollback               Auf die vorherige NixOS-Systemgeneration wechseln

  nix-help                   Diese Übersicht anzeigen

Hinweis: Diese Befehle sind eigene Programme mit Bindestrich. Sie verändern
keine offiziellen Unterbefehle wie `nix shell` oder `nix profile`.
HELP
EOF
