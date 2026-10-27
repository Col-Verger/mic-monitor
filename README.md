# mic-monitor

[![build](https://github.com/Col-Verger/mic-monitor/actions/workflows/build.yml/badge.svg)](https://github.com/Col-Verger/mic-monitor/actions/workflows/build.yml)
[![release](https://img.shields.io/github/v/release/Col-Verger/mic-monitor)](https://github.com/Col-Verger/mic-monitor/releases/latest)
[![license](https://img.shields.io/github/license/Col-Verger/mic-monitor)](LICENSE)
[![windows](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)](https://github.com/Col-Verger/mic-monitor/releases/latest)

**English** · [Русский](README.ru.md)

**Download:** [installer](https://github.com/Col-Verger/mic-monitor/releases/latest) ·
[portable exe](https://github.com/Col-Verger/mic-monitor/releases/latest)

A tiny always-on-top overlay for Windows that shows the **current microphone level**, the **live input
signal**, and a **history of who changed the volume** — with the process name, its exe path, and a sound
alert on every change.

Pin it in a corner and you can see when Discord, a game, or a vendor panel (Realtek, Nahimic,
SteelSeries Sonar, Voicemeeter) touched your mic, by how much, and what was running at that moment.

![Overlay](docs/screenshot-overlay.png)

![History](docs/screenshot-history.png)

## The problem it solves

Windows shows your microphone level only if you dig into *Settings → Sound → Input*. The system keeps
**no history** and never tells you **which program** changed the level. Hence the usual situations:

- **"Nobody can hear me anymore"** — the mic got quieter, and you have no idea when or why.
  Discord, Teams, Steam, a game, Realtek or SteelSeries Sonar could have lowered it in the background.
- **"I plugged my headset back in"** — Windows reset the slider to 100%, your voice is clipping,
  and nothing tells you the level changed at all.
- **"Settings are fighting each other"** — two programs both think they own the mic and keep
  resetting it: 100% → 40% → 100%.
- **"I want to see it, not guess"** — you need the level raised for every app at once, not to walk
  through each app's settings.
- **"I can't prove it"** — support asks for facts: when, by how much, and which program.

mic-monitor does exactly this: keeps the level in sight, writes every change with a timestamp and the
suspected process, and beeps so a change never slips by unnoticed.

| Problem | What the app does |
|---|---|
| you don't know what lowered the mic | log entry with process, exe path, parent process and confidence |
| you can't see the current level | always-on-top overlay: percent, bar, live signal |
| the change slipped by | sound alert on every change (a different one for mute) |
| you need the pattern | change history and a per-program summary: how many times, which values |
| you need to hand over facts | CSV export and a plain-text log |

## Features

- **Always-on-top overlay**: recording device, volume in percent, volume bar, thin live signal bar,
  the last change and the suspected process.
- **Compact mode** — device, percent and bar only.
- **Change history**: time, before → after, device, suspect and confidence; a second tab is a
  per-program summary (how many matches, which values it set).
- **Plain-text log** with evidence: `%LOCALAPPDATA%\MicMonitor\mic-monitor.log` — suspect, exe path,
  parent process, active window, who holds the mic, recently started processes.
- **Sound alert on change** (built-in Windows sounds, no extra files), toggleable in the menu.
- **CSV export** and recording-device picker in the menu.
- **Start with Windows** — menu toggle (also a checkbox in the installer).
- Drag to move, always-on-top/opacity, remembered position, single instance.
- **English and Russian UI**, detected from the system language and switchable at runtime
  (menu → Language, or `--lang en`).

## Install

**Installer (recommended):** download `MicMonitor-Setup-<version>.exe` from
[Releases](https://github.com/Col-Verger/mic-monitor/releases/latest) and run it.

- no administrator rights, installs into `%LOCALAPPDATA%\Programs\mic-monitor`;
- Start Menu shortcut and (optionally) a desktop shortcut;
- shows up in *Settings → Apps*, uninstalls from there;
- optional "start with Windows" checkbox;
- if the app is running, the installer and uninstaller close it automatically.

**Portable:** `MicMonitor.exe` from the same release — just run it, nothing is installed.

**From source:**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe mic_monitor.py
```

Or `.\run.ps1`, which creates the venv and installs dependencies for you.

Useful modes:

```powershell
python mic_monitor.py --probe        # recording devices, volume, audio sessions
python mic_monitor.py --watch 60     # log changes to the console for 60 seconds, no window
python mic_monitor.py --lang en      # force the UI language (en / ru)
```

## Controls

- **drag** — move the overlay, the position is remembered;
- **double click** — history window;
- **right click** — menu: history, compact view, always on top, sound, start with Windows, open log,
  device picker, language, quit;
- **✕** — quit.

## Where the data lives

`%LOCALAPPDATA%\MicMonitor\`

| file | contents |
|---|---|
| `mic-monitor.log` | plain-text change log with evidence (rotates at 1 MB) |
| `history.jsonl` | the same events as JSON, last 500 |
| `config.json` | window position, opacity, sound, language, chosen device |
| `mic-history-*.csv` | exports from the history window |

## The honest limitation

Windows **does not tell you** which process changed the recording volume: Core Audio has no such event,
only the new level. So the "suspect" is a **heuristic**, not a fact.

What is actually measured: device volume/mute (the same slider as *Level* in Windows settings), the
signal peak, and the programs that have the mic open at that moment (real WASAPI audio sessions).

Candidates gain weight from these signals:

| signal | weight |
|---|---|
| just opened the mic (≤ 4 s) | 3.2 |
| active window at the moment of change | 3.0 |
| started just now (≤ 8 s) | 2.2 |
| holds the mic | 2.0 |
| known audio control panel (Realtek, Sonar, SteelSeries, Voicemeeter…) | +1.2 |

Both the log and the history window state the confidence: `high` / `medium` / `low`. If two processes
are equally plausible, the confidence is low — and that is the honest answer.

What the app **does not** do: it does not change the driver-level "Microphone Boost (+dB)" (only the
vendor panel can) and it does not touch per-app input gain (Discord/OBS/Teams manage that themselves).

## Build

```powershell
.\build.ps1            # dist\MicMonitor.exe (portable)
.\build-installer.ps1  # dist\MicMonitor-Setup-<version>.exe (Inno Setup)
```

`build.ps1` creates/updates the venv, installs dependencies, generates the icon
(`tools/make_icon.py`) and the PyInstaller version resource, builds the single-file windowless exe and
copies it to the desktop. `build-installer.ps1` then builds the installer from
`installer\mic-monitor.iss` (requires [Inno Setup 6](https://jrsoftware.org/isinfo.php):
`winget install --id JRSoftware.InnoSetup -e`).

The version comes from `mic_monitor.__version__`. CI runs the tests on every push and PR, and on a `v*`
tag builds the exe and the installer and attaches them to the release
(`git tag v1.3.0 && git push origin v1.3.0`).

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Covers the pure logic — change detection, candidate weighting and confidence, formatting, history,
text log, system sound choice — plus translation key parity, placeholder parity and both languages
rendering.

## Requirements

- Windows 10 / 11 (Core Audio, WASAPI and tkinter ship with Python);
- Python 3.10+ when running from source; the released exe has no dependencies;
- the exe is not code-signed, so SmartScreen may ask for confirmation.

## License

MIT — see [LICENSE](LICENSE).
