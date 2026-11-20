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
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import i18n
import plug_control as pc
import updater

SCRIPT_DIR = Path(__file__).resolve().parent
ICONS_DIR = SCRIPT_DIR / 'icons'
REPO_ROOT = SCRIPT_DIR.parent.parent
PACKAGE_ROOT = REPO_ROOT.parent
CONFIG_PATH = REPO_ROOT / 'secrets' / 'tuya_plug.json'
MEETINGS_DIR = REPO_ROOT / 'data' / 'work' / 'meetings'
TRAY_LOG = MEETINGS_DIR / 'tray.log'
PLUG_LOG = MEETINGS_DIR / 'plug.log'
EVENTS_LOG = MEETINGS_DIR / 'events.log'
MEETINGS_STATE = MEETINGS_DIR / 'state.json'
REPORT_SCRIPT = PACKAGE_ROOT / 'tools' / 'report_support.py'
MUTEX_NAME = 'Local\\OnAirLampPlugTray'
POLL_SECONDS = 2.0
STATUS_STALE_SECONDS = 30
# Наблюдатель пишет state.json не реже раза в 10 с; 45 с — с запасом.
MEETINGS_STALE_SECONDS = 45

DEADLINE_ITEMS = (
    ('deadline_1h', '1h'),
    ('deadline_2h', '2h'),
    ('deadline_eod', 'eod'),
    ('deadline_manual', 'manual'),
)

AUTO_CHECK_SECONDS = 20
AUTO_CHECK_INTERVAL = 24 * 60 * 60
UPDATE_CONFIRM_FLAGS = 0x00000004 | 0x00000020 | 0x00010000  # YESNO|QUESTION|SETFOREGROUND

_state: dict = {'control': None, 'status': None, 'meetings': None,
                'mode': pc.MODE_AUTO, 'until': None, 'alive': False,
                'meetings_alive': False, 'meeting': False,
                'meeting_names': [], 'meeting_seconds': None,
                'badge': False, 'kind': None, 'theme': None,
                'update': {'status': 'idle', 'version': '', 'error': ''}}
_update_check: updater.UpdateCheck | None = None
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


