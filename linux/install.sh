#!/usr/bin/env bash
# Install the Linux port into ~/.local/bin and create default config.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
BIN_DIR="${HOME}/.local/bin"
TARGET="${BIN_DIR}/dictate"
BUILD_ASR=0
DOWNLOAD_MODEL=""
HYPRLAND=0
HOLD=0
YES=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --build-asr) BUILD_ASR=1 ;;
    --download-model)
      DOWNLOAD_MODEL="bark-3.0"
      if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then
        DOWNLOAD_MODEL="$2"
        shift
      fi
      ;;
    --hyprland) HYPRLAND=1 ;;
    --hold) HOLD=1 ;;
    --yes|-y) YES=1 ;;
    --force) FORCE=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: linux/install.sh [options]
  --build-asr              build the CPU-only whisper.cpp parakeet runtime
  --download-model ID      download/convert a model and select it (default: bark-3.0)
  --hyprland               add the keybind block to Hyprland config
  --hold                   install press/release hold binds
  --yes                    do not prompt
  --force                  replace an existing non-symlink launcher
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required")
PY

mkdir -p "$BIN_DIR"
chmod +x "$ROOT/linux/dictate"
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  if [ -L "$TARGET" ] && [ "$(readlink -f "$TARGET")" = "$(readlink -f "$ROOT/linux/dictate")" ]; then
    :
  elif [ "$FORCE" -eq 1 ]; then
    rm -f "$TARGET"
  else
    BACKUP="${TARGET}.bak-$(date +%Y%m%d-%H%M%S)"
    echo "Existing $TARGET moved to $BACKUP (use --force to replace instead)."
    mv "$TARGET" "$BACKUP"
  fi
fi
ln -sfn "$ROOT/linux/dictate" "$TARGET"
echo "Installed launcher: $TARGET"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Warning: $BIN_DIR is not on PATH. Add it to your shell configuration." ;;
esac

# Create the default config on first install.
"$TARGET" config show >/dev/null

if [ "$BUILD_ASR" -eq 1 ]; then
  "$ROOT/scripts/build-asr-linux.sh"
fi
if [ -n "$DOWNLOAD_MODEL" ]; then
  "$TARGET" models download "$DOWNLOAD_MODEL" --use
fi
if [ "$HYPRLAND" -eq 1 ]; then
  ARGS=(setup --hyprland --no-download)
  [ "$HOLD" -eq 1 ] && ARGS+=(--hold)
  [ "$YES" -eq 1 ] && ARGS+=(--yes)
  "$TARGET" "${ARGS[@]}"
elif [ "$DOWNLOAD_MODEL" = "" ]; then
  echo
  echo "Next steps:"
  echo "  python3 -m venv .venv && source .venv/bin/activate"
  echo "  pip install numpy constriction              # conversion only"
  echo "  ./scripts/build-asr-linux.sh             # CPU-only parakeet-cli"
  echo "  dictate models download bark-3.0 --use   # ~167 MB download, ~1.2 GB converted"
  echo "  deactivate"
  echo "  dictate setup --hyprland                 # keybinds (or copy linux/hyprland.conf.example)"
  echo "  dictate doctor"
fi
