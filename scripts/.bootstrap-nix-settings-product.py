#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "nix-settings"
UPSTREAM_COMMIT = "0b0f7449e79275a7ad5cd1c0dee48c6d71f1f7f1"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"expected anchor missing: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Licensing + exact Linutil TUI source snapshot
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    checkout = Path(tmp) / "linutil"
    run("git", "clone", "--quiet", "https://github.com/ChrisTitusTech/linutil.git", str(checkout))
    run("git", "checkout", "--quiet", UPSTREAM_COMMIT, cwd=checkout)

    vendor = PRODUCT / "vendor" / "linutil-tui"
    if vendor.exists():
        shutil.rmtree(vendor)
    vendor.mkdir(parents=True)
    shutil.copytree(checkout / "tui" / "src", vendor / "src")
    shutil.copytree(checkout / "tui" / "assets", vendor / "assets")
    shutil.copy2(checkout / "tui" / "Cargo.toml", vendor / "Cargo.toml")
    shutil.copy2(checkout / "tui" / "cool_tips.txt", vendor / "cool_tips.txt")
    shutil.copy2(checkout / "LICENSE", vendor / "LICENSE")
    write(
        vendor / "UPSTREAM.md",
        f"""# Linutil TUI upstream snapshot

Source: https://github.com/ChrisTitusTech/linutil
Commit: `{UPSTREAM_COMMIT}`
License: MIT
Copyright: Copyright (c) 2025 Chris Titus

`src/`, `assets/`, `Cargo.toml`, and `cool_tips.txt` are copied from the
upstream TUI at the commit above. They are intentionally kept as an exact
reference snapshot. Nix Settings directly compiles selected upstream modules
(theme, hints, floating-window primitives, confirmation prompt, and system
information) and keeps adapted derivative files separate under `crates/tui`.
""",
    )

write(
    ROOT / "LICENSE",
    """MIT License

Copyright (c) 2026 madebycli

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
""",
)

write(
    ROOT / "THIRD_PARTY_NOTICES.md",
    f"""# Third-party notices

## Linutil TUI

Parts of the Nix Settings terminal user interface are based directly on and
compile selected source modules from Chris Titus Tech's Linutil project.
An exact source snapshot is stored in `nix-settings/vendor/linutil-tui` at
upstream commit `{UPSTREAM_COMMIT}`.

Linutil is licensed under the MIT License:

Copyright (c) 2025 Chris Titus

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
""",
)

# ---------------------------------------------------------------------------
# Rust workspace
# ---------------------------------------------------------------------------
write(
    PRODUCT / "Cargo.toml",
    """[workspace]
members = ["crates/core", "crates/tui"]
default-members = ["crates/core", "crates/tui"]
resolver = "2"

[workspace.package]
version = "0.1.0"
edition = "2021"
license = "MIT"

[profile.release]
opt-level = "z"
lto = true
codegen-units = 1
strip = true
""",
)

write(
    PRODUCT / "crates/core/Cargo.toml",
    """[package]
name = "nix-settings-core"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
anyhow = "1.0"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
""",
)

