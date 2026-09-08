{ lib, pkgs, settings ? { }, ... }:
let
  bundles = settings.bundles or { };
  browser = settings.browser or { };
  integrations = settings.integrations or { };
  filen = integrations.filen or { };

  gaming = bundles.gaming or false;
  office = bundles.office or false;
  development = bundles.development or false;
  multimedia = bundles.multimedia or false;
  browserName = browser.default or "none";

  filenEnabled = filen.enable or false;
  filenClient = filen.client or "desktop";
  filenAutostart = filen.autostart or false;
in
{
  assertions = [
    {
      assertion = builtins.elem browserName [ "none" "firefox" "brave" "librewolf" ];
      message = "Unsupported Nix Settings browser: ${browserName}";
    }
    {
      assertion = builtins.elem filenClient [ "desktop" "cli" ];
      message = "Unsupported Filen client: ${filenClient}";
    }
    {
      assertion = !(filenAutostart && filenClient == "cli");
      message = "Filen CLI autostart needs an explicit sync definition; use Filen Desktop for generic autostart.";
    }
  ];

  programs.steam.enable = lib.mkIf gaming true;
  programs.gamemode.enable = lib.mkIf gaming true;

  environment.systemPackages =
    lib.optionals gaming (with pkgs; [ mangohud ])
    ++ lib.optionals office (with pkgs; [ libreoffice-stable ])
    ++ lib.optionals development (with pkgs; [ git gcc gnumake python3 nodejs ])
    ++ lib.optionals multimedia (with pkgs; [ ffmpeg mpv ])
    ++ lib.optionals (browserName == "firefox") [ pkgs.firefox ]
    ++ lib.optionals (browserName == "brave") [ pkgs.brave ]
    ++ lib.optionals (browserName == "librewolf") [ pkgs.librewolf ]
    ++ lib.optionals (filenEnabled && filenClient == "desktop") [ pkgs.filen-desktop ]
    ++ lib.optionals (filenEnabled && filenClient == "cli") [ pkgs.filen-cli ];

  systemd.user.services.filen-desktop = lib.mkIf (filenEnabled && filenClient == "desktop" && filenAutostart) {
    description = "Filen Desktop";
    after = [ "graphical-session.target" ];
    partOf = [ "graphical-session.target" ];
    wantedBy = [ "graphical-session.target" ];
    serviceConfig = {
      ExecStart = lib.getExe pkgs.filen-desktop;
      Restart = "on-failure";
      RestartSec = 3;
    };
  };
}
