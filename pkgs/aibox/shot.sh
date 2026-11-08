#!/bin/sh
# shot URL OUT.png [WIDTHxHEIGHT] - headless Chromium screenshot inside the container
set -eu
if [ "$#" -lt 2 ]; then echo "usage: shot URL OUT.png [WIDTHxHEIGHT]" >&2; exit 2; fi
size="${3:-1280x800}"
profile="$(mktemp -d)"
exec chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
  --user-data-dir="$profile" --window-size="${size%x*},${size#*x}" \
  --virtual-time-budget=5000 --screenshot="$2" "$1"
