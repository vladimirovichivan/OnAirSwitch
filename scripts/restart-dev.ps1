# Перезапуск трёх процессов OnAir Lamp из этого проекта.
#
#   powershell -ExecutionPolicy Bypass -File scripts\restart-dev.ps1
#
# Останавливает только процессы, чья командная строка указывает на этот проект,
# поэтому рабочая копия из другого каталога не затрагивается. Затем запускает
# packaging\start.vbs и проверяет, что процессы поднялись.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $root 'app\scripts\meetings'
$start = Join-Path $root 'packaging\start.vbs'

if (-not (Test-Path (Join-Path $scripts 'plug_executor.py'))) {
    Write-Host "Не найден проект: $scripts" -ForegroundColor Red
    exit 2
}
if (-not (Test-Path $start)) {
    Write-Host "Не найден запускатель: $start" -ForegroundColor Red
    exit 3
}

$rootPattern = [Regex]::Escape($root)
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and
    ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'powershell.exe') -and
    $_.CommandLine -match $rootPattern -and
    $_.CommandLine -match 'plug_executor\.py|tray_plug\.py|watch_meetings\.ps1'
}

if ($targets) {
    Write-Host ('Останавливаю процессов: {0}' -f @($targets).Count)
    foreach ($process in $targets) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host 'Работающих процессов этого проекта нет.'
}

Start-Process wscript.exe -ArgumentList ('"{0}"' -f $start)
Start-Sleep -Seconds 6

$running = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and
    ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'powershell.exe') -and
    $_.CommandLine -match $rootPattern -and
    $_.CommandLine -match 'plug_executor\.py|tray_plug\.py|watch_meetings\.ps1'
}
Write-Host ('Запущено процессов: {0}' -f @($running).Count) -ForegroundColor Green
$running | Select-Object ProcessId, Name, CommandLine | Format-List
