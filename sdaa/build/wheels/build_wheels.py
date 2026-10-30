"""Build the two dependencies absent from the pinned base image and validate offline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import struct
import subprocess
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
PROJECT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE.parent)).resolve()
BASE = 'sha256:3e425da47a74a03b589f8e1c18a67dcb90c8bcbde977cc1df09fa01209b7a524'
BUILD = 'sha256:4a525f89da01d9e27ad95920dab2fc4fd504843f85c7d6f1815a2a6356aa5561'
p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--assets', type=Path, default=PROJECT/'assets/native-full-20261019')
p.add_argument('--jobs', type=int, default=8)
p.add_argument('--validation-tag', default='deepdegradome-wheel-validation:20261026-01')
a = p.parse_args()
assert platform.machine() == 'loongarch64'
assert 1 <= a.jobs <= 32
out, work = a.output.resolve(), a.work.resolve()
assert out.is_relative_to(PROJECT/'deliverables') and work.is_relative_to(PROJECT/'native')
out.mkdir(parents=True, exist_ok=False)
work.mkdir(parents=True, exist_ok=False)
wheels = out/'wheelhouse'; wheels.mkdir()
(out/'licenses').mkdir()
records = []

def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + '\n')

def run(label, command, timeout=7200):
    print('START ' + label, flush=True)
    started = datetime.now(timezone.utc).isoformat()
    with (out/(label+'.log')).open('x') as log:
        r = subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    item = {'label': label, 'started_utc': started, 'exitcode': r.returncode, 'command': list(map(str, command))}
    records.append(item); save(out/'progress.json', records)
    print(label, r.returncode, flush=True)
    if r.returncode: raise RuntimeError(label + ' failed; see ' + str(out/(label+'.log')))

for image in [BASE, BUILD]:
    assert subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip() == image
tag_exists = subprocess.run(['docker','image','inspect',a.validation_tag],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
assert not tag_exists, 'Choose a fresh validation tag; do not overwrite an existing image'
lock = json.loads((HERE/'sources.json').read_text())
for name, entry in lock.items():
    archive = a.assets/entry['filename']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry['sha256'], name
    dest = work/'src'/name; dest.mkdir(parents=True)
    with tarfile.open(archive) as t:
        for member in t:
            parts = PurePosixPath(member.name).parts[1:]
            if not parts: continue
            rel = PurePosixPath(*parts)
            assert not rel.is_absolute() and '..' not in rel.parts
            path = dest/str(rel)
            if member.isdir(): path.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True,exist_ok=True)
                with t.extractfile(member) as src, path.open('wb') as dst: shutil.copyfileobj(src,dst)
                path.chmod(member.mode & 0o777)
            else: raise RuntimeError('Unexpected archive link: '+member.name)

glm = work/'prefix/include/glm'; glm.parent.mkdir(parents=True)
shutil.copytree(work/'src/glm/glm', glm)
shutil.copy2(work/'src/glm/copying.txt',work/'src/pymol/LICENSE-GLM.txt')
setup = work/'src/pymol/setup.py'
text = setup.read_text(); needle = 'cpu_count = os.cpu_count() or 1'
assert text.count(needle) == 1
setup.write_text(text.replace(needle,'cpu_count = options.jobs or os.cpu_count() or 1'))
save(out/'source-build-changes.json', {'pymol_setup': {'before':needle,'after':'cpu_count = options.jobs or os.cpu_count() or 1'}, 'purpose':'Respect bounded jobs; no scientific algorithm change', 'added_notice':'LICENSE-GLM.txt'})
for src,dst in [('pymol/LICENSE','pymol-LICENSE'),('docopt/LICENSE-MIT','docopt-LICENSE-MIT'),('glm/copying.txt','GLM-copying.txt')]:
    shutil.copy2(work/'src'/src,out/'licenses'/dst)

common = ['docker','run','--rm','--network','none','--cpus',str(a.jobs),'--memory','32g',
          '--user',str(os.getuid())+':'+str(os.getgid()),'-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1',
          '-e','PIP_NO_CACHE_DIR=1','-e','PREFIX_PATH=/work/prefix:/usr:/usr/local',
          '-v',str(work)+':/work','-v',str(wheels)+':/wheelhouse','-w','/work/src/pymol','--entrypoint','python3.12',BUILD]
run('build-docopt',common+['-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir','/wheelhouse','/work/src/docopt'])
run('build-pymol',common+['setup.py','--use-msgpackc=no','--no-vmd-plugins=false','--jobs='+str(a.jobs),'bdist_wheel','--dist-dir','/wheelhouse'])

manifest = []
for wheel in sorted(wheels.glob('*.whl')):
    with zipfile.ZipFile(wheel) as z:
        names=z.namelist(); metadata=next(n for n in names if n.endswith('.dist-info/METADATA'))
        wheelmeta=next(n for n in names if n.endswith('.dist-info/WHEEL'))
        data=z.read(metadata).decode(); meta={}
        for line in data.splitlines():
            if line.startswith(('Name: ','Version: ')): k,v=line.split(': ',1);meta[k.lower()]=v
        tags=[x[5:] for x in z.read(wheelmeta).decode().splitlines() if x.startswith('Tag: ')]
        notices=[n for n in names if '.dist-info/licenses/' in n]
        assert notices, 'Wheel is missing license notices'
        elf=[]
        for n in names:
            if not n.endswith('.so'):continue
            b=z.read(n)[:64]
            if b.startswith(b'\x7fELF'):
                machine=struct.unpack(('<' if b[5]==1 else '>')+'H',b[18:20])[0]
                assert machine==258,(n,machine)
                elf.append(n)
        if meta['name']=='pymol':
            assert tags==['cp312-cp312-linux_loongarch64'] and elf
            assert any(n.endswith('/LICENSE-GLM.txt') for n in notices)
        else: assert meta['name']=='docopt' and all(t.endswith('-none-any') for t in tags)
    manifest.append(dict(meta,filename=wheel.name,bytes=wheel.stat().st_size,sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),tags=tags,license_files=notices,elf_extensions=elf))
assert {x['name'] for x in manifest}=={'pymol','docopt'}

run('build-minimal-runtime-deps',['docker','build','--pull=false','-f',HERE/'Dockerfile.runtime-deps','-t',a.validation_tag,HERE],timeout=900)
runtime = subprocess.check_output(['docker','image','inspect',a.validation_tag,'--format','{{.Id}}'],text=True).strip()
validation = work/'wheel-validation';validation.mkdir()
code = """import json,subprocess,venv,importlib.util,os
assert importlib.util.find_spec('pymol') is None
assert importlib.util.find_spec('docopt') is None
assert not os.path.exists('/opt/deepdegradome')
venv.EnvBuilder(with_pip=True,system_site_packages=True).create('/out/venv')
# This base image exposes its scientific Python stack via /home/py312.
from pathlib import Path
base_site=Path('/home/py312/lib/python3.12/site-packages')
assert (base_site/'numpy').is_dir()
Path('/out/venv/lib/python3.12/site-packages/pinned-base-runtime.pth').write_text(str(base_site)+'\\n')
py='/out/venv/bin/python'
env=dict(os.environ,PYTHONPATH='',PYTHONNOUSERSITE='1')
subprocess.run([py,'-m','pip','install','--no-index','--no-deps','--find-links','/wheelhouse','pymol==3.1.0','docopt==0.6.2'],env=env,check=True)
subprocess.run([py,'/verify.py'],env=env,check=True)
"""
run('offline-install-and-functional-test',['docker','run','--rm','--network','none','--cpus','2','--memory','8g',
    '--user',str(os.getuid())+':'+str(os.getgid()),'-e','HOME=/tmp','-e','PYTHONDONTWRITEBYTECODE=1',
    '-e','PYTHONPATH=','-e','DISPLAY=','-v',str(validation)+':/out','-v',str(wheels)+':/wheelhouse:ro',
    '-v',str(HERE/'verify_installed.py')+':/verify.py:ro','--entrypoint','python3.12',runtime,'-c',code],timeout=240)
result=json.loads((validation/'validation.json').read_text());assert result['passed'] and result['isolated_from_previous_native_prefix']
save(out/'validation.json',result)
save(out/'manifest.json',{'base_image_id':BASE,'build_image_id':BUILD,'validation_image_id':runtime,
    'architecture':'loongarch64','sources':lock,'wheels':manifest,'validation_passed':True,'validation_report':'validation.json',
    'system_runtime_requirements':['libGLEW-2.2.0-7.lns23','libglvnd-glx-1.6.0-3.lns23'],
    'scope':'Additional Python wheels over the pinned base image; not a complete CPU tool distribution.'})
(out/'requirements-wheels.txt').write_text('\n'.join(x['name']+'=='+x['version']+' --hash=sha256:'+x['sha256'] for x in manifest)+'\n')
(out/'SHA256SUMS').write_text(''.join(x['sha256']+'  wheelhouse/'+x['filename']+'\n' for x in manifest))
save(out/'completion.json',{'completed':True,'wheel_count':2,'validation_passed':True,'records':records})
print('WHEEL_DELIVERY_COMPLETED',flush=True)
