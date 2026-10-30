"""Verify and assemble the exact source selections used by the native build."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
p.add_argument('--native-root', type=Path, required=True)
a = p.parse_args()
a.native_root.mkdir(parents=True, exist_ok=False)
assets = a.root/'assets/native-full-20261019'
records = []
for name, subdir in [
    ('chimera-headless-sources-01', 'src'), ('chimera-headless-extra-02', 'src'),
    ('chimera-amber-build-patches-03', 'src'),
    ('chimera-amber18-addcharge-sources-01', 'build'),
    ('chimera-amber-common-headers-04', 'build')]:
    record = json.loads((assets/(name+'.json')).read_text())
    archive = assets/record['filename']
    assert hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() == record['sha256']
    dest = a.native_root/subdir
    dest.mkdir(exist_ok=True)
    with tarfile.open(archive) as stream:
        stream.extractall(dest, filter='data')
    for entry in record['members']:
        path = dest/entry['name']
        assert path.resolve().is_relative_to(dest.resolve())
        assert hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() == entry['sha256'], path
    records.append({k:v for k,v in record.items() if k != 'members'})
src = a.native_root/'src/chimera.src'
changes = [
    ('mk/detectOS.make', '\telse ifeq ($(MACHINE),ia64)',
     '\telse ifeq ($(MACHINE),loongarch64)\n\t\tOSARCH = LinuxLoong64\n\telse ifeq ($(MACHINE),ia64)'),
    ('mk/os.make', 'else ifeq ($(OSARCH),LinuxIA64)',
     'else ifeq ($(OSARCH),LinuxLoong64)\n\tPTR64BIT = 1\n\tTARGET_ARCH =\nelse ifeq ($(OSARCH),LinuxIA64)'),
    ('libs/gfxinfo/GfxInfo.h', '# ifdef GFXINFO_AGL\n// want our glext.h because it is newer',
     '# if defined(GFXINFO_AGL) || defined(GFXINFO_OSMESA)\n// use the supplied extension typedefs consistently')]
patches = []
for relative, needle, replacement in changes:
    path = src/relative
    before = path.read_text()
    assert before.count(needle) == 1, relative
    after = before.replace(needle, replacement)
    path.write_text(after)
    patches.append({'path':relative, 'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
                    'after_sha256':hashlib.sha256(after.encode()).hexdigest()})
(a.native_root/'source-preparation.json').write_text(json.dumps({
    'archives':records, 'compatibility_patches':patches,
    'chemistry_ordering_experiments_enabled':False}, indent=2)+'\n')
print('Verified source selections and prepared', a.native_root)
