#!/usr/bin/env python3
"""Локализация интерфейса OnAir Lamp: русский и английский.

Язык интерфейса выбирается в трее: «Авто» (по языку Windows), «Русский» или
«English». Выбор хранится в `data/work/meetings/settings.json` рядом с
состоянием приложения, поэтому обновление программы его не сбрасывает.

Переводятся только пользовательские строки: меню трея, уведомления, мастер
настройки и вывод CLI. Технические журналы (`plug.log`, `events.log`,
`tray.log`, `supervisor.log`) остаются на русском: их читает поддержка, а не
пользователь.

Модуль не зависит от Windows: если язык системы узнать не удалось, берётся
английский.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SETTINGS_PATH = REPO_ROOT / 'data' / 'work' / 'meetings' / 'settings.json'

LANGUAGE_AUTO = 'auto'
LANGUAGE_RU = 'ru'
LANGUAGE_EN = 'en'
LANGUAGES = (LANGUAGE_AUTO, LANGUAGE_RU, LANGUAGE_EN)
DEFAULT_LANGUAGE = LANGUAGE_EN

MESSAGES: dict[str, dict[str, str]] = {
    'ru': {
        # Длительность и сроки
        'less_than_minute': 'меньше минуты',
        'duration_min': '{minutes} мин',
        'duration_hm': '{hours} ч {minutes:02d} мин',
        'duration_h': '{hours} ч',
        'remaining': ' · осталось {duration}',
        # Встреча и лампа
        'meeting': 'Встреча: {names}',
        'meeting_with_duration': 'Встреча: {names} · {duration}',
        'lamp_not_configured': 'Лампа: розетка не настроена — «Настроить розетку…»',
        'lamp_no_data': 'Лампа: нет данных (исполнитель не запущен)',
        'lamp_stale': 'Лампа: ? — исполнитель не отвечает (статус от {stamp})',
        'lamp_on': 'включена',
        'lamp_off': 'выключена',
        'lamp_unknown': 'состояние неизвестно',
        'lamp_state': 'Лампа: {state}',
        'lamp_checked': 'Лампа: {state} · проверено {checked}',
        'mode': 'Режим: {description}',
        'reason_executor_down': 'Исполнитель не отвечает — статус и команды могут не работать',
        'reason_watcher_down': 'Нет данных о встречах — наблюдатель не отвечает',
        'reason_meeting_lamp_off': 'Встреча идёт, а лампа выключена — откройте plug.log',
        'reason_meeting_manual_off': 'Встреча идёт, но лампа выключена вручную',
        'reason_no_meeting_manual_on': 'Встреч нет, лампа включена вручную',
        'reason_paused': 'Автоматика снята — лампа не меняется',
        'error_device': 'Ошибка устройства: {error}',
        # Заголовок значка
        'title': 'OnAir Lamp: {state} · {mode}',
        'title_meeting': ' · встреча {names}',
        'title_meeting_duration': ' · встреча {names} {duration}',
        'state_not_configured': 'розетка не настроена',
        'state_on': 'включена',
        'state_off': 'выключена',
        'state_paused': 'автоматика снята',
        'state_unknown': 'нет данных',
        # Режимы (plug_control.describe)
        'desc_auto': 'автоматика по встречам',
        'desc_paused': 'автоматика снята',
        'desc_on': 'включена вручную',
        'desc_off': 'выключена вручную',
        'desc_manual_until': '{base}, до ручного возврата',
        'desc_until': '{base} до {time}',
        # Действия и уведомления
        'act_failed': 'Не удалось записать режим: {error}',
        'log_open_failed': 'Не удалось открыть журнал: {error}',
        'events_open_failed': 'Не удалось открыть журнал встреч: {error}',
        'verify_missing': 'Не найден verify.cmd — переустановите OnAir Lamp.',
        'verify_failed': 'Не удалось проверить розетку: {error}',
        'report_missing': 'Не найден report_support.py — переустановите OnAir Lamp.',
        'report_failed': 'Не удалось собрать отчёт: {error}',
        'report_saved': 'Отчёт на рабочем столе: {name}',
        'report_failed_log': 'Не удалось собрать отчёт — подробности в tray.log.',
        'setup_missing': 'Не найден setup.cmd — переустановите OnAir Lamp.',
        'setup_failed': 'Не удалось открыть настройку: {error}',
        'first_run_title': 'OnAir Lamp',
        'first_run_text': (
            'Розетка ещё не настроена, поэтому лампа пока не будет реагировать '
            'на встречи.\n\n'
            'Открыть мастер настройки? Для него нужны Access ID и Access Secret '
            'из Tuya IoT Platform (шаги 3.1–3.4 инструкции).\n\n'
            'Настроить можно и позже: значок лампы в трее → «Настроить розетку…».'
        ),
        # Меню
        'menu_on': 'Включить',
        'menu_off': 'Выключить',
        'menu_auto': 'Автоматика по встречам',
        'menu_pause': 'Снять автоматику',
        'menu_setup': 'Настроить розетку…',
        'menu_verify': 'Проверить розетку',
        'menu_plug_log': 'Открыть plug.log',
        'menu_events_log': 'Открыть журнал встреч',
        'menu_report': 'Отчёт для поддержки',
        'menu_exit': 'Выход',
        'menu_language': 'Язык',
        'lang_auto': 'Авто (по языку Windows)',
        'lang_ru': 'Русский',
        'lang_en': 'English',
        'deadline_1h': 'на 1 час',
        'deadline_2h': 'на 2 часа',
        'deadline_eod': 'до конца дня',
        'deadline_manual': 'до ручного возврата',
        # Обновления
        'menu_update_check': 'Проверить обновления…',
        'menu_update_checking': 'Проверка обновлений…',
        'menu_update_downloading': 'Загрузка обновления {version}…',
        'menu_update_install': 'Установить обновление {version}…',
        'menu_version': 'Версия {version}',
        'update_available': 'Доступно обновление {version}',
        'update_up_to_date': 'Установлена последняя версия {version}',
        'update_check_failed': 'Не удалось проверить обновления: {error}',
        'update_confirm_title': 'Обновление OnAir Lamp',
        'update_confirm': (
            'Скачать и установить обновление {version}?\n\n'
            'Приложение закроется, установщик заменит файлы, затем OnAir Lamp '
            'запустится снова. Настройки розетки сохранятся.'
        ),
        'update_dev_only': 'Обновление доступно только в установленной копии.',
        'update_download_failed': 'Не удалось скачать обновление: {error}',
        'update_bad_checksum': 'Файл обновления повреждён (не совпала контрольная сумма).',
        'update_launching': 'Запускаю установщик обновления {version}…',
        'update_install_failed': 'Не удалось запустить установщик: {error}',
        'update_install_unavailable': 'В выпуске нет установщика для этого обновления.',
        # CLI plug_control
        'cli_mode': 'mode: {mode} ({description})',
        'cli_expired': 'control.json: {mode} просрочен, исполнитель вернёт auto',
        'cli_control_updated': 'control updated: {stamp} (source {source})',
        'cli_status_missing': 'executor: plug_state.json отсутствует',
        'cli_not_configured': 'executor: розетка не настроена (мастер настройки ещё не пройден)',
        'cli_lamp': 'lamp: {state}{suffix}',
        'cli_heartbeat': 'executor: heartbeat {stamp}; режим исполнителя {mode}',
        'cli_error': 'error: {error}',
        'cli_failed': 'failed: {error}',
        'cli_applied': (
            'исполнитель применит режим в течение нескольких секунд '
            '(если он запущен и состояние устройства читается)'
        ),
        # Мастер настройки Tuya
        'setup_http_error': 'HTTP {code} при обращении к {path}',
        'setup_conn_error': 'нет связи с {base}: {error}',
        'setup_api_error': 'API отказал на {path}: код {code} {message}',
        'setup_empty_value': '(пусто)',
        'setup_arg_description': 'Получение ключей Tuya и запись secrets/tuya_plug.json',
        'setup_arg_region': 'дата-центр проекта (по умолчанию eu)',
        'setup_arg_address': 'IP розетки; при совпадении устройство выбирается без вопросов',
        'setup_arg_device_id': 'Device ID для проверки в режиме --diagnose',
        'setup_arg_diagnose': 'только проверить доступность API, ничего не записывать',
        'setup_arg_verify': 'проверить настроенную розетку: поиск, чтение, переключение и возврат',
        'setup_arg_force': 'в режиме --verify переключать даже во время встречи',
        'setup_arg_reconfigure': 'записать ключи заново, даже если файл настроек уже есть',
        'setup_arg_skip_verify': 'не проверять розетку сразу после записи настроек',
        'setup_arg_out': 'файл конфигурации: куда записать или что проверять в --verify',
        'setup_no_token': 'в ответе нет access_token',
        'setup_no_uid': 'в ответе нет uid аккаунта',
        'setup_token_ok': 'токен получен, аккаунт связан (uid …{tail})',
        'setup_list_unavailable': '  список {path} недоступен: {error}',
        'setup_device_card': 'карточка устройства (Smart Home Basic)',
        'setup_user_devices': 'список устройств аккаунта (Smart Home Basic)',
        'setup_associated': 'связанные аккаунты (Smart Home Basic)',
        'setup_check_failed': '  ✗ {title}: {error}',
        'setup_check_ok': '  ✓ {title}: доступен (полей/записей: {size})',
        'setup_device_in_list': '    устройство {mask} в списке: {answer}',
        'setup_yes': 'да',
        'setup_no': 'нет',
        'setup_config_missing': 'конфигурация не найдена: {path}',
        'setup_config_missing_hint': 'Сначала выполните настройку: python tuya_setup.py --address <IP>',
        'setup_config_unreadable': 'конфигурация не читается: {error}',
        'setup_config_incomplete': 'в конфигурации нет dev_id или local_key — повторите настройку.',
        'setup_meeting': 'сейчас идёт встреча: проверка переключила бы лампу.',
        'setup_meeting_hint': 'Дождитесь окончания или запустите с --force, если это безопасно.',
        'setup_no_tinytuya': 'tinytuya не установлен: для --verify нужен .venv или vendor.',
        'setup_searching': 'поиск розетки в локальной сети…',
        'setup_not_found': 'устройство не найдено: проверьте, что розетка в той же сети.',
        'setup_found_udp': '  найдено UDP-поиском: {addresses}',
        'setup_udp_silent': '  UDP-поиск не ответил, проверяю сохранённый адрес',
        'setup_protocol_error': '  {address}, протокол {version}: {error}',
        'setup_no_response': 'нет ответа ({error})',
        'setup_no_dp': 'в ответе нет DP {dp}; доступны {available}',
        'setup_read_failed': 'не удалось прочитать состояние: адрес отвечает, но ключ или протокол',
        'setup_read_failed_hint': 'не подошли. Проверьте, что розетку не перепривязывали в Smart Life.',
        'setup_device': '  устройство: {name}',
        'setup_dev_id': '  dev_id:     {mask}',
        'setup_address': '  адрес:      {address}',
        'setup_protocol': '  протокол:   {version}, DP {dp}',
        'setup_state': '  состояние:  {state}',
        'setup_state_on': 'включена',
        'setup_state_off': 'выключена',
        'setup_switching_on': '  переключаю: включить…',
        'setup_switching_off': '  переключаю: выключить…',
        'setup_rejected': '  устройство отклонило команду: {error}',
        'setup_confirm_failed': '  не удалось подтвердить переключение: {error}',
        'setup_mismatch': '  состояние после команды не совпало с ожидаемым',
        'setup_confirmed': '  подтверждено чтением: {state}',
        'setup_restoring_on': '  возвращаю исходное состояние: включить…',
        'setup_restoring_off': '  возвращаю исходное состояние: выключить…',
        'setup_restore_failed': '  вернуть не удалось: {error}',
        'setup_reread_failed': '  не удалось перечитать состояние: {error}',
        'setup_restore_unconfirmed': '  внимание: исходное состояние не подтверждено',
        'setup_restored': '  исходное состояние восстановлено: {state}',
        'setup_verify_passed': 'проверка пройдена: связь, ключ, DP и переключение работают.',
        'setup_already': 'Розетка уже настроена: {path}',
        'setup_already_hint': 'Выполняю проверку подключения (перезаписать ключи: --reconfigure).',
        'setup_credentials_hint': 'Access ID и Access Secret из Tuya IoT Platform → ваш проект → Overview.',
        'setup_access_id': 'Access ID: ',
        'setup_access_secret': 'Access Secret (ввод не отображается): ',
        'setup_credentials_required': 'нужны оба значения',
        'setup_api_check': 'проверка API:',
        'setup_explicit_device': 'устройство задано явно: {mask}',
        'setup_devices_count': 'устройств в аккаунте: {count}',
        'setup_empty_list': 'Список пуст: проверьте привязку аккаунта Smart Life в проекте (Devices → Link Tuya App Account).',
        'setup_ip_not_found': 'Устройство с IP {address} не найдено. Доступны:',
        'setup_choose_number': 'Номер устройства: ',
        'setup_enter_number': 'введите номер из списка',
        'setup_error': 'ошибка: {error}',
        'setup_1106': 'Код 1106 — вызов API не разрешён этому проекту. Проверьте Service API проекта:',
        'setup_1106_service': '  Cloud → Development → ваш проект → Service API: у "Smart Home Basic Service"',
        'setup_1106_status': '  статус должен быть Subscribed/Authorized, а не Not subscribed/Expired.',
        'setup_1106_skip': '  Если проект создавался кнопкой Skip вместо Authorize, подписки нет — подпишите вручную.',
        'setup_1106_wait': '  После подписки подождите минуту и повторите; токен кэшируется на 2 часа, но права применяются сразу.',
        'setup_1106_quick': 'Быстрая проверка без записи файла: добавьте --diagnose --device-id <id>',
        'setup_no_local_key': 'в ответе нет local_key: устройство может быть без локального протокола.',
        'setup_default_name': 'розетка',
        'setup_search_address': 'поиск адреса розетки в локальной сети (UDP)…',
        'setup_found_address': '  найден адрес: {address}',
        'setup_address_fallback': '  устройство не ответило на поиск; беру адрес из --address или облака',
        'setup_address_warning': '  внимание: поиск нашёл {found}, но взят адрес из --address',
        'setup_written': 'записано: {path}',
        'setup_local_key_ok': '  local_key:  получен ({length} символов)',
        'setup_address_unset': '  адрес:      (не указан)',
        'setup_cloud_external': '  (облако сообщает {ip} — это внешний IP; взят адрес из --address)',
        'setup_cloud_warning': (
            '  внимание: адрес взят из облака и может быть внешним IP; для локального\n'
            '  протокола укажите --address <IP в домашней сети> и повторите.'
        ),
        'setup_verify_skipped': 'Проверка пропущена (--skip-verify).',
        'setup_verify_start': 'Проверка подключения: чтение, переключение и возврат состояния.',
        'setup_done': 'Настройка и проверка завершены: розетка работает.',
        'setup_saved_meeting': (
            'Настройки сохранены. Сейчас идёт встреча, поэтому переключение\n'
            'не проверялось; проверка повторится при следующем запуске мастера.'
        ),
        'setup_saved_failed': 'Настройки сохранены, но проверка не пройдена (код {code}).',
        'setup_will_start': 'Приложение всё равно запустится; если лампа не работает — SUPPORT.md.',
        'setup_repeat': 'Повторная проверка: setup.cmd или tuya_setup.py --verify.',
        'setup_protocol_fallback': 'Если подключение не удастся, версия протокола подбирается: 3.3 → 3.4 → 3.5.',
    },
    'en': {
        'less_than_minute': 'less than a minute',
        'duration_min': '{minutes} min',
        'duration_hm': '{hours} h {minutes:02d} min',
        'duration_h': '{hours} h',
        'remaining': ' · {duration} left',
        'meeting': 'Meeting: {names}',
        'meeting_with_duration': 'Meeting: {names} · {duration}',
        'lamp_not_configured': 'Lamp: socket is not set up — “Set up the socket…”',
        'lamp_no_data': 'Lamp: no data (executor is not running)',
        'lamp_stale': 'Lamp: ? — executor is not responding (status from {stamp})',
        'lamp_on': 'on',
        'lamp_off': 'off',
        'lamp_unknown': 'state unknown',
        'lamp_state': 'Lamp: {state}',
        'lamp_checked': 'Lamp: {state} · checked {checked}',
        'mode': 'Mode: {description}',
        'reason_executor_down': 'The executor is not responding — status and commands may not work',
        'reason_watcher_down': 'No meeting data — the watcher is not responding',
        'reason_meeting_lamp_off': 'A meeting is in progress but the lamp is off — open plug.log',
        'reason_meeting_manual_off': 'A meeting is in progress but the lamp was turned off manually',
        'reason_no_meeting_manual_on': 'No meetings, the lamp was turned on manually',
        'reason_paused': 'Automation is paused — the lamp will not change',
        'error_device': 'Device error: {error}',
        'title': 'OnAir Lamp: {state} · {mode}',
        'title_meeting': ' · meeting {names}',
        'title_meeting_duration': ' · meeting {names} {duration}',
        'state_not_configured': 'socket is not set up',
        'state_on': 'on',
        'state_off': 'off',
        'state_paused': 'automation paused',
        'state_unknown': 'no data',
        'desc_auto': 'automation by meetings',
        'desc_paused': 'automation paused',
        'desc_on': 'turned on manually',
        'desc_off': 'turned off manually',
        'desc_manual_until': '{base}, until manual release',
        'desc_until': '{base} until {time}',
        'act_failed': 'Failed to save the mode: {error}',
        'log_open_failed': 'Failed to open the log: {error}',
        'events_open_failed': 'Failed to open the meeting log: {error}',
        'verify_missing': 'verify.cmd not found — reinstall OnAir Lamp.',
        'verify_failed': 'Failed to verify the socket: {error}',
        'report_missing': 'report_support.py not found — reinstall OnAir Lamp.',
        'report_failed': 'Failed to build the report: {error}',
        'report_saved': 'Report saved to Desktop: {name}',
        'report_failed_log': 'Failed to build the report — see tray.log.',
        'setup_missing': 'setup.cmd not found — reinstall OnAir Lamp.',
        'setup_failed': 'Failed to open setup: {error}',
        'first_run_title': 'OnAir Lamp',
        'first_run_text': (
            'The socket is not set up yet, so the lamp will not respond to '
            'meetings.\n\n'
            'Open the setup wizard? It needs the Access ID and Access Secret '
            'from Tuya IoT Platform (steps 3.1–3.4 of the instructions).\n\n'
            'You can also do this later: lamp icon in the tray → “Set up the socket…”.'
        ),
        'menu_on': 'Turn on',
        'menu_off': 'Turn off',
        'menu_auto': 'Automation by meetings',
        'menu_pause': 'Pause automation',
        'menu_setup': 'Set up the socket…',
        'menu_verify': 'Verify the socket',
        'menu_plug_log': 'Open plug.log',
        'menu_events_log': 'Open meeting log',
        'menu_report': 'Support report',
        'menu_exit': 'Exit',
        'menu_language': 'Language',
        'lang_auto': 'Auto (Windows language)',
        'lang_ru': 'Русский',
        'lang_en': 'English',
        'deadline_1h': 'for 1 hour',
        'deadline_2h': 'for 2 hours',
        'deadline_eod': 'until end of day',
        'deadline_manual': 'until manual release',
        'menu_update_check': 'Check for updates…',
        'menu_update_checking': 'Checking for updates…',
        'menu_update_downloading': 'Downloading update {version}…',
        'menu_update_install': 'Install update {version}…',
        'menu_version': 'Version {version}',
        'update_available': 'Update {version} is available',
        'update_up_to_date': 'The latest version {version} is installed',
        'update_check_failed': 'Failed to check for updates: {error}',
        'update_confirm_title': 'OnAir Lamp update',
        'update_confirm': (
            'Download and install update {version}?\n\n'
            'The app will close, the installer will replace the files, and then '
            'OnAir Lamp will start again. The socket settings will be kept.'
        ),
        'update_dev_only': 'Updates are only available in the installed copy.',
        'update_download_failed': 'Failed to download the update: {error}',
        'update_bad_checksum': 'The update file is corrupted (checksum mismatch).',
        'update_launching': 'Starting the update installer {version}…',
        'update_install_failed': 'Failed to start the installer: {error}',
        'update_install_unavailable': 'This release has no installer for the update.',
        'cli_mode': 'mode: {mode} ({description})',
        'cli_expired': 'control.json: {mode} has expired, the executor will return to auto',
        'cli_control_updated': 'control updated: {stamp} (source {source})',
        'cli_status_missing': 'executor: plug_state.json is missing',
        'cli_not_configured': 'executor: socket is not set up (setup wizard has not been completed)',
        'cli_lamp': 'lamp: {state}{suffix}',
        'cli_heartbeat': 'executor: heartbeat {stamp}; executor mode {mode}',
        'cli_error': 'error: {error}',
        'cli_failed': 'failed: {error}',
        'cli_applied': (
            'the executor will apply the mode within a few seconds '
            '(if it is running and the device state can be read)'
        ),
        'setup_http_error': 'HTTP {code} while requesting {path}',
        'setup_conn_error': 'cannot reach {base}: {error}',
        'setup_api_error': 'API rejected {path}: code {code} {message}',
        'setup_empty_value': '(empty)',
        'setup_arg_description': 'Get Tuya keys and write secrets/tuya_plug.json',
        'setup_arg_region': 'project data center (default: eu)',
        'setup_arg_address': 'socket IP; if it matches, the device is selected without questions',
        'setup_arg_device_id': 'Device ID to check in --diagnose mode',
        'setup_arg_diagnose': 'only check API availability, do not write anything',
        'setup_arg_verify': 'verify the configured socket: discovery, read, switch and restore',
        'setup_arg_force': 'in --verify mode, switch even during a meeting',
        'setup_arg_reconfigure': 'write the keys again even if the settings file exists',
        'setup_arg_skip_verify': 'do not verify the socket right after saving the settings',
        'setup_arg_out': 'configuration file: where to write or what to verify in --verify',
        'setup_no_token': 'the response has no access_token',
        'setup_no_uid': 'the response has no account uid',
        'setup_token_ok': 'token received, account linked (uid …{tail})',
        'setup_list_unavailable': '  list {path} is unavailable: {error}',
        'setup_device_card': 'device card (Smart Home Basic)',
        'setup_user_devices': 'account device list (Smart Home Basic)',
        'setup_associated': 'linked accounts (Smart Home Basic)',
        'setup_check_failed': '  ✗ {title}: {error}',
        'setup_check_ok': '  ✓ {title}: available (fields/records: {size})',
        'setup_device_in_list': '    device {mask} in the list: {answer}',
        'setup_yes': 'yes',
        'setup_no': 'no',
        'setup_config_missing': 'configuration not found: {path}',
        'setup_config_missing_hint': 'Run setup first: python tuya_setup.py --address <IP>',
        'setup_config_unreadable': 'configuration cannot be read: {error}',
        'setup_config_incomplete': 'the configuration has no dev_id or local_key — run setup again.',
        'setup_meeting': 'a meeting is in progress: verification would switch the lamp.',
        'setup_meeting_hint': 'Wait until it ends, or use --force if that is safe.',
        'setup_no_tinytuya': 'tinytuya is not installed: --verify needs .venv or vendor.',
        'setup_searching': 'searching for the socket on the local network…',
        'setup_not_found': 'device not found: check that the socket is on the same network.',
        'setup_found_udp': '  found by UDP discovery: {addresses}',
        'setup_udp_silent': '  UDP discovery did not answer, checking the saved address',
        'setup_protocol_error': '  {address}, protocol {version}: {error}',
        'setup_no_response': 'no response ({error})',
        'setup_no_dp': 'response has no DP {dp}; available {available}',
        'setup_read_failed': 'cannot read the state: the address responds, but the key or protocol',
        'setup_read_failed_hint': 'did not match. Check that the socket was not re-linked in Smart Life.',
        'setup_device': '  device:     {name}',
        'setup_dev_id': '  dev_id:     {mask}',
        'setup_address': '  address:    {address}',
        'setup_protocol': '  protocol:   {version}, DP {dp}',
        'setup_state': '  state:      {state}',
        'setup_state_on': 'on',
        'setup_state_off': 'off',
        'setup_switching_on': '  switching: turn on…',
        'setup_switching_off': '  switching: turn off…',
        'setup_rejected': '  the device rejected the command: {error}',
        'setup_confirm_failed': '  failed to confirm the switch: {error}',
        'setup_mismatch': '  the state after the command did not match the expected one',
        'setup_confirmed': '  confirmed by reading: {state}',
        'setup_restoring_on': '  restoring the initial state: turn on…',
        'setup_restoring_off': '  restoring the initial state: turn off…',
        'setup_restore_failed': '  failed to restore: {error}',
        'setup_reread_failed': '  failed to re-read the state: {error}',
        'setup_restore_unconfirmed': '  warning: the initial state was not confirmed',
        'setup_restored': '  initial state restored: {state}',
        'setup_verify_passed': 'verification passed: connection, key, DP and switching work.',
        'setup_already': 'The socket is already set up: {path}',
        'setup_already_hint': 'Running a connection check (overwrite the keys: --reconfigure).',
        'setup_credentials_hint': 'Access ID and Access Secret from Tuya IoT Platform → your project → Overview.',
        'setup_access_id': 'Access ID: ',
        'setup_access_secret': 'Access Secret (input is hidden): ',
        'setup_credentials_required': 'both values are required',
        'setup_api_check': 'API check:',
        'setup_explicit_device': 'device specified explicitly: {mask}',
        'setup_devices_count': 'devices in the account: {count}',
        'setup_empty_list': 'The list is empty: check that the Smart Life account is linked in the project (Devices → Link Tuya App Account).',
        'setup_ip_not_found': 'No device with IP {address} was found. Available:',
        'setup_choose_number': 'Device number: ',
        'setup_enter_number': 'enter a number from the list',
        'setup_error': 'error: {error}',
        'setup_1106': 'Code 1106 — this project is not allowed to call the API. Check the project Service API:',
        'setup_1106_service': '  Cloud → Development → your project → Service API: for "Smart Home Basic Service"',
        'setup_1106_status': '  the status must be Subscribed/Authorized, not Not subscribed/Expired.',
        'setup_1106_skip': '  If the project was created with Skip instead of Authorize, there is no subscription — subscribe manually.',
        'setup_1106_wait': '  After subscribing, wait a minute and retry; the token is cached for 2 hours, but permissions apply immediately.',
        'setup_1106_quick': 'Quick check without writing a file: add --diagnose --device-id <id>',
        'setup_no_local_key': 'the response has no local_key: the device may not support the local protocol.',
        'setup_default_name': 'socket',
        'setup_search_address': 'searching for the socket address on the local network (UDP)…',
        'setup_found_address': '  found address: {address}',
        'setup_address_fallback': '  the device did not answer discovery; using the --address or cloud address',
        'setup_address_warning': '  warning: discovery found {found}, but the --address value is used',
        'setup_written': 'written: {path}',
        'setup_local_key_ok': '  local_key:  received ({length} characters)',
        'setup_address_unset': '  address:    (not set)',
        'setup_cloud_external': '  (the cloud reports {ip} — this is an external IP; the --address value is used)',
        'setup_cloud_warning': (
            '  warning: the address came from the cloud and may be an external IP; for the local\n'
            '  protocol, specify --address <home network IP> and retry.'
        ),
        'setup_verify_skipped': 'Verification skipped (--skip-verify).',
        'setup_verify_start': 'Connection check: reading, switching and restoring the state.',
        'setup_done': 'Setup and verification complete: the socket works.',
        'setup_saved_meeting': (
            'Settings saved. A meeting is in progress, so switching was not\n'
            'verified; verification will run the next time the wizard starts.'
        ),
        'setup_saved_failed': 'Settings saved, but verification failed (code {code}).',
        'setup_will_start': 'The app will start anyway; if the lamp does not work, see SUPPORT.md.',
        'setup_repeat': 'Verify again: setup.cmd or tuya_setup.py --verify.',
        'setup_protocol_fallback': 'If the connection fails, the protocol version is tried in order: 3.3 → 3.4 → 3.5.',
    },
}

_cached_language: str | None = None


def detect_language() -> str:
    """Язык интерфейса Windows: русский или английский."""
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = lang_id & 0x3FF
        return LANGUAGE_RU if primary == 0x19 else LANGUAGE_EN
    except (AttributeError, OSError, ImportError):
        pass
    try:
        import locale
        name = (locale.getdefaultlocale()[0] or '').lower()
        return LANGUAGE_RU if name.startswith(('ru', 'be', 'uk')) else LANGUAGE_EN
    except (AttributeError, ImportError, ValueError):
        return DEFAULT_LANGUAGE


def read_settings(path: Path | None = None) -> dict:
    """Настройки интерфейса; отсутствующий или битый файл — пустые настройки."""
    path = path or SETTINGS_PATH
    try:
        raw = path.read_text(encoding='utf-8-sig')
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(data: dict, path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    os.replace(tmp, path)


def language_setting(path: Path | None = None) -> str:
    """Выбранный язык: 'auto', 'ru' или 'en'."""
    value = str(read_settings(path).get('language') or LANGUAGE_AUTO).lower()
    return value if value in LANGUAGES else LANGUAGE_AUTO


def current_language(path: Path | None = None) -> str:
    value = language_setting(path)
    return detect_language() if value == LANGUAGE_AUTO else value


def get_language() -> str:
    """Действующий язык с учётом выбора в трее (и кэша после смены)."""
    return _cached_language or current_language()


def set_language(value: str, path: Path | None = None) -> str:
    """Сохранить выбор языка и применить его сразу. Возвращает 'ru' или 'en'."""
    global _cached_language
    value = (value or LANGUAGE_AUTO).lower()
    if value not in LANGUAGES:
        value = LANGUAGE_AUTO
    settings = read_settings(path)
    settings['language'] = value
    write_settings(settings, path)
    _cached_language = detect_language() if value == LANGUAGE_AUTO else value
    return _cached_language


def reset_cache() -> None:
    """Сбросить кэш (например, в тестах)."""
    global _cached_language
    _cached_language = None


def translate(key: str, language: str | None = None, **kwargs) -> str:
    """Строка интерфейса на заданном (или текущем) языке.

    Неизвестный ключ возвращается как есть: так опечатка видна, но интерфейс
    не падает.
    """
    language = language or get_language()
    template = MESSAGES.get(language, {}).get(key)
    if template is None:
        template = MESSAGES[LANGUAGE_RU].get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def t(key: str, **kwargs) -> str:
    """Строка интерфейса на текущем языке."""
    return translate(key, **kwargs)


def format_time(value: datetime) -> str:
    return value.strftime('%H:%M')
