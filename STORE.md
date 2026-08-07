# Publishing to the Ubuntu / Snap Store

Volume Mixer is packaged as a **strictly confined Snap** for the [Snap Store](https://snapcraft.io/store) (shown in Ubuntu App Center).

## Prerequisites

1. **Ubuntu One account** — https://login.ubuntu.com
2. **Publisher profile** — https://snapcraft.io/account
3. **Snapcraft** — `sudo snap install snapcraft --classic`
4. **LXD** (recommended for clean builds) — `sudo snap install lxd --classic && sudo lxd init --auto`

## One-time setup

```bash
# Log in to the store
snapcraft login

# Register the snap name (permanent; choose carefully)
snapcraft register volume-mixer
```

If the name is taken, pick another (e.g. `volume-mixer-ziad`) and update `name:` in `snap/snapcraft.yaml`.

## Build

```bash
./scripts/build-snap.sh
```

This produces `volume-mixer_<version>_amd64.snap` (and/or `arm64`) in the project root.

### Test locally

```bash
sudo snap install ./volume-mixer_*.snap --dangerous
volume-mixer
```

Verify:

- [ ] Main window opens and lists playing apps
- [ ] Volume sliders work (output, input, per-app)
- [ ] Tray icon appears (left-click popup, right-click menu)
- [ ] Global mute shortcut registers (Settings → Keyboard → Custom Shortcuts)
- [ ] “Open at Startup” writes autostart with `/snap/bin/volume-mixer --background`
- [ ] App survives PipeWire restart

Remove test install:

```bash
sudo snap remove volume-mixer
```

## Upload

```bash
snapcraft upload --release=stable ./volume-mixer_*.snap
```

The store runs automated checks. Fix any reported issues, rebuild, and upload again.

## Store listing checklist

Prepare these in the [Snap Store dashboard](https://snapcraft.io/volume-mixer/listing) or via `snapcraft upload-metadata`:

| Item | Source in repo |
|------|----------------|
| **Title** | Volume Mixer |
| **Summary** | From `snap/snapcraft.yaml` / metainfo |
| **Description** | `data/io.github.ziad.Mixer.metainfo.xml` |
| **Icon** | `data/io.github.ziad.Mixer.svg` (export 256×256 PNG if needed) |
| **Screenshots** | `mixer.jpeg` |
| **License** | MIT (`LICENSE`) |
| **Privacy policy URL** | Link to `PRIVACY.md` on GitHub |
| **Support URL** | GitHub Issues |
| **Website** | GitHub repo |

### Suggested categories

- Audio & Video
- Utilities

## Version bumps

1. Update `version` in `pyproject.toml`
2. Add a `<release>` in `data/io.github.ziad.Mixer.metainfo.xml`
3. Rebuild and upload

`adopt-info` in `snapcraft.yaml` reads the version from metainfo automatically.

## Known Snap limitations

| Feature | Status |
|---------|--------|
| Audio control | Works via `audio-playback` / `audio-record` plugs (auto-connected on Ubuntu) |
| System tray | Works with AppIndicators + `dbus` slot |
| Global mute shortcut | Uses `gsettings` plug; test after install |
| Per-app icons from other Snaps | May show generic icons (sandbox cannot read `/snap/discord/...`) |
| Settings | Stored in `~/snap/volume-mixer/current/.config/mixer/` |

## CI (optional)

Use [remote-build](https://documentation.ubuntu.com/snapcraft/latest/explanation/remote-build/) or GitHub Actions with `SNAPCRAFT_STORE_CREDENTIALS` for automated uploads.

## Resources

- [Publish a snap](https://documentation.ubuntu.com/snapcraft/latest/how-to/publishing/publish-a-snap/)
- [Craft a GTK4 app](https://documentation.ubuntu.com/snapcraft/latest/how-to/integrations/craft-a-gtk4-app/)
- [Craft a Python app](https://documentation.ubuntu.com/snapcraft/latest/how-to/integrations/craft-a-python-app/)
