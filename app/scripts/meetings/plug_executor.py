#!/usr/bin/env python3
"""Исполнитель умной розетки (Smart Life / Tuya) по событиям наблюдателя встреч.

Читает состояние наблюдателя (data/work/meetings/state.json), приводит розетку
к нужному состоянию: включена, пока идёт встреча, выключена, когда встреч нет.

Почему состояние, а не поток событий: сверка "нужно/фактически" идемпотентна.
Пропущенное событие, перезапуск исполнителя или разрыв сети не оставят лампу
включённой на всю ночь — следующий проход увидит расхождение и исправит его.
Если наблюдатель остановлен (поле updated устарело), исполнитель ничего не
переключает: неизвестное состояние не считается "встречи нет".

По умолчанию работает в режиме dry-run: печатает действия в лог, но ничего не
переключает. Реальное управление включается флагом --apply.

Приоритет источников желаемого состояния (plug_control.py):
  paused (автоматика снята) > принудительно on/off > state.json наблюдателя.
Принудительный режим живёт в data/work/meetings/control.json и имеет срок
(или «до ручного возврата»); после срока исполнитель сам возвращает auto.

Исполнитель публикует фактическое состояние в data/work/meetings/plug_state.json
(его читает трей; сам трей к устройству не подключается).

Зависимости: tinytuya нужен только для --apply. В dry-run достаточно
стандартной библиотеки Python 3.9+.

  python plug_executor.py                      # dry-run
  python plug_executor.py --apply              # реальное управление
  python plug_executor.py --apply --once       # один проход и выход

Конфигурация (вне Git, каталог secrets/ из .gitignore):
  secrets/tuya_plug.json
    {
      "name": "Лампа у монитора",
      "dev_id": "...",
      "local_key": "...",
      "address": "192.168.111.124",
      "version": "3.3",
      "switch_dp": "1"
    }

Значения dev_id и local_key не печатаются ни в лог, ни в консоль.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import plug_control as pc
import tuya_discovery as discovery

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_STATE = REPO_ROOT / 'data' / 'work' / 'meetings' / 'state.json'
DEFAULT_LOG = REPO_ROOT / 'data' / 'work' / 'meetings' / 'plug.log'
DEFAULT_CONFIG = REPO_ROOT / 'secrets' / 'tuya_plug.json'
DEFAULT_CONTROL = REPO_ROOT / 'data' / 'work' / 'meetings' / 'control.json'
DEFAULT_STATUS = REPO_ROOT / 'data' / 'work' / 'meetings' / 'plug_state.json'
DEFAULT_BUILD = REPO_ROOT / 'build.json'
MUTEX_NAME = 'Local\\LegacyPlugExecutor'
LOG_MAX_BYTES = 1024 * 1024
STATUS_HEARTBEAT = 5.0
REDISCOVERY_COOLDOWN = 600.0  # не искать устройство чаще, чем раз в 10 минут
_UNSET = object()  # «желаемое ещё не вычислялось» (None — законное значение)


class Log:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, message: str) -> None:
        line = f'{datetime.now():%Y-%m-%d %H:%M:%S}  {message}'
        # Под pythonw.exe (скрытый автозапуск) стандартных потоков нет: stdout = None.
        try:
            if sys.stdout is not None:
                print(line, flush=True)
        except (OSError, ValueError):
            pass
        try:
            if self.path.exists() and self.path.stat().st_size > LOG_MAX_BYTES:
                rotated = self.path.with_suffix(self.path.suffix + '.1')
                self.path.replace(rotated)
            with self.path.open('a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        except OSError as exc:  # лог не должен ронять исполнителя
            try:
                if sys.stderr is not None:
                    print(f'failed to write log: {exc}', file=sys.stderr)
            except (OSError, ValueError):
                pass


def acquire_single_instance() -> bool:
    """Именованный mutex в той же сессии, что и наблюдатель."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def read_build_info(path: Path) -> str:
    """Строка версии сборки для журнала: «1.0.0 (2026-11-16, abc1234)».

    В репозитории build.json нет — это нормальный режим разработки, тогда «dev».
    """
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return 'dev'
    if not isinstance(data, dict):
        return 'dev'
    version = str(data.get('version') or '').strip()
    if not version:
        return 'dev'
    details = [str(data.get(key) or '').strip() for key in ('built', 'commit')]
    details = [value[:7] if index == 1 else value for index, value in enumerate(details)]
    details = [value for value in details if value]
    return f'{version} ({", ".join(details)})' if details else version


