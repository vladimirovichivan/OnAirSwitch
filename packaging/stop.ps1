# Останавливает процессы OnAir Lamp: наблюдатель встреч и исполнитель розетки,
# а с ключом -IncludeTray — ещё и трей.
#
# «Выход» в трее вызывает скрипт без -IncludeTray: трей завершает иконку сам.
# Перезапуск после настройки и деинсталлятор вызывают с -IncludeTray.
#
# Путь определяется по расположению самого скрипта: в установке он лежит рядом
# с app\, в dev-копии — в packaging\, на уровень выше app\.

param(
    [string]$Root = '',
    [switch]$IncludeTray
)

$ErrorActionPreference = 'SilentlyContinue'

if ($Root) {
    $base = $Root
} else {
    $base = $PSScriptRoot
    if (-not (Test-Path (Join-Path $base 'app\scripts\meetings\plug_executor.py'))) {
        $base = Split-Path -Parent $base
    }
}
$base = (Resolve-Path $base).Path
$pattern = [Regex]::Escape($base)

$targets = 'plug_executor\.py|watch_meetings\.ps1'
if ($IncludeTray) {
    $targets = $targets + '|tray_plug\.py'
}

$running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match $pattern -and
        $_.CommandLine -match $targets
    }

foreach ($process in $running) {
    Stop-Process -Id $process.ProcessId -Force
}

if ($running) {
    Start-Sleep -Milliseconds 300
}

exit 0
