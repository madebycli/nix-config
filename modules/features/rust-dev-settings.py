"""Seed editable VSCodium settings and migrate the former Home Manager symlink."""
import json
import os
from pathlib import Path
import sys
import tempfile


def materialize(target, defaults, store_dir=Path('/nix/store')):
    target = Path(target)
    if not target.is_symlink():
        if target.exists():
            return  # Preserve user JSONC, comments, themes and custom settings verbatim.
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(defaults, output, indent=2)
            output.write('\n')
        return

    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(store_dir):
        return  # Respect writable links managed by the user or dots.
    original = resolved.read_bytes()
    content = original
    try:
        settings = json.loads(original)
        # Only migrate the old module's store-pinned tool paths. Leave all other
        # preferences intact, including Noctalia's selected color theme.
        for key in ('rust-analyzer.server.path', 'rust-analyzer.cargo.sysrootSrc'):
            if isinstance(settings.get(key), str) and settings[key].startswith('/nix/store/'):
                settings[key] = defaults[key]
        content = (json.dumps(settings, indent=2) + '\n').encode()
    except (ValueError, TypeError, AttributeError):
        pass  # Preserve unfamiliar/JSONC content rather than replacing preferences.

    backup = target.with_name(target.name + '.before-rust-dev-writable')
    # Exclusive creation: never overwrite an earlier recovery copy.
    try:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            output.write(original)
    except FileExistsError:
        if backup.read_bytes() != original:
            raise RuntimeError(f'Recovery file already exists with different content: {backup}')

    descriptor, temporary = tempfile.mkstemp(prefix='.rust-dev-settings-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    materialize(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
