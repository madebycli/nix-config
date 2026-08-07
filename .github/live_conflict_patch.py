from pathlib import Path

path = Path("scripts/config-sync.py")
text = path.read_text(encoding="utf-8")

if "def resolve_dotfile_conflicts(" not in text:
    anchor = "\ndef upstream(repo: Path) -> str | None:\n"
    if anchor not in text:
        raise SystemExit("resolve helper anchor missing")
    helper = '''
def resolve_dotfile_conflicts(
    repo: Path,
    changes: ChangeSet,
    *,
    policy: str | None,
    assume_yes: bool,
) -> None:
    """Resolve only already-classified dotfile conflicts after an explicit choice."""
    if not changes.conflicts:
        return
    if policy not in {"local", "repository"}:
        raise SyncError(
            "Dotconfig-Konflikte erkannt. Explizit lokale oder Repository-Version wählen."
        )

    print("\nKonfliktauflösung:")
    for relative in changes.conflicts:
        print(f"  {relative}")

    if policy == "local":
        if not confirm(
            "Lokale Versionen für diese Konflikte übernehmen?",
            assume_yes,
        ):
            raise SyncError("Konfliktauflösung abgebrochen.")
        copy_local_to_mirror(repo, changes.conflicts)
        print("\nLokale Versionen wurden für die ausgewählten Konflikte übernommen.")
        return

    backup_root = state_dir(repo) / "backups" / now_stamp()
    apply_mirror_to_local(
        repo,
        changes.conflicts,
        backup_root,
        assume_yes=assume_yes,
    )
    print(f"\nLokale Konflikt-Backups: {backup_root}")

'''
    text = text.replace(anchor, helper + anchor, 1)

old_push = '''        if changes.conflicts:
            raise SyncError("Dotconfig-Konflikte erkannt. Keine Datei wurde überschrieben.")
        if changes.remote:
            raise SyncError("Repository-Dotconfigs sind neuer. Zuerst pull oder sync ausführen.")
        copy_local_to_mirror(repo, changes.local)
'''
new_push = '''        if changes.remote:
            raise SyncError("Repository-Dotconfigs sind neuer. Zuerst pull oder sync ausführen.")
        if changes.conflicts:
            policy = getattr(args, "conflict_policy", None)
            if policy not in {None, "local"}:
                raise SyncError("Upload kann Konflikte nur explizit mit lokalen Versionen auflösen.")
            resolve_dotfile_conflicts(
                repo,
                changes,
                policy=policy,
                assume_yes=args.yes,
            )
            active, mirror, baseline = manifests(repo)
            changes = classify(active, mirror, baseline)
            if changes.conflicts:
                raise SyncError("Konflikte blieben nach lokaler Auflösung bestehen.")
        copy_local_to_mirror(repo, changes.local)
'''
if old_push in text:
    text = text.replace(old_push, new_push, 1)
elif "Upload kann Konflikte nur explizit mit lokalen Versionen auflösen." not in text:
    raise SystemExit("push conflict block missing")

old_pull = '''        if changes.conflicts:
            raise SyncError("Lokale und entfernte Dotconfigs wurden gleichzeitig geändert.")
        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
'''
new_pull = '''        if changes.conflicts:
            policy = getattr(args, "conflict_policy", None)
            if policy not in {None, "repository"}:
                raise SyncError("Download kann Konflikte nur explizit mit Repository-Versionen auflösen.")
            resolve_dotfile_conflicts(
                repo,
                changes,
                policy=policy,
                assume_yes=args.yes,
            )
            active, mirror, baseline = manifests(repo)
            changes = classify(active, mirror, baseline)
            if changes.conflicts:
                raise SyncError("Konflikte blieben nach Repository-Auflösung bestehen.")
        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
'''
if old_pull in text:
    text = text.replace(old_pull, new_pull, 1)
elif "Download kann Konflikte nur explizit mit Repository-Versionen auflösen." not in text:
    raise SystemExit("pull conflict block missing")

old_sync = '''        if changes.conflicts:
            raise SyncError("Konflikte erkannt. Keine automatische Gewinnerwahl nach Datum.")

        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
        copy_local_to_mirror(repo, changes.local)
'''
new_sync = '''        if changes.conflicts:
            resolve_dotfile_conflicts(
                repo,
                changes,
                policy=getattr(args, "conflict_policy", None),
                assume_yes=args.yes,
            )
            active, mirror, baseline = manifests(repo)
            changes = classify(active, mirror, baseline)
            if changes.conflicts:
                raise SyncError("Konflikte blieben nach expliziter Auflösung bestehen.")

        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
        copy_local_to_mirror(repo, changes.local)
'''
if old_sync in text:
    text = text.replace(old_sync, new_sync, 1)
