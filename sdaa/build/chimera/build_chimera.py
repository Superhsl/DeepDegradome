"""Build only the native headless structure-preparation profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT',HERE.parents[3])).resolve()
COMPILER = 'sha256:735ea20d75cf081723aba78d3e9495899fc21a74e91a27e0a44141966a6c390d'
RUNTIME = 'sha256:a4c8e0c7e7fb1edb3791f2763154454dcdd181f2b4b52bafb9087644539489f0'
p = argparse.ArgumentParser()
p.add_argument('--stage', required=True, choices=['environment','prepare','python','bootstrap','core','pil','amber','install','package','runtime','all'])
p.add_argument('--native-root', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--compiler-image', default=COMPILER)
p.add_argument('--parent-runtime', default=RUNTIME)
p.add_argument('--runtime-tag', default='deepdegradome-native:loong-chimera-rebuild')
a = p.parse_args()
native, output = a.native_root.resolve(), a.output.resolve()
assert native.is_relative_to(ROOT/'native') and output.is_relative_to(ROOT/'outputs')
output.mkdir(parents=True, exist_ok=False)

def run(name, command):
    (output/(name+'-command.json')).write_text(json.dumps(command,indent=2)+'\n')
    with (output/(name+'.log')).open('w') as log:
        r = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    (output/(name+'.exitcode')).write_text(str(r.returncode)+'\n')
    print(name,r.returncode,flush=True)
    if r.returncode: raise SystemExit('Failed: '+name)

def container(command):
    image = json.loads(subprocess.check_output(['docker','image','inspect',a.compiler_image],text=True))[0]
    assert image['Architecture'] in ['loongarch64','loong64']
    return ['docker','run','--rm','--network','none','--cpus','8','--memory','24g',
            '--user',f'{os.getuid()}:{os.getgid()}','-e','HOME=/tmp',
            '-v',str(native)+':/chimera','-v',str(HERE)+':/task:ro','-v',str(HERE.parents[1]/'patches')+':/patches:ro',
            '--entrypoint','bash',image['Id'],'-ec',command]

def stage(name):
    if name == 'prepare':
        run(name,[sys.executable,str(HERE/'prepare_chimera.py'),'--root',str(ROOT),'--native-root',str(native)])
    elif name in ['python','bootstrap','core','pil','amber']:
        run(name,container('bash /task/build_chimera_'+name+'.sh'))
    elif name == 'install':
        run(name,container('python3.12 /task/install_chimera_amber.py && python3.12 /task/install_chimera_headless.py'))
    elif name == 'package':
        run(name,container('python3.12 /task/package_chimera_runtime.py'))
    elif name == 'runtime':
        context = native/'package'
        shutil.copy2(HERE/'Dockerfile.chimera-runtime',context/'Dockerfile')
        (context/'.dockerignore').write_text('*\n!install/\n!install/**\n!Dockerfile\n')
        parent = subprocess.check_output(['docker','image','inspect',a.parent_runtime,'--format','{{.Id}}'],text=True).strip()
        run(name,['docker','build','--pull=false','--network','none','--build-arg','VALIDATED_RUNTIME='+parent,'-t',a.runtime_tag,str(context)])
        image = subprocess.check_output(['docker','image','inspect',a.runtime_tag],text=True)
        (output/'runtime-image.json').write_text(image)
    else:
        run(name,['docker','build','--pull=false','-f',str(HERE/'Dockerfile.chimera-build'),'-t','deepdegradome-chimera-build:loong-local',str(HERE)])

for name in (['prepare','python','bootstrap','core','pil','amber','install','package','runtime'] if a.stage == 'all' else [a.stage]):
    stage(name)
