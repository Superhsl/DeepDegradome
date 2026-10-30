"""Install the built native AM1-BCC tools and their actual project dependencies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

src = Path('/chimera/build/amber18')
prefix = Path('/chimera/install')
destination = prefix/'bin/amber18'
binary_dir = destination/'bin'
binary_dir.mkdir(parents=True, exist_ok=False)
records = []
for directory in [src/'bin', src/'bin/to_be_dispatched']:
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in ['nccopy','ncdump','ncgen','ncgen3']:
            shutil.copy2(path, binary_dir/path.name)
shutil.copytree(src/'dat', destination/'dat')
env = dict(os.environ, LD_LIBRARY_PATH=str(src/'lib')+':'+os.environ.get('LD_LIBRARY_PATH',''))
for binary in sorted(binary_dir.iterdir()):
    data = binary.read_bytes()
    if not data.startswith(b'\x7fELF'):
        continue
    assert int.from_bytes(data[18:20], 'little') == 258, binary
    dependencies = subprocess.check_output(['ldd',str(binary)],env=env,text=True)
    assert 'not found' not in dependencies, dependencies
    for line in dependencies.splitlines():
        fields = line.split()
        if '=>' not in fields:
            continue
        path = Path(fields[fields.index('=>')+1])
        if path.is_absolute() and path.resolve().is_relative_to(src):
            target = prefix/'lib'/path.name
            if target.exists():
                assert target.read_bytes() == path.read_bytes(), target
            else:
                shutil.copy2(path,target)
    records.append({'path':str(binary.relative_to(prefix)), 'sha256':hashlib.sha256(data).hexdigest()})
assert {'sqm','antechamber','atomtype','bondtype','am1bcc'}.issubset({p.name for p in binary_dir.iterdir()})
(destination/'native-elf-manifest.json').write_text(json.dumps(records,indent=2)+'\n')
print('Installed',len(records),'native charge-tool executables')
