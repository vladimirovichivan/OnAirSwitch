# Перезапуск OnAir Lamp после настройки: новые настройки розетки подхватываются
# только запущенным исполнителем. Сначала останавливаем процессы именно этой
# копии (по пути в командной строке), затем запускаем start.vbs заново.
# Вторые экземпляры безопасны: каждый процесс защищён mutex.

$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$pattern = [Regex]::Escape($root)

$running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match $pattern -and
        $_.CommandLine -match 'plug_executor\.py|tray_plug\.py|watch_meetings\.ps1'
    }

foreach ($process in $running) {
    Stop-Process -Id $process.ProcessId -Force
}

if ($running) {
    Start-Sleep -Seconds 2
}

$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$start = Join-Path $root 'start.vbs'
Start-Process -FilePath $wscript -ArgumentList ('"{0}"' -f $start)

exit 0
