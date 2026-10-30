"""Install the delivered wheels into a fresh venv over the agreed base stack."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

p = argparse.ArgumentParser()
p.add_argument('--bundle', type=Path, required=True)
p.add_argument('--venv', type=Path, required=True)
p.add_argument('--base-site', type=Path, default=Path('/home/py312/lib/python3.12/site-packages'))
a = p.parse_args()
assert sys.version_info[:2] == (3, 12) and platform.machine() == 'loongarch64'
bundle, target, base = a.bundle.resolve(), a.venv.resolve(), a.base_site.resolve()
assert not target.exists(), 'Use a fresh virtual environment directory'
assert (base/'numpy').is_dir() and (base/'torch').is_dir(), 'Pinned base Python stack is missing'
for name in ['libGL.so.1', 'libGLEW.so.2.2']:
    try: ctypes.CDLL(name)
    except OSError as error:
        raise SystemExit(str(error)+'; prepare the image with Dockerfile.runtime-deps first')
manifest = json.loads((bundle/'manifest.json').read_text())
wheelhouse = (bundle/manifest.get('wheel_directory', 'wheelhouse')).resolve()
assert wheelhouse.is_relative_to(bundle), 'Wheel path must remain within the bundle'
assert {x['name'] for x in manifest['wheels']} == {'pymol', 'docopt'}
for item in manifest['wheels']:
    assert Path(item['filename']).name == item['filename']
    wheel = wheelhouse/item['filename']
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == item['sha256'], wheel
venv.EnvBuilder(with_pip=True, system_site_packages=True).create(target)
(target/'lib/python3.12/site-packages/pinned-base-runtime.pth').write_text(str(base)+'\n')
python = target/'bin/python'
env = dict(os.environ, PYTHONPATH='', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
command = [str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', '--ignore-installed',
           '--require-hashes', '--find-links', str(wheelhouse),
           '-r', str(bundle/'requirements-wheels.txt')]
subprocess.run(command, env=env, check=True)
subprocess.run([str(python), str(Path(__file__).with_name('verify_installed.py')),
                '--output', str(target/'wheel-verification')], env=env, check=True)
print('Installed and verified wheels in '+str(target))
