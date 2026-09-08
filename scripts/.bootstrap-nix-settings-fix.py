#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
state = root / "nix-settings/crates/tui/src/state.rs"
text = state.read_text()
text = text.replace("    float::Float,\n", "    float::{Float, FloatContent},\n", 1)
text = text.replace("    layout::{Constraint, Direction, Layout, Rect},\n", "    layout::{Constraint, Layout, Rect},\n", 1)
old = '''        let name = self\n            .visible_items()\n            .get(self.item_state.selected().unwrap_or(0))\n            .map(|i| i.name.as_str())\n            .unwrap_or("Apply selected action");\n        self.confirm = Some(Float::new(\n            Box::new(ConfirmPrompt::new(&[name])),\n'''
new = '''        let visible = self.visible_items();\n        let name = visible\n            .get(self.item_state.selected().unwrap_or(0))\n            .map(|i| i.name.as_str())\n            .unwrap_or("Apply selected action");\n        self.confirm = Some(Float::new(\n            Box::new(ConfirmPrompt::new(&[name])),\n'''
if old not in text:
    raise SystemExit("confirmation lifetime anchor missing")
text = text.replace(old, new, 1)
text = text.replace("Paragraph::new(lines).block(", "Paragraph::new(lines.into_vec()).block(", 1)
state.write_text(text)

core = root / "nix-settings/crates/core/src/lib.rs"
core_text = core.read_text().replace("    let host = &snapshot.host;\n", "", 1)
core.write_text(core_text)
