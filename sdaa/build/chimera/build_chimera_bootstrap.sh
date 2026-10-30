#!/usr/bin/env bash
set -euo pipefail
SRC=/chimera/src/chimera.src
PREFIX=/chimera/install
export LD_LIBRARY_PATH="$PREFIX/lib:${LD_LIBRARY_PATH:-}"
export PATH="$PREFIX/bin:$PATH"
mkdir -p "$PREFIX/include" "$PREFIX/lib" "$PREFIX/bin" "$PREFIX/share" /chimera/foreign/src
# The OTF makefile has x86-only flags by default for unrecognized CPUs.
# Keep all target flags empty for this native compiler.
make -C "$SRC/otf" -j1 OTF="$PREFIX" PYVER=2.7 \
    PYINC="$PREFIX/include/python2.7" TARGET_ARCH= \
    CXX='g++ -pipe -pthread -fPIC -Wall -Wextra -std=gnu++03' install
make -C "$SRC/foreign/tr" -j4 build_root=/chimera/build/chimera \
    build_prefix="$PREFIX" foreign_prefix=/chimera/foreign \
    OPENGL_PLATFORM=OSMESA TARGET_ARCH= install-for-chimera-build
file "$PREFIX/bin/wrappy2" "$PREFIX/lib/libwrappy2.so" "$PREFIX/lib/libtr.so"
