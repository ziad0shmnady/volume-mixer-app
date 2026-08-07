#!/usr/bin/env bash
# Build a Snap package for Volume Mixer (Ubuntu Store / Snap Store).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v snapcraft >/dev/null 2>&1; then
  echo "error: snapcraft is required." >&2
  echo "Install with: sudo snap install snapcraft --classic" >&2
  exit 1
fi

echo "==> Building Snap (strict confinement, core24)"
snapcraft pack --use-lxd

echo
echo "Install locally for testing:"
echo "  sudo snap install ./volume-mixer_*.snap --dangerous"
echo
echo "Publish to the Snap Store:"
echo "  snapcraft login"
echo "  snapcraft register volume-mixer   # first time only"
echo "  snapcraft upload --release=stable ./volume-mixer_*.snap"
echo
echo "See STORE.md for the full publishing checklist."
