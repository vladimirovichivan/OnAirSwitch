#!/usr/bin/env python3
"""Одноразовая настройка: получить dev_id и local_key розетки Tuya и записать их
в secrets/tuya_plug.json (каталог secrets/ в .gitignore).

Секреты вводятся только в этом процессе: Access ID и Access Secret спрашиваются
интерактивно и нигде не печатаются. В вывод попадают лишь имя устройства, его IP
и признак "ключ получен".

Требуется аккаунт Tuya IoT Platform, Cloud-проект с привязанным аккаунтом
Smart Life и подписка на API "Smart Home Basic Service" (бесплатный trial).

  python tuya_setup.py                     # регион eu (Central Europe)
  python tuya_setup.py --region we         # Western Europe
  python tuya_setup.py --address 192.168.111.124
  python tuya_setup.py --verify            # только проверить настроенную розетку
  python tuya_setup.py --reconfigure       # записать ключи заново

После записи настроек скрипт сразу проверяет розетку тем же режимом `--verify`.
Повторный запуск без `--reconfigure` тоже выполняет проверку, а не отказывается
работать: для пользователя это один инструмент «настройка и проверка».

Для настройки достаточно стандартной библиотеки Python 3.9+. Проверка
переключает розетку и возвращает её в исходное состояние, поэтому требует
tinytuya и не запускается во время встречи (обойти — `--force`).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import tuya_discovery as discovery

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_OUT = REPO_ROOT / 'secrets' / 'tuya_plug.json'
DEFAULT_STATE = REPO_ROOT / 'data' / 'work' / 'meetings' / 'state.json'

REGIONS = {
    'eu': 'https://openapi.tuyaeu.com',
    'we': 'https://openapi-weaz.tuyaeu.com',
    'us': 'https://openapi.tuyaus.com',
    'in': 'https://openapi.tuyain.com',
    'cn': 'https://openapi.tuyacn.com',
}

EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()


class TuyaError(RuntimeError):
    pass


class TuyaCloud:
    def __init__(self, client_id: str, secret: str, region: str):
        self.client_id = client_id
        self.secret = secret
        self.base = REGIONS[region]
        self.token = None

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        body_str = json.dumps(body) if body is not None else ''
        content_hash = hashlib.sha256(body_str.encode()).hexdigest() if body_str else EMPTY_SHA256
        string_to_sign = f'{method}\n{content_hash}\n\n{path}'
        stamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        message = self.client_id + (self.token or '') + stamp + nonce + string_to_sign
        sign = hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).hexdigest().upper()

        headers = {
            'client_id': self.client_id,
            'sign': sign,
            'sign_method': 'HMAC-SHA256',
            't': stamp,
            'nonce': nonce,
            'Content-Type': 'application/json',
        }
        if self.token:
            headers['access_token'] = self.token

        request = urllib.request.Request(
            self.base + path,
            data=body_str.encode() if body_str else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            raise TuyaError(f'HTTP {exc.code} при обращении к {path}') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TuyaError(f'нет связи с {self.base}: {exc}') from exc

        if not payload.get('success'):
            raise TuyaError(f'API отказал на {path}: код {payload.get("code")} {payload.get("msg")}')
        return payload.get('result') or {}

    def connect(self) -> str:
        result = self._request('GET', '/v1.0/token?grant_type=1')
        self.token = result.get('access_token')
        if not self.token:
            raise TuyaError('в ответе нет access_token')
        uid = result.get('uid')
        if not uid:
            raise TuyaError('в ответе нет uid аккаунта')
        print(f'токен получен, аккаунт связан (uid …{uid[-4:]})')
        return uid

    def devices(self, uid: str) -> list[dict]:
        """Список устройств. Вызов /v1.0/users/{uid}/devices у части проектов
        запрещён (код 1106), поэтому есть резервный путь и обход вложенности."""
        found: dict[str, dict] = {}
        for path in (f'/v1.0/users/{uid}/devices', '/v1.0/iot-01/associated-users/devices'):
            try:
                result = self._request('GET', path)
            except TuyaError as exc:
                print(f'  список {path} недоступен: {exc}')
                continue
            for node in walk_dicts(result):
                if node.get('id') and ('name' in node or 'local_key' in node):
                    found[node['id']] = node
            if found:
                break
        return list(found.values())

    def device(self, device_id: str) -> dict:
        return self._request('GET', f'/v1.0/devices/{device_id}')


def mask(value: str) -> str:
    if not value:
        return '(пусто)'
    return value[:4] + '…' + value[-2:]


def walk_dicts(node):
    """Рекурсивно перебирает словари в ответе API (структура бывает вложенной)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_dicts(item)


