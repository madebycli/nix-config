"""Editable Codium preferences must survive activation and Noctalia theme changes."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / 'modules/features/rust-dev-settings.py'
spec = importlib.util.spec_from_file_location('settings', script)
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'nix/store'
        self.store.mkdir(parents=True)
        self.target = self.root / 'home/.config/VSCodium/User/settings.json'
        self.target.parent.mkdir(parents=True)
        self.defaults = {
            'rust-analyzer.server.path': '/run/current-system/sw/bin/rust-analyzer',
            'rust-analyzer.cargo.sysrootSrc': '/etc/rust-dev/rust-src',
            'rust-analyzer.check.command': 'clippy',
        }

    def seed(self):
        settings.materialize(self.target, self.defaults, self.store)

    def managed(self, contents):
        source = self.store / 'old-vscode-user-settings'
        source.write_bytes(contents)
        source.chmod(0o444)
        self.target.symlink_to(source)

    def test_first_install_creates_editable_defaults(self):
        self.seed()
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(json.loads(self.target.read_text()), self.defaults)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.target.write_text('{"workbench.colorTheme":"NoctaliaTheme"}')
        self.seed()
        self.assertEqual(json.loads(self.target.read_text())['workbench.colorTheme'], 'NoctaliaTheme')

    def test_existing_jsonc_and_theme_are_preserved_byte_for_byte(self):
        original = '// personal settings\n{"workbench.colorTheme": "NoctaliaTheme",}\n'
        self.target.write_text(original)
        self.seed()
        self.assertEqual(self.target.read_text(), original)

    def test_old_store_link_becomes_editable_and_backup_preserves_original(self):
        original = json.dumps({**self.defaults,
            'rust-analyzer.server.path': '/nix/store/old-rust-analyzer/bin/rust-analyzer',
            'rust-analyzer.cargo.sysrootSrc': '/nix/store/old-rust-src/library',
            'workbench.colorTheme': 'NoctaliaTheme', 'editor.fontSize': 17}).encode()
        self.managed(original)
        with self.assertRaises(PermissionError):
            self.target.write_text('cannot write the store')
        self.seed()
        self.assertFalse(self.target.is_symlink())
        value = json.loads(self.target.read_text())
        self.assertEqual(value['editor.fontSize'], 17)
        self.assertEqual(value['workbench.colorTheme'], 'NoctaliaTheme')
        for key in ('rust-analyzer.server.path', 'rust-analyzer.cargo.sysrootSrc'):
            self.assertEqual(value[key], self.defaults[key])
        backup = self.target.with_name(self.target.name + '.before-rust-dev-writable')
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        value['workbench.colorTheme'] = 'Another theme'
        self.target.write_text(json.dumps(value))
        self.seed()
        self.assertEqual(json.loads(self.target.read_text())['workbench.colorTheme'], 'Another theme')
        self.assertEqual(backup.read_bytes(), original)

    def test_custom_link_outside_store_is_preserved(self):
        source = self.root / 'dots-settings.json'
        source.write_text('{"workbench.colorTheme":"NoctaliaTheme"}')
        self.target.symlink_to(source)
        self.seed()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.resolve(), source)

    def test_unfamiliar_store_content_is_copied_without_loss(self):
        original = b'// JSONC\n{"workbench.colorTheme":"NoctaliaTheme",}\n'
        self.managed(original)
        self.seed()
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(self.target.is_symlink())

    def test_existing_different_backup_aborts_without_removing_link(self):
        self.managed(b'{}')
        self.target.with_name(self.target.name + '.before-rust-dev-writable').write_text('earlier backup')
        with self.assertRaises(RuntimeError):
            self.seed()
        self.assertTrue(self.target.is_symlink())


if __name__ == '__main__':
    unittest.main()
