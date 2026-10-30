"""Run fresh neural generation and the existing one-candidate fixed-complex tail."""
from pathlib import Path
import argparse,json,subprocess,os,time,hashlib,datetime,csv
p=argparse.ArgumentParser();p.add_argument('--target',choices=['gpu1','loong'],required=True);p.add_argument('--gpu-index',type=int,default=0);p.add_argument('--output',type=Path,required=True);p.add_argument('--after',type=Path);a=p.parse_args()
root=Path(os.environ.get('DEEPDEGRADOME_PROJECT', Path(__file__).resolve().parents[4])).expanduser().resolve()
here=Path(__file__).resolve().parent;out=a.output.resolve()
assert root/'outputs' in out.parents and not out.exists()
if a.after:
 deadline=time.monotonic()+43200
 while not (a.after/'pipeline-completion.json').is_file():
  failures=[p for p in (a.after/'end-to-end').glob('*-launcher.json') if json.loads(p.read_text()).get('exitcode',0)]
  if failures:raise RuntimeError('Preceding official chain failed; retained evidence: '+str(failures))
  assert time.monotonic()<deadline,'Preceding official run did not complete within 12h'
  time.sleep(30)
out.mkdir();(out/'generation').mkdir()
fixed=here/'fixed-inputs';assert fixed.is_dir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files={p.name:sha(p) for p in fixed.iterdir() if p.is_file()}
assert files==json.loads((here/'fixed-input-sha256.json').read_text())
source=root/'scripts/full-comparison-20261023/source-gpu' if a.target=='gpu1' else root/'DeepDegradome'
harness=root/'scripts/full-comparison-20261023' if a.target=='gpu1' else source/'sdaa/scripts/full_comparison'
image='sha256:71e9f83f87a749592ca628a6e1460000350a29660521bb2e8bab3d6a3347dcaf' if a.target=='gpu1' else 'sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'
assert subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()==image
protocol={'target':a.target,'fresh_generation':True,'postprocess_candidate_limit':1,'fixed_input_sha256':files,'image_id':image,'sampler_samples_per_length':50,'linker_atom_lengths':[7,8,9,10,11],'conformer_trials':16,'refinement_max_mmff_iterations':1000,'ifit_population':500,'ifit_generations':500,'fixed_16_accepted_rounds':False,'code_sha256':{n:sha(here/n) for n in ['ifit.py','generate_fixed.py']},'scope':'Experimental fixed-complex chain from frozen prepared generation features; fresh DEVELOP generation then one sorted canonical candidate; not the official DeepPROTACs scoring branch'}
(out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
wait_start=time.monotonic();gpu=None
if a.target=='gpu1':
 while True:
  snapshot=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True)
  options=[r for r in csv.reader(snapshot.splitlines(),skipinitialspace=True) if int(r[0])==a.gpu_index and int(r[2])<1024 and int(r[3])==0]
  if options:gpu=options[0][1];break
  print('WAITING_GPU',a.gpu_index,flush=True);time.sleep(30)
 (out/'gpu.json').write_text(json.dumps({'gpu_index':a.gpu_index,'uuid':gpu,'snapshot':snapshot},indent=2)+'\n')
cmd=['docker','run','--rm','--network','none','--name','dd-final-ifit-gen-'+a.target+'-'+str(os.getpid()),'--user',str(os.getuid())+':'+str(os.getgid()),'--cpus','4','--memory','32g','--shm-size','4g']
env={'HOME':'/tmp','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NVIDIA_TF32_OVERRIDE':'0','DD_COMPARE_TARGET':a.target,'AutoFBDD_FOL':'/source','DeepDegradome_FOL':'/source','TORCH_SDAA_CONV_USE_FP32':'0','LATX_AOT':'0','LATX_KZT':'0','ROSETTA_FOL':'/rosetta' if a.target=='gpu1' else '/opt/deepdegradome/rosetta','PATCHDOCK':'/patchdock' if a.target=='gpu1' else '/validation/runtime/tools/patchdock'}
if a.target=='gpu1':
 env['BABEL_DATADIR']='/ob-data'
 assert (root/'assets/openbabel-3.1.1-data/superatom.txt').is_file()
 cmd+=['-v',str(root/'assets/openbabel-3.1.1-data')+':/ob-data:ro']
if gpu:cmd+=['--gpus','device='+gpu]
if a.target=='loong':cmd+=['--device','/dev/tcaicard0']
for k,v in env.items():cmd+=['-e',k+'='+v]
for src,dst in [(source,'/source:ro'),(harness,'/harness:ro'),(here,'/code:ro'),(fixed,'/fixed:ro'),(out/'generation','/out')]:cmd+=['-v',str(src)+':'+dst]
cmd+=['-w','/out','--entrypoint','python' if a.target=='gpu1' else 'python3.12',image,'/code/generate_fixed.py']
(out/'generation-command.json').write_text(json.dumps(cmd,indent=2)+'\n')
print('START fresh-generation',flush=True);start=time.monotonic()
with (out/'generation.log').open('x') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
records=[{'stage':'fresh-neural-generation','exitcode':rc,'wall_seconds':time.monotonic()-start,'resource_wait_seconds':time.monotonic()-wait_start-(time.monotonic()-start)}]
(out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
if rc:
 (out/'completion.json').write_text(json.dumps({'execution_completed':False,'failed_stage':'fresh-generation','records':records},indent=2)+'\n');raise SystemExit(rc)
post=root/'reports/protac-postprocess-20261028-01/v2/run_example.py' if a.target=='gpu1' else source/'sdaa/scripts/protac_postprocess/run_example.py'
shim=root/'reports/protac-postprocess-20261028-01/parameters/libfixedtime.so' if a.target=='gpu1' else source/'sdaa/vendor/ifit_clock_x86/libfixedtime.so'
cmd=['python3',str(post),'--target',a.target,'--input',str(out/'generation/generated_smi_1/pd.10_docking_0002_generated_smiles.smi'),'--fragments',str(fixed/'fragments.sdf'),'--receptor',str(fixed/'receptor.pdb'),'--output',str(out/'postprocess'),'--fixed-time-shim',str(shim),'--conformer-trials','16','--population','500','--generations','500']
(out/'postprocess-command.json').write_text(json.dumps(cmd,indent=2)+'\n')
print('START one-candidate-postprocess',flush=True);start=time.monotonic()
with (out/'postprocess.log').open('x') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
records.append({'stage':'one-candidate-postprocess','exitcode':rc,'wall_seconds':time.monotonic()-start})
(out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
if rc:
 (out/'completion.json').write_text(json.dumps({'execution_completed':False,'failed_stage':'postprocess','records':records},indent=2)+'\n');raise SystemExit(rc)
post_done=json.loads((out/'postprocess/completion.json').read_text())
assert post_done['functional_postprocess_completed']
assert files=={p.name:sha(p) for p in fixed.iterdir() if p.is_file()}
done={'execution_completed':True,'fresh_neural_generation_executed':True,'generation_report':json.loads((out/'generation/generation-report.json').read_text()),'postprocess':post_done,'stages':records,'active_pipeline_seconds':sum(x['wall_seconds'] for x in records),'fixed_inputs_unchanged':True,'strict_official_pipeline_equivalence':False}
(out/'completion.json').write_text(json.dumps(done,indent=2)+'\n');print(json.dumps(done,indent=2),flush=True)
