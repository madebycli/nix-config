//! Fast, native `status` and `updates` reports.
//!
//! Neither report walks `/nix/store`, copies the repository, evaluates the
//! flake or builds anything. `status` only reads a handful of small files and
//! `updates` compares the revisions pinned in `flake.lock` against the remote
//! heads with parallel `git ls-remote` calls.

use crate::{current_host, find_repo};
use anyhow::{Context, Result};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
};

const REMOTE_TIMEOUT_SECS: &str = "20";

fn run(program: &str, args: &[&str], cwd: Option<&Path>) -> Option<String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .env("GIT_TERMINAL_PROMPT", "0")
        .stdin(Stdio::null())
        .stderr(Stdio::null());
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    let result = command.output().ok()?;
    if !result.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&result.stdout).trim().to_string())
}

fn human_bytes(bytes: u64) -> String {
    const UNITS: [&str; 5] = ["B", "KiB", "MiB", "GiB", "TiB"];
    let mut value = bytes as f64;
    let mut unit = 0;
    while value >= 1024.0 && unit < UNITS.len() - 1 {
        value /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{bytes} B")
    } else {
        format!("{value:.1} {}", UNITS[unit])
    }
}

/// `(used, total)` bytes of the filesystem holding `path`, via a single `df`.
fn disk_usage(path: &str) -> Option<(u64, u64)> {
    let out = run("df", &["-B1", "--output=size,used", path], None)?;
    let mut fields = out.lines().nth(1)?.split_whitespace();
    let total = fields.next()?.parse().ok()?;
    let used = fields.next()?.parse().ok()?;
    Some((used, total))
}

/// Generation numbers of the system profile and which one is running.
fn generations() -> (usize, Option<u64>, Option<u64>) {
    let current = fs::canonicalize("/run/current-system").ok();
    let mut numbers = Vec::new();
    let mut active = None;
    if let Ok(entries) = fs::read_dir("/nix/var/nix/profiles") {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            let Some(number) = name
                .strip_prefix("system-")
                .and_then(|n| n.strip_suffix("-link"))
                .and_then(|n| n.parse::<u64>().ok())
            else {
                continue;
            };
            numbers.push(number);
            if let (Some(current), Ok(target)) = (&current, fs::canonicalize(entry.path())) {
                if *current == target {
                    active = Some(number);
                }
            }
        }
    }
    (numbers.len(), active, numbers.into_iter().max())
}

fn age(timestamp: u64) -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = now.saturating_sub(timestamp) / 86_400;
    match days {
        0 => "today".into(),
        1 => "1 day ago".into(),
        n => format!("{n} days ago"),
    }
}

#[derive(Debug, Clone)]
struct LockedInput {
    name: String,
    url: Option<String>,
    reference: Option<String>,
    rev: String,
    last_modified: u64,
}

fn load_lock(repo: &Path) -> Result<Value> {
    let path = repo.join("flake.lock");
    let raw = fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))
}

fn resolve_node(lock: &Value, input: &Value) -> Option<String> {
    match input {
        Value::String(node) => Some(node.clone()),
        Value::Array(path) => {
            // A `follows` path starts at the root node.
            let mut node = lock["root"].as_str()?.to_string();
            for step in path {
                let next = &lock["nodes"][&node]["inputs"][step.as_str()?];
                node = resolve_node(lock, next)?;
            }
            Some(node)
        }
        _ => None,
    }
}

fn locked_inputs(lock: &Value) -> Vec<LockedInput> {
    let Some(root) = lock["nodes"][lock["root"].as_str().unwrap_or("root")]["inputs"].as_object()
    else {
        return Vec::new();
    };
    let mut inputs = Vec::new();
    for (name, value) in root {
        let Some(node) = resolve_node(lock, value) else { continue };
        let locked = &lock["nodes"][&node]["locked"];
        let original = &lock["nodes"][&node]["original"];
        let text = |v: &Value| v.as_str().map(str::to_string);
        let url = match locked["type"].as_str() {
            Some("github") => Some(format!(
                "https://github.com/{}/{}.git",
                locked["owner"].as_str().unwrap_or_default(),
                locked["repo"].as_str().unwrap_or_default()
            )),
            Some("gitlab") => Some(format!(
                "https://gitlab.com/{}/{}.git",
                locked["owner"].as_str().unwrap_or_default(),
                locked["repo"].as_str().unwrap_or_default()
            )),
            Some("git") => text(&locked["url"]),
            _ => None,
        };
        inputs.push(LockedInput {
            name: name.clone(),
            url,
            reference: text(&original["ref"]),
            rev: text(&locked["rev"]).unwrap_or_default(),
            last_modified: locked["lastModified"].as_u64().unwrap_or(0),
        });
    }
    inputs.sort_by(|a, b| a.name.cmp(&b.name));
    inputs
}

fn remote_head(input: &LockedInput) -> Option<String> {
    let url = input.url.as_deref()?;
    let reference = input.reference.as_deref().unwrap_or("HEAD");
    let out = run(
        "timeout",
        &[REMOTE_TIMEOUT_SECS, "git", "ls-remote", url, reference],
        None,
    )?;
    out.lines()
        .next()
        .and_then(|line| line.split_whitespace().next())
        .map(str::to_string)
}

fn short(rev: &str) -> &str {
    &rev[..rev.len().min(10)]
}

