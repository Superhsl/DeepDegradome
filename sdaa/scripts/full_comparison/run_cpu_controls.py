"""Execute the native/x86 CPU control suite, serially within each host."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import argparse,hashlib,json,os,shlex,subprocess,time
from pathlib import Path

PIPE='sha256:71e9f83f87a749592ca628a6e1460000350a29660521bb2e8bab3d6a3347dcaf'
CHIMERA='sha256:a57df831b92fab91562a1cb70eac41007252ec0e02c6a63562c5597572677c5b'
NATIVE='sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')

def main():
    p=argparse.ArgumentParser();p.add_argument('--target',choices=['gpu1','loong'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true')
    p.add_argument('--wait-for-pipeline',action='store_true');p.add_argument('--only-chimera',action='store_true');a=p.parse_args()
    root=PROJECT_ROOT
    scripts=SOURCE_ROOT/'sdaa/scripts/full_comparison';source=Path(os.environ.get('DEEPDEGRADOME_CUDA_SOURCE',scripts/'source-gpu')) if a.target=='gpu1' else SOURCE_ROOT
    out=a.output.resolve();assert (root/'outputs') in out.parents
    out.mkdir(parents=True,exist_ok=a.resume)
    if a.wait_for_pipeline:
        while not (out.parent/'pipeline-completion.json').exists():
            failure=out.parent/'pipeline-driver-status.json'
            if failure.exists() and json.loads(failure.read_text())['exitcode']!=0:
                print('PIPELINE_STOPPED; RUN_INDEPENDENT_CPU_CONTROLS',flush=True)
                break
            print('WAITING_FOR_PIPELINE_TO_AVOID_TIMING_OVERLAP',flush=True);time.sleep(30)
    fixtures=json.loads((scripts/'fixtures-manifest.json').read_text())
    for rel,value in fixtures['files'].items():assert sha(scripts/'fixtures'/rel)==value
    save(out/'protocol.json',{'target':a.target,'repeats':3,'fixture_manifest':fixtures,
                             'cpu_threads':1,'cpu_quota_basic_dock_params_rosetta':1,'cpu_quota_chimera':4,
                             'coordinate_tolerance_angstrom':1e-3,'charge_tolerance_e':1e-4,
                             'source_harness_sha256':{n:sha(scripts/n) for n in ['cpu_tools.py','run_cpu_controls.py','pipeline_stage.py']},
                             'timing':'Program process launch to exit; one process per CLI repetition, library tests exclude imports. No device mapped.'})
    records=[]
    if not a.only_chimera:
        assets=root/'work/binary-translation-20261022-01/assets'
        asset_sha={str(p.relative_to(assets)):sha(p) for p in assets.rglob('*') if p.is_file()}
        previous=out.parent/'translation-status.json'
        if previous.exists():
            old=json.loads(previous.read_text());assert old['exitcode']==0
            assert json.loads((out.parent/'translation-assets-before.json').read_text())==asset_sha
            progress=json.loads((out.parent/'translation-three-repeats/progress.json').read_text())
            assert progress['status']=='complete' and len(progress['jobs'])==12
            assert all(not row['timed_out'] and row['functional_output_present'] for row in progress['jobs'])
            records.append({'stage':'translation','exitcode':0,'wall_seconds':old['elapsed_seconds'],'reused_same_current_run':True})
        else:
            save(out.parent/'translation-assets-before.json',asset_sha)
            image=PIPE if a.target=='gpu1' else NATIVE
            command=['docker','run','--rm','--network','none','--cpus','1','--memory','4g','--user',str(os.getuid())+':'+str(os.getgid()),
                     '-e','HOME=/tmp','-e','LATX_AOT=0','-e','LATX_KZT=0',
                     '-v',str(assets)+':/assets:ro','-v',str(SOURCE_ROOT/'sdaa/scripts/translation/probe_runner.py')+':/runner.py:ro',
                     '-v',str(out.parent)+':/out']
            if a.target=='loong':command+=['-v',str(root/'native/latx-48a9c55d/lat64')+':/translator:ro']
            command+=['--entrypoint','python3',image,'/runner.py','--backend','x86' if a.target=='gpu1' else 'latx',
                      '--tools','patchdock','cyndi','ifit_eval','ifit_dock','--label','translation-three-repeats',
                      '--timeout','300','--repeats','3','--freeze-cyndi-seed','--freeze-seed-time']
            save(out.parent/'translation-command.json',command);start=time.monotonic()
            with (out.parent/'translation-driver.log').open('x') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
            old={'command':command,'exitcode':result.returncode,'elapsed_seconds':time.monotonic()-start}
            save(previous,old);assert result.returncode==0
            records.append({'stage':'translation','exitcode':0,'wall_seconds':old['elapsed_seconds'],'reused_same_current_run':False})
    stages=['chimera-01','chimera-02','chimera-03'] if a.only_chimera else ['basic','dock','params','rosetta','chimera-01','chimera-02','chimera-03']
    for stage in stages:
        d=out/stage
        if d.exists():
            assert a.resume
            old=json.loads((d/'launcher-status.json').read_text());assert old['exitcode']==0
            records.append(old);continue
        d.mkdir()
        is_chimera=stage.startswith('chimera')
        image=NATIVE if a.target=='loong' else CHIMERA if is_chimera else PIPE
        assert subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()==image
        cmd=['docker','run','--rm','--network','none','--name','dd-cpu-'+a.target+'-'+stage+'-'+str(os.getpid()),
             '--user',str(os.getuid())+':'+str(os.getgid()),'--cpus','4' if is_chimera else '1',
             '--memory','16g','--shm-size','2g']
        env={'HOME':'/tmp','CUDA_VISIBLE_DEVICES':'','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1',
             'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
             'DD_COMPARE_TARGET':a.target,'AutoFBDD_FOL':'/source','DeepDegradome_FOL':'/source'}
        mounts=[(scripts,'/harness:ro'),(scripts/'fixtures','/fixtures:ro'),(source,'/source:ro'),
                (root/'runs/pdb-derived-input-preparation','/public-inputs:ro'),(d,'/out')]
        if a.target=='loong':
            env.update(CPU_DOCK6='/opt/deepdegradome/dock6',CPU_PKCOMBU='/opt/deepdegradome/kcombu/bin/pkcombu',
                       ROSETTA_FOL='/opt/deepdegradome/rosetta',
                       PATH='/validation/bin:/opt/deepdegradome/bin:/opt/deepdegradome/dock6/bin:/opt/deepdegradome/kcombu/bin:/opt/deepdegradome/chimera/bin:/home/py312/lib/python3.12/site-packages/openbabel/bin:/home/py312/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
            mounts.append((root/'native/latx-48a9c55d','/validation:ro'));entry='python3.12'
        else:
            env.update(ROSETTA_FOL='/rosetta',PATH='/harness/gpu-bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
            mounts.extend([(root/'runtime/chimera-1.20','/chimera:ro'),(root/'runtime/rosetta-2020.08','/rosetta:ro'),
                           (root/'outputs/full-native-20261019-01/dock-x86-reference-01/dock6','/cpu-dock6:ro'),
                           (root/'outputs/full-native-20261019-01/cpu-tools-x86-reference-01/kcombu/pkcombu','/cpu-pkcombu:ro')])
            entry='python3' if is_chimera else 'python'
        for k,v in env.items():cmd+=['-e',k+'='+v]
        for src,dest in mounts:cmd+=['-v',str(src)+':'+dest]
        cmd+=['-w','/out','--entrypoint',entry,image]
        cmd+=['/harness/pipeline_stage.py','prepare'] if is_chimera else ['/harness/cpu_tools.py',stage]
        save(d/'command.json',cmd);(d/'command.sh').write_text(shlex.join(cmd)+'\n')
        print('START '+stage,flush=True);start=time.monotonic()
        with (d/'driver.log').open('x') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=5400)
        rec={'stage':stage,'exitcode':r.returncode,'wall_seconds':time.monotonic()-start,'image_id':image}
        save(d/'launcher-status.json',rec);records.append(rec);save(out/'progress.json',records)
        print(json.dumps(rec),flush=True)
        if r.returncode:raise SystemExit(r.returncode)
    if not a.only_chimera:
        assert asset_sha=={str(p.relative_to(assets)):sha(p) for p in assets.rglob('*') if p.is_file()}
    save(out/'completion.json',{'execution_completed':True,'only_chimera':a.only_chimera,'records':records,'translation_assets_unchanged':None if a.only_chimera else True,'fixture_files_unchanged':all(sha(scripts/'fixtures'/p)==h for p,h in fixtures['files'].items())})

if __name__=='__main__':main()
