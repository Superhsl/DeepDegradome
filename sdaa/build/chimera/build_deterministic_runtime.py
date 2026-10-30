"""Build a small deterministic Chimera layer above the preserved native runtime."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
PARENT = 'sha256:19a1d2509832b22b2256cd57bb86027bcf4a5f14c942a5136f30e549f9359cef'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-tag', default='deepdegradome-native:loong-chimera-deterministic-20261026')
    args = parser.parse_args()
    root = Path(os.environ.get('DEEPDEGRADOME_PROJECT', HERE.parents[3])).resolve()
    out = args.output.resolve()
    assert platform.machine() == 'loongarch64'
    assert root / 'outputs' in out.parents
    out.mkdir(parents=True, exist_ok=False)
    inspect = lambda name: json.loads(subprocess.check_output(['docker', 'image', 'inspect', name], text=True))[0]
    parent = inspect(PARENT)
    assert parent['Id'] == PARENT and parent['Architecture'] in ['loongarch64', 'loong64']
    context = out / 'context'
    context.mkdir()
    for name in ['apply_determinism.py', 'Dockerfile.chimera-determinism']:
        shutil.copy2(HERE / name, context / name)
    shutil.copy2(HERE.parents[1] / 'patches/chimera-determinism.patch', context / 'chimera-determinism.patch')
    command = ['docker', 'build', '--pull=false', '--network', 'none',
               '--build-arg', 'PARENT_RUNTIME=' + PARENT,
               '--build-arg', 'RUNTIME_USER=' + (parent['Config'].get('User') or '0'),
               '-t', args.runtime_tag,
               '-f', str(context / 'Dockerfile.chimera-determinism'), str(context)]
    (out / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (out / 'build.log').open('w') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    (out / 'exitcode.txt').write_text(str(process.returncode) + '\n')
    if process.returncode:
        raise SystemExit('Image build failed; see ' + str(out / 'build.log'))
    image = inspect(args.runtime_tag)
    layers = parent['RootFS']['Layers']
    assert image['RootFS']['Layers'][:len(layers)] == layers
    assert (image['Config'].get('User') or '0') == (parent['Config'].get('User') or '0')
    record = {'parent_image_id': PARENT, 'image_id': image['Id'],
              'architecture': image['Architecture'], 'parent_layers_preserved': True}
    (out / 'runtime-image.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