write(
    PRODUCT / "crates/core/src/lib.rs",
    r'''use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    env,
    fs,
    path::{Path, PathBuf},
    process::Command as ProcessCommand,
};

#[derive(Clone, Debug)]
pub enum Command {
    Raw(String),
    LocalFile {
        executable: String,
        args: Vec<String>,
        file: PathBuf,
    },
    None,
}

#[derive(Clone, Debug)]
pub struct MenuItem {
    pub name: String,
    pub description: String,
    pub command: Command,
}

impl MenuItem {
    pub fn command(name: impl Into<String>, description: impl Into<String>, raw: impl Into<String>) -> Self {
        Self { name: name.into(), description: description.into(), command: Command::Raw(raw.into()) }
    }

    pub fn info(name: impl Into<String>, description: impl Into<String>) -> Self {
        Self { name: name.into(), description: description.into(), command: Command::None }
    }
}

#[derive(Clone, Debug)]
pub struct Category {
    pub name: &'static str,
    pub items: Vec<MenuItem>,
}

#[derive(Clone, Debug, Serialize)]
pub struct SystemSnapshot {
    pub host: String,
    pub profile: String,
    pub branch: String,
    pub commit: String,
    pub dirty: bool,
    pub generation: String,
    pub nixos_version: String,
    pub repo: PathBuf,
}

fn output(program: &str, args: &[&str], cwd: Option<&Path>) -> Option<String> {
    let mut command = ProcessCommand::new(program);
    command.args(args);
    if let Some(cwd) = cwd { command.current_dir(cwd); }
    let result = command.output().ok()?;
    if !result.status.success() { return None; }
    Some(String::from_utf8_lossy(&result.stdout).trim().to_string())
}

pub fn find_repo() -> Result<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(value) = env::var("NIXOS_CONFIG_REPO") { candidates.push(PathBuf::from(value)); }
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd.clone());
        candidates.extend(cwd.ancestors().skip(1).map(PathBuf::from));
    }
    if let Some(home) = env::var_os("HOME").map(PathBuf::from) {
        candidates.push(home.join("nyx"));
        candidates.push(home.join("aether"));
    }
    for candidate in candidates {
        if candidate.join(".git").is_dir() && candidate.join("flake.nix").is_file() {
            return Ok(candidate.canonicalize().unwrap_or(candidate));
        }
    }
    bail!("NixOS configuration repository not found")
}

pub fn current_host() -> String {
    output("hostname", &["-s"], None).filter(|s| !s.is_empty()).unwrap_or_else(|| "unknown".into())
}

pub fn snapshot() -> Result<SystemSnapshot> {
    let repo = find_repo()?;
    let host = current_host();
    let profile = fs::read_to_string("/etc/nixos-config/profile")
        .ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).unwrap_or_else(|| host.clone());
    let branch = output("git", &["branch", "--show-current"], Some(&repo)).unwrap_or_else(|| "detached".into());
    let commit = output("git", &["rev-parse", "--short", "HEAD"], Some(&repo)).unwrap_or_else(|| "unknown".into());
    let dirty = ProcessCommand::new("git").args(["diff", "--quiet"]).current_dir(&repo).status().map(|s| !s.success()).unwrap_or(false);
    let generation = fs::read_link("/nix/var/nix/profiles/system")
        .ok().and_then(|p| p.file_name().map(|s| s.to_string_lossy().to_string()))
        .unwrap_or_else(|| "unknown".into());
    let nixos_version = output("nixos-version", &[], None).unwrap_or_else(|| "unknown".into());
    Ok(SystemSnapshot { host, profile, branch, commit, dirty, generation, nixos_version, repo })
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DesiredState {
    pub schema: u32,
    pub desktops: Vec<String>,
    pub default_session: String,
    pub shell: String,
    #[serde(default)]
    pub bundles: Bundles,
    #[serde(default)]
    pub browser: Browser,
    #[serde(default)]
    pub integrations: Integrations,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Bundles {
    #[serde(default)] pub gaming: bool,
    #[serde(default)] pub office: bool,
    #[serde(default)] pub development: bool,
    #[serde(default)] pub multimedia: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Browser {
    #[serde(default = "default_browser")] pub default: String,
}
impl Default for Browser { fn default() -> Self { Self { default: default_browser() } } }
fn default_browser() -> String { "none".into() }

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Integrations {
    #[serde(default)] pub filen: FilenIntegration,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FilenIntegration {
    #[serde(default)] pub enable: bool,
    #[serde(default = "default_filen_client")] pub client: String,
    #[serde(default)] pub autostart: bool,
}
impl Default for FilenIntegration {
    fn default() -> Self { Self { enable: false, client: default_filen_client(), autostart: false } }
}
fn default_filen_client() -> String { "desktop".into() }

impl DesiredState {
    pub fn load(repo: &Path, host: &str) -> Result<Self> {
        let path = repo.join("state").join(format!("{host}.json"));
        let raw = fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
        let state: Self = serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
        state.validate()?;
        Ok(state)
    }

    pub fn save(&self, repo: &Path, host: &str) -> Result<()> {
        self.validate()?;
        let path = repo.join("state").join(format!("{host}.json"));
        let raw = serde_json::to_string_pretty(self)? + "\n";
        fs::write(&path, raw).with_context(|| format!("write {}", path.display()))
    }

    pub fn validate(&self) -> Result<()> {
        if self.desktops.is_empty() { bail!("at least one compositor must be enabled"); }
        for desktop in &self.desktops {
            if !matches!(desktop.as_str(), "mango" | "niri" | "hyprland") { bail!("unknown compositor: {desktop}"); }
        }
        if !self.desktops.contains(&self.default_session) { bail!("defaultSession must be enabled"); }
        if !matches!(self.shell.as_str(), "noctalia" | "caelestia") { bail!("unknown shell: {}", self.shell); }
        if self.shell == "caelestia" && self.desktops != ["hyprland"] { bail!("Caelestia requires the Hyprland-only configuration"); }
        if !matches!(self.browser.default.as_str(), "none" | "firefox" | "brave" | "librewolf") { bail!("unsupported browser"); }
        if !matches!(self.integrations.filen.client.as_str(), "desktop" | "cli") { bail!("unsupported Filen client"); }
        Ok(())
    }

    pub fn toggle_desktop(&mut self, desktop: &str) -> Result<()> {
        if let Some(index) = self.desktops.iter().position(|d| d == desktop) {
            if self.desktops.len() == 1 { bail!("at least one compositor must remain enabled"); }
            self.desktops.remove(index);
            if self.default_session == desktop { self.default_session = self.desktops[0].clone(); }
        } else {
            self.desktops.push(desktop.to_string());
        }
        self.desktops.sort_by_key(|d| match d.as_str() { "mango" => 0, "niri" => 1, "hyprland" => 2, _ => 9 });
        if self.shell == "caelestia" && self.desktops != ["hyprland"] { self.shell = "noctalia".into(); }
        self.validate()
    }
}

pub fn categories(snapshot: &SystemSnapshot) -> Vec<Category> {
    let repo = snapshot.repo.display();
    let host = &snapshot.host;
    vec![
        Category { name: "Overview", items: vec![
            MenuItem::info(format!("Host: {}", snapshot.host), "Current host"),
            MenuItem::info(format!("NixOS: {}", snapshot.nixos_version), "Current NixOS version"),
            MenuItem::info(format!("Generation: {}", snapshot.generation), "Active system generation"),
            MenuItem::info(format!("Git: {}{}", snapshot.commit, if snapshot.dirty { " (dirty)" } else { "" }), "Current nix-config commit"),
        ]},
        Category { name: "Configure", items: vec![
            MenuItem::info("System configuration", "Use Space/Enter in this page to change the desired state. Save & Apply writes state/<host>.json and rebuilds the host."),
        ]},
        Category { name: "Updates", items: vec![
            MenuItem::command("Check updates", "Preview Flake input and profile updates", format!("cd {repo} && nix-updates")),
            MenuItem::command("Apply updates", "Refresh Flake inputs, build, switch, commit, and publish", format!("cd {repo} && nix-refresh")),
        ]},
        Category { name: "Packages", items: vec![
            MenuItem::command("Installed profile packages", "Show packages installed through nix profile", "nix profile list"),
            MenuItem::command("Upgrade profile packages", "Upgrade every package installed in the user Nix profile", "nix profile upgrade --all --refresh"),
        ]},
        Category { name: "Config Sync", items: vec![
            MenuItem::command("Synchronize", "Safe two-way synchronization of managed dotconfigs", format!("cd {repo} && config-sync sync")),
            MenuItem::command("Status", "Show local/repository dotconfig differences", format!("cd {repo} && config-sync status")),
            MenuItem::command("Pull", "Pull repository config changes into HOME", format!("cd {repo} && config-sync pull")),
            MenuItem::command("Push", "Push local config changes into the repository", format!("cd {repo} && config-sync push")),
        ]},
        Category { name: "Integrations", items: vec![
            MenuItem::info("Filen", "Install Filen Desktop or Filen CLI from nixpkgs. Desktop can be started automatically as a graphical-session user service."),
        ]},
        Category { name: "Generations", items: vec![
            MenuItem::command("List generations", "List NixOS system generations", "sudo nix-env --list-generations -p /nix/var/nix/profiles/system"),
            MenuItem::command("Rollback", "Switch to the previous NixOS generation", "sudo nixos-rebuild switch --rollback"),
        ]},
        Category { name: "Maintenance", items: vec![
            MenuItem::command("Garbage collect", "Delete unreachable Nix store paths", "sudo nix store gc"),
            MenuItem::command("Optimize store", "Deduplicate identical Nix store files", "sudo nix-store --optimise"),
        ]},
        Category { name: "Diagnostics", items: vec![
            MenuItem::command("Flake check", "Evaluate the current repository without rewriting the lock file", format!("cd {repo} && nix flake check --no-write-lock-file")),
            MenuItem::command("Sync doctor", "Validate repository, sync state, Git history, and secret filters", format!("cd {repo} && config-sync doctor")),
            MenuItem::command("System status", "Show Nix Settings system status", format!("cd {repo} && nix-status")),
        ]},
    ]
}

pub fn apply_command(snapshot: &SystemSnapshot) -> Command {
    Command::Raw(format!("cd {} && sudo nixos-rebuild switch --flake .#{}", snapshot.repo.display(), snapshot.host))
}
''',
)

