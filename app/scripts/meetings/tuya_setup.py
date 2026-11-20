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

import i18n
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
            raise TuyaError(i18n.t('setup_http_error', code=exc.code,
                                   path=path)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TuyaError(i18n.t('setup_conn_error', base=self.base,
                                   error=exc)) from exc

        if not payload.get('success'):
            raise TuyaError(i18n.t('setup_api_error', path=path,
                                   code=payload.get('code'),
                                   message=payload.get('msg')))
        return payload.get('result') or {}

    def connect(self) -> str:
        result = self._request('GET', '/v1.0/token?grant_type=1')
        self.token = result.get('access_token')
        if not self.token:
            raise TuyaError(i18n.t('setup_no_token'))
        uid = result.get('uid')
        if not uid:
            raise TuyaError(i18n.t('setup_no_uid'))
        print(i18n.t('setup_token_ok', tail=uid[-4:]))
        return uid

    def devices(self, uid: str) -> list[dict]:
        """Список устройств. Вызов /v1.0/users/{uid}/devices у части проектов
        запрещён (код 1106), поэтому есть резервный путь и обход вложенности."""
        found: dict[str, dict] = {}
        for path in (f'/v1.0/users/{uid}/devices', '/v1.0/iot-01/associated-users/devices'):
            try:
                result = self._request('GET', path)
            except TuyaError as exc:
                print(i18n.t('setup_list_unavailable', path=path, error=exc))
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
        return i18n.t('setup_empty_value')
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
        (i18n.t('setup_user_devices'), f'/v1.0/users/{uid}/devices'),
        (i18n.t('setup_associated'), '/v1.0/iot-01/associated-users/devices'),
    ]
    if device_id:
        checks.insert(0, (i18n.t('setup_device_card'), f'/v1.0/devices/{device_id}'))
    for title, path in checks:
        try:
            result = cloud._request('GET', path)
        except TuyaError as exc:
            print(i18n.t('setup_check_failed', title=title, error=exc))
            continue
        size = len(result) if isinstance(result, list) else len(result.keys())
        print(i18n.t('setup_check_ok', title=title, size=size))
        if path.endswith('/devices') and isinstance(result, list) and device_id:
            found = [d for d in result if d.get('id') == device_id]
            print(i18n.t('setup_device_in_list', mask=mask(device_id),
                         answer=i18n.t('setup_yes') if found else i18n.t('setup_no')))
    return 0


