#!/usr/bin/env python3
from pathlib import Path

source_path = Path("scripts/.profile-hypr-sync-migration-v3.py")
source = source_path.read_text()
source = source.replace("replacement = r'''", 'replacement = r"""', 1)
marker = "\n'''\n\npatched = source[:start] + replacement + source[end:]"
if marker not in source:
    raise SystemExit("v3 replacement end marker not found")
source = source.replace(
    marker,
    '\n"""\n\npatched = source[:start] + replacement + source[end:]',
    1,
)
compile(source, str(source_path), "exec")
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
