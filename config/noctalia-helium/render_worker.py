#!/usr/bin/env python3
"""Decode and render one image inside the bubblewrap sandbox."""
import json
import resource
import sys
import warnings

resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))

from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = 60_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)
settings = json.loads(sys.argv[1])
with Image.open('/input') as image:
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((3840, 2160), Image.Resampling.LANCZOS)
    if settings['blur']:
        image = image.filter(ImageFilter.GaussianBlur(max(0, min(50, int(settings['radius'])))))
    grain = max(0, min(40, int(settings['grain'])))
    if grain:
        noise = Image.effect_noise(image.size, grain).convert('L')
        image = Image.blend(image, Image.merge('RGB', (noise, noise, noise)), grain / 100)
    image.save(sys.stdout.buffer, 'JPEG', quality=94, subsampling=0)