def _parse_switch(result, switch_dp: str) -> tuple[bool | None, str | None]:
    if not isinstance(result, dict) or 'dps' not in result:
        error = result.get('Error') if isinstance(result, dict) else result
        return None, i18n.t('setup_no_response', error=error)
    value = (result.get('dps') or {}).get(str(switch_dp))
    if value is None:
        available = sorted((result.get('dps') or {}).keys())
        return None, i18n.t('setup_no_dp', dp=switch_dp, available=available)
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
        print(i18n.t('setup_config_missing', path=config_path))
        print(i18n.t('setup_config_missing_hint'))
        return 1
    try:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        print(i18n.t('setup_config_unreadable', error=exc))
        return 1
    dev_id = str(config.get('dev_id') or '')
    local_key = str(config.get('local_key') or '')
    if not dev_id or not local_key:
        print(i18n.t('setup_config_incomplete'))
        return 1
    switch_dp = str(config.get('switch_dp', '1'))
    version = str(config.get('version', '3.3'))

    if _meeting_in_progress(DEFAULT_STATE) and not force:
        print(i18n.t('setup_meeting'))
        print(i18n.t('setup_meeting_hint'))
        return 4

    try:
        import tinytuya
    except ImportError:
        print(i18n.t('setup_no_tinytuya'))
        return 2

    print(i18n.t('setup_searching'))
    discovered = discovery.find_addresses(dev_id, seconds=6.0)
    addresses: list[str] = []
    if override_address:
        addresses.append(override_address)
    addresses.extend(ip for ip, _ in discovered)
    configured = str(config.get('address') or '')
    if configured and configured not in addresses:
        addresses.append(configured)
    if not addresses:
        print(i18n.t('setup_not_found'))
        return 5
    if discovered:
        print(i18n.t('setup_found_udp',
                     addresses=', '.join(ip for ip, _ in discovered)))
    else:
        print(i18n.t('setup_udp_silent'))

    versions = [version] + [item for item in ('3.3', '3.4', '3.5') if item != version]
    chosen = None
    for address in addresses:
        for candidate_version in versions:
            device = _connect(tinytuya, dev_id, address, local_key, candidate_version)
            try:
                result = device.status()
            except Exception as exc:
                print(i18n.t('setup_protocol_error', address=address,
                             version=candidate_version,
                             error=f'{type(exc).__name__}: {exc}'))
                continue
            state, error = _parse_switch(result, switch_dp)
            if error:
                print(i18n.t('setup_protocol_error', address=address,
                             version=candidate_version, error=error))
                continue
            chosen = (address, candidate_version, state, device)
            break
        if chosen:
            break
    if chosen is None:
        print(i18n.t('setup_read_failed'))
        print(i18n.t('setup_read_failed_hint'))
        return 6

    address, used_version, initial, device = chosen
    print('')
    print(i18n.t('setup_device', name=config.get('name') or i18n.t('setup_default_name')))
    print(i18n.t('setup_dev_id', mask=mask(dev_id)))
    print(i18n.t('setup_address', address=address))
    print(i18n.t('setup_protocol', version=used_version, dp=switch_dp))
    print(i18n.t('setup_state', state=i18n.t(
        'setup_state_on' if initial else 'setup_state_off')))

    target = not initial
    switched = False
    restored = None
    try:
        print(i18n.t('setup_switching_on' if target else 'setup_switching_off'))
        result = device.turn_on() if target else device.turn_off()
        if isinstance(result, dict) and result.get('Error'):
            print(i18n.t('setup_rejected', error=result.get('Error')))
            return 7
        switched = True
        time.sleep(1)
        state, error = _parse_switch(device.status(), switch_dp)
        if error:
            print(i18n.t('setup_confirm_failed', error=error))
            return 7
        if state != target:
            print(i18n.t('setup_mismatch'))
            return 7
        print(i18n.t('setup_confirmed', state=i18n.t(
            'setup_state_on' if target else 'setup_state_off')))
    finally:
        if switched:
            print(i18n.t('setup_restoring_on' if initial
                         else 'setup_restoring_off'))
            try:
                result = device.turn_on() if initial else device.turn_off()
                if isinstance(result, dict) and result.get('Error'):
                    print(i18n.t('setup_restore_failed',
                                 error=result.get('Error')))
                else:
                    time.sleep(1)
                    restored, error = _parse_switch(device.status(), switch_dp)
                    if error:
                        print(i18n.t('setup_reread_failed', error=error))
                    elif restored != initial:
                        print(i18n.t('setup_restore_unconfirmed'))
                    else:
                        print(i18n.t('setup_restored', state=i18n.t(
                            'setup_state_on' if initial else 'setup_state_off')))
            except Exception as exc:
                print(i18n.t('setup_restore_failed',
                             error=f'{type(exc).__name__}: {exc}'))

    print('')
    print(i18n.t('setup_verify_passed'))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t('setup_arg_description'))
    parser.add_argument('--region', choices=sorted(REGIONS), default='eu', help=i18n.t('setup_arg_region'))
    parser.add_argument('--address', default='', help=i18n.t('setup_arg_address'))
    parser.add_argument('--device-id', default='', help=i18n.t('setup_arg_device_id'))
    parser.add_argument('--diagnose', action='store_true', help=i18n.t('setup_arg_diagnose'))
    parser.add_argument('--verify', action='store_true',
                        help=i18n.t('setup_arg_verify'))
    parser.add_argument('--force', action='store_true',
                        help=i18n.t('setup_arg_force'))
    parser.add_argument('--reconfigure', action='store_true',
                        help=i18n.t('setup_arg_reconfigure'))
    parser.add_argument('--skip-verify', action='store_true',
                        help=i18n.t('setup_arg_skip_verify'))
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help=i18n.t('setup_arg_out'))
    args = parser.parse_args()

    if args.verify:
        return verify(args.out, args.address, args.force)

    if args.out.exists() and not args.reconfigure and not args.diagnose:
        print(i18n.t('setup_already', path=args.out))
        print(i18n.t('setup_already_hint'))
        return verify(args.out, args.address, args.force)

    print(i18n.t('setup_credentials_hint'))
    client_id = input(i18n.t('setup_access_id')).strip()
    secret = getpass.getpass(i18n.t('setup_access_secret')).strip()
    if not client_id or not secret:
        print(i18n.t('setup_credentials_required'))
        return 1

    cloud = TuyaCloud(client_id, secret, args.region)
    try:
        uid = cloud.connect()
        if args.diagnose:
            print(i18n.t('setup_api_check'))
            return diagnose(cloud, uid, args.device_id)
        chosen = None
        if args.device_id:
            # Явный Device ID: список устройств не требуется (у части проектов он запрещён).
            print(i18n.t('setup_explicit_device', mask=mask(args.device_id)))
            chosen = cloud.device(args.device_id)
        else:
            items = cloud.devices(uid)
            print(i18n.t('setup_devices_count', count=len(items)))
            if not items:
                print(i18n.t('setup_empty_list'))
                return 1

            if args.address:
                for item in items:
                    detail = cloud.device(item['id'])
                    if detail.get('ip') == args.address:
                        chosen = detail
                        break
                if chosen is None:
                    print(i18n.t('setup_ip_not_found', address=args.address))
        if chosen is None:
            for index, item in enumerate(items, 1):
                detail = cloud.device(item['id'])
                print(f'  {index}. {item.get("name")} — id {mask(item["id"])}, '
                      f'ip {detail.get("ip") or "(none)"}'
                      f', online {detail.get("online")}')
            while True:
                answer = input(i18n.t('setup_choose_number')).strip()
                if answer.isdigit() and 1 <= int(answer) <= len(items):
                    chosen = cloud.device(items[int(answer) - 1]['id'])
                    break
                print(i18n.t('setup_enter_number'))
    except TuyaError as exc:
        print(i18n.t('setup_error', error=exc))
        print(i18n.t('setup_1106'))
        print(i18n.t('setup_1106_service'))
        print(i18n.t('setup_1106_status'))
        print(i18n.t('setup_1106_skip'))
        print(i18n.t('setup_1106_wait'))
        print(i18n.t('setup_1106_quick'))
        return 2

    local_key = chosen.get('local_key')
    if not local_key:
        print(i18n.t('setup_no_local_key'))
        return 3

    cloud_ip = chosen.get('ip') or ''
    # Явно указанный LAN-адрес важнее: облако часто сообщает внешний IP, а локальный
    # протокол работает только по адресу в домашней сети.
    discovered_ip = ''
    print('')
    print(i18n.t('setup_search_address'))
    found = discovery.find_addresses(chosen['id'], seconds=6.0)
    if found:
        discovered_ip = found[0][0]
        print(i18n.t('setup_found_address', address=discovered_ip))
    else:
        print(i18n.t('setup_address_fallback'))
    address = args.address or discovered_ip or cloud_ip
    if args.address and discovered_ip and args.address != discovered_ip:
        print(i18n.t('setup_address_warning', found=discovered_ip))

    config = {
        'name': chosen.get('name') or i18n.t('setup_default_name'),
        'dev_id': chosen['id'],
        'local_key': local_key,
        'address': address,
        'version': '3.3',
        'switch_dp': '1',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('')
    print(i18n.t('setup_written', path=args.out))
    print(i18n.t('setup_device', name=config["name"]))
    print(i18n.t('setup_dev_id', mask=mask(config["dev_id"])))
    print(i18n.t('setup_local_key_ok', length=len(local_key)))
    if config["address"]:
        print(i18n.t('setup_address', address=config["address"]))
    else:
        print(i18n.t('setup_address_unset'))
    if cloud_ip and args.address and cloud_ip != args.address:
        print(i18n.t('setup_cloud_external', ip=cloud_ip))
    if not args.address:
        print(i18n.t('setup_cloud_warning'))
    print('')
    if args.skip_verify:
        print(i18n.t('setup_verify_skipped'))
    else:
        print(i18n.t('setup_verify_start'))
        result = verify(args.out, args.address, args.force)
        print('')
        if result == 0:
            print(i18n.t('setup_done'))
        elif result == 4:
            print(i18n.t('setup_saved_meeting'))
        else:
            print(i18n.t('setup_saved_failed', code=result))
            print(i18n.t('setup_will_start'))
    print(i18n.t('setup_repeat'))
    print(i18n.t('setup_protocol_fallback'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
