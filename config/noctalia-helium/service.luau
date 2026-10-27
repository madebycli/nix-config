--!nonstrict
local previous = nil
local busy = false
function update()
    noctalia.setUpdateInterval(5000)
    if busy then return end
    local outputs = noctalia.outputs() or {}
    local connector = noctalia.getConfig("monitor")
    if not connector or connector == "" then connector = outputs[1] and outputs[1].name end
    local wallpaper = connector and noctalia.wallpaperPath(connector) or ""
    local folder = noctalia.getConfig("folder") or ""
    local args = {"python3", noctalia.pluginDir() .. "/sync.py", noctalia.json.encode({
        wallpaper = wallpaper or "", enabled = noctalia.getConfig("wallpaper"),
        folder = noctalia.expandPath(folder), auto_wallpaper = noctalia.getConfig("auto_wallpaper"),
        primary = noctalia.getColor("primary") or "", blur = noctalia.getConfig("blur"),
        radius = noctalia.getConfig("radius"), grain = noctalia.getConfig("grain")
    })}
    local key = args[3]
    if key == previous then return end
    busy = true
    local accepted = noctalia.runAsync(args, function(result)
        busy = false
        if result.exitCode == 0 then previous = key else noctalia.log("Wallpaper export: " .. (result.stderr or "unknown error")) end
    end, 60000)
    if not accepted then busy = false end
end
function onConfigChanged() previous = nil; update() end
function onOutputsChanged() previous = nil; update() end
