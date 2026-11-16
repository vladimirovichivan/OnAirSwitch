@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0tools\report_support.py" %*
echo.
pause
