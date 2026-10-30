"""Install and verify the matching database subset; never reuse x86 caches."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--include-extra', action='store_true')
args = parser.parse_args()
args.destination.mkdir(parents=True, exist_ok=True)
archives = [args.root/'assets'/name for name in ['rosetta-docking-database2020.tar.gz', 'rosetta-sampling-support2020.tar.gz']]
if args.include_extra:
    archives.append(args.root/'assets/native-full-20261019/rosetta-database-extra-native-01.tar.gz')
records = []
for archive in archives:
    record = json.loads(archive.with_suffix('.gz.source.json').read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == record['archive_sha256']
    with tarfile.open(archive) as stream:
        for member in stream:
            relative = Path(member.name)
            target = args.destination/relative
            assert not relative.is_absolute() and '..' not in relative.parts
            assert target.resolve().is_relative_to(args.destination.resolve())
            if member.issym() or member.islnk():
                assert (target.parent/member.linkname).resolve().is_relative_to(args.destination.resolve())
            stream.extract(member, args.destination)
    for entry in record['files']:
        content = (args.destination/entry['path']).read_bytes()
        digest = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        assert digest == entry['git_blob_sha1'], entry['path']
    records.append({'archive': archive.name, 'sha256': record['archive_sha256'], 'files_verified': len(record['files'])})
    print(json.dumps(records[-1]), flush=True)
(args.destination/'native-database-lock.json').write_text(json.dumps(records, indent=2)+'\n')
