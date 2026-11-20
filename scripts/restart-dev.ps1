# Перезапуск процессов OnAir Lamp (супервизор и три процесса) из этого проекта.
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
    $_.CommandLine -match 'supervisor\.py|plug_executor\.py|tray_plug\.py|watch_meetings\.ps1'
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
    $_.CommandLine -match 'supervisor\.py|plug_executor\.py|tray_plug\.py|watch_meetings\.ps1'
}

# В dev-копии pythonw.exe из .venv — это обёртка venvlauncher: она запускает
# настоящий Python из базовой установки и ждёт его. Поэтому на один компонент
# приходится две записи в списке процессов. Считаем компоненты, а не записи.
$components = @(
    @{ File = 'supervisor\.py'; Label = 'супервизор' },
    @{ File = 'watch_meetings\.ps1'; Label = 'наблюдатель' },
    @{ File = 'plug_executor\.py'; Label = 'исполнитель' },
    @{ File = 'tray_plug\.py'; Label = 'трей' }
)
$missing = @()
foreach ($component in $components) {
    $pids = @($running | Where-Object { $_.CommandLine -match $component.File } |
            ForEach-Object { $_.ProcessId })
    if ($pids.Count -eq 0) {
        $missing += $component.Label
        Write-Host ('  {0}: не запущен' -f $component.Label) -ForegroundColor Red
    } else {
        Write-Host ('  {0}: pid {1}' -f $component.Label, ($pids -join ', '))
    }
}
$ok = $components.Count - $missing.Count
$color = if ($missing.Count -eq 0) { 'Green' } else { 'Yellow' }
Write-Host ('Компонентов запущено: {0} из {1}' -f $ok, $components.Count) -ForegroundColor $color
