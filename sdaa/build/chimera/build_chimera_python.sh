#!/usr/bin/env bash
set -euo pipefail
CHROOT=/chimera
SRC=$CHROOT/src/chimera.src
PREFIX=$CHROOT/install
mkdir -p "$CHROOT/build/python" "$PREFIX/include/expat" "$PREFIX/lib" "$PREFIX/share"
tar xzf "$SRC/foreign/Python/Python-2.7.14.tgz" -C "$CHROOT/build/python"
cd "$CHROOT/build/python/Python-2.7.14"
# Keep the supplied non-platform Python patches; GUI patches are harmless in headless mode.
for patchfile in "$SRC"/foreign/Python/Python-2.7.14-*.patch; do
    # The bundled Expat-header relocation patch selects CPython's mangled
    # private headers. System Expat must use upstream's public header instead.
    [[ "$patchfile" == *-expat.patch ]] && continue
    patch -p0 < "$patchfile"
done
cp /usr/share/automake-1.16/config.guess config.guess
cp /usr/share/automake-1.16/config.sub config.sub
ln -s /usr/include/expat.h "$PREFIX/include/expat/expat.h"
ln -s /usr/include/expat_external.h "$PREFIX/include/expat/expat_external.h"
export LD_LIBRARY_PATH="$PREFIX/lib:${LD_LIBRARY_PATH:-}"
./configure --prefix="$PREFIX" --enable-shared --enable-unicode=ucs4 --disable-ipv6 \
    --with-cxx-main --with-system-expat --with-system-ffi --without-ensurepip \
    CPPFLAGS="-I$PREFIX/include" LDFLAGS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib" \
    CFLAGS='-O2 -fPIC -fwrapv -fno-strict-aliasing'
make -j8
make install
"$PREFIX/bin/python2.7" -c 'import sys, platform, ctypes, pyexpat, zlib; print(sys.version); print(platform.machine())'
cd "$CHROOT/build"
tar xzf "$SRC/foreign/setuptools/setuptools-3.1.tar.gz"
cd setuptools-3.1
"$PREFIX/bin/python2.7" setup.py install
cd "$CHROOT/build"
tar xzf "$SRC/foreign/numpy/numpy-1.7.2.tar.gz"
python3.12 /task/patch_chimera_numpy.py
cd numpy-1.7.2
"$PREFIX/bin/python2.7" setup.py build
"$PREFIX/bin/python2.7" setup.py install
cd /tmp
"$PREFIX/bin/python2.7" -c 'import numpy; print(numpy.__version__); print(numpy.dot(numpy.eye(2),numpy.ones(2)))'
