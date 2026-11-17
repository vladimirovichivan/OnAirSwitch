; Установщик OnAir Lamp (per-user, без прав администратора).
;
; Собирается из packaging\build.ps1:
;   iscc /DAppVersion=1.0.1 /DStageDir=D:\...\build\portable\OnAirLamp-1.0.1-win64 OnAirLamp.iss
;
; Раскладка повторяет портативную папку; app\data и app\secrets при удалении
; сохраняются, потому что установщик о них не знает.

#ifndef AppVersion
  #define AppVersion "1.0.1"
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
; Процессы Лампы скрытые и на WM_CLOSE не отвечают, поэтому Restart Manager
; их не закроет. Останавливаем сами в коде (KillLampProcesses).
CloseApplications=no
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "autostart"; Description: "Запускать OnAir Lamp при входе в Windows"; GroupDescription: "Автозапуск:"
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\onair.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Настройка и проверка OnAir Lamp"; Filename: "{app}\setup.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Отчёт для поддержки"; Filename: "{app}\report.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Если не работает"; Filename: "{app}\SUPPORT.md"
Name: "{autodesktop}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OnAirLamp"; ValueData: "wscript.exe ""{app}\start.vbs"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; Description: "Запустить OnAir Lamp"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop.ps1"" -IncludeTray"; Flags: runhidden; RunOnceId: "StopOnAirLamp"

[Code]
{ Скрытые процессы Лампы (pythonw.exe, powershell.exe наблюдателя) не отвечают
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
    'Удалить сохранённые настройки подключения к розетке?' + #13#10 + #13#10 +
    'Они позволяют после повторной установки продолжить работу без новой ' +
    'настройки розетки.' + #13#10 +
    'Журналы и остальные данные останутся на месте.' + #13#10 + #13#10 +
    'Если удалить, при следующей установке розетку нужно будет настроить заново.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
  begin
    DeleteFile(SettingsFile);
    RemoveDir(ExpandConstant('{app}\app\secrets'));
  end;
end;
