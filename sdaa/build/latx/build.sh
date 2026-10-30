#!/usr/bin/env bash
set -euo pipefail
SOURCE=$(realpath "${1:?LAT source checkout at locks/latx-source.json commit}")
BUILD=$(realpath -m "${2:?new absolute build directory}")
TARGET=${3:-64}
MESON=${MESON:?absolute executable Meson 0.63.3 wrapper required}
test "$(uname -m)" = loongarch64
test -f "$SOURCE/configure"
test ! -e "$BUILD"
mkdir -p "$BUILD"
cd "$BUILD"
EXTRA=()
case "$TARGET" in
 64) ARCH=x86_64-linux-user;;
 32) ARCH=i386-linux-user; EXTRA=(--enable-guest-base-zero --disable-pie);;
 *) echo 'target must be 32 or 64' >&2; exit 2;;
esac
"$SOURCE/configure" --target-list="$ARCH" "${EXTRA[@]}" --enable-latx --optimize-O1 --disable-blobs --disable-debug-info --disable-docs --disable-linux-io-uring --disable-werror --extra-ldflags=-ldl --meson="$MESON"
ninja -j"${JOBS:-8}"
