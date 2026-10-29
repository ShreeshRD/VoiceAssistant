#!/usr/bin/env bash
# Install a self-contained runtime outside the checkout and link the launchers.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
INSTALL_ROOT="${DICTATE_INSTALL_ROOT:-${DATA_HOME}/speech-flow/app}"
TARGET="${BIN_DIR}/dictate"
WAYBAR_TARGET="${BIN_DIR}/dictate-assistant-waybar"
BUILD_ASR=0
DOWNLOAD_MODEL=""
HYPRLAND=0
HOLD=0
ASSISTANT=0
YES=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --build-asr) BUILD_ASR=1 ;;
    --prefix)
      [ $# -ge 2 ] || { echo "--prefix needs a directory" >&2; exit 2; }
      INSTALL_ROOT="$2"
      shift
      ;;
    --download-model)
      DOWNLOAD_MODEL="bark-3.0"
      if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then
        DOWNLOAD_MODEL="$2"
        shift
      fi
      ;;
    --hyprland) HYPRLAND=1 ;;
    --hold) HOLD=1 ;;
    --assistant) ASSISTANT=1 ;;
    --yes|-y) YES=1 ;;
    --force) FORCE=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: linux/install.sh [options]
  --prefix DIR             install the runtime below DIR (default: ~/.local/share/speech-flow/app)
  --build-asr              build the CPU-only whisper.cpp parakeet runtime first
  --download-model ID      download/convert a model and select it (default: bark-3.0)
  --hyprland               add the keybind block to Hyprland config
  --hold                   install press/release hold binds
  --assistant              bind SUPER+A to the voice assistant (with --hyprland)
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

if [ -z "$INSTALL_ROOT" ] || [ "$INSTALL_ROOT" = "/" ]; then
  echo "Refusing to install into '$INSTALL_ROOT'" >&2
  exit 2
fi

if [ "$BUILD_ASR" -eq 1 ]; then
  "$ROOT/scripts/build-asr-linux.sh"
fi

install_runtime() {
  local target="$INSTALL_ROOT/linux"
  rm -rf "$INSTALL_ROOT"
  mkdir -p "$target"
  cp -a "$ROOT/linux/dictate" "$target/"
  cp -a "$ROOT/linux/ASR" "$target/"
  cp -a "$ROOT/linux/models.json" "$target/"
  cp -a "$ROOT/linux/waybar" "$target/"
  cp -a "$ROOT/linux/systemd" "$target/"
  cp -a "$ROOT/linux/hyprland.conf.example" "$target/"
  cp -a "$ROOT/linux/README.md" "$target/"
  find "$target" -name '__pycache__' -type d -prune -exec rm -rf {} +

  local asr_bin="$ROOT/linux/.dependencies/whisper.cpp/build/bin"
  if [ -x "$asr_bin/parakeet-cli" ]; then
    mkdir -p "$target/.dependencies/whisper.cpp/build/bin"
    cp -a "$asr_bin/." "$target/.dependencies/whisper.cpp/build/bin/"
  else
    echo "Warning: parakeet-cli is not built; run linux/install.sh --build-asr." >&2
  fi
}

mkdir -p "$BIN_DIR"
chmod +x "$ROOT/linux/dictate"
install_runtime
chmod +x "$INSTALL_ROOT/linux/dictate"
echo "Installed runtime: $INSTALL_ROOT"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  if [ -L "$TARGET" ] && [ "$(readlink -f "$TARGET")" = "$(readlink -f "$INSTALL_ROOT/linux/dictate")" ]; then
    :
  elif [ "$FORCE" -eq 1 ]; then
    rm -f "$TARGET"
  else
    BACKUP="${TARGET}.bak-$(date +%Y%m%d-%H%M%S)"
    echo "Existing $TARGET moved to $BACKUP (use --force to replace instead)."
    mv "$TARGET" "$BACKUP"
  fi
fi
ln -sfn "$INSTALL_ROOT/linux/dictate" "$TARGET"
echo "Installed launcher: $TARGET"

chmod +x "$INSTALL_ROOT/linux/waybar/dictate-assistant-waybar"
if [ -e "$WAYBAR_TARGET" ] && [ ! -L "$WAYBAR_TARGET" ]; then
  mv "$WAYBAR_TARGET" "${WAYBAR_TARGET}.bak-$(date +%Y%m%d-%H%M%S)"
fi
ln -sfn "$INSTALL_ROOT/linux/waybar/dictate-assistant-waybar" "$WAYBAR_TARGET"
echo "Installed Waybar helper: $WAYBAR_TARGET"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Warning: $BIN_DIR is not on PATH. Add it to your shell configuration." ;;
esac

# Create the default config on first install.
"$TARGET" config show >/dev/null

if [ -n "$DOWNLOAD_MODEL" ]; then
  "$TARGET" models download "$DOWNLOAD_MODEL" --use
fi
if [ "$HYPRLAND" -eq 1 ]; then
  ARGS=(setup --hyprland --no-download)
  [ "$HOLD" -eq 1 ] && ARGS+=(--hold)
  [ "$ASSISTANT" -eq 1 ] && ARGS+=(--assistant)
  [ "$YES" -eq 1 ] && ARGS+=(--yes)
  "$TARGET" "${ARGS[@]}"
elif [ "$DOWNLOAD_MODEL" = "" ]; then
  echo
  echo "Next steps:"
  echo "  python3 -m venv .venv && source .venv/bin/activate"
  echo "  pip install numpy constriction              # conversion only"
  echo "  ./scripts/build-asr-linux.sh             # CPU-only parakeet-cli"
  echo "  ./linux/install.sh --build-asr           # refresh the installed runtime"
  echo "  dictate models download bark-3.0 --use   # ~167 MB download, ~1.2 GB converted"
  echo "  deactivate"
  echo "  dictate setup --hyprland                 # keybinds (or copy linux/hyprland.conf.example)"
  echo "  dictate doctor"
fi
