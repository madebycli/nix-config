use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{env, path::PathBuf, process::Command};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SystemSnapshot {
    pub host: String,
    pub repo: PathBuf,
    pub branch: String,
    pub dirty_files: usize,
    pub generation: Option<u64>,
    #[serde(default)]
    pub features: Vec<String>,
    #[serde(default)]
    pub commit: String,
}

pub fn parse_snapshot(text: &str) -> Result<SystemSnapshot> {
    let snapshot: SystemSnapshot = serde_json::from_str(text).context("invalid nx status JSON")?;
    if !matches!(snapshot.host.as_str(), "nyx" | "aether") || !snapshot.repo.is_absolute() {
        bail!("nx status must identify nyx/aether and an absolute repository path");
    }
    Ok(snapshot)
}

/// Called before the frontend starts threads so nx and nixctl use the same file.
pub fn align_config_env() -> Result<()> {
    let nx = env::var_os("NX_CONF");
    let ctl = env::var_os("NIXCTL_CONF");
    match (nx, ctl) {
        (Some(nx), Some(ctl)) => {
            let canonical = |p: std::ffi::OsString| {
                let path = PathBuf::from(p);
                path.canonicalize().unwrap_or(path)
            };
            if canonical(nx) != canonical(ctl) {
                bail!("NX_CONF and NIXCTL_CONF must identify the same file");
            }
        }
        (Some(path), None) => env::set_var("NIXCTL_CONF", path),
        (None, Some(path)) => env::set_var("NX_CONF", path),
        (None, None) => (),
    }
    Ok(())
}

pub fn snapshot() -> Result<SystemSnapshot> {
    let output = Command::new("nx")
        .args(["status", "--json"])
        .output()
        .context("run nx status; install nx and rebuild /etc/nixctl.conf first")?;
    if !output.status.success() {
        bail!(
            "nx status failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    let mut snapshot = parse_snapshot(&String::from_utf8_lossy(&output.stdout))?;
    let output = Command::new("git")
        .arg("-C")
        .arg(&snapshot.repo)
        .args(["rev-parse", "--short", "HEAD"])
        .output()
        .context("read repository revision")?;
    if !output.status.success() {
        bail!("cannot read the configured Git repository");
    }
    snapshot.commit = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    Ok(snapshot)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn custom_paths_and_worktrees_are_not_inferred_from_hostname() {
        let s = parse_snapshot(r#"{"host":"aether","repo":"/home/me/aether worktree","branch":"main","dirty_files":2,"generation":null,"features":["gaming"]}"#).unwrap();
        assert_eq!(s.repo, PathBuf::from("/home/me/aether worktree"));
        assert_eq!(s.features, ["gaming"]);
    }
    #[test]
    fn invalid_backend_state_is_an_error_instead_of_default_settings() {
        for text in [
            "{}",
            "broken",
            r#"{"host":"../nyx","repo":"/a","branch":"main","dirty_files":0,"generation":1}"#,
            r#"{"host":"nyx","repo":"relative","branch":"main","dirty_files":0,"generation":1}"#,
        ] {
            assert!(parse_snapshot(text).is_err());
        }
    }
}
