local function resize_by_screen(x, y)
    local screen = hl.get_active_monitor()
    if screen and type(screen.width) == "number" and type(screen.height) == "number" then
        if not (x == 0 and y == 0) then
            local w = (x and x > 0) and math.floor(screen.width * x / 100) or screen.width
            local h = (y and y > 0) and math.floor(screen.height * y / 100) or screen.height
            return { x = w, y = h, relative = false }
        end
    end
end

local function resizer(window, pattern, x_percent, y_percent, actions, exact, field)
    local value = window and window[field or "title"]
    if value and string.find(value, pattern, 1, exact) then
        local dispatchers = type(actions) == "table" and actions or { actions }
        for _, dispatcher in ipairs(dispatchers) do
            hl.dispatch(dispatcher)
        end

        local size = resize_by_screen(x_percent, y_percent)
        if size then
            size.window = window
            hl.dispatch(hl.dsp.window.resize(size))
        end

        hl.dispatch(hl.dsp.window.set_prop({
            prop = "keep_aspect_ratio",
            value = "true",
            window = window,
        }))
    end
end

local function move_actions(window)
    local screen = hl.get_active_monitor()

    if screen and screen.width and screen.height and screen.scale and window and window.size then
        local monitor_height = screen.height / screen.scale
        local monitor_width = screen.width / screen.scale
        local scale_factor = (monitor_height / 4) / window.size.y

        local target_width = window.size.x * scale_factor
        local target_height = window.size.y * scale_factor
        local resize_x = math.floor(math.max(200, target_width))
        local resize_y = math.floor(math.max(150, target_height))
        local offset = math.min(monitor_width, monitor_height) * 0.03
        local move_x = math.floor(screen.x + monitor_width - resize_x - offset)
        local move_y = math.floor(screen.y + monitor_height - resize_y - offset)

        return {
            hl.dsp.window.resize({ x = resize_x, y = resize_y, window = window }),
            hl.dsp.window.move({ x = move_x, y = move_y, relative = false, window = window }),
        }
    end
end

return {
    resizer = resizer,
    move_actions = move_actions,
}