elif "Konflikte blieben nach expliziter Auflösung bestehen." not in text:
    raise SystemExit("sync conflict block missing")

if "push.add_argument(\"--conflict-policy\"" not in text:
    push_parser = '''    push.add_argument("--message", "-m")
    push.add_argument("--no-commit", action="store_true")
'''
    push_repl = '''    push.add_argument("--message", "-m")
    push.add_argument("--no-commit", action="store_true")
    push.add_argument("--conflict-policy", choices=("local", "repository"))
'''
    if push_parser not in text:
        raise SystemExit("push parser block missing")
    text = text.replace(push_parser, push_repl, 1)

if "pull.add_argument(\"--conflict-policy\"" not in text:
    pull_parser = '''    pull = commands.add_parser("pull", help="Fast-Forward-Pull und sichere Übernahme")
    pull.add_argument("--no-apply", action="store_true", help="Kein NixOS-Build/Switch")
'''
    pull_repl = '''    pull = commands.add_parser("pull", help="Fast-Forward-Pull und sichere Übernahme")
    pull.add_argument("--no-apply", action="store_true", help="Kein NixOS-Build/Switch")
    pull.add_argument("--conflict-policy", choices=("local", "repository"))
'''
    if pull_parser not in text:
        raise SystemExit("pull parser block missing")
    text = text.replace(pull_parser, pull_repl, 1)

if "sync.add_argument(\"--conflict-policy\"" not in text:
    sync_parser = '''    sync.add_argument("--message", "-m")
    sync.add_argument("--no-commit", action="store_true")
    sync.add_argument("--no-apply", action="store_true")
'''
    sync_repl = '''    sync.add_argument("--message", "-m")
    sync.add_argument("--no-commit", action="store_true")
    sync.add_argument("--no-apply", action="store_true")
    sync.add_argument("--conflict-policy", choices=("local", "repository"))
'''
    if sync_parser not in text:
        raise SystemExit("sync parser block missing")
    text = text.replace(sync_parser, sync_repl, 1)

path.write_text(text, encoding="utf-8")

tests = Path("tests/test_github_cli_sync.py")
t = tests.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
if "test_dotfiles_upload_conflict_can_explicitly_choose_local" not in t:
    if marker not in t:
        raise SystemExit("test insertion marker missing")
    addition = r'''
    def test_dotfiles_upload_conflict_can_explicitly_choose_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            home = root / "home"
            command("git", "init", str(repo))
            configure_identity(repo)
            (repo / "sync").mkdir(parents=True)
            mirror_dir = repo / "config/home/.config/example"
            mirror_dir.mkdir(parents=True)
            active_dir = home / ".config/example"
            active_dir.mkdir(parents=True)
            (repo / "flake.nix").write_text("initial\n", encoding="utf-8")
            (repo / "sync/paths.conf").write_text(".config/example\n", encoding="utf-8")
            (repo / "sync/excludes.conf").write_text("**/*.tmp\n", encoding="utf-8")
            active_file = active_dir / "settings.conf"
            mirror_file = mirror_dir / "settings.conf"
            active_file.write_text("base\n", encoding="utf-8")
            mirror_file.write_text("base\n", encoding="utf-8")
            command("git", "add", ".", cwd=repo)
            command("git", "commit", "-m", "initial", cwd=repo)

            with mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                active, _mirror, _baseline = self.sync.manifests(repo)
                self.sync.save_state(repo, active, "test")
                active_file.write_text("local wins\n", encoding="utf-8")
                mirror_file.write_text("repository changed\n", encoding="utf-8")
                args = argparse.Namespace(
                    repo=str(repo),
                    offline=True,
                    scope="dotfiles",
                    message=None,
                    no_commit=False,
                    profile=None,
                    yes=True,
                    conflict_policy="local",
                )
                with mock.patch.object(self.sync, "ensure_remote"):
                    self.sync.command_push(args)
                active_after, mirror_after, baseline_after = self.sync.manifests(repo)

            self.assertEqual(mirror_file.read_text(encoding="utf-8"), "local wins\n")
            self.assertEqual(active_after, mirror_after)
            self.assertEqual(active_after, baseline_after)
            self.assertEqual(command("git", "status", "--porcelain", cwd=repo), "")

    def test_dotfiles_upload_conflict_without_choice_remains_blocked(self) -> None:
        changes = self.sync.ChangeSet((), (), (), (".config/example/settings.conf",))
        with self.assertRaises(self.sync.SyncError):
            self.sync.resolve_dotfile_conflicts(
                Path("/tmp/repo"),
                changes,
                policy=None,
                assume_yes=True,
            )
'''
    t = t.replace(marker, "\n" + addition + marker, 1)
    tests.write_text(t, encoding="utf-8")
