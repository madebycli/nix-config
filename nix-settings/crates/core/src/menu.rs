use crate::SystemSnapshot;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    Argv { program: String, args: Vec<String> },
    None,
}

#[derive(Clone, Debug)]
pub struct MenuItem {
    pub name: String,
    pub description: String,
    pub command: Command,
    pub confirm: bool,
}

impl MenuItem {
    fn action(name: &str, description: &str, argv: &[&str], confirm: bool) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            confirm,
            command: Command::Argv {
                program: argv[0].into(),
                args: argv[1..].iter().map(|s| s.to_string()).collect(),
            },
        }
    }
    pub fn info(name: impl Into<String>, description: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            command: Command::None,
            confirm: false,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Category {
    pub name: &'static str,
    pub items: Vec<MenuItem>,
}

pub fn categories(s: &SystemSnapshot) -> Vec<Category> {
    use MenuItem as Item;
    let repo = s.repo.to_string_lossy();
    vec![
        Category { name: "Overview", items: vec![
            Item::info(format!("Host: {}", s.host), "Configured local host from nx"),
            Item::info(format!("Generation: {}", s.generation.map(|g| g.to_string()).unwrap_or_else(|| "unknown".into())), "Running system generation"),
            Item::info(format!("Git: {} · {} ({} changed files)", s.branch, s.commit, s.dirty_files), "Local lock changes are expected; updates need no Git identity or login"),
            Item::info(format!("Features: {}", s.features.join(", ")), "Enabled feature modules"),
            Item::action("Refresh status", "Read local status without network access", &["nx", "status"], false),
        ]},
        Category { name: "Configure", items: vec![
            Item::action("Feature switches", "Space toggles features in nixctl. Gaming includes Eden. Edits hosts/<host>/features.nix, then offers build/apply.", &["nixctl"], false),
            Item::action("Desktop and shell", "Select compositors and shell through nixctl; Caelestia requires Hyprland alone", &["nixctl", "desktop"], false),
            Item::action("Kernel", "Select the standard Nixpkgs kernel or opt into CachyOS", &["nixctl", "kernel"], false),
            Item::action("Show settings", "Read the same features.nix used by nixctl and NixOS", &["nixctl", "list"], false),
            Item::action("Build only", "Validate the edited configuration without activation", &["nx", "switch", "--build"], false),
            Item::action("Apply settings", "Build first, show closure changes, then ask before activation", &["nx", "switch"], true),
        ]},
        Category { name: "Updates", items: vec![
            Item::action("Check updates", "Query upstream revisions without changing the lock", &["nx", "check"], false),
            Item::action("Pull configuration", "Fast-forward code while preserving and reconciling the local lock", &["nx", "pull"], true),
            Item::action("Update everything", "Refresh all inputs, build and confirm activation; no commit or push", &["nx", "update"], true),
            Item::action("Update base", "Update Nixpkgs and kernel inputs", &["nx", "update", "base"], true),
            Item::action("Update desktop", "Update desktop inputs including the Noctalia shell", &["nx", "update", "desktop"], true),
            Item::action("Update apps", "Update application inputs", &["nx", "update", "apps"], true),
        ]},
        Category { name: "Packages", items: vec![
            Item::action("Installed profile packages", "Separate user packages; not system inputs", &["nix", "profile", "list"], false),
            Item::action("Upgrade profile packages", "Upgrade only the separate user profile", &["nix", "profile", "upgrade", "--all", "--refresh"], true),
        ]},
        Category { name: "Config Sync", items: vec![
            Item::action("Status", "Read managed dotfile links and pending changes", &["dots", "status"], false),
            Item::action("Synchronize", "Commit, fetch, reconcile and push through dots; review local changes first", &["dots", "sync"], true),
            Item::action("Pull dotfiles", "Fetch and apply managed configuration changes", &["dots", "pull"], true),
            Item::action("Push dotfiles", "Explicitly commit and push local managed configuration", &["dots", "push"], true),
            Item::action("Automatic sync on", "Enable the existing dots timer", &["dots", "on"], true),
            Item::action("Automatic sync off", "Disable the existing dots timer", &["dots", "off"], true),
        ]},
        Category { name: "Generations", items: vec![
            Item::action("List generations", "Inspect running and retained system generations", &["nx", "gen", "list"], false),
            Item::action("Last two generations", "Read the newest retained generations", &["nx", "gen", "list", "--last", "2"], false),
            Item::action("Rollback", "Use the guarded nx rollback flow", &["nx", "rollback"], true),
        ]},
        Category { name: "Maintenance", items: vec![
            Item::action("Cleanup preview", "Show what keeping five rollback generations would remove", &["nx", "clean", "5", "--dry-run"], false),
            Item::action("Cleanup", "Use nx generation protection, preview and confirmation", &["nx", "clean", "5"], true),
            Item::action("Optimize store", "Deduplicate without deleting generations", &["nx", "optimise"], true),
        ]},
        Category { name: "Diagnostics", items: vec![
            Item::action("Flake check", "Evaluate the configured checkout without rewriting the lock", &["nix", "flake", "check", "--no-write-lock-file", &repo], false),
            Item::action("Settings diff", "Read local changes to the authoritative host settings", &["git", "-C", &repo, "--no-pager", "diff", "--", &format!("hosts/{}/features.nix", s.host)], false),
            Item::action("System status", "Read installed nx status", &["nx", "status"], false),
        ]},
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> SystemSnapshot {
        crate::parse_snapshot(r#"{"host":"nyx","repo":"/home/me/a ' $(touch INJECTED)","branch":"main","dirty_files":0,"generation":1}"#).unwrap()
    }
    #[test]
    fn configured_path_is_one_argument_and_never_shell_text() {
        let s = state();
        let menus = categories(&s);
        let check = &menus.last().unwrap().items[0];
        assert_eq!(
            check.command,
            Command::Argv {
                program: "nix".into(),
                args: vec![
                    "flake".into(),
                    "check".into(),
                    "--no-write-lock-file".into(),
                    s.repo.to_string_lossy().into_owned()
                ]
            }
        );
    }
    #[test]
    fn writes_use_current_guarded_commands_and_no_forced_confirmation_or_git_publish() {
        for menu in categories(&state()) {
            for item in menu.items {
                if let Command::Argv { program, args } = item.command {
                    assert!(![
                        "sh",
                        "bash",
                        "sudo",
                        "config-update",
                        "config-sync",
                        "nix-refresh",
                        "nix-clean"
                    ]
                    .contains(&program.as_str()));
                    assert!(!args
                        .iter()
                        .any(|a| ["--yes", "--commit", "--push"].contains(&a.as_str())));
                }
            }
        }
    }
    #[test]
    fn mutating_updates_need_confirmation_and_reads_do_not() {
        let menus = categories(&state());
        let updates = menus.iter().find(|m| m.name == "Updates").unwrap();
        assert!(!updates.items[0].confirm);
        assert!(updates.items[1..].iter().all(|i| i.confirm));
    }
}
