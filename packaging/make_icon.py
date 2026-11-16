#!/usr/bin/env python3
"""Рисует onair.ico тем же мотивом, что и иконка трея.

  python packaging\make_icon.py build\onair.ico
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(size: int = 256) -> Image.Image:
    scale = size / 64.0
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return tuple(round(value * scale) for value in (x0, y0, x1, y1))

    draw.ellipse(box(5, 5, 59, 59), fill=(255, 196, 46, 255),
                 outline=(55, 45, 10, 255), width=max(1, round(3 * scale)))
    draw.ellipse(box(21, 21, 43, 43), fill=(255, 236, 170, 255))
    return img


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'onair.ico')
    out.parent.mkdir(parents=True, exist_ok=True)
    image = make_icon(256)
    image.save(out, format='ICO',
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f'иконка: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
