<#
.SYNOPSIS
  Наблюдатель за встречами: Контур.Толк, Zoom, Яндекс.Телемост.
  Пишет в лог события "встреча началась / закончилась", "камера включена / выключена"
  и "микрофон включён / выключен".

.DESCRIPTION
  Скрипт только читает локальное состояние Windows и ничего не меняет:
    * окна процессов конференций (заголовок + класс);
    * активные аудиосессии приложения в WASAPI — только для диагностики;
    * журнал доступа к камере и микрофону (CapabilityAccessManager ConsentStore).

  Состояния по каждому приложению: нет встречи / окно входа / встреча.
  Встреча определяется только по окну (D-58): аудиосессия приложения может
  оставаться активной вне встречи (например, после окна настроек Толка),
  поэтому самостоятельным признаком не является. События фиксируются
  с дебаунсом, чтобы не реагировать на мигание окон и переподключения.

  Апробация: в строки событий пишутся заголовки видимых окон приложения
  (`title: ...; windows: ...`), чтобы видеть, какой признак сработал. Заголовок
  окна может содержать тему встречи, поэтому при необходимости список
  отключается: -NoTitles.

  Семантика устройств различается:
    * камера освобождается при каждом выключении — события совпадают
      с переключением в интерфейсе;
    * микрофон в Толке и Телемосте при mute остаётся захваченным, поэтому
      "микрофон выключен" фиксируется только при выходе из встречи.
      Реакция на сам mute требует другого источника (UI Automation, API).

.EXAMPLE
  .\watch_meetings.ps1
  .\watch_meetings.ps1 -Once
  .\watch_meetings.ps1 -IntervalSeconds 2
  .\watch_meetings.ps1 -NoTitles
  .\watch_meetings.ps1 -Apps talk

.NOTES
  Файл сохранён в UTF-8 с BOM: Windows PowerShell 5.1 иначе ломает кириллицу.
#>
param(
    [int] $IntervalSeconds = 2,
    [int] $StartPolls = 3,
    [int] $EndPolls = 15,
    [int] $CameraPolls = 2,
    [string] $LogPath = '',
    [string] $StatePath = '',
    [string[]] $Apps = @('talk', 'zoom', 'telemost'),
    [switch] $Once,
    [switch] $Quiet,
    # Пока функционал проходит апробацию, заголовки окон пишутся в лог по умолчанию
    # (в том числе тема встречи). Отключение: -NoTitles.
    [switch] $NoTitles
)

$ErrorActionPreference = 'Stop'

if (-not $LogPath) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $LogPath = Join-Path $repoRoot 'data\work\meetings\events.log'
}
$LogPath = [IO.Path]::GetFullPath($LogPath)

if (-not $StatePath) {
    $StatePath = Join-Path (Split-Path -Parent $LogPath) 'state.json'
}
$StatePath = [IO.Path]::GetFullPath($StatePath)

# --- Профили приложений ---
# WindowMode:
#   anyOtherVisible - встреча = любое видимое окно, кроме служебных (ServicePatterns);
#   patterns        - встреча = видимое окно с заголовком/классом из TitlePatterns/ClassPatterns;
#   audioOnly       - окна пока не размечены, признак только по активной аудиосессии.
$appProfiles = @(
    @{
        Id             = 'talk'
        Name           = 'Talk'
        Processes      = @('ktalk')
        ExeName        = 'ktalk.exe'
        WindowMode     = 'anyOtherVisible'
        ServicePatterns = @('^Толк$', '^ktalk$', '^DDE Server Window$', '^MSCTFIME UI$', '^Default IME$')
        WaitingPattern = '^Подключение к встрече'
        TitlePatterns  = @()
        ClassPatterns  = @()
    },
    @{
        Id             = 'zoom'
        Name           = 'Zoom'
        Processes      = @('Zoom')
        ExeName        = 'Zoom.exe'
        WindowMode     = 'patterns'
        ServicePatterns = @()
        WaitingPattern = ''
        # Заголовок может нести суффикс, например «Zoom Meeting 40-Minutes»
        # (лимит бесплатного тарифа, Zoom 7.1.9). Поэтому после «Zoom Meeting»
        # допускается продолжение, а не только конец строки.
        TitlePatterns  = @('(?i)^zoom meeting\b', '(?i)\s-\szoom meeting\b', '(?i)^zoom$')
        # ZPFloatVideoWndClass/VideoFrameWndClass — плавающее окно видео: при
        # сворачивании встречи в маленькое окно основное окно конференции
        # становится невидимым, остаются только эти окна (D-59).
        ClassPatterns  = @('ZPContentViewWndClass', 'ZPMeetingFrameWnd', 'ZPMeetingWindow',
            'ZPFloatVideoWndClass', 'VideoFrameWndClass')
    },
    @{
        Id             = 'telemost'
        Name           = 'Telemost'
        Processes      = @('YandexTelemost')
        ExeName        = 'YandexTelemost.exe'
        WindowMode     = 'anyOtherVisible'
        ServicePatterns = @('^Яндекс Телемост$', '^Приглашение участников$', '^QTrayIconMessageWindow$', '^ApplicationFallbackWindow$', '^MSCTFIME UI$', '^Default IME$',
            # Окно настроек тоже видимое и не является встречей (D-59).
            '^Настройки$', '^Settings$')
        # Окно «Звонок» — это сам звонок, а не ожидание: в нём уже видны
        # участники и кнопки звонка (проверено 13.11.2026, D-60). Отдельного
        # окна ожидания в этой версии не наблюдалось.
        WaitingPattern = ''
        TitlePatterns  = @()
        ClassPatterns  = @()
    }
)

