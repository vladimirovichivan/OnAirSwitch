; Установщик OnAir Lamp (per-user, без прав администратора).
;
; Собирается из packaging\build.ps1:
;   iscc /DAppVersion=1.1.1 /DStageDir=D:\...\build\portable\OnAirLamp-1.1.1-win64 OnAirLamp.iss
;
; Раскладка повторяет портативную папку. Приложение пишет журналы и состояние
; в app\data, кэш байткода — в __pycache__: установщик о них не знает, поэтому
; они удаляются секцией [UninstallDelete]. app\secrets остаётся, только если
; пользователь попросил сохранить настройки розетки.

#ifndef AppVersion
  #define AppVersion "1.1.1"
#endif

#ifndef StageDir
  #define StageDir "..\build\portable\OnAirLamp-" + AppVersion + "-win64"
#endif

#define AppName "OnAir Lamp"
#define AppPublisher "OnAir Lamp"
#define AppId "{{6F1B6C2E-7A55-4B7E-9F31-2D6A4C8E0B11}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVerName={#AppName} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\OnAirLamp
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build
OutputBaseFilename=OnAirLamp-Setup-{#AppVersion}
SetupIconFile=..\build\onair.ico
UninstallDisplayIcon={app}\onair.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AllowNoIcons=yes
; Процессы приложения скрытые и на WM_CLOSE не отвечают, поэтому Restart Manager
; их не закроет. Останавливаем сами в коде (KillLampProcesses).
CloseApplications=no
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.TaskAutostart=Запускать OnAir Lamp при входе в Windows
russian.TaskAutostartGroup=Автозапуск:
russian.TaskDesktopIcon=Ярлык на рабочем столе
russian.TaskDesktopIconGroup=Дополнительно:
russian.IconSetup=Настройка и проверка OnAir Lamp
russian.IconReport=Отчёт для поддержки
russian.IconSupport=Если не работает
russian.RunApp=Запустить OnAir Lamp
russian.RunReadme=Открыть README.txt — как установить и настроить приложение
russian.UninstallRemoveSettings=Удалить сохранённые настройки подключения к розетке?%n%nОни позволяют после повторной установки продолжить работу без новой настройки розетки.%nПрограмма, журналы и остальные её файлы удаляются в любом случае.%n%nЕсли удалить настройки, при следующей установке розетку нужно будет настроить заново.
english.TaskAutostart=Start OnAir Lamp when you sign in to Windows
english.TaskAutostartGroup=Autostart:
english.TaskDesktopIcon=Desktop shortcut
english.TaskDesktopIconGroup=Optional:
english.IconSetup=Set up and verify OnAir Lamp
english.IconReport=Support report
english.IconSupport=If it does not work
english.RunApp=Start OnAir Lamp
english.RunReadme=Open README.txt — how to install and set up the app
english.UninstallRemoveSettings=Remove the saved socket connection settings?%n%nThey let the app keep working after reinstallation without setting up the socket again.%nThe program, logs and all other files are removed in any case.%n%nIf you remove the settings, you will need to set up the socket again after reinstalling.

[Tasks]
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:TaskAutostartGroup}"
Name: "desktopicon"; Description: "{cm:TaskDesktopIcon}"; GroupDescription: "{cm:TaskDesktopIconGroup}"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\onair.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\{cm:IconSetup}"; Filename: "{app}\setup.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\{cm:IconReport}"; Filename: "{app}\report.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\{cm:IconSupport}"; Filename: "{app}\SUPPORT.md"
Name: "{autodesktop}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OnAirLamp"; ValueData: "wscript.exe ""{app}\start.vbs"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; Description: "{cm:RunApp}"; Flags: postinstall nowait skipifsilent
; README.txt — копия INSTALL.md в папке программы (её кладёт build.ps1). Галочка
; стоит по умолчанию: инструкцию предлагаем открыть сразу, иначе получатель не
; узнает, что розетку нужно настраивать мастером. Блокнот выбран намеренно: он
; есть всегда и не зависит от ассоциаций .md/.txt.
Filename: "{sys}\notepad.exe"; Parameters: """{app}\README.txt"""; Description: "{cm:RunReadme}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Полный путь: в System32 файла powershell.exe нет (он в WindowsPowerShell\v1.0),
; иначе запуск не удаётся, а Inno Setup сообщает «часть элементов не удалось удалить».
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop.ps1"" -IncludeTray"; Flags: runhidden; RunOnceId: "StopOnAirLamp"

