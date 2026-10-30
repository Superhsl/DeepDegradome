"""Unpack verified CPU-tool sources into the independent native build tree."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--native-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
ROOT, NATIVE, OUT = args.root.resolve(), args.native_root.resolve(), args.output.resolve()
assert NATIVE.is_relative_to(ROOT / 'native')
OUT.mkdir(parents=True, exist_ok=True)
ASSETS = ROOT / 'assets/native-full-20261019'


def unpack(archive, destination, strip_root=True):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as stream:
        for member in stream:
            parts = PurePosixPath(member.name).parts
            if strip_root and len(parts) < 2:
                continue
            relative = PurePosixPath(*(parts[1:] if strip_root else parts))
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError(member.name)
            member.name = str(relative)
            if member.issym() or member.islnk():
                target = (destination / member.name).parent / member.linkname
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError(member.linkname)
            stream.extract(member, destination)


records = json.loads((ASSETS / 'source-manifest.json').read_text())
records.append(json.loads((ASSETS / 'glm-source.json').read_text()))
for entry in records:
    archive = ASSETS / entry['filename']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry['sha256']
    unpack(archive, NATIVE / 'src' / entry['project'])

archive = ROOT / 'DeepDegradome/eMolFrag/kcombu-src-20200414.tar.gz'
content = archive.read_bytes()
blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
expected = subprocess.check_output(['git', '-C', str(ROOT / 'DeepDegradome'), 'rev-parse',
                                    '8b77f9897258064ef1d9a5ac4a42a547fb3eacea:eMolFrag/kcombu-src-20200414.tar.gz'], text=True).strip()
assert blob == expected
unpack(archive, NATIVE / 'src/kcombu-20200414', strip_root=False)
records.append(dict(project='kcombu', filename=str(archive), git_blob=blob,
                    source_commit='8b77f9897258064ef1d9a5ac4a42a547fb3eacea',
                    sha256=hashlib.sha256(content).hexdigest(), source_directory='kcombu-20200414'))

glm = NATIVE / 'install/glm/include'
glm.mkdir(parents=True, exist_ok=False)
shutil.copytree(NATIVE / 'src/glm/glm', glm / 'glm')
shutil.copyfile(NATIVE / 'src/glm/copying.txt', NATIVE / 'install/glm/LICENSE.txt')

# Respect the public --jobs option for this CMake-based release instead of
# scheduling all 128 host CPUs inside an eight-CPU build container.
setup = NATIVE / 'src/pymol-open-source/setup.py'
text = setup.read_text()
needle = 'cpu_count = os.cpu_count() or 1'
assert text.count(needle) == 1
setup.write_text(text.replace(needle, 'cpu_count = options.jobs or os.cpu_count() or 1'))
(OUT / 'native-tool-source-lock.json').write_text(json.dumps(records, indent=2) + '\n')
# Normalize only pkcombu's successful main return; its scientific mapping is unchanged.
pk = NATIVE / 'src/kcombu-20200414/src/pkcombu.c'
text = pk.read_text()
assert text.count('return(1);') == 1 and '} /* end of main() */' in text
pk.write_text(text.replace('return(1);', 'return(0);'))
# The upstream test harness invokes this exported script directly.
diff = NATIVE / 'src/dock6/install/test/dockdif'
diff.chmod(diff.stat().st_mode | 0o100)
print(json.dumps({'prepared': [entry['project'] for entry in records]}, indent=2))
