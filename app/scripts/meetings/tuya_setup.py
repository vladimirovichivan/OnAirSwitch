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

Только стандартная библиотека Python 3.9+.
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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_OUT = REPO_ROOT / 'secrets' / 'tuya_plug.json'

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


def main() -> int:
    parser = argparse.ArgumentParser(description='Получение ключей Tuya и запись secrets/tuya_plug.json')
    parser.add_argument('--region', choices=sorted(REGIONS), default='eu', help='дата-центр проекта (по умолчанию eu)')
    parser.add_argument('--address', default='', help='IP розетки; при совпадении устройство выбирается без вопросов')
    parser.add_argument('--device-id', default='', help='Device ID для проверки в режиме --diagnose')
    parser.add_argument('--diagnose', action='store_true', help='только проверить доступность API, ничего не записывать')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.out.exists():
        print(f'{args.out} уже существует — перезапись не выполняется.')
        print('Удалите файл вручную, если действительно нужны новые ключи.')
        return 1

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
    address = args.address or cloud_ip

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
    print('Проверка: python plug_executor.py --once  (dry-run, устройство не переключается)')
    print('Если подключение не удастся, версия протокола подбирается: 3.3 → 3.4 → 3.5.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
