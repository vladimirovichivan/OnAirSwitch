#!/usr/bin/env python3
"""Собирает zip с журналами и состоянием для передачи в поддержку.

Внутрь попадают только рабочие файлы лампы и выжимка из конфигурации:
имя, адрес, версия протокола и номер DP. `local_key` и `dev_id` не включаются
ни в каком виде — ни целиком, ни маской. В `info.txt` также пишутся версия
сборки приложения и версия Windows с номером сборки: по ним видно, на какой
системе воспроизводится проблема.

  python tools\\report_support.py              # архив на рабочий стол
  python tools\\report_support.py --out D:\\Temp

Только стандартная библиотека Python 3.9+.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DATA_DIR = ROOT / 'app' / 'data' / 'work' / 'meetings'
CONFIG = ROOT / 'app' / 'secrets' / 'tuya_plug.json'
BUILD = ROOT / 'app' / 'build.json'

DATA_FILES = ('plug.log', 'events.log', 'state.json', 'control.json',
              'plug_state.json')
LOG_FILES = ('plug.log', 'events.log')
LOG_TAIL_BYTES = 512 * 1024

# CSIDL_DESKTOPDIRECTORY; SHGetFolderPath учитывает перенос рабочего стола
# (например, в OneDrive), в отличие от простой склейки %USERPROFILE%\Desktop.
CSIDL_DESKTOPDIRECTORY = 0x0010


def desktop_dir() -> Path:
    buffer = ctypes.create_unicode_buffer(260)
    try:
        result = ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_DESKTOPDIRECTORY, None, 0, buffer)
    except (AttributeError, OSError):
        result = -1
    if result == 0 and buffer.value:
        return Path(buffer.value)
    return Path.home() / 'Desktop'


def tail(path: Path, limit: int) -> bytes:
    try:
        size = path.stat().st_size
        with path.open('rb') as handle:
            if size > limit:
                handle.seek(size - limit)
                return (f'[первые {size - limit} байт опущены]\n'.encode('utf-8')
                        + handle.read())
            return handle.read()
    except OSError:
        return b''


def config_summary() -> str:
    """Выжимка конфигурации без секретов: ключи только фактом наличия."""
    if not CONFIG.exists():
        return 'конфигурация не найдена: app\\secrets\\tuya_plug.json\n'
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        return f'конфигурация не читается: {exc}\n'
    if not isinstance(data, dict):
        return 'конфигурация имеет неожидаемый формат\n'
    lines = ['Конфигурация розетки (без секретов):']
    for key in ('name', 'address', 'version', 'switch_dp'):
        if data.get(key) not in (None, ''):
            lines.append(f'  {key}: {data.get(key)}')
    lines.append('  dev_id: скрыт')
    lines.append('  local_key: скрыт')
    return '\n'.join(lines) + '\n'


def build_summary() -> str:
    if not BUILD.exists():
        return 'версия сборки: dev (app\\build.json отсутствует)\n'
    try:
        data = json.loads(BUILD.read_text(encoding='utf-8-sig'))
        version = data.get('version') or 'неизвестно'
        built = data.get('built') or 'неизвестно'
        commit = data.get('commit') or 'неизвестно'
    except (OSError, ValueError) as exc:
        return f'версия сборки не читается: {exc}\n'
    return f'версия сборки: {version}, {built}, commit {commit}\n'


def windows_values() -> dict:
    """Поля CurrentVersion из реестра; на не-Windows и при ошибках — пусто."""
    values = {}
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
            for name in ('ProductName', 'DisplayVersion',
                         'CurrentBuildNumber', 'UBR'):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return values


def os_summary() -> str:
    """Версия и сборка Windows без имени компьютера и пользователя."""
    values = windows_values()
    product = str(values.get('ProductName') or '').strip()
    if not product:
        return f'ОС: {platform.platform()}\n'
    build_number = str(values.get('CurrentBuildNumber') or '').strip()
    revision = str(values.get('UBR') or '').strip()
    # В реестре Windows 11 нередко до сих пор называется Windows 10;
    # настоящую версию надёжно различает номер сборки.
    try:
        if int(build_number) >= 22000:
            product = product.replace('Windows 10', 'Windows 11', 1)
    except ValueError:
        pass
    build = build_number or platform.version()
    if build_number and revision:
        build += f'.{revision}'
    bits = {'64bit': '64-bit', '32bit': '32-bit'}.get(
        platform.architecture()[0], platform.machine())
    parts = [product]
    if values.get('DisplayVersion'):
        parts.append(str(values['DisplayVersion']).strip())
    parts.append(f'сборка {build}')
    if bits:
        parts.append(str(bits))
    return 'ОС: ' + ', '.join(parts) + '\n'


def make_archive(out_dir: Path) -> tuple[Path, list[str]]:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f'OnAirLamp-report-{stamp}.zip'
    added = []
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        info = [
            'OnAir Lamp — отчёт для поддержки',
            f'создан: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            build_summary().strip(),
            os_summary().strip(),
            '',
            config_summary().strip(),
            '',
            'Журналы и состояние — из app\\data\\work\\meetings.',
            'Ключи устройства (local_key, dev_id) в архив не включаются.',
        ]
        bundle.writestr('info.txt', '\n'.join(info) + '\n')
        for name in DATA_FILES:
            path = DATA_DIR / name
            if not path.exists():
                continue
            if name in LOG_FILES:
                payload = tail(path, LOG_TAIL_BYTES)
            else:
                try:
                    payload = path.read_bytes()
                except OSError:
                    continue
            bundle.writestr(name, payload)
            added.append(name)
    return archive, added


def main() -> int:
    parser = argparse.ArgumentParser(description='Архив журналов для поддержки')
    parser.add_argument('--out', type=Path, default=None,
                        help='куда положить zip (по умолчанию рабочий стол)')
    args = parser.parse_args()

    if not (DATA_DIR.exists() or CONFIG.exists() or BUILD.exists()):
        print(f'не найдены файлы приложения рядом с {ROOT}')
        print('запустите report.cmd из папки установки OnAir Lamp')
        return 1

    target = args.out or desktop_dir()
    try:
        archive, added = make_archive(target)
    except OSError as exc:
        print(f'не удалось создать архив: {exc}')
        return 2

    print(f'архив: {archive}')
    print('внутри: info.txt' + (', ' + ', '.join(added) if added else ''))
    if not added:
        print('внимание: журналов и файлов состояния пока нет — приложение')
        print('ещё не запускалось или работает из другого каталога.')
    print('ключи устройства в архив не включались.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
