-- Layer surfaces should never receive compositor blur. Window blur remains
-- opt-in through rules.lua for Ghostty and Nautilus only.
hl.layer_rule({
    match = { namespace = ".*" },
    blur = false,
    blur_popups = false,
})

-- Let Noctalia render its own shell animations without additional Hyprland
-- layer enter/exit animation on top.
hl.layer_rule({
    match = { namespace = "^noctalia.*$" },
    no_anim = true,
    blur = false,
    blur_popups = false,
})
