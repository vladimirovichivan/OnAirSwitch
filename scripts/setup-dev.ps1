# Создаёт окружение разработки для проекта OnAir Lamp.
# Ничего не устанавливает глобально: всё внутри .venv проекта.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Python 3.12: сначала лаунчер py, затем python из PATH.
$python = $null
foreach ($candidate in @('py -3.12', 'python')) {
    try {
        $version = & cmd /c "$candidate -c ""import sys; print('%d.%d' % sys.version_info[:2])""" 2>$null
    } catch { continue }
    if ($version -eq '3.12') { $python = $candidate; break }
}
if (-not $python) {
    Write-Host 'Не найден Python 3.12. Установите его и повторите.' -ForegroundColor Red
    exit 2
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host "Создаю .venv через $python"
    & cmd /c "$python -m venv .venv"
    if ($LASTEXITCODE -ne 0) { Write-Host 'Не удалось создать .venv' -ForegroundColor Red; exit 3 }
}

Write-Host 'Устанавливаю зависимости из app\scripts\meetings\requirements.txt'
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r app\scripts\meetings\requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host 'Не удалось установить зависимости' -ForegroundColor Red; exit 4 }

Write-Host ''
Write-Host 'Готово. Дальше:' -ForegroundColor Green
Write-Host '  dry-run:  .venv\Scripts\python.exe app\scripts\meetings\plug_executor.py --once'
Write-Host '  трей:     .venv\Scripts\pythonw.exe app\scripts\meetings\tray_plug.py'
Write-Host '  всё:      packaging\start.vbs'
Write-Host '  настройка: .venv\Scripts\python.exe app\scripts\meetings\tuya_setup.py'
