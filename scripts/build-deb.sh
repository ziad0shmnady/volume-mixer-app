#!/usr/bin/env bash
# Build a shareable .deb package for Volume Mixer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep -E '^version\s*=' "$ROOT/pyproject.toml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
PKG="volume-mixer"
ARCH="all"
OUTPUT_DIR="${ROOT}/dist"
STAGING="$(mktemp -d)"

cleanup() {
  rm -rf "$STAGING"
}
trap cleanup EXIT

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "error: dpkg-deb is required (install dpkg)" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required to build the package" >&2
  exit 1
fi

echo "==> Building ${PKG}_${VERSION}_${ARCH}.deb"
mkdir -p "$OUTPUT_DIR"

echo "==> Installing Python package into staging root"
python3 -m pip install \
  --disable-pip-version-check \
  --no-deps \
  --no-compile \
  --target="$STAGING/usr/lib/python3/dist-packages" \
  "$ROOT" >/dev/null

install -d "$STAGING/usr/bin"
cat > "$STAGING/usr/bin/mixer" <<'EOF'
#!/usr/bin/python3
from mixer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
EOF
chmod 755 "$STAGING/usr/bin/mixer"

echo "==> Installing desktop entry and icon"
install -Dm644 "$ROOT/data/io.github.ziad.Mixer.desktop" \
  "$STAGING/usr/share/applications/io.github.ziad.Mixer.desktop"
install -Dm644 "$ROOT/data/io.github.ziad.Mixer.svg" \
  "$STAGING/usr/share/icons/hicolor/scalable/apps/io.github.ziad.Mixer.svg"

echo "==> Writing package metadata"
install -d "$STAGING/DEBIAN"
cat > "$STAGING/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Maintainer: Ziad <ziad@example.com>
Depends: python3 (>= 3.12),
         python3-gi,
         gir1.2-gtk-4.0,
         gir1.2-adw-1,
         python3-pulsectl,
         libpulse0
Recommends: pipewire-pulse
Description: GTK4 per-application volume mixer
 Volume Mixer is a native GTK4 / libadwaita app for Ubuntu that controls
 per-application and device audio levels via PipeWire / PulseAudio.
 Includes a system tray icon, global mute shortcut, and login autostart.
EOF

cat > "$STAGING/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
EOF
chmod 755 "$STAGING/DEBIAN/postinst"

cat > "$STAGING/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
  fi
fi
EOF
chmod 755 "$STAGING/DEBIAN/postrm"

OUTPUT="${OUTPUT_DIR}/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGING" "$OUTPUT"

echo
echo "Created: ${OUTPUT}"
echo
echo "Install on another machine:"
echo "  sudo apt install ./${PKG}_${VERSION}_${ARCH}.deb"
echo
echo "Requires Ubuntu 24.04+ (or any distro with Python 3.12+, GTK4, libadwaita)."