def read_desired(state_path: Path, stale_seconds: int) -> tuple[bool | None, str]:
    """Возвращает (нужно ли включать, пояснение). None — состояние неизвестно."""
    try:
        raw = state_path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        return None, 'state file is missing'
    except OSError as exc:
        return None, f'state file is unreadable: {exc}'

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f'state file is corrupted: {exc}'

    stamp = data.get('updated')
    try:
        updated = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None, 'state has no valid "updated" field'

    age = (datetime.now() - updated).total_seconds()
    if age > stale_seconds:
        # Текст намеренно стабильный: по нему исполнитель определяет смену причины,
        # и «возраст» в секундах не должен выглядеть как новая причина каждые 3 с.
        return None, f'state is stale (threshold {stale_seconds}s)'

    active = [
        info.get('app') or key
        for key, info in (data.get('apps') or {}).items()
        if info.get('state') == 'meeting'
    ]
    if data.get('meeting'):
        return True, 'meeting: ' + ', '.join(active)
    return False, 'no meeting'


def resolve_desired(args, log: Log) -> tuple[bool | None, str, str, datetime | None]:
    """Желаемое состояние с учётом приоритета ручного режима.

    Возвращает (включить?, причина, действующий режим, срок).
    `None` в первом поле — либо состояние встреч неизвестно, либо автоматика
    снята; различает эти случаи действующий режим (paused).
    """
    control = pc.read_control(args.control)
    mode, until, expired = pc.resolve(control)
    if expired:
        if pc.expire_control(args.control, control):
            log(f'manual mode expired ({control.get("until")}); back to auto')
            control = pc.read_control(args.control)
            mode, until, expired = pc.resolve(control)

    due = f' until {pc.format_stamp(until)}' if until else ' (until manual release)'
    if mode == pc.MODE_PAUSED:
        return None, 'automation is off' + due, mode, until
    if mode in (pc.MODE_ON, pc.MODE_OFF):
        reason = f'manual {mode} from {control.get("source") or "unknown"}{due}'
        return mode == pc.MODE_ON, reason, mode, until

    desired, reason = read_desired(args.state, args.stale)
    return desired, reason, mode, until


