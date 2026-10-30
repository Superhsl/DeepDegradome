"""Collect only the built Rosetta target, its project libraries and Python helper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
args = parser.parse_args()
source = args.source.resolve()
destination = args.destination.resolve()
assert destination != source and not source.is_relative_to(destination)
destination.mkdir(parents=True, exist_ok=False)
binary = (source/'bin/rosetta_scripts.default.linuxgccrelease').resolve(strict=True)
assert binary.is_relative_to(source)
library_paths = sorted({str(p.parent) for parent in [source/'build', source/'external/build']
                        for p in parent.rglob('*.so')})
env = {**os.environ, 'LD_LIBRARY_PATH': ':'.join(library_paths)}
result = subprocess.run(['ldd', str(binary)], env=env, text=True, capture_output=True, check=True)
assert 'not found' not in result.stdout, result.stdout
libraries = []
for line in result.stdout.splitlines():
    fields = line.split()
    if '=>' not in fields:
        continue
    path = Path(fields[fields.index('=>')+1])
    if path.is_absolute() and path.resolve().is_relative_to(source):
        libraries.append(path.resolve())
assert libraries, 'No project shared libraries were found'
assert len({p.name for p in libraries}) == len(libraries), 'Ambiguous library basenames'
records = []
for original, relative in [(binary, Path('bin/rosetta_scripts.default.linuxgccrelease')),
                           *((p, Path('lib')/p.name) for p in libraries)]:
    target = destination/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, target)
    records.append({'path': str(relative), 'bytes': target.stat().st_size,
                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
public = source/'scripts/python/public'
target = destination/'scripts/python/public'
target.mkdir(parents=True)
shutil.copy2(public/'molfile_to_params.py', target/'molfile_to_params.py')
# This unused multiprocessing helper is Python2 syntax. Keep the upstream
# source, while installing only Python3-compatible files needed by the caller.
shutil.copytree(public/'rosetta_py', target/'rosetta_py',
                ignore=shutil.ignore_patterns('ForkManager.py', '*.pyc', '__pycache__'))
(destination/'native-runtime-files.json').write_text(json.dumps(records, indent=2)+'\n')
(destination/'ldd-source.txt').write_text(result.stdout)
print(json.dumps({'project_binaries_and_libraries': len(records),
                  'destination': str(destination)}, indent=2))
