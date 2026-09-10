#!/usr/bin/env bash
set -euo pipefail

# This is a read-only snapshot for intermittent channel-balance reports. Keep
# the output limited to routing, channel and reconnect state; do not dump the
# full PipeWire graph because it can contain application paths and metadata.

printf 'aether-audio-snapshot %s\n' "$(date --iso-8601=seconds)"

printf '\n--- wpctl status ---\n'
wpctl status --name 2>&1 | sed -E 's/cookie:[[:space:]]*[0-9]+/cookie:<redacted>/g'

printf '\n--- default sink volume ---\n'
wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>&1 || true

printf '\n--- default sink properties ---\n'
sink_inspect=$(wpctl inspect @DEFAULT_AUDIO_SINK@ 2>&1 || true)
printf '%s\n' "$sink_inspect" | sed -E '/object\.(id|serial|path)|client\.id|alsa\.long_card_name|api\.alsa\.card\.longname/d'

sink_id=$(printf '%s\n' "$sink_inspect" | sed -n 's/^id \([0-9][0-9]*\),.*/\1/p' | head -n 1)
if [ -n "$sink_id" ]; then
  printf '\n--- default sink channel parameters ---\n'
  pw-cli enum-params "$sink_id" Props 2>&1 | awk '
    /Prop: key .* (volume|mute|channelVolumes|channelMap|softMute|softVolumes|monitorMute|monitorVolumes) \(/ {
      keep = 1
    }
    /^    Prop: key / && keep && $0 !~ / (volume|mute|channelVolumes|channelMap|softMute|softVolumes|monitorMute|monitorVolumes) \(/ {
      keep = 0
    }
    keep { print }
  '
else
  printf 'No default audio sink is currently available.\n'
fi

printf '\n--- recent PipeWire/WirePlumber events ---\n'
journalctl --user -b -u pipewire -u pipewire-pulse -u wireplumber -n 80 -o short-monotonic 2>&1 | sed -E 's#/home/[^[:space:]]+#/home/<user>#g'
