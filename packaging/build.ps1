# Сборка портативной версии OnAir Lamp.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#   powershell ... -Version 1.0.2
#
# Скачивает официальный embeddable Python, ставит зависимости в vendor\,
# проверяет импорты под эмбеддированным интерпретатором и складывает готовую
# папку и zip в build\. Установщик Inno Setup собирается, если найден iscc.exe
# и есть packaging\OnAirLamp.iss. Компиляции кода нет: копируются .py/.ps1.

param(
    [string]$Version = '1.0.2',
    [string]$PythonVersion = '3.12.10',
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# В поставку не должны попадать байткод и кэш: они появляются от pip и от
# проверки импортов, привязаны к машине сборки и только раздувают архив.
function Remove-Pycache {
    param([string]$Path)
    Get-ChildItem $Path -Recurse -Directory -Filter '__pycache__' -Force |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $Path -Recurse -File -Include '*.pyc', '*.pyo' -Force |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
$build = Join-Path $root 'build'
$stage = Join-Path $build "portable\OnAirLamp-$Version-win64"
$pythonDir = Join-Path $build 'python'
$vendorDir = Join-Path $build 'vendor'
$pythonZip = Join-Path $build "python-$PythonVersion-embed-amd64.zip"
$pythonExe = Join-Path $pythonDir 'python.exe'

New-Item -ItemType Directory -Force -Path $build | Out-Null

Write-Host "1/6 Python $PythonVersion"
if (-not (Test-Path $pythonExe)) {
    if (-not (Test-Path $pythonZip)) {
        $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
        Write-Host "  скачиваю $url"
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -L --fail --silent --show-error --output $pythonZip $url
            if ($LASTEXITCODE -ne 0) { throw "curl не смог скачать $url" }
        } else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $pythonZip -UseBasicParsing
        }
    }
    if (Test-Path $pythonDir) { Remove-Item $pythonDir -Recurse -Force }
    Expand-Archive -Path $pythonZip -DestinationPath $pythonDir -Force
} else {
    Write-Host "  уже распакован: $pythonDir"
}

# Строки поиска модулей: стандартная библиотека, текущая папка, vendor и сами
# скрипты. Каталог скрипта embeddable-Python сам не добавляет (режим _pth),
# поэтому без последней строки не находятся plug_control/tuya_discovery.
$pth = Get-ChildItem $pythonDir -Filter '*._pth' | Select-Object -First 1
if (-not $pth) { throw "в $pythonDir нет файла *._pth" }
$pthLines = @('python312.zip', '.', '..\vendor', '..\app\scripts\meetings')
[IO.File]::WriteAllText($pth.FullName, (($pthLines -join "`r`n") + "`r`n"), [Text.UTF8Encoding]::new($false))
Write-Host "  $($pth.Name): $($pthLines -join ', ') (без import site)"

Write-Host '2/6 зависимости в vendor'
if (-not (Test-Path (Join-Path $root '.venv\Scripts\python.exe'))) {
    throw 'нет .venv: сначала выполните scripts\setup-dev.ps1'
}
if (Test-Path $vendorDir) { Remove-Item $vendorDir -Recurse -Force }
& (Join-Path $root '.venv\Scripts\python.exe') -m pip install --disable-pip-version-check `
    --target $vendorDir -r (Join-Path $root 'app\scripts\meetings\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install в vendor завершился с ошибкой' }
Remove-Pycache $vendorDir

Write-Host "3/6 раскладка $stage"
Write-Host '  иконка onair.ico'
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'packaging\make_icon.py') (Join-Path $build 'onair.ico')
if ($LASTEXITCODE -ne 0) { throw 'не удалось нарисовать onair.ico' }
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $pythonDir (Join-Path $stage 'python') -Recurse
Copy-Item $vendorDir (Join-Path $stage 'vendor') -Recurse
$appScripts = Join-Path $stage 'app\scripts\meetings'
New-Item -ItemType Directory -Force -Path $appScripts | Out-Null
Copy-Item (Join-Path $root 'app\scripts\meetings\*.py') $appScripts
Copy-Item (Join-Path $root 'app\scripts\meetings\*.ps1') $appScripts
if (Test-Path (Join-Path $root 'app\scripts\meetings\icons')) {
    Copy-Item (Join-Path $root 'app\scripts\meetings\icons') $appScripts -Recurse
}
Copy-Item (Join-Path $root 'app\scripts\meetings\requirements.txt') $appScripts
Copy-Item (Join-Path $root 'packaging\start.vbs') $stage
Copy-Item (Join-Path $root 'packaging\restart.ps1') $stage
Copy-Item (Join-Path $root 'packaging\stop.ps1') $stage
Copy-Item (Join-Path $root 'packaging\setup.cmd') $stage
Copy-Item (Join-Path $root 'packaging\verify.cmd') $stage
Copy-Item (Join-Path $root 'packaging\report.cmd') $stage
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'tools') | Out-Null
Copy-Item (Join-Path $root 'tools\report_support.py') (Join-Path $stage 'tools')
Copy-Item (Join-Path $build 'onair.ico') $stage
Copy-Item (Join-Path $root 'docs\SUPPORT.md') $stage
Copy-Item (Join-Path $root 'docs\INSTALL.md') $stage
# README.txt — та же инструкция, но простым текстом: установщик предлагает
# открыть её в Блокноте сразу после установки. Конвертер убирает маркдаун,
# который Блокнот не понимает, а источник остаётся один — docs\INSTALL.md.
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'packaging\md_to_text.py') `
    (Join-Path $root 'docs\INSTALL.md') (Join-Path $stage 'README.txt')
