#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND="${1:?Backend fehlt}"
shift
ARGS=("$@")
REPO=""
SCOPE="all"
COMMAND=""
OFFLINE=0

for ((i = 0; i < ${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --repo)
      i=$((i + 1))
      REPO="${ARGS[$i]:-}"
      ;;
    --scope)
      i=$((i + 1))
      SCOPE="${ARGS[$i]:-all}"
      ;;
    --offline)
      OFFLINE=1