$activeProfiles = @($appProfiles | Where-Object { $Apps -contains $_.Id })

$utf8 = New-Object Text.UTF8Encoding($false)

function Write-Event {
    param([string] $Message)
    $line = '{0}  {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Message
    if (-not $Quiet) { Write-Host $line }
    try {
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogPath))
        [IO.File]::AppendAllText($LogPath, $line + "`r`n", $utf8)
    } catch {
        if (-not $Quiet) { Write-Host ("failed to write log: {0}" -f $_.Exception.Message) }
    }
}

# --- Состояние для внешних исполнителей ---
# Пишется отдельный JSON, чтобы потребители (например, исполнитель розетки) не
# разбирали текстовый лог. Файл перезаписывается атомарно: временный файл + Move.
# Поле updated — Heartbeat: если наблюдатель остановлен, исполнитель увидит
# устаревшее состояние и ничего не будет переключать.
$stateHeartbeatSeconds = 10
$stateCore = $null
$stateWrittenAt = $null

function Write-State {
    $apps = [ordered]@{}
    $anyMeeting = $false
    foreach ($profile in $activeProfiles) {
        $rt = $runtime[$profile.Id]
        $apps[$profile.Id] = [ordered]@{
            app   = $profile.Name
            state = $rt.State
            since = if ($rt.Since) { $rt.Since.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
        }
        if ($rt.State -eq 'meeting') { $anyMeeting = $true }
    }

    $core = [ordered]@{
        intervalSeconds = $IntervalSeconds
        meeting         = $anyMeeting
        apps            = $apps
    }
    $coreJson = $core | ConvertTo-Json -Depth 5 -Compress

    $now = Get-Date
    if ($coreJson -eq $script:stateCore -and $script:stateWrittenAt -and
            ($now - $script:stateWrittenAt).TotalSeconds -lt $stateHeartbeatSeconds) {
        return
    }

    $full = [ordered]@{ updated = $now.ToString('yyyy-MM-dd HH:mm:ss') }
    foreach ($key in $core.Keys) { $full[$key] = $core[$key] }
    try {
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($StatePath))
        $tmp = "$StatePath.tmp"
        [IO.File]::WriteAllText($tmp, ($full | ConvertTo-Json -Depth 5 -Compress), $utf8)
        Move-Item -LiteralPath $tmp -Destination $StatePath -Force
        $script:stateCore = $coreJson
        $script:stateWrittenAt = $now
    } catch {
        if (-not $Quiet) { Write-Host ("failed to write state: {0}" -f $_.Exception.Message) }
    }
}

# --- Окна процессов ---
$winSrc = @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class MeetWin {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static List<string> Snapshots(uint[] pids) {
    var res = new List<string>();
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (Array.IndexOf(pids, p) >= 0 && IsWindowVisible(h)) {
        var t = new StringBuilder(512); GetWindowTextW(h, t, 512);
        var c = new StringBuilder(256); GetClassNameW(h, c, 256);
        string title = t.ToString().Trim();
        if (title.Length > 0) res.Add(p + "\t" + c.ToString() + "\t" + title);
      }
      return true;
    }, IntPtr.Zero);
    return res;
  }
}
'@
if (-not ('MeetWin' -as [type])) { Add-Type -TypeDefinition $winSrc -Language CSharp }

