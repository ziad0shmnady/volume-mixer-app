#!/usr/bin/env bash
# Install Mixer into a local venv and register a .desktop entry (no sudo).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${ROOT}/.venv"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_ID="io.github.ziad.Mixer"

# Ensure user-local bin (uv) is visible even in non-login shells.
export PATH="${HOME}/.local/bin:${PATH}"

# Prefer uv when available (works without python3-venv / ensurepip).
UV="${UV:-}"
if [[ -z "${UV}" ]]; then
  if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
  elif [[ -x "${HOME}/.local/bin/uv" ]]; then
    UV="${HOME}/.local/bin/uv"
  fi
fi

echo "==> Creating venv with system site packages (for PyGObject/gi)..."
if [[ -n "${UV}" ]]; then
  "${UV}" venv --system-site-packages --python python3 "${VENV}"
  # shellcheck disable=SC1091
  source "${VENV}/bin/activate"
  echo "==> Installing Mixer with uv..."
  "${UV}" pip install -e "${ROOT}[dev]"
else
  python3 -m venv --system-site-packages "${VENV}"
  # shellcheck disable=SC1091
  source "${VENV}/bin/activate"
  echo "==> Installing Mixer..."
  pip install --upgrade pip
  pip install -e "${ROOT}[dev]"
fi

echo "==> Installing desktop entry..."
mkdir -p "${DESKTOP_DIR}" "${ICON_DIR}"

ICON_SRC="${ROOT}/data/${DESKTOP_ID}.svg"
ICON_NAME="audio-volume-high"
if [[ -f "${ICON_SRC}" ]]; then
  cp "${ICON_SRC}" "${ICON_DIR}/${DESKTOP_ID}.svg"
  ICON_NAME="${DESKTOP_ID}"
fi

# Resolve mixer binary inside the venv
MIXER_BIN="${VENV}/bin/mixer"

cat > "${DESKTOP_DIR}/${DESKTOP_ID}.desktop" <<EOF
[Desktop Entry]
Name=Volume Mixer
Comment=Control per-application and device volume
Exec=${MIXER_BIN}
Icon=${ICON_NAME}
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Settings;
StartupNotify=true
Keywords=volume;mixer;audio;pulse;pipewire;
X-GNOME-UsesNotifications=false
EOF

# Optional: do not auto-enable startup here; user toggles it in the app menu.

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
echo "Installed. Launch with:"
echo "  ${MIXER_BIN}"
echo "or from the GNOME app grid as \"Volume Mixer\"."
