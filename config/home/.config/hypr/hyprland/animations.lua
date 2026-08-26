hl.config({
    animations = {
        enabled = true,
    },
})

-- Fast, clean easing for normal window and layer motion.
hl.curve("snappy", { type = "bezier", points = { { 0.2, 0.85 }, { 0.2, 1.0 } } })
hl.curve("snappyOut", { type = "bezier", points = { { 0.25, 0.75 }, { 0.25, 1.0 } } })

-- Keep the workspace animation exactly as tuned before.
hl.curve("workspaceBounce", { type = "bezier", points = { { 0.25, 1.25 }, { 0.5, 1 } } })

hl.animation({ leaf = "layersIn", enabled = true, speed = 1.6, bezier = "snappy", style = "slide" })
hl.animation({ leaf = "layersOut", enabled = true, speed = 1.2, bezier = "snappyOut", style = "slide" })
hl.animation({ leaf = "fadeLayers", enabled = true, speed = 1.4, bezier = "snappy" })

hl.animation({ leaf = "windowsIn", enabled = true, speed = 1.6, bezier = "snappy" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.2, bezier = "snappyOut" })
hl.animation({ leaf = "windowsMove", enabled = true, speed = 1.4, bezier = "snappy" })

hl.animation({ leaf = "workspaces", enabled = true, speed = 4, bezier = "workspaceBounce", style = "slidevert" })

hl.animation({
    leaf = "specialWorkspace",
    enabled = true,
    speed = 1.8,
    bezier = "snappy",
    style = "slidefadevert 12%"
})

hl.animation({ leaf = "fade", enabled = true, speed = 1.4, bezier = "snappy" })
hl.animation({ leaf = "fadeDim", enabled = true, speed = 1.4, bezier = "snappy" })
hl.animation({ leaf = "border", enabled = true, speed = 1.2, bezier = "snappy" })