def _body_mask(img: Image.Image) -> tuple[Image.Image | None,
                                          tuple[int, int, int, int] | None]:
    """Маска самой крупной связной фигуры и её границы.

    У включённой лампы сверху нарисованы дуги Wi-Fi — отдельные фигуры. В трее
    на 16–24 px они превращаются в бледную дымку, но занимают четверть высоты,
    поэтому в иконку берётся только корпус лампы. Поиск идёт по уменьшенной
    копии альфы: перебирать 1024×1024 пикселей на каждом обновлении слишком
    долго.
    """
    step = 4
    alpha = img.getchannel('A')
    size = (max(1, img.width // step), max(1, img.height // step))
    solid = alpha.resize(size, Image.BOX).point(
        lambda value: 255 if value >= 96 else 0)
    width, height = solid.size
    pixels = solid.load()
    seen = bytearray(width * height)
    best: list[tuple[int, int]] = []

    for y in range(height):
        for x in range(width):
            index = y * width + x
            if seen[index] or not pixels[x, y]:
                continue
            stack = [(x, y)]
            seen[index] = 1
            points = []
            while stack:
                cx, cy = stack.pop()
                points.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy),
                               (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        other = ny * width + nx
                        if not seen[other] and pixels[nx, ny]:
                            seen[other] = 1
                            stack.append((nx, ny))
            if len(points) > len(best):
                best = points

    if not best:
        return None, None

    xs = [point[0] for point in best]
    ys = [point[1] for point in best]
    bounds = (min(xs) * step, min(ys) * step,
              (max(xs) + 1) * step, (max(ys) + 1) * step)
    coarse = Image.new('L', (width, height), 0)
    fill = coarse.load()
    for x, y in best:
        fill[x, y] = 255
    mask = coarse.resize(img.size, getattr(
        Image, 'Resampling', Image).BILINEAR).point(
            lambda value: 255 if value >= 128 else 0)
    return mask, bounds


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

    # В трее остаётся только корпус: дуги и ореол свечения не попадают в кадр.
    # Затем обрезаем по содержимому и выравниваем в квадрат: иначе Windows
    # растянет неквадратную картинку и лампа перекосится.
    mask, bounds = _body_mask(img)
    if mask is not None:
        img.putalpha(ImageChops.multiply(img.getchannel('A'), mask))
        pad = max(2, round(max(bounds[2] - bounds[0],
                               bounds[3] - bounds[1]) * 0.015))
        img = img.crop((max(0, bounds[0] - pad), max(0, bounds[1] - pad),
                        min(img.width, bounds[2] + pad),
                        min(img.height, bounds[3] + pad)))
        side = round(max(img.size) * 1.03)
        padded = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        padded.alpha_composite(
            img, ((side - img.width) // 2, (side - img.height) // 2))
        img = padded

    return img.resize((64, 64), getattr(Image, 'Resampling', Image).LANCZOS)


def _draw_lamp(kind: str) -> Image.Image:
    """Запасная отрисовка, если файлов иконок нет.

    Рисунок задан в сетке 64×64 и растеризуется с четырёхкратным запасом:
    Windows берёт из иконки 16 и 32 px, и без сглаживания края рвутся. Дуги
    Wi-Fi, как и в PNG, не рисуются: лампа должна занимать всю плитку.
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
        ImageDraw.Draw(glow).ellipse(box(8, 4, 56, 52),
                                     fill=(255, 205, 95, 95))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * scale)))

    draw = ImageDraw.Draw(img)

    if on:
        body, edge = (252, 204, 92, 255), (224, 166, 45, 255)
        shine = (255, 231, 150, 255)
    else:
        body, edge = (176, 184, 195, 255), (128, 137, 149, 255)
        shine = (211, 217, 225, 255)

    base = (54, 60, 68, 255) if on else (58, 64, 72, 255)
    inset = (72, 79, 89, 255) if on else (74, 80, 90, 255)

    # Цоколь рисуется первым: колба и шейка перекрывают его верх.
    draw.rounded_rectangle(box(23.0, 47.0, 41.0, 57.5), radius=2 * scale,
                           fill=base)
    draw.rounded_rectangle(box(26.0, 50.0, 38.0, 56.0), radius=1.2 * scale,
                           fill=inset)
    draw.rounded_rectangle(box(28.0, 56.0, 36.0, 59.0), radius=1 * scale,
                           fill=base)

    draw.polygon(box(18.0, 43, 46.0, 43, 42, 48, 22, 48), fill=body)
    draw.ellipse(box(12, 8, 52, 48), fill=body, outline=edge,
                 width=round(1.4 * scale))
    draw.ellipse(box(18, 14, 46, 42), fill=shine)
    draw.ellipse(box(21.0, 17.0, 27.0, 23.0), fill=(255, 250, 232, 235))

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


def make_image(kind: str, theme: str = 'light', badge: bool = False) -> Image.Image:
    """Иконка трея для состояния лампы.

    `on` и `off` берутся из файлов `icons\\lamp-on.png` и `icons\\lamp-off.png`;
    если файла нет, рисуется запасной вариант. `paused` — та же выключенная
    лампа с паузой, `unknown` — полупрозрачная, когда исполнитель не отвечает.
    На тёмной теме тёмный цоколь поднимается по яркости. `badge` — оранжевая
    точка в углу: встреча идёт, а лампа выключена.
    """
    if kind in ('on', 'off'):
        img = _asset(kind) or _draw_lamp(kind)
    else:
        img = (_asset('off') or _draw_lamp('off')).copy()
        if kind == 'paused':
            draw = ImageDraw.Draw(img)
            for left in (24.5, 35.0):
                draw.rounded_rectangle((left, 19.0, left + 4.5, 37.0),
                                       radius=1.5, fill=(35, 40, 48, 255))
        else:  # unknown: нет данных от исполнителя
            img.putalpha(
                img.getchannel('A').point(lambda value: value * 60 // 100))

    if theme == 'dark':
        img = _lift_darks(img)
    if badge:
        draw = ImageDraw.Draw(img)
        ring = (245, 245, 245, 235) if theme == 'dark' else (35, 40, 48, 235)
        draw.ellipse((43, 43, 62, 62), fill=(255, 138, 0, 255),
                     outline=ring, width=3)
    return img


def status_age(status: dict | None) -> float | None:
    if not status:
        return None
    stamp = pc.parse_stamp(status.get('updated'))
    if stamp is None:
        return None
    return (datetime.now() - stamp).total_seconds()


def human_duration(seconds: float, language: str | None = None) -> str:
    """Длительность для меню: «меньше минуты», «42 мин», «1 ч 05 мин»."""
    minutes = int(max(0.0, seconds)) // 60
    if minutes < 1:
        return i18n.translate('less_than_minute', language)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return i18n.translate('duration_hm', language, hours=hours,
                              minutes=minutes)
    if hours:
        return i18n.translate('duration_h', language, hours=hours)
    return i18n.translate('duration_min', language, minutes=minutes)


def remaining_suffix(until: datetime | None,
                     now: datetime | None = None) -> str:
    if until is None:
        return ''
    seconds = (until - (now or datetime.now())).total_seconds()
    if seconds <= 0:
        return ''
    return i18n.t('remaining', duration=human_duration(seconds))


def read_meetings() -> dict | None:
    """state.json наблюдателя; None — файла нет или он битый."""
    try:
        raw = MEETINGS_STATE.read_text(encoding='utf-8-sig')
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def meetings_age(state: dict | None,
                 now: datetime | None = None) -> float | None:
    if not state:
        return None
    stamp = pc.parse_stamp(state.get('updated'))
    if stamp is None:
        return None
    return ((now or datetime.now()) - stamp).total_seconds()


def meeting_summary(state: dict | None,
                    now: datetime | None = None) -> tuple[list[str], float | None]:
    """Приложения с идущей встречей и секунды с начала самой ранней."""
    if not state:
        return [], None
    apps = state.get('apps')
    if not isinstance(apps, dict):
        return [], None
    names: list[str] = []
    starts: list[datetime] = []
    for key, info in apps.items():
        if not isinstance(info, dict) or info.get('state') != 'meeting':
            continue
        names.append(str(info.get('app') or key))
        since = pc.parse_stamp(info.get('since'))
        if since is not None:
            starts.append(since)
    started = min(starts) if starts else None
    seconds = ((now or datetime.now()) - started).total_seconds() \
        if started else None
    return names, seconds


def is_unconfigured() -> bool:
    if not CONFIG_PATH.exists():
        return True
    status = _state['status']
    return status is not None and status.get('configured') is False


def meeting_text(item=None) -> str:
    names = _state.get('meeting_names') or []
    if not names:
        return ''
    joined = ', '.join(names)
    seconds = _state.get('meeting_seconds')
    if seconds is not None:
        return i18n.t('meeting_with_duration', names=joined,
                      duration=human_duration(seconds))
    return i18n.t('meeting', names=joined)


def lamp_text(item=None) -> str:
    status = _state['status']
    if is_unconfigured():
        return i18n.t('lamp_not_configured')
    age = status_age(status)
    if status is None:
        return i18n.t('lamp_no_data')
    if age is None or age > STATUS_STALE_SECONDS:
        return i18n.t('lamp_stale',
                      stamp=status.get('updated') or '?')
    actual = status.get('actual')
    word = {True: i18n.t('lamp_on'),
            False: i18n.t('lamp_off')}.get(actual, i18n.t('lamp_unknown'))
    checked = (status.get('checked') or '')[11:19]
    if checked:
        return i18n.t('lamp_checked', state=word, checked=checked)
    return i18n.t('lamp_state', state=word)


def mode_text(item=None) -> str:
    return i18n.t('mode', description=pc.describe(
        _state['mode'], _state['until'])) + \
        remaining_suffix(_state['until'])


def reason_text(item=None) -> str:
    """Почему лампа сейчас такая: ручной режим, конфликт или нет данных."""
    status = _state.get('status')
    mode = _state.get('mode')
    until = _state.get('until')
    actual = status.get('actual') if status else None
    if not _state.get('alive'):
        return i18n.t('reason_executor_down')
    if not _state.get('meetings_alive'):
        return i18n.t('reason_watcher_down')
    if _state.get('meeting') and mode == pc.MODE_AUTO and actual is False:
        return i18n.t('reason_meeting_lamp_off')
    if _state.get('meeting') and mode == pc.MODE_OFF:
        return i18n.t('reason_meeting_manual_off') + \
            remaining_suffix(until)
    if not _state.get('meeting') and mode == pc.MODE_ON:
        return i18n.t('reason_no_meeting_manual_on') + remaining_suffix(until)
    if mode == pc.MODE_PAUSED:
        return i18n.t('reason_paused') + remaining_suffix(until)
    return ''


def error_text() -> str | None:
    status = _state['status'] or {}
    error = status.get('error')
    if not error:
        return None
    return i18n.t('error_device', error=error)[:120]


def refresh() -> None:
    control = pc.read_control()
    status = pc.read_status()
    meetings = read_meetings()
    mode, until, _ = pc.resolve(control)
    age = status_age(status)
    alive = age is not None and age <= STATUS_STALE_SECONDS
    m_age = meetings_age(meetings)
    meetings_alive = m_age is not None and m_age <= MEETINGS_STALE_SECONDS
    names, seconds = meeting_summary(meetings if meetings_alive else None)
    meeting = bool(names)
    actual = status.get('actual') if status is not None and alive else None
    # Оранжевая точка: автоматика считает, что идёт встреча, а лампа выключена.
    badge = bool(meeting and mode == pc.MODE_AUTO and actual is False)

    kind = 'unknown'
    if status is not None and alive:
        if mode == pc.MODE_PAUSED:
            kind = 'paused'
        elif status.get('actual') is True:
            kind = 'on'
        elif status.get('actual') is False:
            kind = 'off'

    theme = system_theme()
    changed = (kind != _state['kind'] or theme != _state.get('theme')
               or badge != _state.get('badge'))
    _state.update(control=control, status=status, meetings=meetings, mode=mode,
                  until=until, alive=alive, meetings_alive=meetings_alive,
                  meeting=meeting, meeting_names=names, meeting_seconds=seconds,
                  badge=badge, kind=kind, theme=theme)
    if _icon is None:
        return
    if changed:
        _icon.icon = make_image(kind, theme, badge)
    if is_unconfigured():
        title_word = i18n.t('state_not_configured')
    else:
        title_word = {'on': i18n.t('state_on'),
                      'off': i18n.t('state_off'),
                      'paused': i18n.t('state_paused')}.get(
                          kind, i18n.t('state_unknown'))
    title = i18n.t('title', state=title_word,
                   mode=pc.describe(mode, until))
    if meeting:
        if seconds is not None:
            title += i18n.t('title_meeting_duration',
                            names=', '.join(names),
                            duration=human_duration(seconds))
        else:
            title += i18n.t('title_meeting', names=', '.join(names))
    _icon.title = title[:120]
    _icon.update_menu()


def act(mode: str, spec: str = pc.DEFAULT_DEADLINE) -> None:
    try:
        pc.apply_mode(mode, spec, pc.SOURCE_TRAY)
    except (OSError, ValueError) as exc:
        log(f'action failed: {mode}/{spec}: {exc}')
        if _icon is not None:
            _icon.notify(i18n.t('act_failed', error=exc), 'OnAir Lamp')
    refresh()


def open_log() -> None:
    try:
        import os
        os.startfile(str(PLUG_LOG))
    except OSError as exc:
        log(f'cannot open {PLUG_LOG}: {exc}')
        if _icon is not None:
            _icon.notify(i18n.t('log_open_failed', error=exc), 'OnAir Lamp')


def open_events_log() -> None:
    try:
        os.startfile(str(EVENTS_LOG))
    except OSError as exc:
        log(f'cannot open {EVENTS_LOG}: {exc}')
        if _icon is not None:
            _icon.notify(i18n.t('events_open_failed', error=exc), 'OnAir Lamp')


def _console_python() -> Path | None:
    """python.exe рядом с текущим интерпретатором: нужен видимый прогресс."""
    exe = Path(sys.executable)
    candidate = exe.with_name('python.exe')
    if candidate.exists():
        return candidate
    return exe if exe.name.lower() == 'python.exe' else None


def open_verify() -> None:
    """Проверка розетки: verify.cmd из установки или скрипт в dev-копии."""
    installed = PACKAGE_ROOT / 'verify.cmd'
    if installed.exists():
        try:
            os.startfile(str(installed))
            return
        except OSError as exc:
            log(f'cannot open {installed}: {exc}')
    python = _console_python()
    script = SCRIPT_DIR / 'tuya_setup.py'
    if python is None or not script.exists():
        if _icon is not None:
            _icon.notify(i18n.t('verify_missing'), 'OnAir Lamp')
        return
    comspec = os.environ.get('ComSpec', 'cmd.exe')
    try:
        subprocess.Popen(
            [comspec, '/k', f'"{python}" "{script}" --verify'],
            cwd=str(SCRIPT_DIR), creationflags=0x00000010,  # CREATE_NEW_CONSOLE
        )
    except OSError as exc:
        log(f'cannot start verify: {exc}')
        if _icon is not None:
            _icon.notify(i18n.t('verify_failed', error=exc), 'OnAir Lamp')


def make_report() -> None:
    """Собирает zip для поддержки скрыто и сообщает имя файла."""
    if not REPORT_SCRIPT.exists():
        if _icon is not None:
            _icon.notify(i18n.t('report_missing'), 'OnAir Lamp')
        return

    def worker() -> None:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        try:
            proc = subprocess.run(
                [sys.executable, str(REPORT_SCRIPT)],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                env=env, timeout=120, creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log(f'report failed: {type(exc).__name__}: {exc}')
            if _icon is not None:
                _icon.notify(i18n.t('report_failed', error=exc), 'OnAir Lamp')
            return
        output = (proc.stdout or '') + (proc.stderr or '')
        archive = ''
        for line in output.splitlines():
            if line.startswith(('архив:', 'archive:')):
                archive = line.split(':', 1)[1].strip()
        log(f'report: rc={proc.returncode} archive={archive or "?"}')
        if proc.returncode == 0 and archive:
            if _icon is not None:
                _icon.notify(i18n.t('report_saved', name=Path(archive).name),
                             'OnAir Lamp')
        elif _icon is not None:
            _icon.notify(i18n.t('report_failed_log'), 'OnAir Lamp')

    threading.Thread(target=worker, daemon=True).start()


def open_setup() -> None:
    """Открывает мастер настройки из папки установки (или packaging в dev-копии)."""
    candidates = (PACKAGE_ROOT / 'setup.cmd', PACKAGE_ROOT / 'packaging' / 'setup.cmd')
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        if _icon is not None:
            _icon.notify(i18n.t('setup_missing'), 'OnAir Lamp')
        return
    try:
        import os
        os.startfile(str(path))
    except OSError as exc:
        log(f'cannot open {path}: {exc}')
        if _icon is not None:
            _icon.notify(i18n.t('setup_failed', error=exc), 'OnAir Lamp')


def first_run_prompt() -> None:
    """Первый запуск без настроек: предложить сразу пройти мастер.

    Диалог показывается в отдельном потоке, чтобы иконка в трее появилась
    независимо от ответа. Отказ ничего не блокирует: трей продолжает работать
    и пункт «Настроить розетку…» остаётся в меню.
    """
    answer = ctypes.windll.user32.MessageBoxW(
        None,
        i18n.t('first_run_text'),
        i18n.t('first_run_title'),
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


def _deadline_item(key: str, mode: str, spec: str) -> pystray.MenuItem:
    """Один пункт подменю: обработчик с сигнатурой (icon, item), как ждёт pystray."""
    def handler(icon, item):
        act(mode, spec)
    return pystray.MenuItem(i18n.t(key), handler)


def _deadline_submenu(mode: str) -> pystray.Menu:
    """Подменю «на 1 час / на 2 часа / до конца дня / до ручного возврата»."""
    return pystray.Menu(*(_deadline_item(key, mode, spec)
                          for key, spec in DEADLINE_ITEMS))


def change_language(value: str) -> None:
    """Сменить язык интерфейса и сразу перестроить меню и заголовок."""
    resolved = i18n.set_language(value)
    log(f'language changed: {value} -> {resolved}')
    if _icon is not None:
        _icon.menu = build_menu()
        _icon.update_menu()
        refresh()


def _language_item(value: str, key: str) -> pystray.MenuItem:
    return pystray.MenuItem(
        i18n.t(key), lambda icon, item: change_language(value),
        checked=lambda item: i18n.language_setting() == value, radio=True)


def _language_submenu() -> pystray.Menu:
    return pystray.Menu(
        _language_item(i18n.LANGUAGE_AUTO, 'lang_auto'),
        _language_item(i18n.LANGUAGE_RU, 'lang_ru'),
        _language_item(i18n.LANGUAGE_EN, 'lang_en'),
    )


def _notify(message: str) -> None:
    if _icon is not None:
        try:
            _icon.notify(message, 'OnAir Lamp')
        except Exception as exc:  # уведомление не должно ронять трей
            log(f'notify failed: {type(exc).__name__}: {exc}')


def _version_label() -> str:
    version = updater.current_version()
    return 'dev' if version == '0.0.0' else version


def update_text(item=None) -> str:
    info = _state.get('update') or {}
    status = info.get('status')
    version = info.get('version') or ''
    if status == 'checking':
        return i18n.t('menu_update_checking')
    if status == 'downloading':
        return i18n.t('menu_update_downloading', version=version)
    if status == 'available':
        return i18n.t('menu_update_install', version=version)
    return i18n.t('menu_update_check')


def update_enabled(item=None) -> bool:
    return (_state.get('update') or {}).get('status') not in (
        'checking', 'downloading')


def _remember_check() -> None:
    try:
        settings = i18n.read_settings()
        settings['update_last_check'] = pc.now_stamp()
        i18n.write_settings(settings)
    except OSError as exc:
        log(f'cannot save update check time: {exc}')


def start_check(manual: bool = True) -> None:
    """Проверить выпуски в фоне; ручная проверка сообщает результат всегда."""
    info = _state.get('update') or {}
    if info.get('status') == 'checking':
        return
    _state['update'] = dict(info, status='checking', error='')
    if _icon is not None:
        _icon.update_menu()

    def worker() -> None:
        global _update_check
        check = updater.check_for_update()
        _update_check = check
        log(f'update check: current {check.current}; latest {check.version or "?"}; '
            f'available {check.available}; error {check.error or "none"}')
        if check.error:
            _state['update'] = {'status': 'idle', 'version': check.version,
                                'error': check.error}
            if manual:
                _notify(i18n.t('update_check_failed', error=check.error))
        elif check.available:
            _state['update'] = {'status': 'available',
                                'version': check.version, 'error': ''}
            _notify(i18n.t('update_available', version=check.version))
            _remember_check()
        else:
            _state['update'] = {'status': 'idle',
                                'version': check.version, 'error': ''}
            if manual:
                _notify(i18n.t('update_up_to_date', version=check.current))
            _remember_check()
        if _icon is not None:
            _icon.update_menu()

    threading.Thread(target=worker, daemon=True).start()


def start_install() -> None:
    """Спросить подтверждение, скачать и запустить установщик обновления."""
    info = _state.get('update') or {}
    check = _update_check
    if check is None or not check.available or info.get('status') != 'available':
        start_check(manual=True)
        return
    if not updater.is_installed():
        _notify(i18n.t('update_dev_only'))
        return
    answer = ctypes.windll.user32.MessageBoxW(
        None, i18n.t('update_confirm', version=check.version),
        i18n.t('update_confirm_title'), UPDATE_CONFIRM_FLAGS)
    log(f'update install: user answered {answer}')
    if answer != 6:  # IDYES
        return

    version = check.version
    _state['update'] = dict(info, status='downloading', version=version)
    if _icon is not None:
        _icon.update_menu()

    def worker() -> None:
        try:
            installer = updater.download_update(check)
        except updater.UpdateError as exc:
            log(f'update download failed: {exc}')
            _state['update'] = dict(info, status='available', version=version)
            message = (i18n.t('update_bad_checksum')
                       if 'checksum' in str(exc).lower()
                       else i18n.t('update_download_failed', error=exc))
            _notify(message)
            if _icon is not None:
                _icon.update_menu()
            return
        log(f'update downloaded: {installer}')
        try:
            updater.launch_installer(installer)
        except updater.UpdateError as exc:
            log(f'update launch failed: {exc}')
            _state['update'] = dict(info, status='available', version=version)
            _notify(i18n.t('update_install_failed', error=exc))
            if _icon is not None:
                _icon.update_menu()
            return
        _notify(i18n.t('update_launching', version=version))
        time.sleep(1.5)
        stop_all()
        if _icon is not None:
            _icon.stop()

    threading.Thread(target=worker, daemon=True).start()


def update_action(icon, item) -> None:
    if (_state.get('update') or {}).get('status') == 'available':
        start_install()
    else:
        start_check(manual=True)


def _auto_check_due() -> bool:
    stamp = pc.parse_stamp(i18n.read_settings().get('update_last_check'))
    if stamp is None:
        return True
    return (datetime.now() - stamp).total_seconds() >= AUTO_CHECK_INTERVAL


def auto_check_loop() -> None:
    """Фоновая проверка при старте: не чаще раза в сутки."""
    if not _auto_check_due():
        return
    time.sleep(AUTO_CHECK_SECONDS)
    if _icon is not None:
        start_check(manual=False)


def build_menu() -> pystray.Menu:
    version_item = pystray.MenuItem(
        lambda item: i18n.t('menu_version', version=_version_label()),
        None, enabled=False,
        visible=lambda item: updater.is_installed())
    return pystray.Menu(
        pystray.MenuItem(meeting_text, None, enabled=False,
                         visible=lambda item: meeting_text() != ''),
        pystray.MenuItem(lamp_text, None, enabled=False),
        pystray.MenuItem(mode_text, None, enabled=False),
        pystray.MenuItem(reason_text, None, enabled=False,
                         visible=lambda item: reason_text() != ''),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(i18n.t('menu_on'), _deadline_submenu(pc.MODE_ON)),
        pystray.MenuItem(i18n.t('menu_off'), _deadline_submenu(pc.MODE_OFF)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(i18n.t('menu_auto'), lambda icon, item: act(pc.MODE_AUTO),
                         checked=lambda item: _state['mode'] == pc.MODE_AUTO, radio=True),
        pystray.MenuItem(i18n.t('menu_pause'), _deadline_submenu(pc.MODE_PAUSED)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: error_text() or '', open_log,
                         visible=lambda item: error_text() is not None, enabled=False),
        pystray.MenuItem(i18n.t('menu_setup'), open_setup,
                         visible=lambda item: is_unconfigured()),
        pystray.MenuItem(i18n.t('menu_verify'), open_verify),
        pystray.MenuItem(i18n.t('menu_plug_log'), open_log),
        pystray.MenuItem(i18n.t('menu_events_log'), open_events_log),
        pystray.MenuItem(i18n.t('menu_report'), make_report),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(i18n.t('menu_language'), _language_submenu()),
        pystray.MenuItem(update_text, update_action, enabled=update_enabled),
        version_item,
        pystray.MenuItem(i18n.t('menu_exit'), quit_app),
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
    _icon = pystray.Icon('onair-lamp',
                         make_image(_state['kind'] or 'unknown',
                                    _state['theme'] or system_theme()),
                         'OnAir Lamp', build_menu())
    if not CONFIG_PATH.exists():
        threading.Thread(target=first_run_prompt, daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=poll_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=auto_check_loop, daemon=True).start()
    log(f'tray started (language {i18n.get_language()}, '
        f'version {_version_label()})')
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