write(
    PRODUCT / "crates/tui/Cargo.toml",
    """[package]
name = "nix-settings-tui"
version.workspace = true
edition.workspace = true
license.workspace = true

[[bin]]
name = "nix-settings"
path = "src/main.rs"

[dependencies]
anyhow = "1.0"
clap = { version = "4.6.1", features = ["derive"] }
nix-settings-core = { path = "../core" }
oneshot = { version = "0.2.1", features = ["std"], default-features = false }
portable-pty = "0.9.0"
ratatui = { version = "0.30.0", features = ["crossterm"], default-features = false }
time = { version = "0.3.47", features = ["formatting", "local-offset", "macros"], default-features = false }
tui-term = { version = "0.3.4", default-features = false }
vt100-ctt = "0.17.1"
""",
)

# Adapt Linutil's PTY runner with only the core import and log filename changed.
running = (PRODUCT / "vendor/linutil-tui/src/running_command.rs").read_text(encoding="utf-8")
running = running.replace("use linutil_core::Command;", "use nix_settings_core::Command;")
running = running.replace("linutil_log_", "nix_settings_log_")
write(PRODUCT / "crates/tui/src/running_command.rs", running)

write(
    PRODUCT / "crates/tui/src/main.rs",
    r'''#[path = "../../../vendor/linutil-tui/src/theme.rs"]
mod theme;
#[path = "../../../vendor/linutil-tui/src/hint.rs"]
mod hint;
#[path = "../../../vendor/linutil-tui/src/float.rs"]
mod float;
#[path = "../../../vendor/linutil-tui/src/confirmation.rs"]
mod confirmation;
#[path = "../../../vendor/linutil-tui/src/system_info.rs"]
mod system_info;
mod running_command;
mod state;

use clap::Parser;
use ratatui::{
    backend::CrosstermBackend,
    crossterm::{
        event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyEventKind},
        style::ResetColor,
        terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
        ExecutableCommand,
    },
    Terminal,
};
use running_command::TERMINAL_UPDATED;
use state::AppState;
use std::{io::{stdout, Result, Stdout}, sync::atomic::Ordering, time::Duration};
use theme::Theme;

#[derive(Debug, Parser, Clone)]
#[command(name = "nix-settings", version, about = "NixOS configuration and system manager")]
struct Args {
    #[arg(short, long, value_enum, default_value_t = Theme::Default)]
    theme: Theme,
    #[arg(short = 'm', long)]
    mouse: bool,
    #[arg(short = 's', long)]
    size_bypass: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    stdout().execute(EnterAlternateScreen)?;
    if args.mouse { stdout().execute(EnableMouseCapture)?; }
    let mut state = AppState::new(args.theme, args.mouse, args.size_bypass);
    enable_raw_mode()?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout()))?;
    terminal.clear()?;
    let result = run(&mut terminal, &mut state);
    disable_raw_mode()?;
    terminal.backend_mut().execute(LeaveAlternateScreen)?;
    if args.mouse { terminal.backend_mut().execute(DisableMouseCapture)?; }
    terminal.backend_mut().execute(ResetColor)?;
    terminal.show_cursor()?;
    result
}

fn run(terminal: &mut Terminal<CrosstermBackend<Stdout>>, state: &mut AppState) -> Result<()> {
    loop {
        if !event::poll(Duration::from_millis(30))? {
            if TERMINAL_UPDATED.compare_exchange(true, false, Ordering::AcqRel, Ordering::Acquire).is_ok() {
                terminal.draw(|frame| state.draw(frame))?;
            }
            continue;
        }
        match event::read()? {
            Event::Key(key) => {
                if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat { continue; }
                if !state.handle_key(&key) { return Ok(()); }
            }
            Event::Mouse(mouse) if !state.handle_mouse(&mouse) => return Ok(()),
            _ => {}
        }
        terminal.draw(|frame| state.draw(frame))?;
    }
}
''',
)

