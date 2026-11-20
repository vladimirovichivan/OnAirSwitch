# OnAir Lamp

**English** | [Русский](README.ru.md)

An "On air" indicator for your desk: a Tuya smart plug switches a lamp on while a
video meeting is running in Microsoft Teams (Talk), Telemost or Zoom, and turns
it off when the meeting ends. Everything runs locally — no cloud account is
needed in everyday use, and no administrator rights are required.

[**Download the latest release**](https://github.com/vladimirovichivan/OnAirSwitch/releases/latest)

## How it works

- A PowerShell watcher detects meeting windows of supported apps and writes
  events to a local log. It never controls the device itself.
- A separate executor reads the desired state, talks to the plug over the local
  Tuya protocol and verifies every command by reading the state back.
- A tray icon shows the current meeting and its duration, the lamp state, the
  reason for that state, and lets you switch the lamp on or off for a chosen
  time or disable automation.
- A small supervisor starts and restarts all three processes, so a crashed
  component recovers on its own.

The device is polled only when a command is needed, and the plug address is
rediscovered over UDP if the router assigns a new one.

## Features

- Meeting detection by visible window titles (Teams/Talk, Telemost, Zoom),
  with a 3-sample threshold to avoid flicker.
- Local Tuya protocol; keys are stored only in a local file, never uploaded.
- Manual modes: on/off until a deadline, pause automation, resume.
- English and Russian UI; defaults to the Windows display language.
- Guided first-run setup, plug verification and a support report that contains
  logs but no keys or device identifiers.
- Automatic update check through GitHub Releases, with SHA-256 verification of
  the installer before it is launched.
- Single-file installer for Windows 10/11 (per-user, no UAC) and a portable ZIP.

## Requirements

- Windows 10 or Windows 11 (64-bit).
- A Tuya-compatible smart plug added to the Smart Life app.
- The PC and the plug on the same local network (not a guest Wi-Fi).
- For building from source: Python 3.12 and, optionally, Inno Setup 7 or 6.

## Install

1. Download `OnAirLamp-Setup-x.y.z.exe` from
   [Releases](https://github.com/vladimirovichivan/OnAirSwitch/releases/latest).
2. Run it and keep the "Start OnAir Lamp at sign-in" option enabled.
3. On first launch the app offers a setup wizard: enter the Tuya device ID,
   local key and address (the address can be found over UDP).

The full end-user guide is in [`docs/INSTALL.md`](docs/INSTALL.md) (Russian, as
shipped with the installer as `README.txt`). Troubleshooting is in
[`docs/SUPPORT.md`](docs/SUPPORT.md).

## Build from source

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The result is written to `build\`: a portable folder, a ZIP archive, and — if
Inno Setup is installed — `OnAirLamp-Setup-<version>.exe`. Checksums are stored
in `build\SHA256SUMS.txt`.

For development runs, use `packaging\start.vbs` or start the components
manually:

```powershell
.venv\Scripts\python.exe app\scripts\meetings\plug_executor.py --once
.venv\Scripts\pythonw.exe app\scripts\meetings\tray_plug.py
powershell -NoProfile -File app\scripts\meetings\watch_meetings.ps1 -Once
.venv\Scripts\python.exe app\scripts\meetings\tuya_setup.py --verify
```

## Privacy

- The app does not open a cloud connection for its daily work; it only talks to
  the plug on the local network.
- Tuya credentials and the local key stay in
  `%LOCALAPPDATA%\Programs\OnAirLamp\app\secrets\tuya_plug.json` on your PC.
- Window titles are written to a local log during the trial period; the support
  report excludes keys and device identifiers.
- The update check sends a single anonymous request to the GitHub Releases API.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design and components.
- [`docs/HISTORY.md`](docs/HISTORY.md) — decisions and verification log.
- [`docs/plan_packaging.md`](docs/plan_packaging.md) — packaging plan and status.
- [`docs/SUPPORT.md`](docs/SUPPORT.md) — troubleshooting.
- [`docs/INSTALL.md`](docs/INSTALL.md) — end-user installation guide.

## License

[MIT](LICENSE) © 2026 vladimirovichivan
