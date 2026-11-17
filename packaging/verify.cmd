@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title OnAir Lamp - проверка розетки

rem Отдельный ярлык больше не нужен: обычно проверка запускается из
rem «Настройка и проверка OnAir Lamp». Этот файл остаётся для поддержки
rem и прямого запуска из папки установки.
"%~dp0python\python.exe" "%~dp0app\scripts\meetings\tuya_setup.py" --verify %*
echo.
pause
