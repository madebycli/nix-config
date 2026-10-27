#!/usr/bin/env python3
"""Export and optionally synchronize a wallpaper, and record Noctalia's color."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

args = json.loads(sys.argv[1])
home = Path.home()
data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'noctalia/helium-wallpaper'
profile = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'net.imput.helium/Default'
background = profile / 'background.jpg'
backup = data / 'original-background.jpg'
marker = data / 'last-background.sha256'

def atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

auto = bool(args.get('auto_wallpaper'))
color = args.get('primary', '')
if len(color) != 7 or not color.startswith('#'):
    sys.exit('Noctalia color unavailable')
try:
    int(color[1:], 16)
except ValueError:
    sys.exit('Invalid Noctalia color')
if not auto and marker.exists():
    if background.exists() and backup.exists() and digest(background) == marker.read_text().strip():
        atomic(background, backup.read_bytes())
    marker.unlink(missing_ok=True)
if not args['enabled'] and not auto:
    atomic(data / 'current.json', (json.dumps({'color': color, 'auto_wallpaper': False}) + '\n').encode())
    sys.exit(0)
if not args['wallpaper'] or not Path(args['wallpaper']).is_file():
    sys.exit('Noctalia wallpaper unavailable')
if args['enabled'] and (not args['folder'] or not Path(args['folder']).is_absolute()):
    sys.exit('Output folder must be an absolute path')
source = Path(args['wallpaper']).resolve(strict=True)
if source.stat().st_size > 128 * 1024 * 1024:
    sys.exit('Wallpaper exceeds the 128 MiB limit')
# On NixOS, resolve the system package or an already installed store copy.
bwrap = shutil.which('bwrap')
if not bwrap:
    bwrap = next((str(p) for p in sorted(Path('/nix/store').glob('*-bubblewrap-*/bin/bwrap')) if p.is_file()), None)
if not bwrap:
    sys.exit('bubblewrap is required for safe wallpaper processing')
python = str(Path(sys.executable).resolve())
worker = Path(__file__).resolve().with_name('render_worker.py')
command = [bwrap, '--unshare-all', '--die-with-parent', '--new-session',
           '--ro-bind', '/nix/store', '/nix/store', '--ro-bind', str(source), '/input',
           '--ro-bind', str(worker), '/worker.py', '--proc', '/proc', '--dev', '/dev',
           '--tmpfs', '/tmp', '--chdir', '/', '--clearenv', '--setenv', 'HOME', '/nonexistent',
           python, '-I', '/worker.py', json.dumps({
               'blur': bool(args.get('blur')), 'radius': args.get('radius', 0),
               'grain': args.get('grain', 0)})]
with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(f'Sandbox failed: {exc}')
    if result.returncode:
        errors.seek(0)
        sys.exit('Sandboxed wallpaper processing failed: ' + errors.read(2048).decode(errors='replace').strip())
    if not 2 <= output.tell() <= 32 * 1024 * 1024:
        sys.exit('Invalid wallpaper output size')
    output.seek(0)
    payload = output.read()
    if not payload.startswith(b'\xff\xd8'):
        sys.exit('Invalid wallpaper output format')
if args['enabled']:
    atomic(Path(args['folder']) / 'noctalia-wallpaper.jpg', payload)
if auto:
    if not profile.is_dir():
        sys.exit('Helium Default profile missing')
    if background.exists() and (not marker.exists() or digest(background) != marker.read_text().strip()):
        atomic(backup, background.read_bytes())
    atomic(background, payload)
    atomic(marker, hashlib.sha256(payload).hexdigest().encode())
atomic(data / 'current.json', (json.dumps({'color': color, 'auto_wallpaper': auto}) + '\n').encode())
