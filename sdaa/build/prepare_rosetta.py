"""Prepare the pinned Rosetta CPU source in a separate native build directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--native-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
ROOT, NATIVE, OUT = args.root.resolve(), args.native_root.resolve(), args.output.resolve()
assert NATIVE.is_relative_to(ROOT / 'native')
OUT.mkdir(parents=True, exist_ok=True)
DEST = NATIVE / 'src/rosetta-2020.08/main/source'
DEST.mkdir(parents=True, exist_ok=False)


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        for member in stream:
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2:
                continue
            relative = PurePosixPath(*parts[1:])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError(member.name)
            member.name = str(relative)
            if member.issym() or member.islnk():
                target = (destination / member.name).parent / member.linkname
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError(member.linkname)
            stream.extract(member, destination)


archive = ROOT / 'assets/rosetta-source-tree2020.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == (
    '466ce3d7482a50aba20e2d6efad64d9a05b31e21c8f2a912422595f6c8e79b2c')
unpack(archive, DEST)
for name, relative, expected in [
    ('msgpack-208595b.tar.gz', 'external/msgpack/msgpack-c.upstream',
     '34bcb261506ab2d7fdb9e7b9a2eba125822d19764b611ae658cc491097340896'),
    ('mmtf-4e5ce8d.tar.gz', 'external/mmtf/mmtf-cpp',
     '7413a64977e1ce1a8db4b5e5a6312b90f578e0c1f0d36938c05dc85ad689c5a7'),
]:
    dependency = ROOT / 'assets' / name
    assert hashlib.sha256(dependency.read_bytes()).hexdigest() == expected
    unpack(dependency, DEST / relative)

# Use the version metadata captured by the successful matching CUDA build.
# Rosetta supports exported source through main/.release.json, without a fake Git repo.
release = json.loads((ROOT / 'assets/native-full-20261019/rosetta-version2020.json').read_text())
assert release['source']['main'] == 'ac40c05c67b0d7249198ba8a89fd27eb795d6f4f'
(DEST.parent / '.release.json').write_text(json.dumps(release, indent=2) + '\n')

options = DEST / 'tools/build/options.settings'
original = options.read_text()
marker = '"arch" : {'
assert original.count(marker) == 1
updated = original.replace(marker, marker + '\n        "loongarch64" : [ "64" ],', 1)
options.write_text(updated)
(DEST / 'tools/build/user.settings').write_text(
    "settings = {'user': {'prepends': {}, 'overrides': {}, 'appends': {}, "
    "'removes': {'flags': {'warn': ['Werror']}}}}\n")
stripe = DEST / 'src/numeric/geometry/hashing/xyzStripeHashWithMeta.hh'
text = stripe.read_text()
assert text.count('delete grid_atoms_;') == 1
assert text.count('delete grid_stripe_;') == 1
stripe.write_text(text.replace('delete grid_atoms_;', 'delete [] grid_atoms_;')
                  .replace('delete grid_stripe_;', 'delete [] grid_stripe_;'))
for relative, needle, replacement in [
    ('src/core/io/silent/SilentStruct.cc',
     '\tusing std::map;\n\tusing std::string;\n\tmap< string, string > comments = get_all_comments();',
     '\tusing std::map;\n\tmap< string, string > comments = get_all_comments();'),
    ('src/protocols/forge/remodel/RemodelWorkingSet.cc',
     '\tusing core::chemical::ChemicalManager;\n\tusing build::BuildInstructionOP;',
     '\tusing core::chemical::ChemicalManager;'),
]:
    path = DEST / relative
    text = path.read_text()
    assert text.count(needle) == 1, relative
    path.write_text(text.replace(needle, replacement))
from apply_rosetta_zero_chi import apply as apply_zero_chi
zero_chi_record = apply_zero_chi(DEST)

record = {
    'zero_chi_patch': zero_chi_record,
    'source_commit': 'ac40c05c67b0d7249198ba8a89fd27eb795d6f4f',
    'source_archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'destination': str(DEST),
    'compatibility_changes': ['loongarch64 architecture table', 'truthful exported-source version metadata',
                              'GCC12 release warnings retained without Werror', 'paired new[]/delete[] correction',
                              'remove redundant using declarations in SilentStruct and RemodelWorkingSet'],
    'modifications': [{'file': 'tools/build/options.settings',
                       'reason': 'Recognize the native LoongArch64 architecture',
                       'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
                       'after_sha256': hashlib.sha256(updated.encode()).hexdigest()}],
}
(OUT / 'rosetta-source-preparation.json').write_text(
    json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
