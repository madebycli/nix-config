"""Describe our existing engine for upstream Control, inside the same ROCm image.

This is a local unsigned package, not an upstream release or a standalone ROCm
redistribution. Its shared ROCm dependencies remain in the parent OCI image.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys


def bundle(root, output, arch):
    version = re.search(r"project\(strata VERSION ([0-9.]+)",
                        (root / "CMakeLists.txt").read_text(), re.I)
    if not version or not re.fullmatch(r"gfx[0-9a-f]+", arch):
        raise ValueError("Missing engine version or invalid GPU architecture")
    version = version[1]
    target = output / f"{version}-linux-x86_64-hip-aibox"
    target.mkdir(parents=True)
    files = []
    source = root / "build-hip"
    paths = [source / "strata", source / "strata-device"]
    paths += [p for p in source.glob("*.so*") if p.is_file()]
    for path in paths:
        destination = target / path.name
        shutil.copy2(path, destination)
        files.append({"path": path.name, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                      "bytes": destination.stat().st_size})
    manifest = {"schema_version": 2, "id": "strata-engine", "name": "strata-engine",
                "version": version, "platform": "linux-x86_64", "backend": "hip",
                "archs": [arch], "entrypoint": "strata", "files": files,
                "build_id": "011c9e600a93bbc9fd451c563501b5831c32bbca",
                "variant": "aibox", "signature": None,
                "notes": "Local aibox build; ROCm libraries supplied by parent OCI image."}
    (target / "engine-component.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return target


if __name__ == "__main__":
    from strata_control import engine_component
    folder = bundle(Path("/opt/strata"), Path("/opt/aibox-engine-bundle"), sys.argv[1])
    engine_component.verify(engine_component.read_manifest(folder), full=True)
