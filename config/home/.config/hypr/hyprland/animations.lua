hl.config({
    animations = {
        enabled = true,
    },
})

-- Window timing and easing mapped from the Mango reference config.
hl.curve("mangoOpen", { type = "bezier", points = { { 0.4, 0.9 }, { 0.6, 1.0 } } })
hl.curve("mangoClose", { type = "bezier", points = { { 0.08, 0.82 }, { 0.17, 1.0 } } })
hl.curve("mangoMove", { type = "bezier", points = { { 0.46, 1.0 }, { 0.29, 1.0 } } })
hl.curve("mangoFadeOut", { type = "bezier", points = { { 0.5, 0.5 }, { 0.5, 0.5 } } })

-- Keep the workspace animation exactly as tuned before.
hl.curve("workspaceBounce", { type = "bezier", points = { { 0.25, 1.25 }, { 0.5, 1 } } })

-- Mango has layer animations disabled. Fuzzel and Noctalia therefore stay instant.
hl.animation({ leaf = "layersIn", enabled = false })
hl.animation({ leaf = "layersOut", enabled = false })
hl.animation({ leaf = "fadeLayers", enabled = false })

-- Mango timings: open 300 ms, close 200 ms, move/resize 500 ms.
hl.animation({ leaf = "windowsIn", enabled = true, speed = 3, bezier = "mangoOpen", style = "popin 80%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2, bezier = "mangoClose", style = "popin 80%" })
hl.animation({ leaf = "windowsMove", enabled = true, speed = 5, bezier = "mangoMove" })

-- Do not touch the workspace switch animation.
hl.animation({ leaf = "workspaces", enabled = true, speed = 4, bezier = "workspaceBounce", style = "slidevert" })

hl.animation({
    leaf    = "specialWorkspace",
    enabled = true,
    speed   = 3,
    bezier  = "mangoMove",
    style   = "slidefadevert 15%"
})

hl.animation({ leaf = "fadeIn", enabled = true, speed = 3, bezier = "mangoMove" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 2, bezier = "mangoFadeOut" })
hl.animation({ leaf = "fadeSwitch", enabled = false })
hl.animation({ leaf = "fadeDim", enabled = true, speed = 3, bezier = "mangoMove" })
hl.animation({ leaf = "border", enabled = false })
