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
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

import plug_control as pc

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PACKAGE_ROOT = REPO_ROOT.parent
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
                'until': None, 'alive': False, 'kind': None}
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


def make_image(kind: str) -> Image.Image:
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if kind == 'on':
        draw.ellipse((6, 6, 58, 58), fill=(255, 196, 46, 255), outline=(55, 45, 10, 255), width=3)
        draw.ellipse((22, 22, 42, 42), fill=(255, 236, 170, 255))
    elif kind == 'off':
        draw.ellipse((6, 6, 58, 58), outline=(140, 140, 140, 255), width=5)
    elif kind == 'paused':
        draw.ellipse((6, 6, 58, 58), fill=(108, 120, 140, 255), outline=(30, 34, 40, 255), width=3)
        draw.rectangle((20, 28, 44, 36), fill=(245, 245, 245, 235))
    else:  # unknown / состояние неизвестно
        draw.ellipse((6, 6, 58, 58), fill=(120, 120, 120, 255))
        draw.ellipse((26, 22, 38, 34), fill=(245, 245, 245, 235))
        draw.rectangle((29, 40, 35, 47), fill=(245, 245, 245, 235))
    return img


def status_age(status: dict | None) -> float | None:
    if not status:
        return None
    stamp = pc.parse_stamp(status.get('updated'))
    if stamp is None:
        return None
    return (datetime.now() - stamp).total_seconds()


def is_unconfigured() -> bool:
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

    changed = kind != _state['kind']
    _state.update(control=control, status=status, mode=mode, until=until,
                  alive=alive, kind=kind)
    if _icon is None:
        return
    if changed:
        _icon.icon = make_image(kind)
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


def quit_app() -> None:
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
    _icon = pystray.Icon('legacy-plug', make_image(_state['kind'] or 'unknown'),
                         'Лампа On air', build_menu())
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
