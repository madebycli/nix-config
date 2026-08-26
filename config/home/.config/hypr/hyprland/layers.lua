-- Layer surfaces should never receive compositor blur. Window blur remains
-- opt-in through rules.lua for Ghostty and Nautilus only.
hl.layer_rule({
    match = { namespace = ".*" },
    blur = false,
    blur_popups = false,
})

-- Explicitly override Noctalia's Hyprland blur recipe. ignore_alpha = 1.0 is
-- an additional guard: even if another Noctalia rule enables layer blur, every
-- pixel is ignored by the blur pass.
hl.layer_rule({
    name = "noctalia",
    match = { namespace = "^noctalia.*$" },
    no_anim = true,
    blur = false,
    blur_popups = false,
    ignore_alpha = 1.0,
})