def diagnose(cloud: TuyaCloud, uid: str, device_id: str) -> int:
    """Проверяет доступность разных эндпоинтов: видно, что именно запрещено."""
    checks = [
        ('список устройств аккаунта (Smart Home Basic)', f'/v1.0/users/{uid}/devices'),
        ('связанные аккаунты (Smart Home Basic)', '/v1.0/iot-01/associated-users/devices'),
    ]
    if device_id:
        checks.insert(0, ('карточка устройства (Smart Home Basic)', f'/v1.0/devices/{device_id}'))
    for title, path in checks:
        try:
            result = cloud._request('GET', path)
        except TuyaError as exc:
            print(f'  ✗ {title}: {exc}')
            continue
        size = len(result) if isinstance(result, list) else len(result.keys())
        print(f'  ✓ {title}: доступен (полей/записей: {size})')
        if path.endswith('/devices') and isinstance(result, list) and device_id:
            found = [d for d in result if d.get('id') == device_id]
            print(f'    устройство {mask(device_id)} в списке: {"да" if found else "нет"}')
    return 0


def _parse_switch(result, switch_dp: str) -> tuple[bool | None, str | None]:
    if not isinstance(result, dict) or 'dps' not in result:
        error = result.get('Error') if isinstance(result, dict) else result
        return None, f'нет ответа ({error})'
    value = (result.get('dps') or {}).get(str(switch_dp))
    if value is None:
        available = sorted((result.get('dps') or {}).keys())
        return None, f'в ответе нет DP {switch_dp}; доступны {available}'
    return str(value).lower() in ('true', '1', 'on'), None


def _connect(tinytuya, dev_id: str, address: str, local_key: str, version: str):
    device = tinytuya.OutletDevice(dev_id, address, local_key, version=float(version))
    device.set_version(float(version))
    device.set_socketTimeout(5)
    device.set_socketPersistent(False)
    return device


