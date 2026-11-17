#!/usr/bin/env python3
"""Иконка в трее для лампы On air: включить/выключить и снять автоматику.

Трей не подключается к розетке: он пишет намерение в control.json и читает
plug_state.json, который обновляет исполнитель (plug_executor.py). Поэтому
соединение с устройством остаётся одно (розетка держит один слот), а секреты
и сетевой протокол трею не нужны.

Каждое действие — ручное изменение состояния (L2): клик и есть подтверждение,
режим пишется в plug.log с источником `tray`.

Запуск: scripts/meetings/.venv/Scripts/pythonw.exe tray_plug.py
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFilter

import plug_control as pc

SCRIPT_DIR = Path(__file__).resolve().parent
ICONS_DIR = SCRIPT_DIR / 'icons'
REPO_ROOT = SCRIPT_DIR.parent.parent
PACKAGE_ROOT = REPO_ROOT.parent
CONFIG_PATH = REPO_ROOT / 'secrets' / 'tuya_plug.json'
TRAY_LOG = REPO_ROOT / 'data' / 'work' / 'meetings' / 'tray.log'
PLUG_LOG = REPO_ROOT / 'data' / 'work' / 'meetings' / 'plug.log'
MUTEX_NAME = 'Local\\LegacyPlugTray'
POLL_SECONDS = 2.0
STATUS_STALE_SECONDS = 30

DEADLINE_ITEMS = (
    ('на 1 час', '1h'),
    ('на 2 часа', '2h'),
    ('до конца дня', 'eod'),
    ('до ручного возврата', 'manual'),
)

_state: dict = {'control': None, 'status': None, 'mode': pc.MODE_AUTO,
                'until': None, 'alive': False, 'kind': None, 'theme': None}
_icon: pystray.Icon | None = None


def log(message: str) -> None:
    try:
        TRAY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TRAY_LOG.open('a', encoding='utf-8') as fh:
            fh.write(f'{pc.now_stamp()}  {message}\n')
    except OSError:
        pass


def acquire_single_instance() -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _asset(kind: str) -> Image.Image | None:
    """Готовая иконка из app\\scripts\\meetings\\icons, если она есть."""
    name = {'on': 'lamp-on.png', 'off': 'lamp-off.png'}.get(kind)
    if not name:
        return None
    path = ICONS_DIR / name
    try:
        with Image.open(path) as source:
            img = source.convert('RGBA')
    except (OSError, ValueError) as exc:
        log(f'icon {path.name} not loaded: {type(exc).__name__}: {exc}')
        return None

    # Исходники нарисованы с большими полями. Обрезаем по содержимому, но
    # оставляем свечению воздух, и выравниваем в квадрат: иначе Windows
    # растянет неквадратную картинку и лампа перекосится.
    bounds = img.getchannel('A').point(
        lambda value: 255 if value >= 8 else 0).getbbox()
    if bounds:
        img = img.crop(bounds)
        side = round(max(img.size) * 1.06)
        padded = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        padded.alpha_composite(
            img, ((side - img.width) // 2, (side - img.height) // 2))
        img = padded

    return img.resize((64, 64), getattr(Image, 'Resampling', Image).LANCZOS)


def _draw_lamp(kind: str) -> Image.Image:
    """Запасная отрисовка, если файлов иконок нет.

    Рисунок задан в сетке 64×64 и растеризуется с четырёхкратным запасом:
    Windows берёт из иконки 16 и 32 px, и без сглаживания края рвутся.
    """
    scale = 4
    px = 64 * scale
    img = Image.new('RGBA', (px, px), (0, 0, 0, 0))

    def box(*values: float) -> tuple[int, ...]:
        return tuple(round(value * scale) for value in values)

    on = kind == 'on'

    if on:
        # Мягкое свечение вокруг колбы — только у включённой лампы.
        glow = Image.new('RGBA', (px, px), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(box(17, 19, 47, 47),
                                     fill=(255, 205, 95, 95))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * scale)))

    draw = ImageDraw.Draw(img)

    arc = (255, 253, 246, 255) if on else (74, 81, 91, 255)
    for radius, top in ((14.5, 7.5), (10.0, 15.0)):
        draw.arc(box(32 - radius, top, 32 + radius, top + 2 * radius),
                 start=200, end=340, fill=arc, width=round(3.4 * scale))

    if on:
        body, edge = (252, 204, 92, 255), (224, 166, 45, 255)
        shine = (255, 231, 150, 255)
    else:
        body, edge = (176, 184, 195, 255), (128, 137, 149, 255)
        shine = (211, 217, 225, 255)

    base = (54, 60, 68, 255) if on else (58, 64, 72, 255)
    inset = (72, 79, 89, 255) if on else (74, 80, 90, 255)

    # Цоколь рисуется первым: колба и шейка перекрывают его верх.
    draw.rounded_rectangle(box(25.0, 45.5, 39.0, 55.5), radius=2 * scale,
                           fill=base)
    draw.rounded_rectangle(box(27.5, 48.5, 36.5, 54.0), radius=1.2 * scale,
                           fill=inset)
    draw.rounded_rectangle(box(29.0, 54.0, 35.0, 56.5), radius=1 * scale,
                           fill=base)

    draw.polygon(box(24.0, 42, 40.0, 42, 37, 47, 27, 47), fill=body)
    draw.ellipse(box(18, 18, 46, 46), fill=body, outline=edge,
                 width=round(1.4 * scale))
    draw.ellipse(box(23.5, 23.5, 40.5, 40.5), fill=shine)
    draw.ellipse(box(26.0, 26.0, 31.0, 31.0), fill=(255, 250, 232, 235))

    return img.resize((64, 64), getattr(Image, 'Resampling', Image).LANCZOS)


def system_theme() -> str:
    """Тема оформления Windows: 'light' или 'dark'."""
    try:
        import winreg
        path = (r'Software\Microsoft\Windows\CurrentVersion'
                r'\Themes\Personalize')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'light' if value else 'dark'
    except (OSError, ImportError):
        return 'light'


def _lift_darks(img: Image.Image) -> Image.Image:
    """Поднимает тёмные детали для тёмной темы.

    Цоколь и контур нарисованы почти чёрными: на тёмной панели задач они
    сливаются с фоном. Подъём тем сильнее, чем темнее пиксель, поэтому светлые
    части (колба, корпус) не меняются, а оттенок сохраняется.
    """
    pixels = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            top = max(r, g, b)
            if top >= 140:
                continue
            lift = round(220 * (1 - top / 140) ** 2)
            if top == 0:
                pixels[x, y] = (120, 120, 120, a)
                continue
            scale = (top + lift) / top
            pixels[x, y] = (min(255, round(r * scale)),
                            min(255, round(g * scale)),
                            min(255, round(b * scale)), a)
    return img


def make_image(kind: str, theme: str = 'light') -> Image.Image:
    """Иконка трея для состояния лампы.

    `on` и `off` берутся из файлов `icons\\lamp-on.png` и `icons\\lamp-off.png`;
    если файла нет, рисуется запасной вариант. `paused` — та же выключенная
    лампа с паузой, `unknown` — полупрозрачная, когда исполнитель не отвечает.
    На тёмной теме тёмный цоколь поднимается по яркости.
    """
    if kind in ('on', 'off'):
        img = _asset(kind) or _draw_lamp(kind)
    else:
        img = (_asset('off') or _draw_lamp('off')).copy()
        if kind == 'paused':
            draw = ImageDraw.Draw(img)
            for left in (26.5, 33.5):
                draw.rounded_rectangle((left, 25.5, left + 3.0, 40.0),
                                       radius=1, fill=(35, 40, 48, 255))
        else:  # unknown: нет данных от исполнителя
            img.putalpha(
                img.getchannel('A').point(lambda value: value * 60 // 100))

    if theme == 'dark':
        img = _lift_darks(img)
    return img


def status_age(status: dict | None) -> float | None:
    if not status:
        return None
    stamp = pc.parse_stamp(status.get('updated'))
    if stamp is None:
        return None
    return (datetime.now() - stamp).total_seconds()


def is_unconfigured() -> bool:
    if not CONFIG_PATH.exists():
        return True
    status = _state['status']
    return status is not None and status.get('configured') is False


def lamp_text(item=None) -> str:
    status = _state['status']
    if is_unconfigured():
        return 'Лампа: розетка не настроена — «Настроить розетку…»'
    age = status_age(status)
    if status is None:
        return 'Лампа: нет данных (исполнитель не запущен)'
    if age is None or age > STATUS_STALE_SECONDS:
        return f'Лампа: ? — исполнитель не отвечает (статус от {status.get("updated") or "?"})'
    actual = status.get('actual')
    word = {True: 'включена', False: 'выключена'}.get(actual, 'состояние неизвестно')
    checked = (status.get('checked') or '')[11:19]
    return f'Лампа: {word}' + (f' · проверено {checked}' if checked else '')


def mode_text(item=None) -> str:
    return 'Режим: ' + pc.describe(_state['mode'], _state['until'])


def error_text() -> str | None:
    status = _state['status'] or {}
    error = status.get('error')
    if not error:
        return None
    return f'Ошибка устройства: {error}'[:120]


def refresh() -> None:
    control = pc.read_control()
    status = pc.read_status()
    mode, until, _ = pc.resolve(control)
    age = status_age(status)
    alive = age is not None and age <= STATUS_STALE_SECONDS

    kind = 'unknown'
    if status is not None and alive:
        if mode == pc.MODE_PAUSED:
            kind = 'paused'
        elif status.get('actual') is True:
            kind = 'on'
        elif status.get('actual') is False:
            kind = 'off'

    theme = system_theme()
    changed = kind != _state['kind'] or theme != _state.get('theme')
    _state.update(control=control, status=status, mode=mode, until=until,
                  alive=alive, kind=kind, theme=theme)
    if _icon is None:
        return
    if changed:
        _icon.icon = make_image(kind, theme)
    if is_unconfigured():
        title_word = 'розетка не настроена'
    else:
        title_word = {'on': 'включена', 'off': 'выключена',
                      'paused': 'автоматика снята'}.get(kind, 'нет данных')
    _icon.title = ('Лампа On air: ' + title_word + ' · ' + pc.describe(mode, until))[:120]
    _icon.update_menu()


def act(mode: str, spec: str = pc.DEFAULT_DEADLINE) -> None:
    try:
        pc.apply_mode(mode, spec, pc.SOURCE_TRAY)
    except (OSError, ValueError) as exc:
        log(f'action failed: {mode}/{spec}: {exc}')
        if _icon is not None:
            _icon.notify(f'Не удалось записать режим: {exc}', 'Лампа On air')
    refresh()


def open_log() -> None:
    try:
        import os
        os.startfile(str(PLUG_LOG))
    except OSError as exc:
        log(f'cannot open {PLUG_LOG}: {exc}')
        if _icon is not None:
            _icon.notify(f'Не удалось открыть журнал: {exc}', 'Лампа On air')


def open_setup() -> None:
    """Открывает мастер настройки из папки установки (или packaging в dev-копии)."""
    candidates = (PACKAGE_ROOT / 'setup.cmd', PACKAGE_ROOT / 'packaging' / 'setup.cmd')
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        if _icon is not None:
            _icon.notify('Не найден setup.cmd — переустановите OnAir Lamp.', 'Лампа On air')
        return
    try:
        import os
        os.startfile(str(path))
    except OSError as exc:
        log(f'cannot open {path}: {exc}')
        if _icon is not None:
            _icon.notify(f'Не удалось открыть настройку: {exc}', 'Лампа On air')


def first_run_prompt() -> None:
    """Первый запуск без настроек: предложить сразу пройти мастер.

    Диалог показывается в отдельном потоке, чтобы иконка в трее появилась
    независимо от ответа. Отказ ничего не блокирует: трей продолжает работать
    и пункт «Настроить розетку…» остаётся в меню.
    """
    answer = ctypes.windll.user32.MessageBoxW(
        None,
        'Розетка ещё не настроена, поэтому лампа пока не будет реагировать '
        'на встречи.\n\n'
        'Открыть мастер настройки? Для него нужны Access ID и Access Secret '
        'из Tuya IoT Platform (шаги 3.1–3.4 инструкции).\n\n'
        'Настроить можно и позже: значок лампы в трее → «Настроить розетку…».',
        'OnAir Lamp',
        0x00000004 | 0x00000020 | 0x00010000,  # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND
    )
    log(f'first run: setup prompt answered {answer}')
    if answer == 6:  # IDYES
        open_setup()


def stop_all() -> None:
    """Останавливает наблюдателя и исполнителя перед выходом из трея.

    «Выход» означает полное выключение лампы, а не только закрытие иконки:
    иначе исполнитель продолжал бы управлять розеткой без видимого интерфейса.
    """
    candidates = (PACKAGE_ROOT / 'stop.ps1', PACKAGE_ROOT / 'packaging' / 'stop.ps1')
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        log('stop.ps1 not found: watcher and executor may keep running')
        return
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / \
        'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    try:
        subprocess.run(
            [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', str(path)],
            timeout=20, check=False, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        log('exit requested: watcher and executor stopped')
    except (OSError, subprocess.SubprocessError) as exc:
        log(f'cannot stop watcher and executor: {type(exc).__name__}: {exc}')


def quit_app() -> None:
    stop_all()
    if _icon is not None:
        _icon.stop()


def _deadline_item(text: str, mode: str, spec: str) -> pystray.MenuItem:
    """Один пункт подменю: обработчик с сигнатурой (icon, item), как ждёт pystray."""
    def handler(icon, item):
        act(mode, spec)
    return pystray.MenuItem(text, handler)


def _deadline_submenu(mode: str) -> pystray.Menu:
    """Подменю «на 1 час / на 2 часа / до конца дня / до ручного возврата»."""
    return pystray.Menu(*(_deadline_item(text, mode, spec) for text, spec in DEADLINE_ITEMS))


def build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem(lamp_text, None, enabled=False),
        pystray.MenuItem(mode_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Включить', _deadline_submenu(pc.MODE_ON)),
        pystray.MenuItem('Выключить', _deadline_submenu(pc.MODE_OFF)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Автоматика по встречам', lambda icon, item: act(pc.MODE_AUTO),
                         checked=lambda item: _state['mode'] == pc.MODE_AUTO, radio=True),
        pystray.MenuItem('Снять автоматику', _deadline_submenu(pc.MODE_PAUSED)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: error_text() or '', open_log,
                         visible=lambda item: error_text() is not None, enabled=False),
        pystray.MenuItem('Настроить розетку…', open_setup,
                         visible=lambda item: is_unconfigured()),
        pystray.MenuItem('Открыть plug.log', open_log),
        pystray.MenuItem('Выход', quit_app),
    )


def poll_loop(stop: threading.Event) -> None:
    while not stop.wait(POLL_SECONDS):
        try:
            refresh()
        except Exception as exc:  # трей не должен падать из-за чтения файлов
            log(f'refresh failed: {type(exc).__name__}: {exc}')


def main() -> int:
    global _icon
    if not acquire_single_instance():
        log('tray is already running, second instance is not needed')
        return 0

    refresh()
    _icon = pystray.Icon('legacy-plug',
                         make_image(_state['kind'] or 'unknown',
                                    _state['theme'] or system_theme()),
                         'Лампа On air', build_menu())
    if not CONFIG_PATH.exists():
        threading.Thread(target=first_run_prompt, daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=poll_loop, args=(stop,), daemon=True).start()
    log('tray started')
    try:
        _icon.run()
    finally:
        stop.set()
        log('tray stopped')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        log('tray crashed:\n' + traceback.format_exc())
        raise
