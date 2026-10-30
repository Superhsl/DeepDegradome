"""Launch an immutable, bounded full workflow with per-stage timing and safe resume."""
import argparse,csv,datetime,hashlib,json,os,platform,shlex,subprocess,time
from pathlib import Path

IMAGES={'prepare':'sha256:a57df831b92fab91562a1cb70eac41007252ec0e02c6a63562c5597572677c5b',
        'cpu':'sha256:71e9f83f87a749592ca628a6e1460000350a29660521bb2e8bab3d6a3347dcaf',
        'eval':'sha256:a0ed27920bd1b82c70624ecb3da1ea1ba62c2f13c0a284b7ac2cbd5885369e8a',
        'loong':'sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'}

def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def capture(cmd):return subprocess.check_output(cmd,text=True,timeout=60)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--target',choices=['gpu1','loong'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--gpu-index',type=int)
    a=p.parse_args()
    root=Path(os.environ.get('DEEPDEGRADOME_PROJECT', Path(__file__).resolve().parents[4])).expanduser().resolve()
    scripts=root/'scripts/full-comparison-20261023' if a.target=='gpu1' else root/'DeepDegradome/sdaa/scripts/full_comparison'
    source=scripts/'source-gpu' if a.target=='gpu1' else root/'DeepDegradome'
    inputs=root/'runs/pdb-derived-input-preparation'
    out=a.output.resolve()
    assert (root/'outputs') in out.parents
    if out.exists():assert a.resume
    else:out.mkdir(parents=True)
    fp={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file() and p.suffix in ['.py','.pickle','.pth','.xml','.flags','.csv','.txt']}
    inp={name:sha(inputs/name) for name in ['WDR5.pdb','CRBN.pdb','compound4.mol2','CRBN_ligand.mol2']}
    protocol={'target':a.target,'raw_inputs_sha256':inp,'source_assets_sha256':fp,
              'harness_sha256':{n:sha(scripts/n) for n in ['pipeline_stage.py','native_base.py','run_pipeline.py']},
              'global_poses':10,'refinement_attempts':20,'refinement_workers':4,'per_pose_seed_base':1000,
              'sampler_samples_per_length':50,'assessment_raw_rows_per_pose':20,'cpu_quota':4,
              'conv_fp32':'0','end_to_end_repetitions':1,'diagnostic_profiler_in_timed_main_chain':False,
              'controller_sha256':sha(Path(__file__)),
              'rosetta_zero_chi_header_sha256':'c69c96fb1eb2dcf78ab12fdee44c61311a993ee5352cf2ef64c64d264e1a2d60',
              'reference_type':'Both platforms include zero-only Rosetta source fix; modified x86 reference',
              'scope':'Public-PDB functional workflow, not author input/paper reproduction; different sampling streams and accepted branches retained.'}
    protocol_path=out/'pipeline-protocol.json'
    if protocol_path.exists():assert json.loads(protocol_path.read_text())==protocol
    else:save(protocol_path,protocol)
    e2e=out/'end-to-end';e2e.mkdir(exist_ok=True)
    history=[];started=time.monotonic()
    for stage in ['prepare','global_dock','refine','generate','assess','evaluate','summarize']:
        status=e2e/(stage+'-launcher.json')
        if status.exists():
            old=json.loads(status.read_text())
            assert old['exitcode']==0,'Previous failed stage retained; use an explicit repaired attempt.'
            history.append(old);continue
        image=IMAGES['loong'] if a.target=='loong' else IMAGES['prepare' if stage=='prepare' else 'eval' if stage in ['evaluate','summarize'] else 'cpu']
        assert capture(['docker','image','inspect',image,'--format','{{.Id}}']).strip()==image
        waiting=0;gpu=None
        if a.target=='gpu1' and stage in ['generate','evaluate']:
            wait_start=time.monotonic()
            while True:
                text=capture(['nvidia-smi','--query-gpu=index,uuid,memory.used,utilization.gpu','--format=csv,noheader,nounits'])
                rows=list(csv.reader(text.splitlines(),skipinitialspace=True))
                override=out/'gpu-override.json'
                options=json.loads(override.read_text()) if override.exists() else {}
                index=options.get('gpu_index',a.gpu_index)
                allow_shared=options.get('allow_shared',False)
                choices=[r for r in rows if (index is None or int(r[0])==index) and int(r[3])==0 and (int(r[2])<1024 or allow_shared)]
                if choices:
                    row=choices[0];gpu=row[1]
                    save(e2e/(stage+'-gpu.json'),{'index':int(row[0]),'uuid':gpu,'memory_used_mb':int(row[2]),'shared_gpu_authorized':allow_shared,'snapshot':text})
                    break
                save(out/'waiting-for-gpu.json',{'stage':stage,'elapsed_seconds':time.monotonic()-wait_start,'snapshot':text})
                print('WAITING_GPU '+stage,flush=True);time.sleep(30)
            waiting=time.monotonic()-wait_start
        cmd=['docker','run','--rm','--network','none','--name','dd-all-'+a.target+'-'+stage+'-'+str(os.getpid()),
             '--user',str(os.getuid())+':'+str(os.getgid()),'--cpus','4','--memory','32g','--shm-size','4g']
        env={'HOME':'/tmp','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0',
             'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NVIDIA_TF32_OVERRIDE':'0',
             'DD_COMPARE_TARGET':a.target,'AutoFBDD_FOL':'/source','DeepDegradome_FOL':'/source',
             'TORCH_SDAA_CONV_USE_FP32':'0','LATX_AOT':'0','LATX_KZT':'0'}
        mounts=[(scripts,'/harness:ro'),(source,'/source:ro'),(inputs,'/public-inputs:ro'),(e2e,'/out')]
        if a.target=='loong':
            env.update(DEEPDEGRADOME_DEVICE='sdaa',PATCHDOCK='/validation/runtime/tools/patchdock',
                       ROSETTA_FOL='/opt/deepdegradome/rosetta',
                       PATH='/validation/bin:/opt/deepdegradome/chimera/bin:/opt/deepdegradome/bin:/opt/deepdegradome/kcombu/bin:/opt/deepdegradome/dock6/bin:/opt/deepdegradome/rosetta/main/source/bin:/home/py312/lib/python3.12/site-packages/openbabel/bin:/home/py312/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
            mounts.append((root/'native/latx-48a9c55d','/validation:ro'))
            if stage in ['generate','evaluate']:cmd+=['--device','/dev/tcaicard0']
            entry='python3.12'
        else:
            env.update(PATCHDOCK='/patchdock',ROSETTA_FOL='/rosetta',
                       PATH='/harness/gpu-bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
            mounts.extend([(root/'runtime/chimera-1.20-deterministic','/chimera:ro'),(root/'runtime/rosetta-2020.08','/rosetta:ro'),
                           (root/'runs/native-tools-preparation/PatchDock','/patchdock:ro')])
            if stage=='generate':
                env['BABEL_DATADIR']='/ob-data';mounts.append((root/'assets/openbabel-3.1.1-data','/ob-data:ro'))
            if stage=='evaluate':env['DEEPDEGRADOME_DEVICE']='cuda'
            if gpu:cmd+=['--gpus','device='+gpu]
            entry='python3' if stage=='prepare' else 'python'
        if a.target=='gpu1' and stage=='refine':
            package=root/'reports/rosetta-zero-chi-fix-20261029-01/runtime-package'
            manifest=package/'runtime-files.json'
            assert manifest.is_file()
            fixed=json.loads((root/'reports/rosetta-zero-chi-fix-20261029-01/build-status.json').read_text())
            assert sha(package/'bin/rosetta_scripts.default.linuxgccrelease')==fixed['binary_sha256']
            mounts.append((package,'/rosetta/main/source:ro'))
            baseline=json.loads(capture(['docker','image','inspect',image]))[0]
            prev=dict(x.split('=',1) for x in baseline['Config'].get('Env',[]) if '=' in x)
            env['LD_LIBRARY_PATH']='/rosetta/main/source/lib'+(':'+prev['LD_LIBRARY_PATH'] if prev.get('LD_LIBRARY_PATH') else '')
            save(e2e/'rosetta-runtime.json',{'manifest_sha256':sha(manifest),'binary_sha256':fixed['binary_sha256'],'source':'zero-only fixed x86 CPU runtime'})
        for k,v in env.items():cmd+=['-e',k+'='+v]
        for src,dest in mounts:cmd+=['-v',str(src)+':'+dest]
        cmd+=['-w','/out','--entrypoint',entry,image,'/harness/pipeline_stage.py',stage]
        save(e2e/(stage+'-command.json'),cmd)
        (e2e/(stage+'-command.sh')).write_text(shlex.join(cmd)+'\n')
        print('START '+stage,flush=True)
        start=time.monotonic()
        with (e2e/(stage+'.log')).open('x') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=14400)
        rec={'stage':stage,'exitcode':r.returncode,'wall_seconds':time.monotonic()-start,'resource_wait_seconds':waiting,'image_id':image}
        save(status,rec);history.append(rec);save(out/'pipeline-progress.json',history)
        print(json.dumps(rec),flush=True)
        if r.returncode:raise SystemExit(r.returncode)
    after={rel:sha(source/rel) for rel in fp}
    assert after==fp
    assert {n:sha(inputs/n) for n in inp}==inp
    summary={'execution_completed':True,'target':a.target,'stages':history,'assets_unchanged':True,
             'active_pipeline_seconds':sum(r['wall_seconds'] for r in history),
             'gpu_resource_wait_seconds':sum(r['resource_wait_seconds'] for r in history),
             'controller_wall_seconds':time.monotonic()-started,'end_to_end_repetitions':1}
    save(out/'pipeline-completion.json',summary)
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
