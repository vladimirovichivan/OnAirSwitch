#!/usr/bin/env python3
"""Вырезает чёрный фон из иконок трея, сохраняя полупрозрачность свечения.

Иконки нарисованы на чёрном фоне без альфа-канала. Просто «сделать чёрный
прозрачным» нельзя: у выключенной лампы цоколь и дуги сами почти чёрные, а у
включённой вокруг колбы есть мягкое свечение, которое должно остаться
полупрозрачным.

Поэтому альфа считается из двух масок:

1. Свечение — по яркости: пиксель темнее `--black` считается фоном, ярче —
   получает альфу пропорционально яркости. Цвет при этом делится на альфу
   (обратное умножение), иначе подсвеченный край останется тускло-коричневым.
2. Корпус — по порогу `--solid` с дилатацией и размытием: детали темнее порога
   (цоколь, дуги, контур) остаются полностью непрозрачными, иначе на тёмной
   панели задач они растворялись бы.

Запуск:
    python packaging/key_icon.py app/scripts/meetings/icons/lamp-on.png
    python packaging/key_icon.py icons\\*.png --black 6 --solid 46
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


def key_black(
    image: Image.Image,
    black: int = 6,
    solid: int = 46,
    dilate: int = 7,
    blur: float = 1.6,
    denoise: float = 1.2,
) -> Image.Image:
    """Возвращает RGBA-копию без чёрного фона."""
    r, g, b = image.convert('RGB').split()
    lum = ImageChops.lighter(ImageChops.lighter(r, g), b)

    # Свечение: сглаживаем, чтобы шум сжатия не превращался в искры, и
    # растягиваем яркость в альфу от --black до белого.
    glow = lum.filter(ImageFilter.GaussianBlur(denoise))
    span = max(1, 255 - black)
    alpha_glow = glow.point(
        lambda value: 0 if value <= black
        else min(255, round((value - black) * 255 / span)))

    # Корпус: тёмные, но структурные пиксели. Дилатация захватывает контур,
    # размытие смягчает границу между корпусом и свечением.
    size = dilate if dilate % 2 else dilate + 1
    alpha_solid = lum.point(lambda value: 255 if value >= solid else 0)
    alpha_solid = alpha_solid.filter(ImageFilter.MaxFilter(size))
    alpha_solid = alpha_solid.filter(ImageFilter.GaussianBlur(blur))

    alpha = ImageChops.lighter(alpha_glow, alpha_solid)

    # Обратное умножение: цвет делится на альфу, поэтому свечение остаётся
    # ярко-жёлтым, а не тусклым. Где альфа мала, множитель ограничен — иначе
    # шум фона вылезал бы белыми точками.
    multiplier = alpha.point(
        lambda value: 255 if value == 0 else min(255, round(255 * 255 / value)))
    color = Image.merge('RGB', [ImageChops.multiply(channel, multiplier)
                                for channel in (r, g, b)])
    return Image.merge('RGBA', (*color.split(), alpha))


def _has_transparency(image: Image.Image) -> bool:
    """Похоже ли, что чёрный фон уже вырезан."""
    if image.mode not in ('RGBA', 'LA', 'PA') and 'transparency' not in image.info:
        return False
    alpha = image.convert('RGBA').getchannel('A')
    total = alpha.width * alpha.height
    transparent = sum(count for value, count in alpha.getcolors() or ()
                      if value < 250)
    return transparent > total * 0.01


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Убрать чёрный фон с иконки, сохранив свечение.')
    parser.add_argument('images', nargs='+', type=Path,
                        help='PNG-файлы; результат пишется поверх них')
    parser.add_argument('--black', type=int, default=6,
                        help='яркость, ниже которой пиксель считается фоном')
    parser.add_argument('--solid', type=int, default=46,
                        help='яркость, с которой пиксель считается корпусом')
    parser.add_argument('--dilate', type=int, default=7,
                        help='расширение маски корпуса, пикселей')
    parser.add_argument('--blur', type=float, default=1.6,
                        help='смягчение границы маски корпуса')
    parser.add_argument('--out', type=Path,
                        help='куда сохранить (по умолчанию поверх исходника)')
    parser.add_argument('--force', action='store_true',
                        help='обработать даже файл, где прозрачность уже есть')
    args = parser.parse_args()

    if args.out and len(args.images) > 1:
        parser.error('--out допустим только для одного файла')

    for path in args.images:
        with Image.open(path) as source:
            if not args.force and _has_transparency(source):
                print(f'{path.name}: уже с прозрачностью — пропускаю '
                      f'(--force, чтобы обработать заново)')
                continue
            result = key_black(source, args.black, args.solid,
                               args.dilate, args.blur)
        target = args.out or path
        target.parent.mkdir(parents=True, exist_ok=True)
        result.save(target, 'PNG', optimize=True)
        print(f'{path.name} -> {target} ' +
              f'({result.size[0]}x{result.size[1]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
