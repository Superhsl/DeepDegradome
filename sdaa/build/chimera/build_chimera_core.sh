#!/usr/bin/env bash
set -euo pipefail
SRC=/chimera/src/chimera.src
PREFIX=/chimera/install
export LD_LIBRARY_PATH="$PREFIX/lib:${LD_LIBRARY_PATH:-}"
export PATH="$PREFIX/bin:$PATH"
cd /tmp
"$PREFIX/bin/python2.7" -c 'import numpy; print(numpy.__version__)'
for module in path gfxinfo ioutil _chimera _molecule _volumearray vrml _surface _closepoints _distances _volume _contour _tkinter; do
    make -C "$SRC/libs/$module" -j8 build_root=/chimera/build/chimera \
        build_prefix="$PREFIX" foreign_prefix=/chimera/foreign \
        OPENGL_PLATFORM=OSMESA TARGET_ARCH= \
        EXTRA_CXXFLAGS="$(pkg-config --cflags freetype2)" install
done
PYTHONPATH="$PREFIX/lib:$SRC/libs" "$PREFIX/bin/python2.7" -c 'import _chimera,_molecule,_surface,_vrml; print("headless C++ cores imported")'