class TuyaPlug:
    """Обёртка над tinytuya.OutletDevice: только статус и переключение."""

    def __init__(self, config: dict, apply: bool, log: Log):
        self.apply = apply
        self.log = log
        self.name = config.get('name') or config.get('dev_id') or 'plug'
        self.dev_id = config.get('dev_id') or ''
        self.local_key = config.get('local_key') or ''
        self.address = config.get('address') or '(not set)'
        self.version = float(config.get('version', 3.3))
        self.switch_dp = str(config.get('switch_dp', '1'))
        # Последнее прочитанное состояние — для plug_state.json (трея).
        self.last_status: bool | None = None
        self.last_checked: str | None = None
        self.last_error: str | None = None
        self.device = None
        self.rediscovery_next = 0.0
        if apply and not (self.dev_id and self.local_key):
            raise SystemExit('secrets/tuya_plug.json must contain dev_id and local_key')
        if apply:
            self.device = self._connect()

    def _connect(self, address: str | None = None):
        try:
            import tinytuya  # noqa: PLC0415 - нужен только в режиме --apply
        except ImportError:
            raise SystemExit(
                'tinytuya is not installed. For --apply: python -m pip install tinytuya'
            )
        target = address or self.address
        device = tinytuya.OutletDevice(self.dev_id, target, self.local_key, version=self.version)
        device.set_version(self.version)
        device.set_socketTimeout(5)
        # Соединение не держим: команда нужна раз в несколько часов, а постоянный
        # сокет занимает единственный слот устройства и мешает приложению и диагностике.
        device.set_socketPersistent(False)
        return device

    def _read_status(self):
        try:
            return self.device.status()
        except Exception as exc:  # сеть, таймауты, разбор пакета
            self.last_error = f'status read failed ({type(exc).__name__}: {exc})'
            return None

    def _recover_address(self) -> bool:
        """Один раз найти устройство по dev_id, если настроенный адрес молчит.

        Конфиг не перезаписывается: после смены IP всё равно нужна резервация в
        DHCP, а ручная правка файла остаётся осознанным действием.
        """
        now = time.monotonic()
        if now < self.rediscovery_next or not self.dev_id:
            return False
        self.rediscovery_next = now + REDISCOVERY_COOLDOWN
        found = discovery.find_address(self.dev_id, seconds=6.0)
        if not found or found == self.address:
            return False
        self.log(f'{self.name}: address rediscovered: {self.address} -> {found}')
        self.address = found
        self.device = self._connect()
        return True

    def status(self) -> bool | None:
        if not self.apply:
            return None
        result = self._read_status()
        if not isinstance(result, dict) or 'dps' not in result:
            if self._recover_address():
                result = self._read_status()
        if not isinstance(result, dict) or 'dps' not in result:
            error = result.get('Error') if isinstance(result, dict) else result
            if self.last_error is None:
                self.last_error = f'no response when reading status ({error})'
            self.log(f'{self.name}: {self.last_error}')
            return None
        value = (result.get('dps') or {}).get(self.switch_dp)
        if value is None:
            self.last_error = f'response has no DP {self.switch_dp}'
            self.log(f'{self.name}: {self.last_error}, available {sorted(result.get("dps") or {})}')
            return None
        self.last_status = str(value).lower() in ('true', '1', 'on')
        self.last_checked = pc.now_stamp()
        self.last_error = None
        return self.last_status

    def switch(self, on: bool) -> bool:
        if not self.apply:
            return True
        try:
            result = self.device.turn_on() if on else self.device.turn_off()
        except Exception as exc:
            self.last_error = f'switch failed ({type(exc).__name__}: {exc})'
            self.log(f'{self.name}: {self.last_error}')
            return False
        if isinstance(result, dict) and result.get('Error'):
            self.last_error = f'device rejected the command ({result.get("Error")})'
            self.log(f'{self.name}: {self.last_error}')
            return False
        return True


def reconcile(plug: TuyaPlug, desired: bool | None, reason: str, args, log: Log,
              last_applied: bool | None) -> bool | None:
    if desired is None:
        if last_applied is not None or args.once:
            log(f'state unknown ({reason}); not switching anything')
        return last_applied

    mode = 'apply' if args.apply else 'dry-run'
    current = plug.status()
    if current is not None and current == desired:
        if args.once:
            log(f'[{mode}] already {"on" if desired else "off"} ({reason})')
        return desired

    if current is None and args.apply:
        # Состояние прочитать не удалось: команду всё равно отправляем, но
        # результат проверяем отдельным чтением ниже.
        log(f'[{mode}] status unavailable, sending command: '
            f'{"turn on" if desired else "turn off"} ({reason})')
    else:
        was = {True: 'on', False: 'off', None: 'unknown'}[current]
        log(f'[{mode}] {was} -> {"turn on" if desired else "turn off"} ({reason})')

    for attempt in range(1, args.retries + 1):
        if not plug.switch(desired):
            time.sleep(args.retry_delay)
            continue
        if not args.apply:
            return desired
        time.sleep(1.0)
        verified = plug.status()
        if verified is None:
            time.sleep(args.retry_delay)
            continue
        if verified == desired:
            log(f'[{mode}] confirmed by device: {"on" if desired else "off"}')
            return desired
        log(f'[{mode}] verification mismatch (attempt {attempt} of {args.retries})')
        time.sleep(args.retry_delay)

    log(f'[{mode}] failed to reach desired state after {args.retries} attempts')
    return None


