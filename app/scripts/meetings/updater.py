#!/usr/bin/env python3
"""Проверка и установка обновлений OnAir Lamp с GitHub Releases.

Проверка идёт по HTTPS без секретов: приложение запрашивает последний выпуск,
сравнивает версию с `app/build.json` и, если выпуск новее, предлагает
обновление в меню трея. Установка — только после подтверждения пользователя:
трей скачивает установщик, сверяет SHA256 с `SHA256SUMS.txt` из того же
выпуска и запускает установщик через отдельный helper. Helper переживает
закрытие приложения: дожидается установки и снова запускает `start.vbs`,
поэтому после обновления работают те же четыре процесса.

Проверка не должна мешать работе: любая сетевая ошибка возвращается как
`UpdateCheck.error`, а трей продолжает работать.

Адрес ленты можно переопределить переменной окружения `ONAIR_UPDATE_FEED`
или ключом `update_feed` в `settings.json` — это нужно, если выпуски лежат не
на GitHub. Ожидается JSON GitHub Releases API либо совместимый по структуре.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PACKAGE_ROOT = REPO_ROOT.parent
BUILD_PATH = REPO_ROOT / 'build.json'
UPDATES_DIR = REPO_ROOT / 'data' / 'updates'
SETTINGS_PATH = REPO_ROOT / 'data' / 'work' / 'meetings' / 'settings.json'

DEFAULT_REPO = 'vladimirovichivan/OnAirSwitch'
DEFAULT_FEED = f'https://api.github.com/repos/{DEFAULT_REPO}/releases/latest'
USER_AGENT = 'OnAirLamp-Updater/1.1'
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 120
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000


class UpdateError(RuntimeError):
    """Проверка или загрузка обновления не удалась."""


@dataclass
class UpdateCheck:
    """Результат проверки: данные выпуска или причина ошибки."""

    current: str
    available: bool = False
    version: str = ''
    installer_url: str = ''
    installer_name: str = ''
    sums_url: str = ''
    notes: str = ''
    html_url: str = ''
    error: str = ''

    def as_dict(self) -> dict:
        return {
            'current': self.current,
            'available': self.available,
            'version': self.version,
            'installer_url': self.installer_url,
            'installer_name': self.installer_name,
            'sums_url': self.sums_url,
            'notes': self.notes,
            'html_url': self.html_url,
            'error': self.error,
        }


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' → (1, 2, 3); нечисловые суффиксы отбрасываются."""
    numbers = re.findall(r'\d+', str(text or ''))
    if not numbers:
        return (0,)
    return tuple(int(value) for value in numbers)


def is_newer(latest: str, current: str) -> bool:
    left, right = parse_version(latest), parse_version(current)
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


