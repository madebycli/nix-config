#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND="${1:?Pfad zum config-sync-Backend fehlt}"
shift
ORIGINAL_ARGS=("$@")

REPO=""
SCOPE="all"
COMMAND=""
OFFLINE=0

for ((i = 0; i < ${#ORIGINAL_ARGS[@]}; i++)); do
  token="${ORIGINAL_ARGS[$i]}"
  case "$token" in
    --repo)
      i=$((i + 1))
      ((i < ${#ORIGINAL_ARGS[@]})) || { printf 'Fehler: --repo benötigt einen Pfad.\n' >&2; exit 2; }
      REPO="${ORIGINAL_ARGS[$i]}"
      ;;
    --scope)
      i=$((i + 1))
      ((i < ${#ORIGINAL_ARGS[@]})) || { printf 'Fehler: --scope benötigt einen Wert.\n' >&2;