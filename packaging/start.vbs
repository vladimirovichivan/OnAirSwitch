' OnAir Lamp: запуск трёх процессов скрыто — наблюдатель, исполнитель, трей.
' Работает и из папки проекта (packaging\), и из корня установки.
' Вторые экземпляры безопасны: каждый процесс защищён своим mutex.
Option Explicit

Dim fso, sh, here, base, pythonw, scripts, powershell
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
base = here
If Not fso.FileExists(fso.BuildPath(here, "app\scripts\meetings\plug_executor.py")) Then
    base = fso.GetParentFolderName(here)
End If

scripts = fso.BuildPath(base, "app\scripts\meetings")
If Not fso.FileExists(fso.BuildPath(scripts, "plug_executor.py")) Then
    MsgBox "Не найдены файлы приложения в " & scripts, 16, "OnAir Lamp"
    WScript.Quit 1
End If

pythonw = fso.BuildPath(base, "python\pythonw.exe")
If Not fso.FileExists(pythonw) Then
    pythonw = fso.BuildPath(base, ".venv\Scripts\pythonw.exe")
End If
If Not fso.FileExists(pythonw) Then
    MsgBox "Не найден pythonw.exe ни в python\, ни в .venv\. " & _
           "Запустите scripts\setup-dev.ps1 или переустановите приложение.", 16, "OnAir Lamp"
    WScript.Quit 2
End If

powershell = fso.BuildPath(sh.ExpandEnvironmentStrings("%SystemRoot%"), "System32\WindowsPowerShell\v1.0\powershell.exe")

' 1. Наблюдатель встреч (скрытое окно PowerShell, без профиля).
sh.Run """" & powershell & """ -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & _
       fso.BuildPath(scripts, "watch_meetings.ps1") & """", 0, False
' 2. Исполнитель розетки: реальное управление.
sh.Run """" & pythonw & """ """ & fso.BuildPath(scripts, "plug_executor.py") & """ --apply", 0, False
' 3. Иконка в трее.
sh.Run """" & pythonw & """ """ & fso.BuildPath(scripts, "tray_plug.py") & """", 0, False