# --- Аудиосессии WASAPI ---
$audioSrc = @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device); }
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection { int GetCount(out int count); int Item(int i, out IMMDevice device); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface); int OpenPropertyStore(int access, out IntPtr store); int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetState(out int state); }
[ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioSessionManager2 { int NotUsed1(); int NotUsed2(); int GetSessionEnumerator(out IAudioSessionEnumerator e); }
[ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioSessionEnumerator { int GetCount(out int c); int GetSession(int i, [MarshalAs(UnmanagedType.IUnknown)] out object ctl); }
[ComImport, Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioSessionControl2 { int GetState(out int state); int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string n); int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string n, ref Guid ctx); int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string p); int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string p, ref Guid ctx); int GetGroupingParam(out Guid g); int SetGroupingParam(ref Guid g, ref Guid ctx); int RegisterAudioSessionNotification(IntPtr n); int UnregisterAudioSessionNotification(IntPtr n); int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetProcessId(out uint pid); int IsSystemSoundsSession(); int SetDuckingPreference(bool optOut); }
[ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioMeterInformation { int GetPeakValue(out float peak); }
public class MeetAudio {
  public static int ActiveSessions(uint[] pids) {
    int active = 0;
    var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    for (int flow = 0; flow <= 1; flow++) {
      IMMDeviceCollection coll; if (en.EnumAudioEndpoints(flow, 1, out coll) != 0 || coll == null) continue;
      int n; coll.GetCount(out n);
      for (int i = 0; i < n; i++) {
        IMMDevice dev; coll.Item(i, out dev);
        Guid iid = typeof(IAudioSessionManager2).GUID;
        object o; dev.Activate(ref iid, 1, IntPtr.Zero, out o);
        var mgr = o as IAudioSessionManager2; if (mgr == null) continue;
        IAudioSessionEnumerator se; mgr.GetSessionEnumerator(out se);
        int sc; se.GetCount(out sc);
        for (int j = 0; j < sc; j++) {
          object ctl; se.GetSession(j, out ctl);
          var c2 = ctl as IAudioSessionControl2; if (c2 == null) continue;
          uint pid; c2.GetProcessId(out pid);
          if (Array.IndexOf(pids, pid) < 0) continue;
          int st; c2.GetState(out st);
          if (st == 1) active++;
        }
      }
    }
    return active;
  }
}
'@
if (-not ('MeetAudio' -as [type])) { Add-Type -TypeDefinition $audioSrc -Language CSharp }

# --- Камера и микрофон: какие приложения используют устройство прямо сейчас ---
function Get-DeviceOwners {
    param([ValidateSet('webcam', 'microphone')] [string] $Kind)
    $result = @{}
    $root = "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\$Kind\NonPackaged"
    $keys = @()
    try { $keys = @(Get-ChildItem $root -ErrorAction SilentlyContinue) } catch { }
    foreach ($k in $keys) {
        $prop = Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue
        if (-not $prop) { continue }
        $exePath = $k.PSChildName -replace '#', '\'
        $result[$exePath] = ($prop.LastUsedTimeStop -eq 0)
    }
    return $result
}

function Test-DeviceInUse {
    param($Owners, [string] $ExeName)
    foreach ($path in $Owners.Keys) {
        if ([IO.Path]::GetFileName($path) -ieq $ExeName) { return [bool] $Owners[$path] }
    }
    return $false
}

# --- Снимок состояния приложения ---
function Get-AppSnapshot {
    param($Profile)
    $processes = @(Get-Process -Name $Profile.Processes -ErrorAction SilentlyContinue)
    $snap = [pscustomobject]@{
        Profile         = $Profile
        Running         = ($processes.Count -gt 0)
        ConferenceTitle = $null
        IsWaiting       = $false
        ActiveAudio     = 0
        Windows         = @()
    }
    if (-not $snap.Running) { return $snap }

    $pids = @($processes | ForEach-Object { [uint32] $_.Id })
    $windows = @()
    try {
        $windows = @([MeetWin]::Snapshots($pids) | ForEach-Object {
                $parts = $_ -split "`t", 3
                [pscustomobject]@{ Pid = $parts[0]; Class = $parts[1]; Title = $parts[2] }
            })
    } catch { }
    $snap.Windows = $windows

    try { $snap.ActiveAudio = [MeetAudio]::ActiveSessions($pids) } catch { }

    $conferenceTitle = $null
    foreach ($w in $windows) {
        $isService = $false
        foreach ($p in $Profile.ServicePatterns) { if ($w.Title -match $p) { $isService = $true; break } }
        if ($isService) { continue }

        switch ($Profile.WindowMode) {
            'anyOtherVisible' {
                $conferenceTitle = $w.Title
            }
            'patterns' {
                $matched = $false
                foreach ($p in $Profile.TitlePatterns) { if ($w.Title -match $p) { $matched = $true; break } }
                if (-not $matched) {
                    foreach ($p in $Profile.ClassPatterns) { if ($w.Class -match $p) { $matched = $true; break } }
                }
                if ($matched) { $conferenceTitle = $w.Title }
            }
            default { }
        }
        if ($conferenceTitle) { break }
    }

    $snap.ConferenceTitle = $conferenceTitle
    if ($conferenceTitle -and $Profile.WaitingPattern -and ($conferenceTitle -match $Profile.WaitingPattern)) {
        $snap.IsWaiting = $true
    }
    return $snap
}

# 'none' | 'waiting' | 'meeting'
# Встреча определяется только по окну (D-58). Аудиосессии остаются в
# диагностическом хвосте, но самостоятельным признаком не являются: в Толке
# после окна настроек сессии ktalk.exe остаются Active без встречи и без окон,
# и такая «встреча» не завершается.
function Get-RawState {
    param($Snapshot)
    if (-not $Snapshot.Running) { return 'none' }
    if ($Snapshot.ConferenceTitle) {
        if ($Snapshot.IsWaiting) { return 'waiting' }
        return 'meeting'
    }
    return 'none'
}

function Format-Details {
    param($Snapshot)
    $parts = @(
        ('window: ' + $(if ($Snapshot.ConferenceTitle) { 'yes' } else { 'no' })),
        ('audio sessions: ' + $Snapshot.ActiveAudio)
    )
    if (-not $NoTitles) {
        if ($Snapshot.ConferenceTitle) {
            $parts += ('title: "' + $Snapshot.ConferenceTitle + '"')
        }
        # Апробация: перечисляем и остальные видимые окна приложения с классами —
        # по ним видно, какой именно признак сработал или не сработал.
        # Заголовок окна может содержать тему встречи, поэтому список ограничен.
        if ($Snapshot.Windows.Count -gt 0) {
            $max = 6
            $seen = @()
            $i = 0
            foreach ($w in $Snapshot.Windows) {
                if ($i -ge $max) {
                    $seen += ('+{0} more' -f ($Snapshot.Windows.Count - $max))
                    break
                }
                $t = $w.Title
                if ($t.Length -gt 120) { $t = $t.Substring(0, 120) + '...' }
                $seen += ('[' + $w.Class + '] ' + $t)
                $i++
            }
            $parts += ('windows: ' + ($seen -join ' | '))
        }
    }
    return ($parts -join '; ')
}

if ($Once) {
    $webcams = Get-DeviceOwners 'webcam'
    $microphones = Get-DeviceOwners 'microphone'
    foreach ($profile in $activeProfiles) {
        $snap = Get-AppSnapshot $profile
        Write-Output ('[{0}] running={1} state={2} audio={3} camera={4} mic={5} windows={6}' -f `
                $profile.Name, $snap.Running, (Get-RawState $snap), $snap.ActiveAudio,
                (Test-DeviceInUse $webcams $profile.ExeName), (Test-DeviceInUse $microphones $profile.ExeName),
                $snap.Windows.Count)
        foreach ($w in $snap.Windows) { Write-Output ('    [{0}] {1}' -f $w.Class, $w.Title) }
    }
    return
}

# --- Защита от второго экземпляра ---
$mutex = New-Object Threading.Mutex($false, 'Local\LegacyMeetingsWatcher')
$hasMutex = $false
try { $hasMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $hasMutex = $true }
if (-not $hasMutex) {
    if (-not $Quiet) { Write-Host 'watcher is already running, second instance is not needed' }
    return
}

# Ротация лога: держим один архивный файл.
if (Test-Path -LiteralPath $LogPath) {
    try {
        if ((Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
            Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
        }
    } catch { }
}

Write-Event ('watcher started: apps {0}; interval {1}s; log {2}; state {3}' -f `
        (($activeProfiles | ForEach-Object { $_.Name }) -join ', '), $IntervalSeconds, $LogPath, $StatePath)

$runtime = @{}
$deviceKinds = @(
    @{ Kind = 'webcam'; LabelOn = 'camera on'; LabelOff = 'camera off'; SinceLabel = 'was on' },
    @{ Kind = 'microphone'; LabelOn = 'microphone on'; LabelOff = 'microphone off'; SinceLabel = 'was on' }
)
foreach ($profile in $activeProfiles) {
    $devices = @{}
    foreach ($d in $deviceKinds) {
        $devices[$d.Kind] = [pscustomobject]@{ InUse = $false; Votes = 0; Since = $null }
    }
    $runtime[$profile.Id] = [pscustomobject]@{
        State     = 'none'
        Candidate = 'none'
        Streak    = 0
        Since     = $null
        LastSeen  = $null
        Running   = $null
        Devices   = $devices
    }
}

Write-State

while ($true) {
    $owners = @{
        webcam     = Get-DeviceOwners 'webcam'
        microphone = Get-DeviceOwners 'microphone'
    }
    $now = Get-Date

    foreach ($profile in $activeProfiles) {
        $rt = $runtime[$profile.Id]
        $snap = Get-AppSnapshot $profile
        $raw = Get-RawState $snap

        # --- запуск/останов приложения ---
        if ($null -eq $rt.Running) {
            # Первый замер: приложение могло быть запущено задолго до наблюдателя,
            # поэтому это не событие запуска, а только начальное состояние.
            $rt.Running = $snap.Running
        } elseif ($rt.Running -ne $snap.Running) {
            if ($rt.Running -eq $true -and -not $snap.Running) {
                Write-Event ('[{0}] app closed' -f $profile.Name)
            } elseif ($snap.Running) {
                Write-Event ('[{0}] app started' -f $profile.Name)
            }
            $rt.Running = $snap.Running
        }

        # --- состояние встречи ---
        if ($raw -eq $rt.State) {
            $rt.Streak = 0
            $rt.LastSeen = $now
        } else {
            if ($raw -eq $rt.Candidate) {
                $rt.Streak++
            } else {
                $rt.Candidate = $raw
                $rt.Streak = 1
            }

            if ($rt.Streak -ge $StartPolls) {
                $prev = $rt.State
                $duration = $null
                if ($rt.Since) {
                    $leftAt = if ($rt.LastSeen) { $rt.LastSeen } else { $now }
                    $duration = $leftAt - $rt.Since
                }
                $rt.State = $raw
                $rt.Since = $now
                $rt.LastSeen = $now
                $rt.Streak = 0

                $details = Format-Details $snap
                switch ($rt.State) {
                    'waiting' {
                        Write-Event ('[{0}] joining meeting: waiting room ({1})' -f $profile.Name, $details)
                    }
                    'meeting' {
                        if ($prev -eq 'waiting') {
                            Write-Event ('[{0}] meeting STARTED: join confirmed ({1})' -f $profile.Name, $details)
                        } else {
                            Write-Event ('[{0}] meeting STARTED ({1})' -f $profile.Name, $details)
                        }
                    }
                    'none' {
                        if ($prev -eq 'waiting') {
                            Write-Event ('[{0}] join cancelled, did not enter the meeting' -f $profile.Name)
                        } else {
                            # В норме к моменту записи окна и аудиосессий уже нет, поэтому хвост
                            # не пишем. Он остаётся, только если состояние разошлось с ожидаемым:
                            # окно ещё на месте или медиапоток не закрыт.
                            $tail = ''
                            if ($snap.ConferenceTitle -or $snap.ActiveAudio -gt 0) { $tail = '; ' + $details }
                            Write-Event ('[{0}] meeting ENDED (duration {1:hh\:mm\:ss}{2})' -f `
                                    $profile.Name, $duration, $tail)
                        }
                    }
                }
            }
        }

        # --- камера и микрофон ---
        $context = ''
        if ($rt.State -eq 'none') { $context = ' (outside meeting)' }

        foreach ($d in $deviceKinds) {
            $dev = $rt.Devices[$d.Kind]
            $inUseNow = (Test-DeviceInUse $owners[$d.Kind] $profile.ExeName) -and $snap.Running

            if ($inUseNow -eq $dev.InUse) {
                $dev.Votes = 0
                continue
            }

            $dev.Votes++
            if ($dev.Votes -lt $CameraPolls) { continue }

            $dev.InUse = $inUseNow
            $dev.Votes = 0

            if ($inUseNow) {
                $dev.Since = $now
                Write-Event ('[{0}] {1}{2}' -f $profile.Name, $d.LabelOn, $context)
            } else {
                $suffix = ''
                if ($dev.Since) { $suffix = (' ({0} {1:hh\:mm\:ss})' -f $d.SinceLabel, ($now - $dev.Since)) }
                Write-Event ('[{0}] {1}{2}{3}' -f $profile.Name, $d.LabelOff, $suffix, $context)
                $dev.Since = $null
            }
        }
    }

    Write-State
    Start-Sleep -Seconds $IntervalSeconds
}
