local vars = require("variables")

-- Tags an array of window matches. If `field` is given, matches should be an
-- array of strings. Otherwise, it should be an array of tables.
local function tagged_rule(tag, matches, field)
    for _, match in ipairs(matches) do
        if field then
            local table = {}
            table[field] = match
            match = table
        end
        hl.window_rule({ match = match, tag = "+" .. tag })
    end
end

local function create_tag(tag, rules)
    local rule = { match = { tag = tag } }
    for k, v in pairs(rules) do
        rule[k] = v
    end
    hl.window_rule(rule)
end

local opaque_tag = "opaque"
local float_tag = "float"
local float_60_70_tag = "float_60_70"
local float_70_80_tag = "float_70_80"
local float_50_60_tag = "float_50_60"
local xwl_popup_tag = "xwl_popup"

----------------------
---- Window rules ----
----------------------

-- Apply default opacity to all windows except fullscreen.
hl.window_rule({ match = { fullscreen = false }, opacity = vars.windowOpacity .. " override" })

-- Blur is opt-in. Ghostty and Nautilus are slightly more transparent and keep blur enabled.
hl.window_rule({ match = { class = ".*" }, no_blur = true })
hl.window_rule({ match = { class = "ghostty" }, no_blur = false })
hl.window_rule({ match = { class = "ghostty", fullscreen = false }, opacity = "0.92 override" })
hl.window_rule({ match = { class = "org.gnome.Nautilus" }, no_blur = false })
hl.window_rule({ match = { class = "org.gnome.Nautilus", fullscreen = false }, opacity = "0.92 override" })

-- Center all floating Wayland windows. XWayland popups count as windows.
hl.window_rule({ match = { float = true, xwayland = false }, center = true })

-- Picture in picture. Move and resize are handled by execs.lua.
hl.window_rule({
    match             = { title = "Picture(-| )in(-| )[Pp]icture" },
    move              = "(monitor_w*0.98-window_w) (monitor_h*0.97-window_h)",
    pin               = true,
    float             = true,
    keep_aspect_ratio = true,
})

-- Games open on the next empty workspace on the current monitor and use real fullscreen.
for _, class in ipairs({
    "steam_app_[0-9]+",
    "steam_app_default",
    "steam_proton",
    "gamescope",
}) do
    hl.window_rule({
        match        = { class = class },
        workspace    = "emptynm",
        fullscreen   = true,
        opaque       = true,
        idle_inhibit = "fullscreen",
    })
end

----------------------
---- Tagged rules ----
----------------------

-- Opaque apps
tagged_rule(opaque_tag, {
    "foot",
    "equibop",
    "org.quickshell",
    "feh|imv|swappy",
    "krita|gimp|inkscape|darktable",
    "resolve|kdenlive|shotcut",
    "blender|godot",
}, "class")

-- Floating apps
tagged_rule(float_tag, {
    "guifetch",
    "yad|zenity",
    "wev",
    "org.gnome.FileRoller|file-roller",
    "blueman-manager",
    "com.github.GradienceTeam.Gradience",
    "feh|imv|swappy",
    "org.quickshell",
}, "class")
tagged_rule(float_tag, {
    "File (Operation|Upload)( Progress)?",
    ".* Properties",
}, "title")

-- Sized floaters, 60% x 70%
tagged_rule(float_60_70_tag, {
    "(Select|Open)( a)? (File|Folder)(s)?",
    "Save As",
    "Library",
}, "title")
tagged_rule(float_60_70_tag, {
    { title = "(Save|Export) Image", class = "gimp" },
})
tagged_rule(float_60_70_tag, {
    "org.pulseaudio.pavucontrol|com.saivert.pwvucontrol",
    "yad-icon-browser",
}, "class")

-- Sized floaters, 70% x 80%
tagged_rule(float_70_80_tag, {
    "org.gnome.Settings",
}, "class")

-- Sized floaters, 50% x 60%
tagged_rule(float_50_60_tag, {
    "nwg-look",
    "system-config-printer",
}, "class")

-- XWayland popups
tagged_rule(xwl_popup_tag, {
    { xwayland = true, title = "win[0-9]+" },
    { xwayland = true, title = "", class = "", initial_title = "", initial_class = "" },
})

-----------------------
---- Per app rules ----
-----------------------

-- Steam
tagged_rule(float_tag, { { class = "steam", title = "Friends List" } })
tagged_rule(xwl_popup_tag, { { class = "steam", title = "" } })

-- Ueberzugpp
hl.window_rule({ match = { class = "ueberzugpp_.*" }, float = true, no_initial_focus = true })

-- Autodesk Fusion 360
hl.window_rule({ match = { class = "fusion360.exe", title = "Fusion360|(Marking Menu)" }, no_blur = true })

-- Minecraft launcher consoles
tagged_rule(float_tag, {
    { class = "com-atlauncher-App", title = "ATLauncher Console" },
    { class = "PandoraLauncher", title = "Minecraft Game Output" },
})

-------------------------
---- Tag definitions ----
-------------------------

create_tag(opaque_tag, { opaque = true })
create_tag(float_tag, { float = true })
create_tag(float_50_60_tag, { float = true, size = "(monitor_w*0.5) (monitor_h*0.6)", center = true })
create_tag(float_60_70_tag, { float = true, size = "(monitor_w*0.6) (monitor_h*0.7)", center = true })
create_tag(float_70_80_tag, { float = true, size = "(monitor_w*0.7) (monitor_h*0.8)", center = true })
create_tag(xwl_popup_tag, {
    no_dim = true,
    no_shadow = true,
    no_blur = true,
    opaque = true,
    rounding = math.min(10, vars.windowRounding),
})

-------------------------
---- Workspace rules ----
-------------------------

-- Keep the five everyday workspaces available even while empty.
for i = 1, 5 do
    hl.workspace_rule({ workspace = tostring(i), persistent = true })
end

---------------------
---- Layer rules ----
---------------------

hl.layer_rule({ match = { namespace = "hyprpicker" }, animation = "fade" })
hl.layer_rule({ match = { namespace = "logout_dialog" }, animation = "fade" })
hl.layer_rule({ match = { namespace = "selection" }, animation = "fade" })
hl.layer_rule({ match = { namespace = "wayfreeze" }, animation = "fade" })
hl.layer_rule({ match = { namespace = "launcher" }, animation = "popin 80%" })

-- Shell
hl.layer_rule({ match = { namespace = "caelestia-(border-exclusion|area-picker)" }, no_anim = true })
hl.layer_rule({ match = { namespace = "caelestia-(drawers|background)" }, animation = "fade" })