pub fn status() -> Result<()> {
    let host = current_host();
    let profile = fs::read_to_string("/etc/nixos-config/profile")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| host.clone());
    let version = fs::read_to_string("/run/current-system/nixos-version")
        .map(|v| v.trim().to_string())
        .ok()
        .or_else(|| run("nixos-version", &[], None))
        .unwrap_or_else(|| "unknown".into());
    let (count, active, latest) = generations();
    let generation = match (active, latest) {
        (Some(a), Some(l)) if a != l => format!("{a} (latest {l}, {count} total)"),
        (Some(a), _) => format!("{a} ({count} total)"),
        _ => format!("unknown ({count} total)"),
    };
    let kernel = run("uname", &["-r"], None).unwrap_or_else(|| "unknown".into());
    let disk = disk_usage("/nix/store")
        .map(|(used, total)| {
            format!(
                "{} / {} ({}% used)",
                human_bytes(used),
                human_bytes(total),
                used * 100 / total.max(1)
            )
        })
        .unwrap_or_else(|| "unknown".into());

    println!("NixOS overview");
    println!("  {:<12} {}", "Host", host);
    println!("  {:<12} {}", "Profile", profile);
    println!("  {:<12} {}", "NixOS", version);
    println!("  {:<12} {}", "Kernel", kernel);
    println!("  {:<12} {}", "Generation", generation);
    println!("  {:<12} {}", "Nix disk", disk);

    match find_repo() {
        Ok(repo) => {
            let branch = run("git", &["branch", "--show-current"], Some(&repo))
                .filter(|b| !b.is_empty())
                .unwrap_or_else(|| "detached".into());
            let commit = run("git", &["rev-parse", "--short", "HEAD"], Some(&repo))
                .unwrap_or_else(|| "unknown".into());
            let dirty = run("git", &["status", "--porcelain"], Some(&repo))
                .map(|s| !s.is_empty())
                .unwrap_or(false);
            // Local-only relation to the last fetched upstream; never touches the network.
            let upstream = run(
                "git",
                &["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
                Some(&repo),
            )
            .and_then(|s| {
                let mut p = s.split_whitespace();
                Some((p.next()?.to_string(), p.next()?.to_string()))
            })
            .map(|(a, b)| format!("ahead {a} · behind {b} (last fetch)"))
            .unwrap_or_else(|| "no upstream".into());
            println!();
            println!("Repository");
            println!("  {:<12} {}", "Path", repo.display());
            println!(
                "  {:<12} {} @ {}{}",
                "Branch",
                branch,
                commit,
                if dirty { " (dirty)" } else { "" }
            );
            println!("  {:<12} {}", "Upstream", upstream);

            if let Ok(lock) = load_lock(&repo) {
                println!();
                println!("Pinned inputs (flake.lock)");
                for input in locked_inputs(&lock) {
                    println!(
                        "  {:<20} {}  {}",
                        input.name,
                        short(&input.rev),
                        age(input.last_modified)
                    );
                }
            }
        }
        Err(error) => {
            println!();
            println!("Repository: {error}");
        }
    }
    Ok(())
}

pub fn updates() -> Result<()> {
    let repo: PathBuf = find_repo()?;
    let lock = load_lock(&repo)?;
    let inputs = locked_inputs(&lock);

    // Query every remote and the repository's own origin concurrently.
    let fetch_repo = repo.clone();
    let fetch = thread::spawn(move || {
        run(
            "timeout",
            &[REMOTE_TIMEOUT_SECS, "git", "fetch", "--quiet", "origin"],
            Some(&fetch_repo),
        )
        .is_some()
    });
    let handles: Vec<_> = inputs
        .iter()
        .cloned()
        .map(|input| {
            thread::spawn(move || {
                let head = remote_head(&input);
                (input, head)
            })
        })
        .collect();

    println!("Flake inputs");
    let mut outdated = 0;
    let mut failed = 0;
    for handle in handles {
        let Ok((input, head)) = handle.join() else { continue };
        let (marker, detail) = match (&input.url, head) {
            (None, _) => ("?", "not checkable (unsupported input type)".to_string()),
            (Some(_), None) => {
                failed += 1;
                ("!", "remote unreachable".to_string())
            }
            (Some(_), Some(head)) if head == input.rev => {
                ("=", format!("{}  up to date", short(&input.rev)))
            }
            (Some(_), Some(head)) => {
                outdated += 1;
                (
                    "↑",
                    format!(
                        "{}  ->  {}  (pinned {})",
                        short(&input.rev),
                        short(&head),
                        age(input.last_modified)
                    ),
                )
            }
        };
        println!("  {marker} {:<20} {detail}", input.name);
    }

    println!();
    println!("Repository");
    if fetch.join().unwrap_or(false) {
        match run(
            "git",
            &["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
            Some(&repo),
        ) {
            Some(counts) => {
                let mut p = counts.split_whitespace();
                println!(
                    "  ahead {} · behind {}",
                    p.next().unwrap_or("?"),
                    p.next().unwrap_or("?")
                );
            }
            None => println!("  no upstream branch configured"),
        }
    } else {
        println!("  fetch failed");
    }

    println!();
    if outdated > 0 {
        println!("{outdated} input(s) can be updated. Choose \"Apply updates\".");
    } else if failed > 0 {
        println!("Could not reach {failed} remote(s); the rest is up to date.");
    } else {
        println!("Everything is up to date.");
    }
    Ok(())
}
