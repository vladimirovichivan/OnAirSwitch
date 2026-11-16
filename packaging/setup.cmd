@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0app\scripts\meetings\tuya_setup.py" %*
set "rc=%ERRORLEVEL%"
if not "%rc%"=="0" goto done
echo.
echo Перезапускаю OnAir Lamp, чтобы применить настройки...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
:done
echo.
pause