write(
    PRODUCT / "crates/tui/src/state.rs",
    r'''use crate::{
    confirmation::{ConfirmPrompt, ConfirmStatus},
    float::Float,
    hint::{create_shortcut_list, Shortcut},
    running_command::RunningCommand,
    shortcuts,
    system_info::SystemInfo,
    theme::Theme,
};
use nix_settings_core::{apply_command, categories, Command, DesiredState, MenuItem, SystemSnapshot};
use ratatui::{
    crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseEvent},
    layout::{Constraint, Direction, Layout, Rect},
    prelude::*,
    symbols::border,
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph},
};

const MIN_WIDTH: u16 = 100;
const MIN_HEIGHT: u16 = 25;
const FLOAT_SIZE: u16 = 95;
const CONFIRM_SIZE: u16 = 44;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Focus { Categories, Items, Search, Configure, Floating, Confirmation }

pub struct AppState {
    theme: Theme,
    mouse_enabled: bool,
    size_bypass: bool,
    snapshot: SystemSnapshot,
    categories: Vec<nix_settings_core::Category>,
    category_state: ListState,
    item_state: ListState,
    focus: Focus,
    search: String,
    system_info: Option<SystemInfo>,
    float: Option<Float<RunningCommand>>,
    confirm: Option<Float<ConfirmPrompt>>,
    pending: Option<Command>,
    desired: DesiredState,
    desired_dirty: bool,
}

impl AppState {
    pub fn new(theme: Theme, mouse_enabled: bool, size_bypass: bool) -> Self {
        let snapshot = nix_settings_core::snapshot().unwrap_or_else(|_| SystemSnapshot {
            host: "unknown".into(), profile: "unknown".into(), branch: "unknown".into(), commit: "unknown".into(),
            dirty: false, generation: "unknown".into(), nixos_version: "unknown".into(), repo: std::env::current_dir().unwrap_or_default(),
        });
        let desired = DesiredState::load(&snapshot.repo, &snapshot.host).unwrap_or(DesiredState {
            schema: 1, desktops: vec!["mango".into()], default_session: "mango".into(), shell: "noctalia".into(),
            bundles: Default::default(), browser: Default::default(), integrations: Default::default(),
        });
        let categories = categories(&snapshot);
        Self {
            theme, mouse_enabled, size_bypass, snapshot, categories,
            category_state: ListState::default().with_selected(Some(0)),
            item_state: ListState::default().with_selected(Some(0)),
            focus: Focus::Items, search: String::new(), system_info: SystemInfo::gather(),
            float: None, confirm: None, pending: None, desired, desired_dirty: false,
        }
    }

    fn selected_category(&self) -> usize { self.category_state.selected().unwrap_or(0) }
    fn category_name(&self) -> &str { self.categories.get(self.selected_category()).map(|c| c.name).unwrap_or("Overview") }

    fn configure_items(&self) -> Vec<MenuItem> {
        let enabled = |name: &str| self.desired.desktops.iter().any(|d| d == name);
        vec![
            MenuItem::info(format!("[{}] Mango", if enabled("mango") { "x" } else { " " }), "Toggle Mango compositor"),
            MenuItem::info(format!("[{}] Hyprland", if enabled("hyprland") { "x" } else { " " }), "Toggle Hyprland compositor"),
            MenuItem::info(format!("[{}] Niri", if enabled("niri") { "x" } else { " " }), "Toggle Niri compositor"),
            MenuItem::info(format!("Shell: {}", self.desired.shell), "Cycle Noctalia / Caelestia"),
            MenuItem::info(format!("Default session: {}", self.desired.default_session), "Cycle enabled compositors"),
            MenuItem::info(format!("[{}] Gaming bundle", if self.desired.bundles.gaming { "x" } else { " " }), "Gaming software bundle"),
            MenuItem::info(format!("[{}] Office bundle", if self.desired.bundles.office { "x" } else { " " }), "Office software bundle"),
            MenuItem::info(format!("[{}] Development bundle", if self.desired.bundles.development { "x" } else { " " }), "Development software bundle"),
            MenuItem::info(format!("[{}] Multimedia bundle", if self.desired.bundles.multimedia { "x" } else { " " }), "Multimedia software bundle"),
            MenuItem::info(format!("Browser: {}", self.desired.browser.default), "Cycle none / Firefox / Brave / LibreWolf"),
            MenuItem::info(format!("[{}] Filen", if self.desired.integrations.filen.enable { "x" } else { " " }), "Enable Filen integration"),
            MenuItem::info(format!("Filen client: {}", self.desired.integrations.filen.client), "Cycle Desktop / CLI"),
            MenuItem::info(format!("[{}] Filen autostart", if self.desired.integrations.filen.autostart { "x" } else { " " }), "Start Filen Desktop with the graphical session"),
            MenuItem::info(if self.desired_dirty { "Save & Apply *" } else { "Save & Apply" }, "Write desired state and rebuild the host"),
        ]
    }

    fn visible_items(&self) -> Vec<MenuItem> {
        let mut items = if self.category_name() == "Configure" { self.configure_items() } else {
            self.categories.get(self.selected_category()).map(|c| c.items.clone()).unwrap_or_default()
        };
        if !self.search.is_empty() {
            let needle = self.search.to_ascii_lowercase();
            items.retain(|item| item.name.to_ascii_lowercase().contains(&needle) || item.description.to_ascii_lowercase().contains(&needle));
        }
        items
    }

    fn move_selection(state: &mut ListState, len: usize, delta: isize) {
        if len == 0 { state.select(None); return; }
        let current = state.selected().unwrap_or(0) as isize;
        let next = (current + delta).rem_euclid(len as isize) as usize;
        state.select(Some(next));
    }

    fn activate_configure(&mut self) {
        let index = self.item_state.selected().unwrap_or(0);
        let result = match index {
            0 => self.desired.toggle_desktop("mango"),
            1 => self.desired.toggle_desktop("hyprland"),
            2 => self.desired.toggle_desktop("niri"),
            3 => {
                self.desired.shell = if self.desired.shell == "noctalia" { "caelestia".into() } else { "noctalia".into() };
                if self.desired.shell == "caelestia" { self.desired.desktops = vec!["hyprland".into()]; self.desired.default_session = "hyprland".into(); }
                self.desired.validate()
            }
            4 => {
                if let Some(pos) = self.desired.desktops.iter().position(|d| d == &self.desired.default_session) {
                    self.desired.default_session = self.desired.desktops[(pos + 1) % self.desired.desktops.len()].clone();
                }
                Ok(())
            }
            5 => { self.desired.bundles.gaming = !self.desired.bundles.gaming; Ok(()) }
            6 => { self.desired.bundles.office = !self.desired.bundles.office; Ok(()) }
            7 => { self.desired.bundles.development = !self.desired.bundles.development; Ok(()) }
            8 => { self.desired.bundles.multimedia = !self.desired.bundles.multimedia; Ok(()) }
            9 => {
                self.desired.browser.default = match self.desired.browser.default.as_str() {
                    "none" => "firefox", "firefox" => "brave", "brave" => "librewolf", _ => "none"
                }.into(); Ok(())
            }
            10 => { self.desired.integrations.filen.enable = !self.desired.integrations.filen.enable; Ok(()) }
            11 => { self.desired.integrations.filen.client = if self.desired.integrations.filen.client == "desktop" { "cli".into() } else { "desktop".into() }; Ok(()) }
            12 => { self.desired.integrations.filen.autostart = !self.desired.integrations.filen.autostart; Ok(()) }
            13 => {
                if let Err(error) = self.desired.save(&self.snapshot.repo, &self.snapshot.host) {
                    self.pending = Some(Command::Raw(format!("printf '%s\\n' {}", shell_escape(&format!("Failed to save desired state: {error}")))));
                } else {
                    self.desired_dirty = false;
                    self.pending = Some(apply_command(&self.snapshot));
                }
                self.spawn_confirmation();
                return;
            }
            _ => Ok(()),
        };
        if result.is_ok() { self.desired_dirty = true; }
    }

    fn activate_item(&mut self) {
        if self.category_name() == "Configure" { self.activate_configure(); return; }
        let items = self.visible_items();
        let Some(item) = self.item_state.selected().and_then(|i| items.get(i)) else { return; };
        if !matches!(item.command, Command::None) {
            self.pending = Some(item.command.clone());
            self.spawn_confirmation();
        }
    }

    fn spawn_confirmation(&mut self) {
        if self.pending.is_none() { return; }
        let name = self.visible_items().get(self.item_state.selected().unwrap_or(0)).map(|i| i.name.as_str()).unwrap_or("Apply selected action");
        self.confirm = Some(Float::new(Box::new(ConfirmPrompt::new(&[name])), CONFIRM_SIZE, CONFIRM_SIZE));
        self.focus = Focus::Confirmation;
    }

    fn handle_confirmation(&mut self, key: &KeyEvent) {
        let Some(confirm) = self.confirm.as_mut() else { return; };
        confirm.handle_key_event(key);
        if confirm.content.is_finished() {
            match confirm.content.status {
                ConfirmStatus::Confirm => {
                    self.confirm = None;
                    if let Some(command) = self.pending.take() {
                        self.float = Some(Float::new(Box::new(RunningCommand::new(&[&command])), FLOAT_SIZE, FLOAT_SIZE));
                        self.focus = Focus::Floating;
                    }
                }
                ConfirmStatus::Abort => { self.confirm = None; self.pending = None; self.focus = Focus::Items; }
                ConfirmStatus::None => {}
            }
        }
    }

    pub fn handle_key(&mut self, key: &KeyEvent) -> bool {
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) && self.focus != Focus::Floating { return false; }
        if self.focus == Focus::Floating {
            if let Some(float) = self.float.as_mut() {
                if float.handle_key_event(key) { self.float = None; self.focus = Focus::Items; self.refresh(); }
            }
            return true;
        }
        if self.focus == Focus::Confirmation { self.handle_confirmation(key); return true; }
        if self.focus == Focus::Search {
            match key.code {
                KeyCode::Esc | KeyCode::Enter => self.focus = Focus::Items,
                KeyCode::Backspace => { self.search.pop(); self.item_state.select(Some(0)); }
                KeyCode::Char(c) => { self.search.push(c); self.item_state.select(Some(0)); }
                _ => {}
            }
            return true;
        }
        match key.code {
            KeyCode::Char('q') => return false,
            KeyCode::Char('/') => self.focus = Focus::Search,
            KeyCode::Char('t') => self.theme.next(),
            KeyCode::Char('T') => self.theme.prev(),
            KeyCode::Left | KeyCode::Char('h') => self.focus = Focus::Categories,
            KeyCode::Right | KeyCode::Char('l') if self.focus == Focus::Categories => self.focus = Focus::Items,
            KeyCode::Up | KeyCode::Char('k') => {
                if self.focus == Focus::Categories { Self::move_selection(&mut self.category_state, self.categories.len(), -1); self.item_state.select(Some(0)); }
                else { let len = self.visible_items().len(); Self::move_selection(&mut self.item_state, len, -1); }
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if self.focus == Focus::Categories { Self::move_selection(&mut self.category_state, self.categories.len(), 1); self.item_state.select(Some(0)); }
                else { let len = self.visible_items().len(); Self::move_selection(&mut self.item_state, len, 1); }
            }
            KeyCode::Enter | KeyCode::Char(' ') => {
                if self.focus == Focus::Categories { self.focus = Focus::Items; } else { self.activate_item(); }
            }
            _ => {}
        }
        true
    }

    pub fn handle_mouse(&mut self, event: &MouseEvent) -> bool {
        if !self.mouse_enabled { return true; }
        if self.focus == Focus::Floating { if let Some(float) = self.float.as_mut() { float.handle_mouse_event(event); } }
        if self.focus == Focus::Confirmation { if let Some(confirm) = self.confirm.as_mut() { confirm.handle_mouse_event(event); } }
        true
    }

    fn refresh(&mut self) {
        if let Ok(snapshot) = nix_settings_core::snapshot() { self.snapshot = snapshot; self.categories = categories(&self.snapshot); }
    }

    pub fn draw(&mut self, frame: &mut Frame) {
        let area = frame.area();
        if !self.size_bypass && (area.width < MIN_WIDTH || area.height < MIN_HEIGHT) {
            frame.render_widget(Paragraph::new(format!("Terminal too small. Need at least {MIN_WIDTH}x{MIN_HEIGHT}. Use --size-bypass to override.")).centered(), area);
            return;
        }

        let vertical = Layout::vertical([Constraint::Min(10), Constraint::Length(4)]).split(area);
        let main = Layout::horizontal([Constraint::Length(28), Constraint::Min(40)]).split(vertical[0]);
        self.draw_sidebar(frame, main[0]);
        self.draw_content(frame, main[1]);
        self.draw_hints(frame, vertical[1]);

        if let Some(float) = self.float.as_mut() { float.draw(frame, area, &self.theme); }
        if let Some(confirm) = self.confirm.as_mut() { confirm.draw(frame, area, &self.theme); }
    }

    fn draw_sidebar(&mut self, frame: &mut Frame, area: Rect) {
        let info_height = self.system_info.as_ref().map(|i| i.entries_len() as u16 + 2).unwrap_or(2);
        let chunks = Layout::vertical([Constraint::Length(5), Constraint::Min(8), Constraint::Length(info_height)]).split(area);
        let logo = Paragraph::new(vec![
            Line::styled(" NIX SETTINGS ", Style::default().fg(self.theme.tab_color()).bold()),
            Line::styled(format!(" {} · {}", self.snapshot.host, self.snapshot.commit), Style::default().fg(self.theme.unfocused_color())),
        ]).block(Block::bordered().border_set(border::PLAIN).border_style(Style::default().fg(if self.focus == Focus::Categories { self.theme.focused_color() } else { self.theme.unfocused_color() })));
        frame.render_widget(logo, chunks[0]);

        let rows: Vec<ListItem> = self.categories.iter().map(|c| ListItem::new(format!("> {}", c.name))).collect();
        let block = Block::bordered().title(" NIX SETTINGS ").border_set(border::PLAIN)
            .border_style(Style::default().fg(if self.focus == Focus::Categories { self.theme.focused_color() } else { self.theme.unfocused_color() }));
        let list = List::new(rows).block(block).highlight_style(Style::default().fg(self.theme.tab_color()).bold()).highlight_symbol("> ");
        frame.render_stateful_widget(list, chunks[1], &mut self.category_state);

        let info_block = Block::bordered().title(" SYSTEM ").border_set(border::PLAIN).border_style(Style::default().fg(self.theme.unfocused_color()));
        let inner = info_block.inner(chunks[2]);
        frame.render_widget(info_block, chunks[2]);
        if let Some(info) = &self.system_info { frame.render_widget(Paragraph::new(info.render_lines(&self.theme, inner.width as usize)), inner); }
    }

    fn draw_content(&mut self, frame: &mut Frame, area: Rect) {
        let chunks = Layout::vertical([Constraint::Length(3), Constraint::Min(5)]).split(area);
        let search_style = if self.focus == Focus::Search { self.theme.focused_color() } else { self.theme.unfocused_color() };
        let search = Paragraph::new(if self.search.is_empty() { " / Search".into() } else { format!(" / {}", self.search) })
            .block(Block::bordered().title(" SEARCH ").border_set(border::PLAIN).border_style(Style::default().fg(search_style)));
        frame.render_widget(search, chunks[0]);

        let items = self.visible_items();
        let rows: Vec<ListItem> = items.iter().map(|item| {
            let style = match item.command { Command::None => Style::default().fg(self.theme.dir_color()), _ => Style::default().fg(self.theme.cmd_color()) };
            ListItem::new(Line::styled(item.name.clone(), style))
        }).collect();
        let title = format!(" {} ", self.category_name().to_ascii_uppercase());
        let list = List::new(rows)
            .block(Block::bordered().title(title).border_set(border::PLAIN).border_style(Style::default().fg(if self.focus == Focus::Items { self.theme.focused_color() } else { self.theme.unfocused_color() })))
            .highlight_style(Style::default().fg(self.theme.focused_color()).bold())
            .highlight_symbol("> ");
        frame.render_stateful_widget(list, chunks[1], &mut self.item_state);
    }

    fn draw_hints(&self, frame: &mut Frame, area: Rect) {
        let shortcuts: Box<[Shortcut]> = shortcuts!(
            ("Quit", ["q", "CTRL-c"]), ("Navigate", ["j/k", "Up/Down"]),
            ("Panels", ["h/l", "Left/Right"]), ("Open/Toggle", ["Enter", "Space"]),
            ("Search", ["/"]), ("Theme", ["t", "T"]),
        );
        let lines = create_shortcut_list(shortcuts, area.width.saturating_sub(2));
        frame.render_widget(Paragraph::new(lines).block(Block::new().borders(Borders::TOP).title(" SHORTCUTS ")), area);
    }
}

fn shell_escape(value: &str) -> String { format!("'{}'", value.replace('\'', "'\\''")) }
''',
)

