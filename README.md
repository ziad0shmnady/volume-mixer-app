# Volume Mixer

A native **GTK 4 / libadwaita** volume mixer for Linux. Control output, input, and **per-application** audio levels from a clean desktop app or the system tray — built for **Ubuntu** and **PipeWire** (via the PulseAudio compatibility layer).

> **Why this exists:** GNOME’s built-in sound settings only expose a few controls. Volume Mixer gives you a proper per-app mixer (like Windows or macOS), a tray popup for quick changes, and a global mute shortcut — without leaving your workflow.

---

## Features

### Audio control
- **Output** — master volume, mute, and default playback device
- **Input** — microphone volume, mute, and default recording device
- **Applications** — per-app volume sliders, mute, and output routing (move an app to another speaker/headset)
- **Live sync** — changes from other apps (keyboard media keys, Discord, etc.) update instantly
- **Friendly names** — sensible labels for apps (e.g. Discord instead of `WEBRTC VoiceEngine`)

### System tray
Works with Ubuntu’s **AppIndicators** extension (default on Ubuntu).

| Action | Result |
|--------|--------|
| **Left-click** tray icon | Popup with per-app volume sliders |
| **Right-click** tray icon | Context menu (volumes, mute input, open mixer, startup toggle, quit) |
| **Close main window** | Hides to tray (app keeps running) |

### Shortcuts & startup
- **Global mute shortcut** — mute/unmute the microphone from any app (registered in GNOME Settings → Keyboard → Custom Shortcuts)
- **Customizable shortcut** — click the shortcut button next to the mic in the main window to rebind
- **Open at startup** — launch minimized to the tray on login (toggle in the ☰ menu or tray context menu)

### Quality of life
- Over-amplification toggle (allow volume above 100%)
- Reconnects automatically if PipeWire/PulseAudio restarts
- Lightweight — no Electron, no background daemons beyond the tray app itself

---

## Requirements

| Component | Details |
|-----------|---------|
| **OS** | Ubuntu **24.04+** (or any distro with the packages below) |
| **Desktop** | GNOME with AppIndicators (Ubuntu default) |
| **Audio** | PipeWire + `pipewire-pulse` (default on modern Ubuntu) |
| **Python** | 3.12+ |
| **GTK** | GTK 4 + libadwaita (via system packages) |

### System packages (installed automatically by the `.deb`)

```text
python3-gi
gir1.2-gtk-4.0
gir1.2-adw-1
python3-pulsectl
libpulse0
```

---

## Installation

### Option 1 — `.deb` package (recommended)

Download the latest `volume-mixer_*_all.deb` from the [Releases](../../releases) page, then:

```bash
sudo apt install ./volume-mixer_1.0.0_all.deb
```

Launch **Volume Mixer** from the app grid, or run:

```bash
mixer
```

To remove:

```bash
sudo apt remove volume-mixer
```

### Option 2 — Build the `.deb` yourself

```bash
git clone https://github.com/ziad/mixer.git
cd mixer
./scripts/build-deb.sh
```

The package is written to `dist/volume-mixer_1.0.0_all.deb`.

### Option 3 — Install from source (development)

```bash
git clone https://github.com/ziad/mixer.git
cd mixer
./install.sh
```

This creates a local virtual environment, installs the app, and registers a `.desktop` entry in your app grid.

**Optional:** [uv](https://github.com/astral-sh/uv) speeds up venv creation:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
./install.sh
```

Run after installing:

```bash
.venv/bin/mixer
```

---

## Usage

### Main window

Open **Volume Mixer** from the app grid. You’ll see:

1. **Output** and **Input** side by side — device picker + volume slider for each
2. **Applications** below — one row per app currently playing audio

Use the **☰ menu** (top-right) for mute input, refresh, tray toggle, startup toggle, and quit.

### Tray popup

Left-click the tray icon for a compact list of running apps with volume sliders — useful when you don’t need the full window.

### Global microphone mute

Default shortcut: **Ctrl + Shift + M** (customizable in the app).

The shortcut works **even when the mixer window is closed**, as long as Volume Mixer is running in the tray. It is registered as **“Volume Mixer: Mute Input”** in:

> **Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts**

### Start on login

Enable **Open at Startup** from the ☰ menu or the tray right-click menu. Volume Mixer will start hidden in the tray.

---

## Command-line options

```bash
mixer                  # Open the main window (or show if already running)
mixer --background     # Start hidden in the tray
mixer -v               # Verbose logging
mixer --fake           # Run with a fake backend (no audio server needed)
```

---

## Configuration

Settings are stored in:

```text
~/.config/mixer/settings.json
```

| Key | Default | Description |
|-----|---------|-------------|
| `mute_input_accel` | `<Primary><Shift>m` | Global mute shortcut (GTK accelerator format) |
| `show_tray` | `true` | Show the system tray icon |
| `start_on_login` | `false` | Launch on login (writes an XDG autostart file) |
| `start_minimized` | `true` | When autostarting, begin in the tray |

---

## Troubleshooting

### Tray icon does not appear
- Ensure **Ubuntu AppIndicators** is enabled: `gnome-extensions list` should include `ubuntu-appindicators@ubuntu.com`
- Check **Show Tray Icon** is enabled in the ☰ menu

### No applications listed
- Only apps **actively playing audio** appear. Start playback in a browser, Discord, Spotify, etc.
- Confirm PipeWire is running: `pactl info`

### Global mute shortcut does nothing
- Volume Mixer must be running (in the tray counts)
- Check the binding in **Settings → Keyboard → Custom Shortcuts → Volume Mixer: Mute Input**
- Re-open the app or change the shortcut in the mixer UI to re-register it

### Right-click tray menu is empty
- Log out and back in (or restart GNOME Shell) after upgrading — the AppIndicators extension may need to re-read the menu

### Audio service unavailable
- Install/start PipeWire: `sudo apt install pipewire pipewire-pulse`
- Restart the session or run `systemctl --user restart pipewire pipewire-pulse`

---

## Development

### Project layout

```text
src/mixer/
  app.py              Application entrypoint, tray, shortcuts
  models/             Typed audio models (streams, devices)
  services/           PulseAudio backend (threaded worker)
  viewmodel/          UI state, debouncing, volume math
  ui/                 GTK 4 / libadwaita widgets
  util/               Settings, autostart, GNOME shortcuts
data/                 Desktop entry, icon, CSS
scripts/build-deb.sh  Debian package builder
tests/                pytest suite
```

### Architecture

```text
GTK UI  →  MixerViewModel  →  AudioBackend  →  PulseService (worker thread)  →  PipeWire / pulse
```

The Pulse connection lives on a single background thread. Snapshots are pushed to the GTK main loop with `GLib.idle_add`, so the UI stays responsive.

### Run tests

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Build a release package

```bash
./scripts/build-deb.sh
```

---

## Contributing

Contributions are welcome. Please open an issue before large changes.

1. Fork the repository
2. Create a feature branch
3. Run `pytest`
4. Open a pull request

---

## License

[MIT](LICENSE) — see `pyproject.toml` for details.

---

## Acknowledgments

Built with [PyGObject](https://pygobject.gnome.org/), [GTK 4](https://www.gtk.org/), [libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/), and [pulsectl](https://github.com/mk-fg/python-pulse-control).