def main() -> int:
    try:  # консоль Windows может не иметь нужной кодировки для кириллицы
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description='Управление розеткой Tuya по событиям встреч')
    parser.add_argument('--apply', action='store_true', help='переключать устройство (по умолчанию dry-run)')
    parser.add_argument('--once', action='store_true', help='один проход сверки и выход')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--control', type=Path, default=DEFAULT_CONTROL,
                        help='файл ручного режима (по умолчанию data/work/meetings/control.json)')
    parser.add_argument('--status', type=Path, default=DEFAULT_STATUS,
                        help='файл состояния для трея (по умолчанию data/work/meetings/plug_state.json)')
    parser.add_argument('--log', type=Path, default=DEFAULT_LOG)
    parser.add_argument('--interval', type=int, default=3, help='период сверки, с (по умолчанию 3)')
    parser.add_argument('--stale', type=int, default=90, help='порог устаревания состояния, с (по умолчанию 90)')
    parser.add_argument('--retries', type=int, default=3, help='попыток на переключение (по умолчанию 3)')
    parser.add_argument('--retry-delay', type=float, default=2.0, help='пауза между попытками, с')
    parser.add_argument('--failure-backoff', type=float, default=60.0,
                        help='пауза после неудачной сверки, с (по умолчанию 60)')
    args = parser.parse_args()

    log = Log(args.log)
    if not acquire_single_instance():
        log('executor is already running, second instance is not needed')
        return 0

    config = {}
    if args.config.exists():
        try:
            config = json.loads(args.config.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            log(f'config is unreadable: {exc}')
            if args.apply:
                return 2
    elif args.apply:
        log(f'config file {args.config} is missing; it is required for --apply')
        return 2

    try:
        plug = TuyaPlug(config, args.apply, log)
    except KeyError as exc:
        log(f'config has no required field {exc}')
        return 2

    mode = 'apply' if args.apply else 'dry-run'
    build = read_build_info(DEFAULT_BUILD)
    log(f'executor started: build {build}; mode {mode}; device {plug.name} ({plug.address}, '
        f'version {plug.version}, DP {plug.switch_dp}); state {args.state}; '
        f'control {args.control}; stale threshold {args.stale}s')
    if not args.apply:
        log('dry-run: device will not be switched (add --apply)')

    last_applied: bool | None = None
    last_desired: object = _UNSET
    last_reason = None
    last_mode = None
    failed_until = 0.0
    published = None
    next_heartbeat = 0.0
    try:
        while True:
            desired, reason, mode, until = resolve_desired(args, log)
            hold = desired is None and mode == pc.MODE_PAUSED
            needs_action = (args.once or desired != last_desired
                            or reason != last_reason or mode != last_mode)
            if needs_action and time.monotonic() >= failed_until:
                if hold:
                    # Автоматика снята: устройство не трогаем, но одна строка
                    # в журнал нужна — иначе снятый режим не отличить от отказа.
                    log(f'{reason}; not switching')
                    result = last_applied
                else:
                    result = reconcile(plug, desired, reason, args, log, last_applied)
                if result is None and desired is not None:
                    # Устройство недоступно: чтобы не опрашивать его каждые 3 с
                    # и не засорять лог, следующая попытка — не раньше backoff.
                    failed_until = time.monotonic() + args.failure_backoff
                last_applied = result
                last_desired = desired
                last_reason = reason
                last_mode = mode

            payload = {
                'device': plug.name,
                'mode': mode,
                'until': pc.format_stamp(until) if until else None,
                'desired': desired,
                'actual': plug.last_status if args.apply else None,
                'checked': plug.last_checked if args.apply else None,
                'error': plug.last_error,
            }
            if payload != published or time.monotonic() >= next_heartbeat:
                try:
                    pc.write_status(args.status, dict(payload, updated=pc.now_stamp()))
                except OSError as exc:
                    log(f'cannot write status file {args.status}: {exc}')
                published = payload
                next_heartbeat = time.monotonic() + STATUS_HEARTBEAT

            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log('executor stopped')
        return 0


if __name__ == '__main__':
    sys.exit(main())