# ---------------------------------------------------------------------------
# Desired-state files and NixOS feature module
# ---------------------------------------------------------------------------
state_dir = ROOT / "state"
state_dir.mkdir(exist_ok=True)
for host, desktops in (("nyx", ["mango", "hyprland"]), ("aether", ["mango"])):
    write(
        state_dir / f"{host}.json",
        json.dumps({
            "schema": 1,
            "desktops": desktops,
            "defaultSession": "mango" if "mango" in desktops else desktops[0],
            "shell": "noctalia",
            "bundles": {"gaming": False, "office": False, "development": False, "multimedia": False},
            "browser": {"default": "none"},
            "integrations": {"filen": {"enable": False, "client": "desktop", "autostart": False}},
        }, indent=2) + "\n",
    )

write(
    ROOT / "modules/nixos/product-features.nix",
    r'''{ lib, pkgs, settings ? { }, ... }:
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
''',
)

# ---------------------------------------------------------------------------
# flake.nix: product package + managed host state (legacy scripts remain only
# as migration/compatibility helpers, while nixosConfigurations becomes 1/host)
# ---------------------------------------------------------------------------
flake_path = ROOT / "flake.nix"
flake = flake_path.read_text(encoding="utf-8")

flake = replace_once(
    flake,
    "        ./modules/nixos/greeter.nix\n        ./modules/flatpak\n",
    "        ./modules/nixos/greeter.nix\n        ./modules/nixos/product-features.nix\n        ./modules/flatpak\n",
    "product module",
)
flake = replace_once(
    flake,
    "          environment.systemPackages = [\n            configSyncProgram\n",
    "          environment.systemPackages = [\n            nixSettingsProgram\n            configSyncProgram\n",
    "system package",
)
flake = replace_once(
    flake,
    "      mkHost = { hostName, desktops, defaultSession, shell }:\n",
    "      mkHost = { hostName, desktops, defaultSession, shell, settings ? { } }:\n",
    "mkHost signature",
)
flake = re.sub(
    r'''          profileName =\n            if shell == "caelestia" then "\$\{hostName\}-hyprland-caelestia"\n            else if desktops == \[ "mango" \] then hostName\n            else if desktops == \[ "mango" "niri" "hyprland" \] then "\$\{hostName\}-all"\n            else "\$\{hostName\}-\$\{builtins\.concatStringsSep "-" desktops\}";''',
    "          profileName = hostName;",
    flake,
    count=1,
)
flake = replace_once(
    flake,
    "              inherit inputs desktops defaultSession hostName shell;\n",
    "              inherit inputs desktops defaultSession hostName shell settings;\n",
    "specialArgs settings",
)