[UninstallDelete]
; Всё, что приложение создаёт во время работы, удаляется вместе с ним: журналы
; и состояние в app\data, кэш байткода __pycache__, временные файлы. Секция
; обрабатывается рекурсивно, поэтому чистит и подкаталоги, о которых установщик
; не знает. app\secrets сюда не входит: его судьбу решает вопрос в [Code]
; (сохранить настройки розетки или удалить).
Type: filesandordirs; Name: "{app}\app\data"
Type: filesandordirs; Name: "{app}\app\scripts"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\vendor"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\licenses"
; Если файл настроек уже удалён вручную, пустые каталоги тоже не оставляем
; (dirifempty уберёт их, только когда они пусты, — сохранённые настройки целы).
Type: dirifempty; Name: "{app}\app\secrets"
Type: dirifempty; Name: "{app}\app"
Type: dirifempty; Name: "{app}"

[Code]
{ Скрытые процессы приложения (pythonw.exe, powershell.exe наблюдателя) не отвечают
  на запрос закрытия Restart Manager, поэтому установщик и деинсталлятор гасят
  их сами, до копирования и удаления файлов. Фильтр — имя процесса и путь
  установки в командной строке: чужие Python не затрагиваются. }
function KillLampProcesses: Boolean;
var
  Script, ScriptPath, Root: String;
  ResultCode: Integer;
begin
  Root := ExpandConstant('{app}');
  ScriptPath := ExpandConstant('{tmp}') + '\onair-stop.ps1';
  Script :=
    '$root = ' + Chr(39) + Root + Chr(39) + #13#10 +
    '$pattern = [Regex]::Escape($root)' + #13#10 +
    'for ($attempt = 0; $attempt -lt 5; $attempt++) {' + #13#10 +
    '  $found = @(Get-CimInstance Win32_Process | Where-Object {' + #13#10 +
    '    $_.ProcessId -ne $PID -and' + #13#10 +
    '    $_.Name -match ''^(python|pythonw|powershell)\.exe$'' -and' + #13#10 +
    '    $_.CommandLine -match $pattern })' + #13#10 +
    '  if ($found.Count -eq 0) { break }' + #13#10 +
    '  $found | ForEach-Object {' + #13#10 +
    '    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }' + #13#10 +
    '  Start-Sleep -Milliseconds 400' + #13#10 +
    '}' + #13#10;

  SaveStringToFile(ScriptPath, Script, False);
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DeleteFile(ScriptPath);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillLampProcesses;
  Result := '';
end;

{ При удалении спрашиваем про настройки подключения к розетке. Тихая
  деинсталляция их сохраняет; /DELETEAPPSETTINGS удаляет без вопроса. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsFile: String;
  CmdTail: String;
  Answer: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  { Файлы ещё на месте: гасим процессы до [UninstallRun] и удаления. }
  KillLampProcesses;

  SettingsFile := ExpandConstant('{app}\app\secrets\tuya_plug.json');
  if not FileExists(SettingsFile) then
    Exit;

  CmdTail := Lowercase(GetCmdTail);
  if Pos('/deleteappsettings', CmdTail) > 0 then
  begin
    DeleteFile(SettingsFile);
    RemoveDir(ExpandConstant('{app}\app\secrets'));
    Exit;
  end;

  if UninstallSilent then
    Exit;

  Answer := MsgBox(
    ExpandConstant('{cm:UninstallRemoveSettings}'),
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
  begin
    DeleteFile(SettingsFile);
    RemoveDir(ExpandConstant('{app}\app\secrets'));
  end;
end;
