# OnAir Lamp

Лампа «On air»: умная розетка Tuya горит, пока идёт видеовстреча в Толке,
Телемосте или Zoom, и гаснет, когда встреч нет. Локальный протокол, без облака
в повседневной работе, без прав администратора.

Проект выделен из `D:\Legacy`, где остались только история решений D-54…D-63;
копия лампы, данные, ключ розетки и её автозапуск из Legacy удалены 16.11.2026.
Код в `app\scripts\meetings\` — проверенные скрипты, поведение при переезде не
менялось.

## Состояние

- [x] Проект создан, код перенесён.
- [x] Локальный запуск из `D:\onair-lamp` проверен на живых встречах
      (Толк, Zoom, Телемост, 16.11.2026).
- [x] Проверка розетки (`--verify`) и поиск адреса по UDP.
- [x] Автономная сборка (эмбеддированный Python + Inno Setup): портативный zip
      и установщик; проверены установка, автозапуск, удаление и повторная
      установка (16.11.2026).
- [x] Мастер настройки, проверка розетки, отчёт для поддержки.
- [x] Копия лампы и автозапуск убраны из Legacy; работает только эта копия
      (16.11.2026). Проверка перезагрузкой Windows — впереди.
- [ ] Приёмка на чужом ПК (Windows 11 и Windows 10).

Разработка ведётся в `main` этого проекта; версия для передачи другим людям —
отдельный форк, который следует за основной веткой. Релизы — GitHub Releases,
дополнительно портативный zip (D-64, D-65).

План работ и критерии готовности — [`docs/plan_packaging.md`](docs/plan_packaging.md).

## Раскладка

```
app\scripts\meetings\   наблюдатель, исполнитель, трей, настройка и поиск Tuya
docs\                   архитектура, история решений, план сборки, поддержка
packaging\              сборка, сценарий установщика, запуск трёх процессов
tools\                  отчёт для поддержки (zip без ключей)
build\                  результат сборки: портативная папка, zip, установщик
tests\                  тесты чистых функций (план)
```

## Быстрый старт (для разработки)

Нужен Python 3.12. Один раз:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
```

Затем — `packaging\start.vbs` (запускает наблюдатель, исполнитель и трей скрыто)
или вручную:

```powershell
.venv\Scripts\python.exe app\scripts\meetings\plug_executor.py --once        # dry-run
.venv\Scripts\pythonw.exe app\scripts\meetings\tray_plug.py                  # трей
powershell -NoProfile -File app\scripts\meetings\watch_meetings.ps1 -Once    # диагностика
.venv\Scripts\python.exe app\scripts\meetings\tuya_setup.py --verify         # розетка
```

Первый запуск без настроек ожидаем: без `secrets\tuya_plug.json` исполнитель
работает только в dry-run, трей показывает «нет данных».

## Сборка поставки

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Результат: `build\portable\OnAirLamp-<версия>-win64\`, zip и, если найден
Inno Setup 7/6, `build\OnAirLamp-Setup-<версия>.exe`. Хеши — в
`build\SHA256SUMS.txt`. Обычные правки кода пересборки не требуют: для себя
достаточно перезапустить процессы (`scripts\restart-dev.cmd`).

## Документы

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — как устроено и почему.
- [`docs/HISTORY.md`](docs/HISTORY.md) — решения D-54…D-65 и проверки.
- [`docs/plan_packaging.md`](docs/plan_packaging.md) — план автономной сборки.
- [`docs/SUPPORT.md`](docs/SUPPORT.md) — что делать, если не работает.
