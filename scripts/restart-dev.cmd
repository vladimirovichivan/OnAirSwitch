@echo off
rem Перезапуск трёх процессов OnAir Lamp из этого проекта.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-dev.ps1"
if errorlevel 1 pause
