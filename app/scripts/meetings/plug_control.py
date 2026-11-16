#!/usr/bin/env python3
"""Намерение для лампы On air: режим автоматики и принудительное состояние.

Исполнитель (`plug_executor.py`) раз в 3 с сверяет желаемое и фактическое
состояние устройства. Автоматика по встречам — только один из источников
желаемого состояния. Принудительная команда, отправленная прямо в розетку, была
бы отменена следующей сверкой, поэтому управление идёт через отдельный файл
намерения `control.json`, у которого приоритет выше `state.json` наблюдателя.

Режимы (`mode`):
  auto   — по событиям встреч (как раньше);
  on     — лампа включена, автоматика игнорируется;
  off    — лампа выключена, автоматика игнорируется;
  paused — автоматика снята: исполнитель не трогает устройство.

Поле `until` — срок действия режима (локальное время, `%Y-%m-%d %H:%M:%S`).
`null` — до ручного возврата в `auto`. По истечении срока исполнитель сам
записывает `auto` и сообщает об этом в `plug.log`.

Файлы (вне Git, каталог `data/` в .gitignore):
  data/work/meetings/control.json     — намерение (пишут CLI и трей);
  data/work/meetings/plug_state.json  — фактическое состояние (пишет исполнитель).

Модуль не подключается к устройству и не читает секреты: он только работает с
файлами, поэтому его можно использовать и из трея, и из CLI.

  python plug_control.py on --for 1h
  python plug_control.py off --for eod
  python plug_control.py pause --for manual
  python plug_control.py auto
  python plug_control.py status
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

MODE_AUTO = 'auto'
MODE_ON = 'on'
MODE_OFF = 'off'
MODE_PAUSED = 'paused'
MODES = (MODE_AUTO, MODE_ON, MODE_OFF, MODE_PAUSED)

SOURCE_CLI = 'cli'
SOURCE_TRAY = 'tray'
SOURCE_EXPIRY = 'expiry'

TIME_FMT = '%Y-%m-%d %H:%M:%S'
DEFAULT_DEADLINE = '1h'

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_CONTROL = REPO_ROOT / 'data' / 'work' / 'meetings' / 'control.json'
DEFAULT_STATUS = REPO_ROOT / 'data' / 'work' / 'meetings' / 'plug_state.json'
DEFAULT_LOG = REPO_ROOT / 'data' / 'work' / 'meetings' / 'plug.log'


def parse_stamp(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text.strip(), TIME_FMT)
    except ValueError:
        return None


def format_stamp(value: datetime) -> str:
    return value.strftime(TIME_FMT)


def now_stamp() -> str:
    return format_stamp(datetime.now())


def deadline(spec: str, now: datetime | None = None) -> datetime | None:
    """Срок действия режима: '30m', '2h', 'eod' или 'manual' (без срока)."""
    now = now or datetime.now()
    text = (spec or '').strip().lower()
    if text in ('manual', 'none', 'вручную'):
        return None
    if text in ('eod', 'конец дня', 'конец-дня'):
        return now.replace(hour=23, minute=59, second=59, microsecond=0)
    match = re.fullmatch(r'(\d+)\s*([mh])', text)
    if not match:
        raise ValueError(f'unknown deadline "{spec}": use 30m, 1h, 2h, eod or manual')
    minutes = int(match.group(1)) * (60 if match.group(2) == 'h' else 1)
    if minutes <= 0:
        raise ValueError('deadline must be positive')
    return now + timedelta(minutes=minutes)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def read_control(path: Path | None = None) -> dict:
    """Намерение из файла. Отсутствующий или битый файл означает `auto`."""
    path = path or DEFAULT_CONTROL
    empty = {'mode': MODE_AUTO, 'until': None, 'updated': None, 'source': None}
    try:
        raw = path.read_text(encoding='utf-8-sig')
    except (FileNotFoundError, OSError):
        return empty
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    mode = data.get('mode')
    if mode not in MODES:
        mode = MODE_AUTO
    until = data.get('until')
    return {
        'mode': mode,
        'until': until if isinstance(until, str) else None,
        'updated': data.get('updated') if isinstance(data.get('updated'), str) else None,
        'source': data.get('source') if isinstance(data.get('source'), str) else None,
    }


def resolve(control: dict, now: datetime | None = None) -> tuple[str, datetime | None, bool]:
    """Действующий режим: (mode, until, срок истёк).

    Истёкший срок означает `auto`; флаг нужен, чтобы исполнитель один раз
    переписал файл и сообщил об этом в журнал.
    """
    now = now or datetime.now()
    mode = control.get('mode') if control.get('mode') in MODES else MODE_AUTO
    if mode == MODE_AUTO:
        return MODE_AUTO, None, False
    until = parse_stamp(control.get('until'))
    if until is None:
        return mode, None, False
    if now >= until:
        return MODE_AUTO, None, True
    return mode, until, False


def write_control(path: Path | None, mode: str, until: datetime | None = None,
                  source: str = SOURCE_CLI, now: datetime | None = None) -> dict:
    if mode not in MODES:
        raise ValueError(f'unknown mode "{mode}": use {", ".join(MODES)}')
    data = {
        'mode': mode,
        'until': format_stamp(until) if until else None,
        'updated': format_stamp(now or datetime.now()),
        'source': source,
    }
    _atomic_write(path or DEFAULT_CONTROL, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return data


def expire_control(path: Path | None, seen: dict, now: datetime | None = None) -> bool:
    """Возвращает `auto` после истечения срока, если файл ещё не переписали.

    Повторное чтение перед записью не даёт затереть режим, который пользователь
    успел выставить вручную в тот же момент.
    """
    path = path or DEFAULT_CONTROL
    current = read_control(path)
    if current.get('mode') != seen.get('mode'):
        return False
    if (current.get('until') or '') != (seen.get('until') or ''):
        return False
    write_control(path, MODE_AUTO, None, SOURCE_EXPIRY, now)
    return True


def apply_mode(mode: str, spec: str = DEFAULT_DEADLINE, source: str = SOURCE_CLI,
               path: Path | None = None, now: datetime | None = None,
               log_path: Path | None = None) -> dict:
    """Записать режим со сроком и оставить строку в журнале."""
    until = None if mode == MODE_AUTO else deadline(spec, now)
    data = write_control(path, mode, until, source, now)
    log_action(data, path, log_path)
    return data


def log_action(control: dict, control_path: Path | None = None,
               log_path: Path | None = None) -> None:
    """Строка в plug.log: ручное управление меняет состояние (L2), нужен след.

    Каталог журнала тот же, что у исполнителя; запись одной строкой в режиме
    append, поэтому параллельная запись исполнителя не ломает формат.
    """
    log_path = log_path or DEFAULT_LOG
    line = (f'{now_stamp()}  control: mode={control.get("mode")} '
            f'until={control.get("until") or "manual"} source={control.get("source")}\n')
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as fh:
            fh.write(line)
    except OSError as exc:
        print(f'failed to write {log_path}: {exc}', file=sys.stderr)


def read_status(path: Path | None = None) -> dict | None:
    """Состояние, которое опубликовал исполнитель. None — файла нет/битый."""
    path = path or DEFAULT_STATUS
    try:
        raw = path.read_text(encoding='utf-8-sig')
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_status(path: Path | None, payload: dict) -> None:
    """Атомарная публикация состояния для трея (сам трей устройство не читает)."""
    path = path or DEFAULT_STATUS
    text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    _atomic_write(path, text + '\n')


def describe(mode: str, until: datetime | None) -> str:
    """Короткое человеческое описание режима."""
    if mode == MODE_AUTO:
        return 'автоматика по встречам'
    if mode == MODE_PAUSED:
        base = 'автоматика снята'
    elif mode == MODE_ON:
        base = 'включена вручную'
    else:
        base = 'выключена вручную'
    if until is None:
        return base + ', до ручного возврата'
    return base + f' до {format_stamp(until)[11:16]}'


def _report(control: dict, status: dict | None) -> str:
    mode, until, _ = resolve(control)
    lines = [f'mode: {mode} ({describe(mode, until)})']
    if control.get('mode') != mode:
        lines.append(f'control.json: {control.get("mode")} просрочен, исполнитель вернёт auto')
    if control.get('updated'):
        lines.append(f'control updated: {control["updated"]} (source {control.get("source")})')
    if status is None:
        lines.append('executor: plug_state.json отсутствует')
    else:
        actual = status.get('actual')
        lamp = {True: 'включена', False: 'выключена'}.get(actual, 'неизвестно')
        suffix = f' (checked {status.get("checked")})' if status.get('checked') else ''
        lines.append(f'lamp: {lamp}{suffix}')
        lines.append(f'executor: heartbeat {status.get("updated")}; режим исполнителя {status.get("mode")}')
        if status.get('error'):
            lines.append(f'error: {status["error"]}')
    return '\n'.join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description='Режим лампы On air: автоматика или ручное управление')
    parser.add_argument('action', choices=['on', 'off', 'auto', 'resume', 'pause', 'status'])
    parser.add_argument('--for', dest='spec', default=DEFAULT_DEADLINE,
                        help='срок: 30m, 1h, 2h, eod, manual (по умолчанию 1h)')
    parser.add_argument('--source', default=SOURCE_CLI)
    parser.add_argument('--control', type=Path, default=DEFAULT_CONTROL)
    parser.add_argument('--status', type=Path, default=DEFAULT_STATUS)
    parser.add_argument('--log', type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()

    if args.action == 'status':
        print(_report(read_control(args.control), read_status(args.status)))
        return 0

    mode = {'on': MODE_ON, 'off': MODE_OFF, 'auto': MODE_AUTO,
            'resume': MODE_AUTO, 'pause': MODE_PAUSED}[args.action]
    try:
        data = apply_mode(mode, args.spec, args.source, args.control, log_path=args.log)
    except (OSError, ValueError) as exc:
        print(f'failed: {exc}', file=sys.stderr)
        return 2

    until = parse_stamp(data.get('until'))
    print(f'mode: {mode} ({describe(mode, until)})')
    print('исполнитель применит режим в течение нескольких секунд '
          '(если он запущен и состояние устройства читается)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
