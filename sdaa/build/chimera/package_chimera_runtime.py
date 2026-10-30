"""Bundle the native headless install and its resolved, isolated libraries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, default=Path('/chimera/install'))
p.add_argument('--destination', type=Path, default=Path('/chimera/package/install/chimera'))
a = p.parse_args()
assert not a.destination.exists()
shutil.copytree(a.source, a.destination, symlinks=True)
env = dict(os.environ, LD_LIBRARY_PATH=str(a.source/'lib'))
dependencies, binaries = {}, []
glibc = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1',
         'libutil.so.1', 'libresolv.so.2', 'ld-linux-loongarch-lp64d.so.1'}
for binary in sorted(a.source.rglob('*')):
    if not binary.is_file() or binary.is_symlink():
        continue
    with binary.open('rb') as stream:
        header = stream.read(20)
    if not header.startswith(b'\x7fELF'):
        continue
    assert int.from_bytes(header[18:20], 'little') == 258, binary
    binaries.append(str(binary.relative_to(a.source)))
    run = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, env=env)
    assert 'not found' not in run.stdout, run.stdout
    if run.returncode:
        assert 'statically linked' in run.stdout+run.stderr or 'not a dynamic executable' in run.stdout+run.stderr
        continue
    for line in run.stdout.splitlines():
        fields = line.split()
        if '=>' not in fields:
            continue
        library = Path(fields[fields.index('=>')+1])
        if not library.is_absolute() or library.name in glibc or library.resolve().is_relative_to(a.source):
            continue
        target = a.destination/'lib'/library.name
        if target.exists():
            assert target.read_bytes() == library.read_bytes(), library
        else:
            shutil.copy2(library, target)
        dependencies[library.name] = {'origin':str(library),
            'sha256':hashlib.sha256(library.read_bytes()).hexdigest()}
# The installation step applies the reviewed deterministic policy.
# Keep the exact policy manifest with the packaged chemistry runtime.
manifest = {'native_elf_count':len(binaries), 'native_elf_machine':258,
    'native_elfs':binaries, 'isolated_system_libraries':dependencies,
    'chemistry_ordering_experiments_enabled':False,
    'scope':'Headless AddH/AddCharge with Amber18 AM1-BCC; functional tests passed, strict cross-platform numerical equivalence has not passed.'}
policy_path = a.destination/'chimera-determinism.json'
assert policy_path.is_file(), 'Apply the deterministic policy during installation first'
manifest['deterministic_preparation_policy'] = json.loads(policy_path.read_text())
manifest['scope'] = 'Native headless AddH/AddCharge with deterministic ordering and AM1-BCC diag_routine=3; four frozen inputs validated, not arbitrary-input equivalence.'
(a.destination/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'native_elf_count':len(binaries), 'isolated_library_count':len(dependencies),
                  'destination':str(a.destination)},indent=2))
