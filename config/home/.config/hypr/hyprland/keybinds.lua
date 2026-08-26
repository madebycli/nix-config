local vars = require("variables")

local locked           = { locked = true }
local repeating        = { repeating = true }
local locked_repeating = { locked = true, repeating = true }
local mouse            = { mouse = true }

-- Apps
hl.bind("SUPER + Return", hl.dsp.exec_cmd(vars.terminal))
hl.bind("SUPER + Space", hl.dsp.exec_cmd("fuzzel"))
hl.bind("SUPER + E", hl.dsp.exec_cmd(vars.fileExplorer))
hl.bind("SUPER + B", hl.dsp.exec_cmd(vars.browser))
hl.bind("SUPER + W", hl.dsp.exec_cmd(vars.alternateBrowser))
hl.bind("SUPER + V", hl.dsp.exec_cmd(vars.communication))
hl.bind("SUPER + C", hl.dsp.exec_cmd(vars.editor))
hl.bind("CTRL + ALT + V", hl.dsp.exec_cmd(vars.audioSettings))

-- Scrolling layout navigation
hl.bind("SUPER + Left", hl.dsp.layout("focus l"), repeating)
hl.bind("SUPER + Right", hl.dsp.layout("focus r"), repeating)
hl.bind("SUPER + SHIFT + Left", hl.dsp.layout("swapcol l"), repeating)
hl.bind("SUPER + SHIFT + Right", hl.dsp.layout("swapcol r"), repeating)
hl.bind("ALT + E", hl.dsp.layout("colresize 1.0"))
hl.bind("ALT + X", hl.dsp.layout("colresize +conf"))

-- Workspace navigation, including persistent empty workspaces on the current monitor
hl.bind("SUPER + Up", hl.dsp.focus({ workspace = "r-1" }), repeating)
hl.bind("SUPER + Down", hl.dsp.focus({ workspace = "r+1" }), repeating)
hl.bind("SUPER + SHIFT + Up", hl.dsp.window.move({ workspace = "r-1", follow = true }), repeating)
hl.bind("SUPER + SHIFT + Down", hl.dsp.window.move({ workspace = "r+1", follow = true }), repeating)

for i = 1, 9 do
    hl.bind("SUPER + " .. i, hl.dsp.focus({ workspace = i }))
    hl.bind("SUPER + SHIFT + " .. i, hl.dsp.window.move({ workspace = i, follow = true }))
end

-- Window actions
hl.bind("SUPER + Q", hl.dsp.window.close())
-- Native Scrolling toggle between the configured 0.5 and 1.0 widths.
hl.bind("SUPER + A", hl.dsp.layout("colresize +conf"))
hl.bind("SUPER + F", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
hl.bind("SUPER + P", hl.dsp.window.float())

-- Screenshots through Noctalia's compositor-native screencopy support
hl.bind("SUPER + SHIFT + S", hl.dsp.exec_cmd("noctalia msg screenshot-region"))
hl.bind("Print", hl.dsp.exec_cmd("noctalia msg screenshot-fullscreen"))

-- GIF workflow carried over from Mango. These commands are external helper scripts.
hl.bind("SUPER + SHIFT + G", hl.dsp.exec_cmd("gif-picker"))
hl.bind("SUPER + SHIFT + H", hl.dsp.exec_cmd("gif-player edit"))
hl.bind("SUPER + SHIFT + K", hl.dsp.exec_cmd("gif-player stop-all"))
hl.bind("SUPER + SHIFT + J", hl.dsp.exec_cmd("gif-control"))

-- Mouse move and resize
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), mouse)
hl.bind("SUPER + mouse:273", hl.dsp.window.resize(), mouse)

-- Media keys
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd(
    "wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume -l " ..
    (vars.volumeMax / 100) .. " @DEFAULT_AUDIO_SINK@ " .. vars.volumeStep .. "%+"
), locked_repeating)
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd(
    "wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ " .. vars.volumeStep .. "%-"
), locked_repeating)
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), locked)
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), locked)
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), locked)
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), locked)
