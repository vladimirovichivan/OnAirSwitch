#!/usr/bin/env python3
"""Поиск розетки Tuya в локальной сети по dev_id.

Два независимых пути:

1. `tinytuya.scanner.devices(...)` — активный скан (используется, если пакет
   tinytuya установлен). Возвращает найденные адреса и версию протокола.
2. Пассивное прослушивание UDP-портов 6666/6667/7000 — устройства сами
   периодически объявляют себя. Нужен только стандартный Python; работает как
   резерв, если сканер молчит или недоступен.

Ключи (`local_key`) здесь не используются и не печатаются. Найденный адрес всё
равно нужно подтвердить чтением статуса — это делает вызывающий код.
"""

from __future__ import annotations

import json
import socket
import time

SCAN_PORTS = (6666, 6667, 7000)


def _unique(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def scan_tinytuya(dev_id: str, seconds: float = 8.0) -> list[tuple[str, str | None]]:
    """Активный скан через tinytuya. Пустой список — не найден или нет пакета."""
    try:
        import tinytuya  # noqa: F401 - проверка наличия
        import tinytuya.scanner  # noqa: F401 - модуль не подгружается сам
    except ImportError:
        return []
    try:
        result = tinytuya.scanner.devices(
            verbose=False,
            scantime=seconds,
            color=False,
            poll=False,
            forcescan=False,
            byID=True,
            assume_yes=True,
        )
    except Exception:
        return []
    items = result.values() if isinstance(result, dict) else (result or [])
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get('gwId') == dev_id or item.get('id') == dev_id:
            ip = item.get('ip')
            if ip:
                found.append((ip, item.get('version')))
    return _unique(found)


def scan_udp(dev_id: str, seconds: float = 6.0) -> list[tuple[str, str | None]]:
    """Пассивное прослушивание UDP-объявлений устройств (стандартная библиотека).

    Пакеты на 6667/7000 зашифрованы, поэтому для разбора используется
    `tinytuya.decrypt_udp`; при отсутствии tinytuya пробуем открытый JSON.
    """
    decrypt = None
    try:
        import tinytuya

        decrypt = tinytuya.decrypt_udp
    except ImportError:
        pass

    sockets = []
    for port in SCAN_PORTS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(('', port))
        except OSError:
            sock.close()
            continue
        sock.setblocking(False)
        sockets.append(sock)

    found = []
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            for sock in sockets:
                try:
                    data, addr = sock.recvfrom(4096)
                except (BlockingIOError, OSError):
                    continue
                payload = None
                if decrypt is not None:
                    try:
                        payload = json.loads(decrypt(data))
                    except Exception:
                        payload = None
                if payload is None:
                    try:
                        payload = json.loads(data.decode('utf-8', 'replace'))
                    except (ValueError, UnicodeError):
                        continue
                if not isinstance(payload, dict):
                    continue
                gw_id = payload.get('gwId') or payload.get('id')
                if gw_id == dev_id and addr and addr[0]:
                    found.append((addr[0], payload.get('version')))
            time.sleep(0.05)
    finally:
        for sock in sockets:
            sock.close()
    return _unique(found)


def find_addresses(dev_id: str, seconds: float = 6.0,
                   use_scanner: bool = True) -> list[tuple[str, str | None]]:
    """Все известные адреса устройства: сначала активный скан, затем UDP."""
    if not dev_id:
        return []
    found = []
    if use_scanner:
        found.extend(scan_tinytuya(dev_id, seconds=seconds))
    found.extend(scan_udp(dev_id, seconds=seconds))
    return _unique(found)


def find_address(dev_id: str, seconds: float = 6.0,
                 use_scanner: bool = True) -> str | None:
    addresses = find_addresses(dev_id, seconds=seconds, use_scanner=use_scanner)
    return addresses[0][0] if addresses else None
