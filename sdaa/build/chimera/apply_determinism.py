"""Apply the reviewed three-module Chimera patch to a private runtime prefix."""
import argparse
import hashlib
import json
from pathlib import Path
import re

POLICY = 'chemical-order-am1-diag3-v1'
ORIGINAL = {
    'AddH/__init__.py': {'ce81e3a6ad8fed1d761f9a68f95c001aade59bb539f4aedc235dfaa8b5f48c88'},
    'AddH/hbond.py': {'e565f2b42ca5cb3412c9dfa1cdd0c3161f4e31bc09d8b95080e857c1bbe813e8'},
    'AddCharge/__init__.py': {
        '1708a4af3053b4e2644830f45681adee4e16d18ee66120468f178ebb9095503f',
        '21bd80e0dbee800281f9820eb39532424cb090eaadaee44fda0634c1d18f2beb'},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def patched_files(share, patch):
    """Strict unified-diff application: exact context, no fuzz or path traversal."""
    lines = patch.read_text().splitlines(keepends=True)
    result = {}
    i = 0
    while i < len(lines):
        assert lines[i].startswith('--- a/'), lines[i]
        relative = lines[i][6:].rstrip('\n')
        assert relative in ORIGINAL and relative not in result
        i += 1
        assert lines[i] == '+++ b/' + relative + '\n'
        i += 1
        original_bytes = (share / relative).read_bytes()
        assert sha(original_bytes) in ORIGINAL[relative], 'Unexpected original module: ' + relative
        original = original_bytes.decode().splitlines(keepends=True)
        cursor = 0
        updated = []
        while i < len(lines) and lines[i].startswith('@@ '):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n', lines[i])
            assert match, lines[i]
            old_start, old_count, new_start, new_count = match.groups()
            old_count = int(old_count) if old_count is not None else 1
            new_count = int(new_count) if new_count is not None else 1
            start = int(old_start) - (1 if int(old_start) else 0)
            assert start >= cursor
            updated.extend(original[cursor:start])
            cursor = start
            assert len(updated) == int(new_start) - (1 if int(new_start) else 0)
            i += 1
            removed = added = 0
            while i < len(lines) and not lines[i].startswith(('@@ ', '--- a/')):
                marker, content = lines[i][:1], lines[i][1:]
                assert marker in [' ', '+', '-'], lines[i]
                if marker in [' ', '-']:
                    assert cursor < len(original) and original[cursor] == content, (relative, cursor + 1)
                    cursor += 1
                    removed += 1
                if marker in [' ', '+']:
                    updated.append(content)
                    added += 1
                i += 1
            assert (removed, added) == (old_count, new_count), relative
        updated.extend(original[cursor:])
        result[relative] = (original_bytes, ''.join(updated).encode())
    assert set(result) == set(ORIGINAL)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--share', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    args = parser.parse_args()
    share = args.share.resolve()
    manifest_path = share.parent / 'chimera-determinism.json'
    patch_sha = sha(args.patch.read_bytes())
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        assert previous['policy'] == POLICY and previous['patch_sha256'] == patch_sha
        assert all(sha((share / rel).read_bytes()) == row['after_sha256']
                   for rel, row in previous['modules'].items())
        print('Already applied and hashes verified: ' + POLICY)
        return
    changes = patched_files(share, args.patch)
    manifest = {'policy': POLICY, 'patch_sha256': patch_sha,
                'diagnostic_archive_enabled': False, 'modules': {}}
    # All contexts and input hashes pass before any module is replaced.
    for rel, (before, after) in changes.items():
        path = share / rel
        temporary = path.with_name(path.name + '.determinism-new')
        assert not path.is_symlink() and not temporary.exists()
        temporary.write_bytes(after)
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)  # Never modify shared hard-link content in place.
        manifest['modules'][rel] = {'before_sha256': sha(before), 'after_sha256': sha(after)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