old_mkprofile = '''      mkProfile = hostName: desktops: defaultSession: shell:\n        mkHost { inherit hostName desktops defaultSession shell; };\n\n      configSyncProgram = pkgs.writeShellApplication {\n'''
new_mkprofile = '''      managedState = hostName:\n        builtins.fromJSON (builtins.readFile (./state + "/${hostName}.json"));\n\n      mkManagedProfile = hostName:\n        let selected = managedState hostName;\n        in mkHost {\n          inherit hostName;\n          desktops = selected.desktops;\n          defaultSession = selected.defaultSession;\n          shell = selected.shell;\n          settings = selected;\n        };\n\n      nixSettingsProgram = pkgs.rustPlatform.buildRustPackage {\n        pname = "nix-settings";\n        version = "0.1.0";\n        src = ./nix-settings;\n        cargoLock.lockFile = ./nix-settings/Cargo.lock;\n        nativeBuildInputs = [ pkgs.makeWrapper ];\n        postInstall = ''\n          wrapProgram "$out/bin/nix-settings" \\\n            --prefix PATH : ${nixpkgs.lib.makeBinPath [\n              pkgs.coreutils pkgs.fastfetch pkgs.findutils pkgs.gh pkgs.git pkgs.nix pkgs.sudo\n            ]}\n        '';\n        meta = {\n          description = "Nix Settings system manager and TUI";\n          license = nixpkgs.lib.licenses.mit;\n          mainProgram = "nix-settings";\n        };\n      };\n\n      configSyncProgram = pkgs.writeShellApplication {\n'''
flake = replace_once(flake, old_mkprofile, new_mkprofile, "managed profile + package")

