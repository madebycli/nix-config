#!/usr/bin/env bash

# Security: X11 has no Wayland-style clipboard isolation. This bridge only
# mirrors text while a Steam Proton XWayland client is focused, but the current
# clipboard becomes readable by other X11 clients during that window.

set -u

poll_interval="${MANGO_PROTON_CLIPBOARD_INTERVAL:-0.15}"
last_x11=""
was_proton=0

read_wayland_clipboard() {
  wl-paste --no-newline 2>/dev/null
}

read_x11_clipboard() {
  xclip -selection clipboard -target UTF8_STRING -out 2>/dev/null ||
    xclip -selection clipboard -out 2>/dev/null
}

focused_proton_client() {
  local client appid is_xwayland

  client="$(mmsg get focusing-client 2>/dev/null)" || return 1
  appid="$(printf '%s' "$client" | jq -r '.appid // empty' 2>/dev/null)"
  is_xwayland="$(printf '%s' "$client" | jq -r '.is_xwayland // false' 2>/dev/null)"

  [[ "$is_xwayland" == "true" ]] || return 1
  [[ "$appid" == "steam_proton" || "$appid" == steam_app_* || "$appid" == "steam_app_default" ]]
}

sync_wayland_to_x11() {
  local wayland

  wayland="$(read_wayland_clipboard)" || return 0
  [[ -n "$wayland" ]] || return 0

  printf '%s' "$wayland" | xclip -selection clipboard -in 2>/dev/null
  last_x11="$wayland"
}

sync_x11_to_wayland() {
  local current confirm wayland

  current="$(read_x11_clipboard)" || return 0
  [[ -n "$current" ]] || return 0
  [[ "$current" != "$last_x11" ]] || return 0

  sleep 0.10
  confirm="$(read_x11_clipboard)" || return 0
  [[ "$confirm" == "$current" ]] || return 0

  wayland="$(read_wayland_clipboard 2>/dev/null || true)"
  if [[ "$wayland" != "$current" ]]; then
    printf '%s' "$current" | wl-copy
  fi

  last_x11="$current"
}

while true; do
  if focused_proton_client; then
    if (( was_proton == 0 )); then
      # Only expose the current Wayland clipboard to X11 when entering a
      # Proton game. This avoids mirroring every Wayland clipboard update.
      sync_wayland_to_x11
      was_proton=1
    fi

    # Wine/Proton reliably owns the X11 CLIPBOARD after copying, while
    # Mango currently fails to propagate that selection back to Wayland.
    sync_x11_to_wayland
  else
    if (( was_proton == 1 )); then
      # Catch a copy followed immediately by switching away from the game.
      sync_x11_to_wayland
      was_proton=0
    fi
  fi

  sleep "$poll_interval"
done
