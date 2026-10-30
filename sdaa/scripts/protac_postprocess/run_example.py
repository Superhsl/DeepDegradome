"""Run one generated complete PROTAC through an experimental fixed-complex CPU tail."""
from pathlib import Path
import argparse,json,subprocess,hashlib,shutil,os,time,platform,math
p=argparse.ArgumentParser();p.add_argument('--target',choices=['gpu1','loong'],required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--fragments',type=Path,required=True);p.add_argument('--receptor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--population',type=int,default=500);p.add_argument('--generations',type=int,default=500);p.add_argument('--conformer-trials',type=int,default=16);p.add_argument('--fixed-time-shim',type=Path,required=True);p.add_argument('--resume-from',type=Path);p.add_argument('--wait-for-resume',action='store_true');a=p.parse_args()
root=Path(os.environ.get('DEEPDEGRADOME_PROJECT', Path(__file__).resolve().parents[4])).expanduser().resolve()
code=Path(__file__).resolve().parent;out=a.output.resolve()
assert root in out.parents and not out.exists(),'Use a fresh output under the project root'
source=root/'scripts/full-comparison-20261023/source-gpu' if a.target=='gpu1' else root/'DeepDegradome'
image='sha256:71e9f83f87a749592ca628a6e1460000350a29660521bb2e8bab3d6a3347dcaf' if a.target=='gpu1' else 'sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'
assert subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()==image
out.mkdir();frozen=out/'inputs';frozen.mkdir();results=out/'results';results.mkdir()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
inputs={'generated'+a.input.suffix:a.input.resolve(),'fragments.sdf':a.fragments.resolve(),'receptor.pdb':a.receptor.resolve()}
originals={str(q):sha(q) for q in inputs.values()}
for n,q in inputs.items():shutil.copy2(q,frozen/n)
if a.fixed_time_shim:shutil.copy2(a.fixed_time_shim,frozen/'libfixedtime.so')
env={'HOME':'/tmp','CUDA_VISIBLE_DEVICES':'','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','AutoFBDD_FOL':'/source','DeepDegradome_FOL':'/source','LATX_AOT':'0','LATX_KZT':'0'}
mounts=[(code,'/code:ro'),(source,'/source:ro'),(frozen,'/inputs:ro'),(results,'/out')]
if a.target=='gpu1':
 entry='python';eval_source='/source/ifitdock/ifit_eval';env['PATH']='/cpu-dock6/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
 mounts.extend([(root/'runtime/chimera-1.20-deterministic','/chimera:ro'),(root/'outputs/full-native-20261019-01/dock-x86-reference-01/dock6','/cpu-dock6:ro')])
else:
 entry='python3.12';eval_source='/validation/runtime/tools/ifit_eval';env['PATH']='/validation/bin:/opt/deepdegradome/bin:/opt/deepdegradome/dock6/bin:/opt/deepdegradome/chimera/bin:/home/py312/lib/python3.12/site-packages/openbabel/bin:/home/py312/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
 mounts.append((root/'native/latx-48a9c55d','/validation:ro'))
protocol={'target':a.target,'scope':'One generated molecule selected after legality/stereo canonical sorting; experimental full-PROTAC postprocessing, fixed full receptor. No new neural generation and no official full-pipeline equivalence claim.','input_sha256':originals,'frozen_sha256':{n:sha(frozen/n) for n in inputs},'image_id':image,'source_scripts_sha256':{n:sha(code/n) for n in ['protac_candidates.py','ifit_experimental.py','postscore.py','run_example.py','full_sa_reference.py','ifit_exact_sa.py','sa_exact_subset.py','sa_coverage.py']},'limit':1,'conformer_trials':a.conformer_trials,'population':a.population,'generations':a.generations,'fixed_time_shim':a.fixed_time_shim is not None}
(out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
stages=[]
def run(stage,args,timeout):
 cmd=['docker','run','--rm','--network','none','--name','dd-protac-example-'+a.target+'-'+stage+'-'+str(os.getpid()),'--user',str(os.getuid())+':'+str(os.getgid()),'--cpus','4','--memory','32g','--shm-size','2g']
 for k,v in env.items():cmd+=['-e',k+'='+v]
 for src,dst in mounts:cmd+=['-v',str(src)+':'+dst]
 cmd+=['-w','/out','--entrypoint',entry,image]+args
 (out/(stage+'-command.json')).write_text(json.dumps(cmd,indent=2)+'\n');print('START',stage,flush=True);t=time.monotonic()
 with (out/(stage+'.log')).open('x') as log:
  try:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=timeout);rc=r.returncode
  except subprocess.TimeoutExpired:
   subprocess.run(['docker','stop','-t','5',cmd[cmd.index('--name')+1]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);rc=124
 rec={'stage':stage,'exitcode':rc,'wall_seconds':time.monotonic()-t};stages.append(rec);(out/'progress.json').write_text(json.dumps(stages,indent=2)+'\n');print(json.dumps(rec),flush=True)
 if rc:
  (out/'completion.json').write_text(json.dumps({'functional_postprocess_completed':False,'failed_stage':stage,'records':stages,'neural_generation_executed':False},indent=2)+'\n')
  raise SystemExit(rc)
name=next(n for n in inputs if n.startswith('generated'))
args=['/code/protac_candidates.py','--input','/inputs/'+name,'--fragments','/inputs/fragments.sdf','--receptor','/inputs/receptor.pdb','--output','/out/candidates','--limit','1','--conformer-trials',str(a.conformer_trials)]
if a.input.suffix.lower() in ['.smi','.smiles']:args+=['--reembed']
if a.resume_from:
 previous=a.resume_from.resolve();assert root in previous.parents
 deadline=time.monotonic()+1800
 while not (previous/'completion.json').exists():
  assert a.wait_for_resume and time.monotonic()<deadline,'Previous run not finished'
  time.sleep(10)
 old=json.loads((previous/'protocol.json').read_text())
 assert old['input_sha256']==originals and old['image_id']==image
 assert old['population']==a.population and old['generations']==a.generations and old['conformer_trials']==a.conformer_trials
 for label in ['candidates','ifit']:shutil.copytree(previous/'results'/label,results/label)
 core=json.loads((results/'ifit/runtime/ifit-evaluate-command.json').read_text());assert core['exitcode'] in (0,1),'Do not recover a crashed/timed-out core as a valid no-pose result'
 lines=[l.split() for l in (results/'ifit/runtime/protac_scored.list').read_text().splitlines() if l.strip()]
 header=lines[0];assert len(header)==12
 recovered=[]
 for cells in lines[1:]:
  assert len(cells)==12 and all(math.isfinite(float(x)) for x in cells[1:])
  recovered.append({k:(v if i==0 else float(v)) for i,(k,v) in enumerate(zip(header,cells))})
 if not recovered:
  text=(results/'ifit/runtime/ifit-evaluate.log').read_text()
  assert 'generated_data_size_ligand = 0' in text and 'None candidate was found' in text
  assert (results/'ifit/runtime/protac_scored.mol2').stat().st_size==0
 (results/'ifit/ifit-report.json').write_text(json.dumps({'scores':recovered,'engine_no_pose':not recovered,'recovered_same_current_case':str(previous),'actual_original_core_status':core,'scope':'Normalize explicit no-pose termination; no scores fabricated and no generation or docking rerun'},indent=2)+'\n')
 stages.append({'stage':'reuse-candidate-and-bootstrap','kind':'validate_and_copy_same_current_case_outputs','source':str(previous),'original_launcher_completion':json.loads((previous/'completion.json').read_text()),'core_exitcode':core['exitcode']})
else:
 run('candidate-refine',args,1800)
 args=['/code/ifit_experimental.py','--target',a.target,'--eval-source',eval_source,'--extra-source','/source/ifitdock/ifit_dock','--candidates','/out/candidates','--frozen','/inputs','--output','/out/ifit','--population',str(a.population),'--generations',str(a.generations)]
 if a.fixed_time_shim:args+=['--fixed-time-shim','/inputs/libfixedtime.so']
 run('ifit-bootstrap',args,7200)
bootstrap=json.loads((results/'ifit/ifit-report.json').read_text());has_scores=bool(bootstrap['scores']);runtime='/out/ifit/runtime'
if has_scores:
 run('full-sa-reference',['/code/full_sa_reference.py','--target',a.target,'--source',runtime,'--output','/out/full-sa-reference'],400)
 run('ifit-exact-sa',['/code/ifit_exact_sa.py','--target',a.target,'--source',runtime,'--full-sa-prefix','/out/full-sa-reference/full_SA_1','--output','/out/ifit-exact','--score-prefix','protac'],4000)
 runtime='/out/ifit-exact/runtime'
run('final-check',['/code/postscore.py','--runtime',runtime,'--charged-input','/out/ifit/runtime/gen_mols.mol2','--candidate-sdf','/out/candidates/accepted.sdf','--fragments','/inputs/fragments.sdf','--receptor','/inputs/receptor.pdb','--output','/out/final','--score-prefix','protac'],300)
final=json.loads((results/'final/postscore-report.json').read_text())
assert all(sha(q)==value for q,value in originals.items())
done={'functional_postprocess_completed':True,'numeric_evaluation_available':has_scores,'full_SA_neighbor_support_verified':True if has_scores else None,'candidate_terminal':'scored_then_filtered' if has_scores else 'ifit_no_pose','neural_generation_executed':False,'selected_generated_molecules':1,'scored_poses':final['poses_with_numeric_scores'],'retained_poses':final['retained_poses'],'strict_official_pipeline_equivalence':False,'scientific_scope':'One generated molecule; bootstrap may use smaller SA domain, final numeric scoring must preserve full-SA neighbor support and masks for actual output poses. MMFF local strain/new order/thresholds are experimental, not biological validation or strict official equivalence.','records':stages,'original_inputs_unchanged':True}
(out/'completion.json').write_text(json.dumps(done,indent=2)+'\n');print(json.dumps(done,indent=2),flush=True)