if ($LASTEXITCODE -ne 0) { throw 'не удалось собрать README.txt из INSTALL.md' }
if (Test-Path (Join-Path $root 'packaging\licenses')) {
    Copy-Item (Join-Path $root 'packaging\licenses') (Join-Path $stage 'licenses') -Recurse
}

$commit = 'nogit'
try {
    $commit = (& git -C $root rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $commit) { $commit = 'nogit' }
} catch {
    $commit = 'nogit'
}
$buildInfo = [ordered]@{
    version = $Version
    built   = (Get-Date -Format 'yyyy-MM-dd')
    commit  = "$commit".Trim()
}
$buildJson = Join-Path $stage 'app\build.json'
[IO.File]::WriteAllText($buildJson, ($buildInfo | ConvertTo-Json) + "`r`n", [Text.UTF8Encoding]::new($false))

Write-Host '4/6 проверка импортов в готовой раскладке'
$stagePython = Join-Path $stage 'python\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $stagePython -c "import tinytuya, pystray, PIL, cryptography, plug_control, tuya_discovery; print('imports ok')"
if ($LASTEXITCODE -ne 0) { throw 'импорты в портативной раскладке не проходят' }
Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
Remove-Pycache $stage

Write-Host '5/6 zip'
$zipOut = Join-Path $build "OnAirLamp-$Version-win64.zip"
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipOut -Force

Write-Host '6/6 установщик'
$iscc = $null
foreach ($candidate in @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
)) {
    if ($candidate -and (Test-Path $candidate)) { $iscc = $candidate; break }
}
$iss = Join-Path $root 'packaging\OnAirLamp.iss'
if ($iscc -and (Test-Path $iss) -and -not $SkipInstaller) {
    & $iscc "/DAppVersion=$Version" "/DStageDir=$stage" $iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup завершился с ошибкой' }
} else {
    if (-not $iscc) { Write-Host '  Inno Setup 7/6 не найден — установщик не собирался' -ForegroundColor Yellow }
    elseif (-not (Test-Path $iss)) { Write-Host '  packaging\OnAirLamp.iss ещё нет — установщик не собирался' -ForegroundColor Yellow }
}

Write-Host ''
Write-Host "Готово:" -ForegroundColor Green
Write-Host "  папка: $stage"
Write-Host "  zip:   $zipOut"

$artifacts = @($zipOut)
$setupExe = Join-Path $build "OnAirLamp-Setup-$Version.exe"
if (Test-Path $setupExe) { $artifacts += $setupExe }
$hashes = foreach ($file in $artifacts) {
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
    "{0}  {1}" -f $hash, (Split-Path $file -Leaf)
}
[IO.File]::WriteAllText((Join-Path $build 'SHA256SUMS.txt'), (($hashes -join "`r`n") + "`r`n"), [Text.UTF8Encoding]::new($false))
$hashes | ForEach-Object { Write-Host "  $_" }

# Успешное завершение: не наследуем код последней внешней команды.
exit 0
