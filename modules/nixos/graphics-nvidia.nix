{ config, pkgs, nvidiaPrime, ... }:

{
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware.graphics = {
    enable = true;
    enable32Bit = true;
    extraPackages = [ pkgs.intel-media-driver ];
  };

  environment.sessionVariables.LIBVA_DRIVER_NAME = "iHD";

  hardware.nvidia = {
    modesetting.enable = true;
    open = true;
    package = config.boot.kernelPackages.nvidiaPackages.stable;

    powerManagement = {
      enable = true;
      finegrained = true;
    };

    prime = {
      intelBusId = nvidiaPrime.intelBusId;
      nvidiaBusId = nvidiaPrime.nvidiaBusId;
      offload = {
        enable = true;
        enableOffloadCmd = true;
      };
    };
  };
}
