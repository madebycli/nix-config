use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
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
    pub fn command(
        name: impl Into<String>,
        description: impl Into<String>,
        raw: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            command: Command::Raw(raw.into()),
        }
    }

    pub fn info(name: impl Into<String>, description: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            command: Command::None,
        }
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
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    let result = command.output().ok()?;
    if !result.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&result.stdout).trim().to_string())
}

pub fn find_repo() -> Result<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(value) = env::var("NIXOS_CONFIG_REPO") {
        candidates.push(PathBuf::from(value));
    }
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
    output("hostname", &["-s"], None)
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

pub fn snapshot() -> Result<SystemSnapshot> {
    let repo = find_repo()?;
    let host = current_host();
    let profile = fs::read_to_string("/etc/nixos-config/profile")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| host.clone());
    let branch = output("git", &["branch", "--show-current"], Some(&repo))
        .unwrap_or_else(|| "detached".into());
    let commit = output("git", &["rev-parse", "--short", "HEAD"], Some(&repo))
        .unwrap_or_else(|| "unknown".into());
    let dirty = ProcessCommand::new("git")
        .args(["diff", "--quiet"])
        .current_dir(&repo)
        .status()
        .map(|s| !s.success())
        .unwrap_or(false);
    let generation = fs::read_link("/nix/var/nix/profiles/system")
        .ok()
        .and_then(|p| p.file_name().map(|s| s.to_string_lossy().to_string()))
        .unwrap_or_else(|| "unknown".into());
    let nixos_version = output("nixos-version", &[], None).unwrap_or_else(|| "unknown".into());
    Ok(SystemSnapshot {
        host,
        profile,
        branch,
        commit,
        dirty,
        generation,
        nixos_version,
        repo,
    })
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
    #[serde(default)]
    pub gaming: bool,
    #[serde(default)]
    pub office: bool,
    #[serde(default)]
    pub development: bool,
    #[serde(default)]
    pub multimedia: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Browser {
    #[serde(default = "default_browser")]
    pub default: String,
}
impl Default for Browser {
    fn default() -> Self {
        Self {
            default: default_browser(),
        }
    }
}
fn default_browser() -> String {
    "none".into()
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Integrations {
    #[serde(default)]
    pub filen: FilenIntegration,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FilenIntegration {
    #[serde(default)]
    pub enable: bool,
    #[serde(default = "default_filen_client")]
    pub client: String,
    #[serde(default)]
    pub autostart: bool,
}
impl Default for FilenIntegration {
    fn default() -> Self {
        Self {
            enable: false,
            client: default_filen_client(),
            autostart: false,
        }
    }
}
fn default_filen_client() -> String {
    "desktop".into()
}

impl DesiredState {
    pub fn load(repo: &Path, host: &str) -> Result<Self> {
        let path = repo.join("state").join(format!("{host}.json"));
        let raw = fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
        let state: Self =
            serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
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
        if self.desktops.is_empty() {
            bail!("at least one compositor must be enabled");
        }
        for desktop in &self.desktops {
            if !matches!(desktop.as_str(), "mango" | "niri" | "hyprland") {
                bail!("unknown compositor: {desktop}");
            }
        }
        if !self.desktops.contains(&self.default_session) {
            bail!("defaultSession must be enabled");
        }
        if !matches!(self.shell.as_str(), "noctalia" | "caelestia") {
            bail!("unknown shell: {}", self.shell);
        }
        if self.shell == "caelestia" && self.desktops != ["hyprland"] {
            bail!("Caelestia requires the Hyprland-only configuration");
        }
        if !matches!(
            self.browser.default.as_str(),
            "none" | "firefox" | "brave" | "librewolf"
        ) {
            bail!("unsupported browser");
        }
        if !matches!(self.integrations.filen.client.as_str(), "desktop" | "cli") {
            bail!("unsupported Filen client");
        }
        Ok(())
    }

    pub fn toggle_desktop(&mut self, desktop: &str) -> Result<()> {
        if let Some(index) = self.desktops.iter().position(|d| d == desktop) {
            if self.desktops.len() == 1 {
                bail!("at least one compositor must remain enabled");
            }
            self.desktops.remove(index);
            if self.default_session == desktop {
                self.default_session = self.desktops[0].clone();
            }
        } else {
            self.desktops.push(desktop.to_string());
        }
        self.desktops.sort_by_key(|d| match d.as_str() {
            "mango" => 0,
            "niri" => 1,
            "hyprland" => 2,
            _ => 9,
        });
        if self.shell == "caelestia" && self.desktops != ["hyprland"] {
            self.shell = "noctalia".into();
        }
        self.validate()
    }
}

pub fn categories(snapshot: &SystemSnapshot) -> Vec<Category> {
    let repo = snapshot.repo.display();
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
    Command::Raw(format!(
        "cd {} && sudo nixos-rebuild switch --flake .#{}",
        snapshot.repo.display(),
        snapshot.host
    ))
}