pattern = re.compile(r'''      nixosConfigurations = \{\n.*?\n      \};\n\n      packages\.\$\{system\} = \{''', re.S)
replacement = '''      nixosConfigurations = {\n        nyx = mkManagedProfile "nyx";\n        aether = mkManagedProfile "aether";\n      };\n\n      packages.${system} = {'''
flake, count = pattern.subn(replacement, flake, count=1)
if count != 1:
    raise SystemExit("failed to replace legacy profile matrix")

flake = replace_once(
    flake,
    "      packages.${system} = {\n        install = installProgram;\n",
    "      packages.${system} = {\n        nix-settings = nixSettingsProgram;\n        install = installProgram;\n",
    "package output",
)
flake = replace_once(
    flake,
    "      apps.${system} = {\n        install = { type = \"app\"; program = \"${installProgram}/bin/nixos-config-install\"; };\n",
    "      apps.${system} = {\n        nix-settings = { type = \"app\"; program = \"${nixSettingsProgram}/bin/nix-settings\"; };\n        install = { type = \"app\"; program = \"${installProgram}/bin/nixos-config-install\"; };\n",
    "app output",
)
flake_path.write_text(flake, encoding="utf-8")

# New TUI-focused validation workflow for the feature branch.
write(
    ROOT / ".github/workflows/nix-settings-product-check.yml",
    """name: Nix Settings product check

on:
  push:
    branches:
      - feature/nix-settings-tui
  workflow_dispatch:

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cachix/install-nix-action@v31
        with:
          github_access_token: ${{ secrets.GITHUB_TOKEN }}
      - uses: dtolnay/rust-toolchain@stable
      - name: Rust checks
        run: |
          cd nix-settings
          cargo fmt --check
          cargo check --workspace --locked
      - name: Licensing checks
        run: |
          test -f LICENSE
          test -f THIRD_PARTY_NOTICES.md
          test -f nix-settings/vendor/linutil-tui/LICENSE
          grep -q 'Copyright (c) 2025 Chris Titus' nix-settings/vendor/linutil-tui/LICENSE
      - name: Nix checks
        run: |
          nix flake metadata --no-write-lock-file >/dev/null
          nix eval --no-write-lock-file --raw .#nixosConfigurations.nyx.config.networking.hostName | grep -qx nyx
          nix eval --no-write-lock-file --raw .#nixosConfigurations.aether.config.networking.hostName | grep -qx aether
          test \"$(nix eval --no-write-lock-file --json .#nixosConfigurations.nyx.config.programs.hyprland.enable)\" = true
          nix build --no-link .#nix-settings
""",
)

