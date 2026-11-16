@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0app\scripts\meetings\tuya_setup.py" --verify %*
echo.
pause
