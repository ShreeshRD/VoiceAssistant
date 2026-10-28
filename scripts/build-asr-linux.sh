#!/usr/bin/env bash
# Build whisper.cpp's parakeet-cli for the Linux port with every GPU backend disabled.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
DEST="$ROOT/linux/.dependencies/whisper.cpp"
BIN="$DEST/build/bin/parakeet-cli"
TAG="${ASR_TAG:-${WHISPER_TAG:-v1.9.5}}"
JOBS="${JOBS:-$(nproc)}"

if [ "${1:-}" = "--force" ]; then
  rm -rf "$DEST"
fi

if [ -x "$BIN" ]; then
  echo "parakeet-cli already built: $BIN"
  if command -v ldd >/dev/null 2>&1; then
    LIB="$(ldd "$BIN" | awk '/libparakeet\.so/ {print $3; exit}')"
    [ -n "$LIB" ] && echo "Runtime: $(basename "$(readlink -f "$LIB")")"
  fi
  echo "Delete $DEST or pass --force to rebuild."
  exit 0
fi

for tool in git cmake gcc g++; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing build tool: $tool" >&2
    echo "On Arch: sudo pacman -S --needed git cmake base-devel" >&2
    exit 1
  }
done

mkdir -p "$(dirname "$DEST")"
if [ ! -d "$DEST/.git" ]; then
  echo "Cloning whisper.cpp $TAG ..."
  rm -rf "$DEST"
  git clone --depth 1 --branch "$TAG" https://github.com/ggerganov/whisper.cpp "$DEST"
fi

echo "Configuring CPU-only build (CUDA, Vulkan, HIP, SYCL and Metal disabled) ..."
cmake -S "$DEST" -B "$DEST/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=OFF \
  -DGGML_VULKAN=OFF \
  -DGGML_METAL=OFF \
  -DGGML_HIP=OFF \
  -DGGML_SYCL=OFF \
  -DGGML_OPENMP=ON \
  -DGGML_CCACHE=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF \
  -DWHISPER_BUILD_EXAMPLES=ON

echo "Building parakeet-cli with $JOBS jobs ..."
cmake --build "$DEST/build" --config Release -j "$JOBS" --target parakeet-cli

if [ ! -x "$BIN" ]; then
  echo "Build finished but $BIN is missing" >&2
  exit 1
fi

if ! "$BIN" --help 2>&1 | grep -q -- '-ng'; then
  echo "Built binary lacks -ng/--no-gpu; refusing to use it" >&2
  exit 1
fi

echo
echo "Built: $BIN"
if command -v ldd >/dev/null 2>&1; then
  LIB="$(ldd "$BIN" | awk '/libparakeet\.so/ {print $3; exit}')"
  [ -n "$LIB" ] && echo "Runtime: $(basename "$(readlink -f "$LIB")")"
  GPU_LIBS="$(ldd "$BIN" | grep -Ei 'cuda|vulkan|hip|rocm|opencl' || true)"
  if [ -n "$GPU_LIBS" ]; then
    echo "Warning: GPU libraries are linked:" >&2
    echo "$GPU_LIBS" >&2
  else
    echo "CPU-only check: no CUDA/Vulkan/HIP/ROCm/OpenCL libraries linked."
  fi
fi