write(
    ROOT / "docs/NIX-SETTINGS-PRODUCT.md",
    f"""# Nix Settings product architecture

This branch replaces the user-facing collection of maintenance/profile commands
with a product layer named **Nix Settings**.

## TUI provenance

The terminal UI deliberately uses Linutil as its implementation base. An exact
snapshot of Linutil's TUI from `{UPSTREAM_COMMIT}` is kept under
`nix-settings/vendor/linutil-tui`. Selected upstream modules are compiled
directly by Nix Settings. Adapted files are kept separate so upstream copyright
and modifications remain clear. See `THIRD_PARTY_NOTICES.md`.

## Layout

The TUI keeps Linutil's core interaction model: left navigation/system panel,
right search + item list, context shortcuts along the bottom, modal confirmation,
and a real PTY for command output.

Nix Settings pages are product-specific:

- Overview
- Configure
- Updates
- Packages
- Config Sync
- Integrations
- Generations
- Maintenance
- Diagnostics

## Desired state

There is one NixOS configuration per host (`nyx`, `aether`). User choices live
in `state/<host>.json`; the combinatorial desktop profile matrix is not part of
the managed interface anymore. The TUI edits this state and `Save & Apply`
runs a normal `nixos-rebuild switch --flake .#<host>`.

## Integrations

`modules/nixos/product-features.nix` maps desired-state features to NixOS:
software bundles, browser selection, and Filen. Filen Desktop can be installed
and started automatically as a user service; Filen CLI can be installed but is
not blindly autostarted because continuous CLI sync needs explicit sync pairs.

## Migration

The old maintenance/sync executables remain in the branch as compatibility
backends while functionality is moved into the Rust core. The TUI is the normal
interface and does not require users to remember `--scope` or profile names.
""",
)

# Cargo lock + formatting.
run("cargo", "generate-lockfile", cwd=PRODUCT)
run("cargo", "fmt", "--all", cwd=PRODUCT)
print("Nix Settings product bootstrap complete")
