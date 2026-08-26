local vars = require("variables")

hl.config({
    input = {
        kb_layout               = "de",
        numlock_by_default      = false,
        repeat_delay            = 250,
        repeat_rate             = 35,
        follow_mouse            = 1,
        follow_mouse_threshold  = 2.0,
        focus_on_close          = 1,
        mouse_refocus           = true,

        touchpad = {
            natural_scroll       = true,
            disable_while_typing = vars.touchpadDisableTyping,
            scroll_factor        = vars.touchpadScrollFactor,
        },
    },

    binds = {
        scroll_event_delay = 0,
    },

    cursor = {
        hotspot_padding = 1,
    },
})
