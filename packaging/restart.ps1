# Перезапуск OnAir Lamp после настройки: новые настройки розетки подхватываются
# только запущенным исполнителем. Сначала останавливаем процессы именно этой
# копии (по пути в командной строке), затем запускаем start.vbs заново.
# Вторые экземпляры безопасны: каждый процесс защищён mutex.

$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot

# Остановка вынесена в stop.ps1: тот же код использует кнопка «Выход» в трее
# и деинсталлятор. В dev-копии stop.ps1 сам определяет корень на уровень выше.
$stop = Join-Path $root 'stop.ps1'
if (Test-Path $stop) {
    & $stop -IncludeTray
}

$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$start = Join-Path $root 'start.vbs'
Start-Process -FilePath $wscript -ArgumentList ('"{0}"' -f $start)

exit 0
