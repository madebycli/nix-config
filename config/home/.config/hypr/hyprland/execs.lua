local vars = require("variables")
local fn   = require("utils.functions")

hl.on("hyprland.start", function()
    -- Start whichever desktop shell is installed. No service is enabled here.
    hl.exec_cmd([[
        if command -v noctalia >/dev/null 2>&1; then
            exec noctalia
        elif command -v caelestia >/dev/null 2>&1; then
            exec caelestia shell -d
        fi
    ]])

    -- Keyring and auth
    hl.exec_cmd([[
        if command -v lxqt-policykit-agent >/dev/null 2>&1; then
            exec lxqt-policykit-agent
        elif [ -x /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 ]; then
            exec /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1
        fi
    ]])

    -- Clipboard history
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")

    -- Cursors
    hl.exec_cmd("hyprctl setcursor " .. vars.cursorTheme .. " " .. vars.cursorSize)
    hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-theme " .. vars.cursorTheme)
    hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-size " .. vars.cursorSize)
    hl.exec_cmd("XCURSOR_THEME=" .. vars.cursorTheme .. " XCURSOR_SIZE=" .. vars.cursorSize .. " dbus-update-activation-environment --systemd XCURSOR_THEME XCURSOR_SIZE")
end)

-- Resizer listeners
local function apply_resizer_rules(win)
    local float_center = {
        hl.dsp.window.float({ action = "on", window = win }),
        hl.dsp.window.center({ window = win }),
    }
    local pip_actions = fn.move_actions(win) or {}

    -- Bitwarden
    fn.resizer(win, "Bitwarden", 20, 54, float_center, true, "class")
    fn.resizer(win, "^Extension: %(Bitwarden Password Manager%) %- Bitwarden", 20, 54, float_center, false)
    fn.resizer(win, "nngceckbapebfimnlniiiahkandclblb", 20, 54, float_center, true, "class")

    -- Picture in picture
    fn.resizer(win, "Picture[- ]in[- ][Pp]icture", 0, 0, pip_actions, false)
end

hl.on("window.title", apply_resizer_rules)
hl.on("window.open", apply_resizer_rules)
