local vars = require("variables")

hl.config({
    general = {
        layout          = "scrolling",
        allow_tearing   = false,
        gaps_workspaces = vars.workspaceGaps,
        gaps_in         = vars.windowGapsIn,
        gaps_out        = vars.windowGapsOut,
        border_size     = vars.windowBorderSize,

        col = {
            active_border   = vars.activeWindowBorderColour,
            inactive_border = vars.inactiveWindowBorderColour,
        },
    },

    scrolling = {
        fullscreen_on_one_column = false,
        focus_fit_method         = 1,
        column_width             = 1.0,
        follow_focus             = true,
        follow_min_visible       = 0.0,
        explicit_column_widths   = "0.5, 1.0",
        wrap_focus               = false,
        wrap_swapcol             = false,
        direction                = "right",
    },
})
