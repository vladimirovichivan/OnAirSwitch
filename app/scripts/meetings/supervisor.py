#!/usr/bin/env python3
"""Сторож процессов OnAir Lamp: запускает три процесса и перезапускает упавшие.

Запускается скрыто из `start.vbs` вместо трёх отдельных процессов:

  pythonw supervisor.py

Наблюдатель держит mutex `Local\\OnAirLampMeetingsWatcher`, исполнитель —
`Local\\OnAirLampPlugExecutor`, трей — `Local\\OnAirLampPlugTray`. По этим mutex
супервизор понимает, что процесс уже запущен (например, вторым экземпляром
start.vbs), и не плодит дубликаты: такой процесс он «усыновляет» и следит за
ним, пока mutex не исчезнет. Перезапуск — с нарастающей паузой (2…60 с), чтобы
падающий процесс не забивал журнал.

«Выход» в трее и деинсталлятор вызывают stop.ps1: он завершает сначала
супервизор, затем остальные процессы, поэтому сторож не успевает поднять их
снова. Журнал — `data\\work\\meetings\\supervisor.log`.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = REPO_ROOT / 'data' / 'work' / 'meetings'
LOG_PATH = DATA_DIR / 'supervisor.log'

MUTEX_NAME = 'Local\\OnAirLampPlugSupervisor'
POLL_SECONDS = 5.0
MAX_BACKOFF = 60.0
STABLE_SECONDS = 60.0
CREATE_NO_WINDOW = 0x08000000
SYNCHRONIZE = 0x00100000

COMPONENTS = (
    {'name': 'watcher', 'mutex': 'Local\\OnAirLampMeetingsWatcher'},
    {'name': 'executor', 'mutex': 'Local\\OnAirLampPlugExecutor'},
    {'name': 'tray', 'mutex': 'Local\\OnAirLampPlugTray'},
)

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   ctypes.c_wchar_p]
_kernel32.OpenMutexW.restype = ctypes.c_void_p
_kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int,
                                 ctypes.c_wchar_p]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


def log(message: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1_000_000:
            LOG_PATH.replace(LOG_PATH.with_name(LOG_PATH.name + '.1'))
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with LOG_PATH.open('a', encoding='utf-8') as handle:
            handle.write(f'{stamp}  {message}\n')
    except OSError:
        pass


def acquire_single_instance() -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def mutex_exists(name: str) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name('pythonw.exe')
    return str(candidate if candidate.exists() else exe)


def command_for(name: str) -> list[str]:
    if name == 'watcher':
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / \
            'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        return [str(powershell), '-NoProfile', '-WindowStyle', 'Hidden',
                '-ExecutionPolicy', 'Bypass', '-File',
                str(SCRIPT_DIR / 'watch_meetings.ps1')]
    if name == 'executor':
        return [pythonw(), str(SCRIPT_DIR / 'plug_executor.py'), '--apply']
    return [pythonw(), str(SCRIPT_DIR / 'tray_plug.py')]


def run() -> int:
    if not acquire_single_instance():
        log('supervisor is already running, second instance is not needed')
        return 0

    components = []
    for spec in COMPONENTS:
        components.append({
            **spec,
            'args': command_for(spec['name']),
            'proc': None,
            'started_at': 0.0,
            'backoff': 0.0,
            'next_try': 0.0,
            'external': False,
        })

    log('supervisor started')
    try:
        while True:
            now = time.monotonic()
            for component in components:
                watch(component, now)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        for component in components:
            proc = component['proc']
            if proc is not None and proc.poll() is None:
                proc.terminate()
        log('supervisor stopped')
    return 0


def watch(component: dict, now: float) -> None:
    name = component['name']
    proc = component['proc']

    if proc is not None:
        code = proc.poll()
        if code is None:
            if component['started_at'] and \
                    now - component['started_at'] >= STABLE_SECONDS:
                component['backoff'] = 0.0
            return
        log(f'{name}: exited with code {code}')
        component['proc'] = None
        component['started_at'] = 0.0
        component['backoff'] = min(
            max(component['backoff'] * 2, 2.0), MAX_BACKOFF)
        component['next_try'] = now + component['backoff']

    if mutex_exists(component['mutex']):
        if not component['external']:
            log(f'{name}: already running outside supervisor, watching it')
            component['external'] = True
        return
    component['external'] = False

    if now < component['next_try']:
        return

    try:
        created = subprocess.Popen(
            component['args'], cwd=str(SCRIPT_DIR),
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        log(f'{name}: cannot start: {type(exc).__name__}: {exc}')
        component['backoff'] = min(
            max(component['backoff'] * 2, 2.0), MAX_BACKOFF)
        component['next_try'] = now + component['backoff']
        return

    component['proc'] = created
    component['started_at'] = now
    component['next_try'] = 0.0
    log(f'{name}: started, pid {created.pid}')


def main() -> int:
    return run()


if __name__ == '__main__':
    sys.exit(main())
