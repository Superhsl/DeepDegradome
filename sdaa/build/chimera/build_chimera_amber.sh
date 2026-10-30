#!/usr/bin/env bash
set -euo pipefail
SRC=/chimera/build/amber18
PATCHES=/chimera/src/chimera.src/foreign/AmberTools
export AMBERHOME="$SRC"
export LD_LIBRARY_PATH="$SRC/lib:${LD_LIBRARY_PATH:-}"
cd "$SRC"
if [[ "${1:-}" != --resume ]]; then
for name in csh.patch parmchk.patch byacc.patch quote.patch; do
    patch --batch --forward -p0 < "$PATCHES/$name"
done
# Old bundled Autoconf helpers predate LoongArch. Update platform recognition
# using this compiler image's packaged GNU helpers.
python3.12 - <<'PY'
from pathlib import Path
import shutil
root = Path('/chimera/build/amber18')
for name in ['config.guess', 'config.sub']:
    for path in root.rglob(name):
        shutil.copyfile('/usr/share/automake-1.16/'+name, path)
PY
fi
python3.12 /task/patch_chimera_amber_profile.py
export CHIMERA_CHARGE_ONLY=yes
NETCDF=()
if [[ -f "$SRC/lib/libnetcdf.a" && -f "$SRC/lib/libnetcdff.a" ]]; then
    NETCDF=(--with-netcdf "$SRC")
fi
./configure --no-updates -nofftw3 --skip-python -noX11 -nosse "${NETCDF[@]}" gnu
cat >> AmberTools/src/config.h <<'FLAGS'

# GCC12 compatibility and explicit non-contracted CPU arithmetic.
CFLAGS += -fcommon -ffp-contract=off
FFLAGS += -fallow-argument-mismatch -ffp-contract=off
AMBERCFLAGS += -fcommon -ffp-contract=off
AMBERFFLAGS += -fallow-argument-mismatch -ffp-contract=off
FLAGS
for component in c9x-complex byacc cifparse sqm antechamber; do
    if [[ "$component" == c9x-complex ]]; then target=all; else target=install; fi
    make -C "AmberTools/src/$component" -j8 FREEFORMAT_FLAG= "$target"
done
file bin/sqm bin/to_be_dispatched/antechamber