def current_version(path: Path | None = None) -> str:
    """Версия из app/build.json; в dev-копии файла нет — '0.0.0'."""
    try:
        data = json.loads((path or BUILD_PATH).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return '0.0.0'
    if not isinstance(data, dict):
        return '0.0.0'
    return str(data.get('version') or '0.0.0').strip() or '0.0.0'


def is_installed(root: Path | None = None) -> bool:
    """Обновлять можно только установленную копию (рядом есть start.vbs)."""
    root = root or PACKAGE_ROOT
    return (root / 'start.vbs').exists() and (root / 'app' / 'build.json').exists()


def _settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def feed_url() -> str:
    value = os.environ.get('ONAIR_UPDATE_FEED') or _settings().get('update_feed')
    value = str(value or '').strip()
    return value or DEFAULT_FEED


def _get(url: str, timeout: float) -> bytes:
    if not str(url).lower().startswith('https://'):
        raise UpdateError('update URL must use HTTPS')
    request = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/vnd.github+json',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_DOWNLOAD_BYTES:
                raise UpdateError('response is too large')
            return response.read(MAX_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f'HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(str(exc) or type(exc).__name__) from exc


def fetch_release(url: str | None = None, timeout: float = CHECK_TIMEOUT) -> dict:
    raw = _get(url or feed_url(), timeout)
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError('release feed is not valid JSON') from exc
    if not isinstance(data, dict):
        raise UpdateError('release feed has an unexpected format')
    return data


def _asset_name(asset: dict) -> str:
    return str(asset.get('name') or '')


def _asset_url(asset: dict) -> str:
    return str(asset.get('browser_download_url') or asset.get('url') or '')


def pick_assets(release: dict) -> tuple[dict | None, dict | None]:
    """Установщик и файл контрольных сумм из выпуска."""
    assets = release.get('assets')
    if not isinstance(assets, list):
        assets = []
    assets = [asset for asset in assets if isinstance(asset, dict)]
    installer = next((asset for asset in assets
                      if _asset_name(asset).lower().startswith('onairlamp-setup-')
                      and _asset_name(asset).lower().endswith('.exe')), None)
    sums = next((asset for asset in assets
                 if _asset_name(asset).lower() == 'sha256sums.txt'), None)
    return installer, sums


def check_for_update(url: str | None = None, current: str | None = None,
                     timeout: float = CHECK_TIMEOUT) -> UpdateCheck:
    """Последний выпуск и признак «новее установленной версии»."""
    current = current or current_version()
    result = UpdateCheck(current=current)
    try:
        release = fetch_release(url, timeout)
        tag = str(release.get('tag_name') or release.get('name') or '').strip()
        result.version = tag.lstrip('vV')
        result.notes = str(release.get('body') or '')
        result.html_url = str(release.get('html_url') or '')
        if not result.version:
            raise UpdateError('release has no version tag')
        installer, sums = pick_assets(release)
        if installer is None:
            raise UpdateError('release has no installer')
        if sums is None:
            raise UpdateError('release has no SHA256SUMS.txt')
        result.installer_url = _asset_url(installer)
        result.installer_name = _asset_name(installer)
        result.sums_url = _asset_url(sums)
        if not result.installer_url or not result.sums_url:
            raise UpdateError('release assets have no download URL')
        result.available = is_newer(result.version, current)
    except UpdateError as exc:
        result.error = str(exc)
        result.available = False
    return result


def parse_checksums(text: str) -> dict[str, str]:
    """Строки вида '<sha256>  <имя файла>' (в т.ч. с '*' перед именем)."""
    sums: dict[str, str] = {}
    for line in str(text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].strip().lstrip('*')
        if re.fullmatch(r'[0-9a-f]{64}', digest) and name:
            sums[name] = digest
    return sums


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != str(expected).lower():
        raise UpdateError('checksum mismatch')


def download(url: str, destination: Path,
             timeout: float = DOWNLOAD_TIMEOUT) -> Path:
    """Скачать файл во временный `.part` и заменить цель только после успеха."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    if not str(url).lower().startswith('https://'):
        raise UpdateError('update URL must use HTTPS')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                temp.open('wb') as handle:
            total = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise UpdateError('update file is too large')
                handle.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            OSError) as exc:
        temp.unlink(missing_ok=True)
        raise UpdateError(str(exc) or type(exc).__name__) from exc
    except UpdateError:
        temp.unlink(missing_ok=True)
        raise
    os.replace(temp, destination)
    return destination


def download_update(check: UpdateCheck,
                    target_dir: Path | None = None) -> Path:
    """Скачать установщик и проверить его SHA256 по файлу выпуска."""
    if not check.available or not check.installer_url:
        raise UpdateError('no update is available')
    if not check.installer_name:
        raise UpdateError('release has no installer name')
    target_dir = target_dir or UPDATES_DIR
    sums_path = download(check.sums_url, target_dir / 'SHA256SUMS.txt')
    try:
        sums = parse_checksums(sums_path.read_text(encoding='utf-8-sig'))
    except OSError as exc:
        raise UpdateError(f'cannot read checksums: {exc}') from exc
    expected = sums.get(check.installer_name)
    if not expected:
        raise UpdateError('checksum for the installer is missing')
    installer_path = download(check.installer_url,
                              target_dir / check.installer_name)
    verify_checksum(installer_path, expected)
    return installer_path


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value, _ = winreg.QueryValueEx(key, 'OnAirLamp')
        return bool(value)
    except (ImportError, OSError):
        return False


def desktop_icon_exists() -> bool:
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x0010
        if ctypes.windll.shell32.SHGetFolderPathW(
                None, 0x0010, None, 0, buffer) == 0 and buffer.value:
            return (Path(buffer.value) / 'OnAir Lamp.lnk').exists()
    except (AttributeError, OSError):
        pass
    return False


def install_tasks() -> str:
    """Сохранить при обновлении те задачи, которые были выбраны при установке."""
    tasks = []
    if autostart_enabled():
        tasks.append('autostart')
    if desktop_icon_exists():
        tasks.append('desktopicon')
    return ','.join(tasks)


def build_helper(installer: Path, root: Path, tasks: str) -> str:
    """VBS-helper: дождаться выхода приложения, установить, запустить снова.

    VBS выбран вместо .cmd: Windows Script Host корректно читает путь с
    кириллицей (UTF-16), а helper лежит вне папки установки, поэтому установщик
    его не заменяет.
    """
    wscript = Path(os.environ.get('SystemRoot', r'C:\Windows')) / \
        'System32' / 'wscript.exe'
    start_vbs = root / 'start.vbs'
    merge = tasks or '!autostart,!desktopicon'
    return (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        'WScript.Sleep 2000\r\n'
        f'sh.Run """{installer}"" /SILENT /SUPPRESSMSGBOXES /NORESTART '
        f'/SP- /CURRENTUSER /MERGETASKS={merge}", 1, True\r\n'
        'WScript.Sleep 2000\r\n'
        f'sh.Run """{wscript}"" ""{start_vbs}""", 0, False\r\n'
        'fso.DeleteFile WScript.ScriptFullName, True\r\n'
    )


def launch_installer(installer: Path, root: Path | None = None) -> None:
    """Запустить helper вне папки установки: он переживёт закрытие трея."""
    root = root or PACKAGE_ROOT
    if not installer.exists():
        raise UpdateError('installer file is missing')
    if not is_installed(root):
        raise UpdateError('updates are only available in the installed copy')
    helper = Path(tempfile.gettempdir()) / 'onairlamp-update.vbs'
    helper.write_text(build_helper(installer, root, install_tasks()),
                      encoding='utf-16')
    wscript = Path(os.environ.get('SystemRoot', r'C:\Windows')) / \
        'System32' / 'wscript.exe'
    try:
        subprocess.Popen([str(wscript), str(helper)],
                         creationflags=CREATE_NO_WINDOW, close_fds=True)
    except OSError as exc:
        raise UpdateError(str(exc) or type(exc).__name__) from exc
