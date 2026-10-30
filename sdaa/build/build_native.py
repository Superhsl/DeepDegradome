"""Build the verified CPU tools in a fresh project prefix; never install on host."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

BASE = 'sha256:3e425da47a74a03b589f8e1c18a67dcb90c8bcbde977cc1df09fa01209b7a524'
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT',HERE.parents[2])).resolve()
parser = argparse.ArgumentParser()
parser.add_argument('--stage', choices=['environment', 'prepare', 'tools', 'rosetta', 'package', 'runtime', 'all'], required=True)
parser.add_argument('--native-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--jobs', type=int, default=8)
parser.add_argument('--memory', default='32g')
parser.add_argument('--build-image', default='deepdegradome-native-build:loong-20261019')
parser.add_argument('--runtime-tag', default='deepdegradome-native:loong-rebuild')
args = parser.parse_args()
assert platform.machine() == 'loongarch64', 'Run this driver on the native LoongArch host'
assert 1 <= args.jobs <= 64
native, output = args.native_root.resolve(), args.output.resolve()
assert native.is_relative_to(ROOT/'native') and native != ROOT/'native'
assert output.is_relative_to(ROOT/'outputs') and output != ROOT/'outputs'
output.mkdir(parents=True, exist_ok=False)


def run(name, command):
    (output/(name+'-command.json')).write_text(json.dumps(command, indent=2)+'\n')
    with (output/(name+'.log')).open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    (output/(name+'.exitcode')).write_text(str(result.returncode)+'\n')
    print(name, result.returncode, flush=True)
    if result.returncode:
        raise SystemExit(f'{name} failed; see {output/(name+".log")}')


def inspect(image):
    return json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]


def environment():
    # DNF operates only within this project-specific image. Package versions
    # depend on the repository snapshot; retain the resulting RPM manifest.
    assert inspect(BASE)['Architecture'] in {'loongarch64', 'loong64'}
    run('environment', ['docker', 'build', '--pull=false', '--build-arg', 'BASE_IMAGE='+BASE,
                        '-f', str(HERE/'Dockerfile.native-build'), '-t', args.build_image, str(HERE)])


def prepare():
    native.mkdir(parents=True, exist_ok=False)
    for script in ['prepare_sources.py', 'prepare_rosetta.py']:
        run(script[:-3], [sys.executable, str(HERE/script), '--root', str(ROOT),
                          '--native-root', str(native), '--output', str(output)])
    (native/'build/wheels').mkdir(parents=True, exist_ok=True)


build_id = None


def container(command, *, directory='/native'):
    global build_id
    if build_id is None:
        base, build = inspect(BASE), inspect(args.build_image)
        layers = base['RootFS']['Layers']
        assert build['RootFS']['Layers'][:len(layers)] == layers, 'Unexpected base image'
        build_id = build['Id']
        (output/'build-image.json').write_text(json.dumps({'base_id': BASE, 'build_id': build_id,
                                                         'uid': os.getuid(), 'gid': os.getgid()}, indent=2)+'\n')
    return ['docker', 'run', '--rm', '--network', 'none', '--cpus', str(args.jobs),
            '--memory', args.memory, '--user', f'{os.getuid()}:{os.getgid()}',
            '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PIP_NO_CACHE_DIR=1',
            '-e', 'PREFIX_PATH=/native/install/glm:/usr:/usr/local',
            '-v', str(native)+':/native', '-w', directory, '--entrypoint', 'bash', build_id,
            '-ec', command]


def tools():
    run('pymol-wheel', container('python3.12 setup.py --use-msgpackc=no --no-vmd-plugins=false '
                                 f'--jobs={args.jobs} bdist_wheel --dist-dir /native/build/wheels',
                                 directory='/native/src/pymol-open-source'))
    run('python-tools-install', container('python3.12 -m pip install --no-index --no-deps '
        '--no-build-isolation --prefix /native/install/python /native/build/wheels/*.whl /native/src/docopt'))
    run('pkcombu', container(f'make -f Makefile.pkcombu -j{args.jobs}; '
        'mkdir -p /native/install/kcombu/bin; cp -p ../pkcombu /native/install/kcombu/bin/',
        directory='/native/src/kcombu-20200414/src'))
    run('dock-helpers', container("sh configure gnu; printf '%s\\n' 'CFLAGS += -ffp-contract=off' "
        "'FFLAGS += -ffp-contract=off' >> config.h; "
        f'make -C ../src/accessories -j{args.jobs} install; '
        f'make -C ../src/gbsa_grids -j{args.jobs} install; '
        f'make -C ../src/grid -j{args.jobs} install; '
        'mkdir -p /native/install/dock6/bin; '
        'cp -p ../bin/showbox ../bin/showsphere ../bin/sphgen ../bin/sphere_selector '
        '../bin/grid ../bin/nchemgrid_GB ../bin/nchemgrid_SA /native/install/dock6/bin/; '
        'cp -a ../parameters /native/install/dock6/', directory='/native/src/dock6/install'))


def rosetta():
    from apply_rosetta_zero_chi import apply as apply_zero_chi
    patch_record = apply_zero_chi(native/'src/rosetta-2020.08/main/source')
    (output/'rosetta-zero-chi-patch.json').write_text(json.dumps(patch_record,indent=2)+'\n')
    run('rosetta', container(f'/usr/bin/python3 scons.py -j{args.jobs} mode=release '
        'arch=loongarch64 arch_size=64 bin/rosetta_scripts.default.linuxgccrelease',
        directory='/native/src/rosetta-2020.08/main/source'))


def package():
    run('package-rosetta', [sys.executable, str(HERE/'package_rosetta.py'),
        '--source', str(native/'src/rosetta-2020.08/main/source'),
        '--destination', str(native/'install/rosetta/main/source')])
    run('rosetta-database', [sys.executable, str(HERE/'install_rosetta_database.py'),
        '--root', str(ROOT), '--destination', str(native/'install/rosetta/main/database'), '--include-extra'])


def runtime():
    wrappers = native/'wrappers'
    wrappers.mkdir(exist_ok=False)
    for name in ['babel_compat.py', 'emolfrag_cli.py']:
        shutil.copy2(HERE/name, wrappers/name)
    shutil.copy2(HERE/'Dockerfile.native-runtime', native/'Dockerfile.native-runtime')
    (native/'.dockerignore').write_text('*\n!install/\n!install/**\n!wrappers/\n!wrappers/**\n!Dockerfile.native-runtime\n')
    # Freeze the exact compiler image for this build, rather than resolving its tag mid-build.
    image = inspect(args.build_image)['Id']
    run('runtime', ['docker', 'build', '--pull=false', '--network', 'none',
                    '--build-arg', 'BUILD_IMAGE='+image, '-t', args.runtime_tag,
                    '-f', str(native/'Dockerfile.native-runtime'), str(native)])
    final = inspect(args.runtime_tag)
    (output/'runtime-image.json').write_text(json.dumps(final, indent=2)+'\n')
    run('rpm-manifest', ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'rpm',
                         final['Id'], '-qa', '--qf', '%{NAME} %{VERSION}-%{RELEASE} %{ARCH}\n'])
    run('pip-manifest', ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3.12',
                         final['Id'], '-m', 'pip', 'freeze'])


if args.stage == 'all':
    for action in [prepare, tools, rosetta, package, runtime]:
        action()
else:
    globals()[args.stage]()
