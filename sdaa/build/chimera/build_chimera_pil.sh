#!/usr/bin/env bash
set -euo pipefail
export LD_LIBRARY_PATH="/chimera/install/lib:${LD_LIBRARY_PATH:-}"
cd /chimera/build
if [[ "${1:-}" != --resume ]]; then
tar xzf /chimera/src/chimera.src/foreign/Imaging/Imaging-1.1.7.tar.gz
cd Imaging-1.1.7
for patchfile in /chimera/src/chimera.src/foreign/Imaging/Imaging-1.1.7-*.patch; do
    patch -p0 < "$patchfile"
done
else
cd Imaging-1.1.7
fi
python3.12 - <<'PY'
from pathlib import Path
import re
p = Path('setup.py')
t = p.read_text()
for name in ['JPEG', 'ZLIB', 'TIFF', 'TCL', 'TK', 'FREETYPE']:
    include = '/usr/include/freetype2' if name == 'FREETYPE' else '/usr/include'
    replacement = name+'_ROOT = '+repr(('/usr/lib64', include))
    if replacement not in t.splitlines():
        t, count = re.subn('(?m)^'+name+'_ROOT = None$', replacement, t)
        assert count == 1, name
p.write_text(t)
PY
export CFLAGS='-O1 -fno-strict-aliasing -fno-tree-vectorize'
/chimera/install/bin/python2.7 setup.py clean --all
/chimera/install/bin/python2.7 setup.py build_ext --include-dirs="$(pkg-config --variable=includedir freetype2)/freetype2" install
cd /tmp
/chimera/install/bin/python2.7 -c 'from PIL import Image, ImageTk; im=Image.new("RGB",(2,2),(1,2,3)); print(im.getpixel((0,0)))'
