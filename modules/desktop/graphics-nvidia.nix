{ config, lib, pkgs, ... }:

let
  prime = config.my.hardware.nvidiaPrime;
in
{
  options.my.hardware.nvidiaPrime = {
    intelBusId = lib.mkOption {
      type = lib.types.str;
      description = "PCI bus ID of the Intel iGPU (verify with `lspci -D`).";
    };
    nvidiaBusId = lib.mkOption {
      type = lib.types.str;
      description = "PCI bus ID of the NVIDIA dGPU (verify with `lspci -D`).";
    };
  };

  config = {
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
        inherit (prime) intelBusId nvidiaBusId;
        offload = {
          enable = true;
          enableOffloadCmd = true;
        };
      };
    };
  };
}
