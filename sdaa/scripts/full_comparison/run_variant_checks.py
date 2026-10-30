"""Verify all three original generator checkpoints against saved TF1 CPU states."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import argparse,json,os,subprocess,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
p.add_argument('--wait-cpu-controls',type=Path);a=p.parse_args()
root=PROJECT_ROOT;source=SOURCE_ROOT
out=a.output.resolve();assert (root/'outputs') in out.parents
out.mkdir(parents=True,exist_ok=False)
if a.wait_cpu_controls:
    while not (a.wait_cpu_controls/'completion.json').exists():
        print('WAITING_FOR_CPU_CONTROLS',flush=True);time.sleep(30)
image='sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'
evidence=root/'outputs/full-native-20261019-01'
records=[]
for mode in ['0','1']:
    d=out/('conv-fp32-'+mode);d.mkdir()
    command=['docker','run','--rm','--network','none','--cpus','1','--memory','16g',
             '--user',str(os.getuid())+':'+str(os.getgid()),'--device','/dev/tcaicard0',
             '-e','HOME=/tmp','-e','OMP_NUM_THREADS=1','-e','OPENBLAS_NUM_THREADS=1',
             '-e','PYTHONDONTWRITEBYTECODE=1','-e','TORCH_SDAA_CONV_USE_FP32='+mode,
             '-v',str(source)+':/source:ro','-v',str(evidence/'variant-inputs-01')+':/inputs:ro',
             '-v',str(evidence/'variant-reference-01')+':/reference:ro','-v',str(d)+':/out',
             '--entrypoint','python3.12',image,'/source/sdaa/scripts/verify_all_generators.py',
             '--reference','/reference','--inputs','/inputs','--output','/out/result']
    (d/'command.json').write_text(json.dumps(command,indent=2)+'\n')
    start=time.monotonic()
    with (d/'run.log').open('x') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    summary=json.loads((d/'result/summary.json').read_text()) if (d/'result/summary.json').exists() else None
    assert summary is not None and len(summary['tasks'])==3
    known_failure=mode=='0' and r.returncode==1 and not summary['passed']
    assert r.returncode==0 or known_failure
    rec={'conv_fp32':mode,'exitcode':r.returncode,'wall_seconds':time.monotonic()-start,
         'numerical_passed':summary['passed'],'reference':'Previously captured official TF1 CPU fixed states, not new CUDA timing.'}
    records.append(rec);(out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
(out/'completion.json').write_text(json.dumps({'execution_completed':True,'records':records},indent=2)+'\n')
