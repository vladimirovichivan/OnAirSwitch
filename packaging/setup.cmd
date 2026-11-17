@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title OnAir Lamp - настройка и проверка

rem Один инструмент для пользователя: без настроек — мастер и проверка,
rem с настройками — выбор «проверить» или «настроить заново». Приложение
rem перезапускается только после первой настройки, чтобы не дёргать
rem работающую лампу.
set "cfg=%~dp0app\secrets\tuya_plug.json"
set "configured=0"
if exist "%cfg%" set "configured=1"
set "extra="

if not "%configured%"=="1" goto run
echo.
echo Розетка уже настроена. Что сделать?
echo   1. Проверить подключение
echo   2. Настроить заново (розетку заменили или перепривязывали)
choice /c 12 /n /m "Выбор [1/2]: "
if errorlevel 2 set "extra=--reconfigure"

:run
"%~dp0python\python.exe" "%~dp0app\scripts\meetings\tuya_setup.py" %extra% %*
set "rc=%ERRORLEVEL%"
if not "%rc%"=="0" goto done
if "%configured%"=="1" if not "%extra%"=="--reconfigure" goto done
echo.
echo Настройка завершена. Запускаю OnAir Lamp...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
:done
echo.
pause
