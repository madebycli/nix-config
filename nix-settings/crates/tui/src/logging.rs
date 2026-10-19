use std::{
    env, fs,
    io::{Error, ErrorKind, Result, Write},
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub fn save(buffer: &[u8]) -> Result<String> {
    let base = match env::var_os("XDG_STATE_HOME") {
        Some(path) => PathBuf::from(path),
        None => PathBuf::from(
            env::var_os("HOME").ok_or_else(|| Error::new(ErrorKind::NotFound, "HOME is unset"))?,
        )
        .join(".local/state"),
    };
    let path = write(&base.join("nix-settings/logs"), buffer)?;
    Ok(path.to_string_lossy().into_owned())
}

fn write(directory: &Path, buffer: &[u8]) -> Result<PathBuf> {
    fs::create_dir_all(directory)?;
    fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let path = directory.join(format!("{}-{nonce}.log", std::process::id()));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    file.write_all(buffer)?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn logs_are_private_and_do_not_overwrite_existing_files() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = env::temp_dir().join(format!(
            "nix-settings-log-test-{}-{stamp}",
            std::process::id()
        ));
        let first = write(&dir, b"first output").unwrap();
        let second = write(&dir, b"second output").unwrap();
        assert_ne!(first, second);
        assert_eq!(fs::read(&first).unwrap(), b"first output");
        assert_eq!(
            fs::metadata(&first).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(
            fs::metadata(&dir).unwrap().permissions().mode() & 0o777,
            0o700
        );
        fs::remove_dir_all(dir).unwrap();
    }
}
