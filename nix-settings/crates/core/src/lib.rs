//! Nix Settings uses the installed nx/nixctl/dots contracts, never a second state file.
mod menu;
mod snapshot;

pub use menu::{categories, Category, Command, MenuItem};
pub use snapshot::{align_config_env, parse_snapshot, snapshot, SystemSnapshot};

pub fn status_json() -> anyhow::Result<String> {
    Ok(serde_json::to_string_pretty(&snapshot()?)?)
}