def _meeting_in_progress(state_path: Path) -> bool:
    try:
        data = json.loads(state_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return False
    if not data.get('meeting'):
        return False
    try:
        updated = time.mktime(time.strptime(data.get('updated'), '%Y-%m-%d %H:%M:%S'))
    except (TypeError, ValueError):
        return True
    return time.time() - updated <= 90


def verify(config_path: Path, override_address: str, force: bool) -> int:
    """Проверка настроенной розетки: поиск → чтение → переключение → возврат.

    Печатает имя, адрес, протокол, DP и состояние. `local_key` не печатается,
    `dev_id` — только маской.
    """
    if not config_path.exists():
        print(f'конфигурация не найдена: {config_path}')
        print('Сначала выполните настройку: python tuya_setup.py --address <IP>')
        return 1
    try:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        print(f'конфигурация не читается: {exc}')
        return 1
    dev_id = str(config.get('dev_id') or '')
    local_key = str(config.get('local_key') or '')
    if not dev_id or not local_key:
        print('в конфигурации нет dev_id или local_key — повторите настройку.')
        return 1
    switch_dp = str(config.get('switch_dp', '1'))
    version = str(config.get('version', '3.3'))

    if _meeting_in_progress(DEFAULT_STATE) and not force:
        print('сейчас идёт встреча: проверка переключила бы лампу.')
        print('Дождитесь окончания или запустите с --force, если это безопасно.')
        return 4

    try:
        import tinytuya
    except ImportError:
        print('tinytuya не установлен: для --verify нужен .venv или vendor.')
        return 2

    print('поиск розетки в локальной сети…')
    discovered = discovery.find_addresses(dev_id, seconds=6.0)
    addresses: list[str] = []
    if override_address:
        addresses.append(override_address)
    addresses.extend(ip for ip, _ in discovered)
    configured = str(config.get('address') or '')
    if configured and configured not in addresses:
        addresses.append(configured)
    if not addresses:
        print('устройство не найдено: проверьте, что розетка в той же сети.')
        return 5
    if discovered:
        print('  найдено UDP-поиском: ' + ', '.join(ip for ip, _ in discovered))
    else:
        print('  UDP-поиск не ответил, проверяю сохранённый адрес')

    versions = [version] + [item for item in ('3.3', '3.4', '3.5') if item != version]
    chosen = None
    for address in addresses:
        for candidate_version in versions:
            device = _connect(tinytuya, dev_id, address, local_key, candidate_version)
            try:
                result = device.status()
            except Exception as exc:
                print(f'  {address}, протокол {candidate_version}: '
                      f'{type(exc).__name__}: {exc}')
                continue
            state, error = _parse_switch(result, switch_dp)
            if error:
                print(f'  {address}, протокол {candidate_version}: {error}')
                continue
            chosen = (address, candidate_version, state, device)
            break
        if chosen:
            break
    if chosen is None:
        print('не удалось прочитать состояние: адрес отвечает, но ключ или протокол')
        print('не подошли. Проверьте, что розетку не перепривязывали в Smart Life.')
        return 6

    address, used_version, initial, device = chosen
    print('')
    print(f'  устройство: {config.get("name") or "розетка"}')
    print(f'  dev_id:     {mask(dev_id)}')
    print(f'  адрес:      {address}')
    print(f'  протокол:   {used_version}, DP {switch_dp}')
    print(f'  состояние:  {"включена" if initial else "выключена"}')

    target = not initial
    switched = False
    restored = None
    try:
        print(f'  переключаю: {"включить" if target else "выключить"}…')
        result = device.turn_on() if target else device.turn_off()
        if isinstance(result, dict) and result.get('Error'):
            print(f'  устройство отклонило команду: {result.get("Error")}')
            return 7
        switched = True
        time.sleep(1)
        state, error = _parse_switch(device.status(), switch_dp)
        if error:
            print(f'  не удалось подтвердить переключение: {error}')
            return 7
        if state != target:
            print('  состояние после команды не совпало с ожидаемым')
            return 7
        print(f'  подтверждено чтением: {"включена" if target else "выключена"}')
    finally:
        if switched:
            print(f'  возвращаю исходное состояние: '
                  f'{"включить" if initial else "выключить"}…')
            try:
                result = device.turn_on() if initial else device.turn_off()
                if isinstance(result, dict) and result.get('Error'):
                    print(f'  вернуть не удалось: {result.get("Error")}')
                else:
                    time.sleep(1)
                    restored, error = _parse_switch(device.status(), switch_dp)
                    if error:
                        print(f'  не удалось перечитать состояние: {error}')
                    elif restored != initial:
                        print('  внимание: исходное состояние не подтверждено')
                    else:
                        print(f'  исходное состояние восстановлено: '
                              f'{"включена" if initial else "выключена"}')
            except Exception as exc:
                print(f'  вернуть не удалось: {type(exc).__name__}: {exc}')

    print('')
    print('проверка пройдена: связь, ключ, DP и переключение работают.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Получение ключей Tuya и запись secrets/tuya_plug.json')
    parser.add_argument('--region', choices=sorted(REGIONS), default='eu', help='дата-центр проекта (по умолчанию eu)')
    parser.add_argument('--address', default='', help='IP розетки; при совпадении устройство выбирается без вопросов')
    parser.add_argument('--device-id', default='', help='Device ID для проверки в режиме --diagnose')
    parser.add_argument('--diagnose', action='store_true', help='только проверить доступность API, ничего не записывать')
    parser.add_argument('--verify', action='store_true',
                        help='проверить настроенную розетку: поиск, чтение, переключение и возврат')
    parser.add_argument('--force', action='store_true',
                        help='в режиме --verify переключать даже во время встречи')
    parser.add_argument('--reconfigure', action='store_true',
                        help='записать ключи заново, даже если файл настроек уже есть')
    parser.add_argument('--skip-verify', action='store_true',
                        help='не проверять розетку сразу после записи настроек')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='файл конфигурации: куда записать или что проверять в --verify')
    args = parser.parse_args()

    if args.verify:
        return verify(args.out, args.address, args.force)

    if args.out.exists() and not args.reconfigure and not args.diagnose:
        print(f'Розетка уже настроена: {args.out}')
        print('Выполняю проверку подключения (перезаписать ключи: --reconfigure).')
        return verify(args.out, args.address, args.force)

    print('Access ID и Access Secret из Tuya IoT Platform → ваш проект → Overview.')
    client_id = input('Access ID: ').strip()
    secret = getpass.getpass('Access Secret (ввод не отображается): ').strip()
    if not client_id or not secret:
        print('нужны оба значения')
        return 1

    cloud = TuyaCloud(client_id, secret, args.region)
    try:
        uid = cloud.connect()
        if args.diagnose:
            print('проверка API:')
            return diagnose(cloud, uid, args.device_id)
        chosen = None
        if args.device_id:
            # Явный Device ID: список устройств не требуется (у части проектов он запрещён).
            print(f'устройство задано явно: {mask(args.device_id)}')
            chosen = cloud.device(args.device_id)
        else:
            items = cloud.devices(uid)
            print(f'устройств в аккаунте: {len(items)}')
            if not items:
                print('Список пуст: проверьте привязку аккаунта Smart Life в проекте (Devices → Link Tuya App Account).')
                return 1

            if args.address:
                for item in items:
                    detail = cloud.device(item['id'])
                    if detail.get('ip') == args.address:
                        chosen = detail
                        break
                if chosen is None:
                    print(f'Устройство с IP {args.address} не найдено. Доступны:')
        if chosen is None:
            for index, item in enumerate(items, 1):
                detail = cloud.device(item['id'])
                print(f'  {index}. {item.get("name")} — id {mask(item["id"])}, ip {detail.get("ip") or "(нет)"}'
                      f', online {detail.get("online")}')
            while True:
                answer = input('Номер устройства: ').strip()
                if answer.isdigit() and 1 <= int(answer) <= len(items):
                    chosen = cloud.device(items[int(answer) - 1]['id'])
                    break
                print('введите номер из списка')
    except TuyaError as exc:
        print(f'ошибка: {exc}')
        print('Код 1106 — вызов API не разрешён этому проекту. Проверьте Service API проекта:')
        print('  Cloud → Development → ваш проект → Service API: у "Smart Home Basic Service"')
        print('  статус должен быть Subscribed/Authorized, а не Not subscribed/Expired.')
        print('  Если проект создавался кнопкой Skip вместо Authorize, подписки нет — подпишите вручную.')
        print('  После подписки подождите минуту и повторите; токен кэшируется на 2 часа, но права применяются сразу.')
        print('Быстрая проверка без записи файла: добавьте --diagnose --device-id REDACTED')
        return 2

    local_key = chosen.get('local_key')
    if not local_key:
        print('в ответе нет local_key: устройство может быть без локального протокола.')
        return 3

    cloud_ip = chosen.get('ip') or ''
    # Явно указанный LAN-адрес важнее: облако часто сообщает внешний IP, а локальный
    # протокол работает только по адресу в домашней сети.
    discovered_ip = ''
    print('')
    print('поиск адреса розетки в локальной сети (UDP)…')
    found = discovery.find_addresses(chosen['id'], seconds=6.0)
    if found:
        discovered_ip = found[0][0]
        print(f'  найден адрес: {discovered_ip}')
    else:
        print('  устройство не ответило на поиск; беру адрес из --address или облака')
    address = args.address or discovered_ip or cloud_ip
    if args.address and discovered_ip and args.address != discovered_ip:
        print(f'  внимание: поиск нашёл {discovered_ip}, но взят адрес из --address')

    config = {
        'name': chosen.get('name') or 'розетка',
        'dev_id': chosen['id'],
        'local_key': local_key,
        'address': address,
        'version': '3.3',
        'switch_dp': '1',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('')
    print(f'записано: {args.out}')
    print(f'  устройство: {config["name"]}')
    print(f'  dev_id:     {mask(config["dev_id"])}')
    print(f'  local_key:  получен ({len(local_key)} символов)')
    print(f'  адрес:      {config["address"] or "(не указан)"}')
    if cloud_ip and args.address and cloud_ip != args.address:
        print(f'  (облако сообщает {cloud_ip} — это внешний IP; взят адрес из --address)')
    if not args.address:
        print('  внимание: адрес взят из облака и может быть внешним IP; для локального')
        print('  протокола укажите --address <IP в домашней сети> и повторите.')
    print('')
    if args.skip_verify:
        print('Проверка пропущена (--skip-verify).')
    else:
        print('Проверка подключения: чтение, переключение и возврат состояния.')
        result = verify(args.out, args.address, args.force)
        print('')
        if result == 0:
            print('Настройка и проверка завершены: розетка работает.')
        elif result == 4:
            print('Настройки сохранены. Сейчас идёт встреча, поэтому переключение')
            print('не проверялось; проверка повторится при следующем запуске мастера.')
        else:
            print(f'Настройки сохранены, но проверка не пройдена (код {result}).')
            print('Приложение всё равно запустится; если лампа не работает — SUPPORT.md.')
    print('Повторная проверка: setup.cmd или tuya_setup.py --verify.')
    print('Если подключение не удастся, версия протокола подбирается: 3.3 → 3.4 → 3.5.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
