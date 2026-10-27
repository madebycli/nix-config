import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'sync.py'

class ExportTest(unittest.TestCase):
    def test_automatic_wallpaper_and_invalid_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / 'config/net.imput.helium/Default'
            profile.mkdir(parents=True)
            background = profile / 'background.jpg'
            background.write_bytes(b'original wallpaper')
            source = root / 'source.png'
            Image.new('RGB', (64, 48), '#224466').save(source)
            env = dict(os.environ, XDG_DATA_HOME=str(root / 'data'), XDG_CONFIG_HOME=str(root / 'config'))
            args = {'wallpaper': str(source), 'folder': '', 'enabled': False,
                    'auto_wallpaper': True, 'primary': '#f0b3e8',
                    'blur': True, 'radius': 3, 'grain': 5}
            subprocess.run(['python3', str(SCRIPT), json.dumps(args)], check=True, env=env)
            with Image.open(background) as image:
                self.assertEqual(image.format, 'JPEG')
            rendered = background.read_bytes()
            source.write_bytes(b'invalid image')
            failed = subprocess.run(['python3', str(SCRIPT), json.dumps(args)], env=env, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(background.read_bytes(), rendered)
            args['auto_wallpaper'] = False
            subprocess.run(['python3', str(SCRIPT), json.dumps(args)], check=True, env=env)
            self.assertEqual(background.read_bytes(), b'original wallpaper')

    def test_export_and_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.png'
            Image.new('RGB', (80, 60), '#3366aa').save(source)
            folder = root / 'output'
            env = dict(os.environ, XDG_DATA_HOME=str(root / 'data'), XDG_CONFIG_HOME=str(root / 'config'))
            args = {'wallpaper': str(source), 'folder': str(folder), 'enabled': True, 'auto_wallpaper': False, 'primary': '#f0b3e8', 'blur': True, 'radius': 3, 'grain': 0}
            subprocess.run(['python3', str(SCRIPT), json.dumps(args)], check=True, env=env)
            result = folder / 'noctalia-wallpaper.jpg'
            with Image.open(result) as image:
                self.assertEqual(image.size, (80, 60))
                self.assertEqual(image.format, 'JPEG')
            original = result.read_bytes()
            Image.new('RGB', (80, 60), '#aa3333').save(source)
            args['enabled'] = False
            subprocess.run(['python3', str(SCRIPT), json.dumps(args)], check=True, env=env)
            self.assertEqual(result.read_bytes(), original)
            args['enabled'] = True
            subprocess.run(['python3', str(SCRIPT), json.dumps(args)], check=True, env=env)
            self.assertNotEqual(result.read_bytes(), original)

if __name__ == '__main__':
    unittest.main()
