local scheme = require("scheme.current")

return {
    -- Apps
    terminal                   = "ghostty",
    browser                    = "brave",
    alternateBrowser           = "librewolf",
    editor                     = "codium",
    fileExplorer               = "nautilus",
    communication              = "vesktop",
    audioSettings              = "pavucontrol",

    -- Touchpad and gestures
    touchpadDisableTyping      = true,
    touchpadScrollFactor       = 0.3,
    workspaceSwipeFingers      = 4,
    gestureFingersMore         = 4,

    -- Blur
    blurEnabled                = true,
    blurSpecialWs              = false,
    blurPopups                 = true,
    blurInputMethods           = true,
    blurSize                   = 8,
    blurPasses                 = 2,
    blurXray                   = false,

    -- Shadow
    shadowEnabled              = true,
    shadowRange                = 15,
    shadowRenderPower          = 4,
    shadowColour               = "rgba(" .. scheme.inversePrimary .. "10)",

    -- Gaps
    workspaceGaps              = 0,
    windowGapsIn               = 3,
    windowGapsOut              = 6,

    -- Window styling
    windowOpacity              = 1.0,
    windowRounding             = 6,
    windowBorderSize           = 2,
    activeWindowBorderColour   = "rgba(" .. scheme.primary .. "e6)",
    inactiveWindowBorderColour = "rgba(" .. scheme.onSurfaceVariant .. "11)",

    -- Misc
    volumeStep                 = 10,
    volumeMax                  = 100,
    cursorTheme                = "sweet-cursors",
    cursorSize                 = 24,
    sleepGestureCmd            = "systemctl suspend-then-hibernate",
}
