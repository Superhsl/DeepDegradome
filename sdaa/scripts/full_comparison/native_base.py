"""Bounded public-PDB functional validation; preserve upstream chemistry and filters."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
from pathlib import Path
import argparse, hashlib, json, math, os, runpy, shutil, subprocess, sys, time

OUT=Path('/out'); CASE=OUT/'case'; SOURCE=Path('/source')
sys.path.insert(0,str(SOURCE/'sdaa/scripts'))
def dump(name,value):
 (OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def execute(command,cwd,log,allow_rejected=False):
 start=time.perf_counter()
 with Path(log).open('w') as f:r=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 record={'command':list(map(str,command)),'cwd':str(cwd),'seconds':time.perf_counter()-start,'exitcode':r.returncode}
 Path(str(log)+'.json').write_text(json.dumps(record,indent=2)+'\n')
 if r.returncode and not allow_rejected:raise AssertionError(record)
 return record
def ns():return runpy.run_path(str(SOURCE/'DeepDegradome_PROTACs.py'),run_name='functional_validation_functions')
def molcount(path):
 from rdkit import Chem
 ms=list(Chem.SDMolSupplier(str(path)))
 assert ms and all(m is not None for m in ms),str(path)
 assert all(math.isfinite(v) for m in ms for p in m.GetConformer().GetPositions() for v in p)
 return len(ms)
def prepare_global():
 CASE.mkdir(); prep=OUT/'preparation';prep.mkdir()
 inp=Path('/public-inputs')
 for stage,file,target in [('prepare-protein','WDR5.pdb','WDR5'),('prepare-protein','CRBN.pdb','CRBN'),('prepare-ligand','compound4.mol2','compound4'),('prepare-ligand','CRBN_ligand.mol2','CRBN_ligand')]:
  execute([sys.executable,str(SOURCE/'sdaa/scripts/native_pipeline.py'),stage,'--input',str(inp/file),'--output',str(prep/target)],prep,prep/(target+'.log'))
  product='target.pdb' if stage=='prepare-protein' else 'ligand.mol2'
  shutil.copy2(prep/target/product,CASE/file)
 global_dock()
def global_dock():
 os.chdir(CASE); f=ns(); anchors=[]
 for ligand,protein in [('compound4.mol2','WDR5.pdb'),('CRBN_ligand.mol2','CRBN.pdb')]:
  anchors.append(f['obtain_anchor'](ligand,f['obtain_surround'](ligand,protein)))
 params=[]
 for ligand,name in [('compound4.mol2','War'),('CRBN_ligand.mol2','E3l')]:
  pdb,param=f['mol_to_params'](f['add_H'](ligand),name,name)
  assert Path(pdb).is_file() and Path(param).is_file();params.append((pdb,param))
 Path('target_warhead.pdb').write_text(Path(params[0][0]).read_text()+Path('WDR5.pdb').read_text())
 Path('E3_ligase_ligand.pdb').write_text(Path(params[1][0]).read_text()+Path('CRBN.pdb').read_text())
 count=f['patchdock'](['target_warhead.pdb','E3_ligase_ligand.pdb'],[a+1 for a in anchors],5,15,10,2.0)
 expected=sum(sum(l.startswith(('ATOM  ','HETATM')) for l in Path(n).read_text().splitlines()) for n in ['target_warhead.pdb','E3_ligase_ligand.pdb'])
 distances=[]
 for p in Path('Patchdock_Results').glob('pd.*.pdb'):
  rows=[l for l in p.read_text().splitlines() if l.startswith(('ATOM  ','HETATM'))]
  assert len(rows)==expected and {'A','B','X','Y'}<=set(l[21] for l in rows)
  pts=[]
  for chain,anchor in zip(['X','Y'],anchors):
   l=next(l for l in rows if l[21]==chain and int(l[6:11])==anchor+1);pts.append([float(l[k:k+8]) for k in [30,38,46]])
  d=math.dist(*pts); assert 4.98<=d<=15.02;distances.append(d)
 assert count==len(distances)>0
 dump('global-report.json',{'count':count,'atoms_per_complex':expected,'anchors_zero_based':anchors,'anchor_distances':distances,'inputs':'Public PDB 9LWY / 8OIZ; fresh native Chimera preparation','official_prepared_inputs':False})
def generate():
 import torch
 torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
 os.chdir(CASE);f=ns();selected=json.loads((CASE/'refined-selection.json').read_text())
 import brick_linking
 Original=brick_linking.DenseGGNNChemModel; records=[]
 class Observed(Original):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   assert len(self.sess.model.weights)==123
   assert all(v.device.type=='sdaa' for v in self.sess.model.weights.values())
   self.operation_evidence={};original=self.sess.model.cache_structure
   def cache(value):
    if self.operation_evidence:return original(value)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.PrivateUse1]) as prof:
     result=original(value);torch.sdaa.synchronize()
    path=OUT/(Path.cwd().name+'-generator-cnn-trace.json');prof.export_chrome_trace(str(path))
    events=[e for e in prof.events() if 'privateuse1' in str(e.device_type).lower() or 'sdaa' in str(e.device_type).lower()]
    assert events,'No accelerator events in actual generation'
    self.operation_evidence.update(device_events=len(events),trace=str(path),original_weight_arrays=123)
    return result
   self.sess.model.cache_structure=cache
  def train(self,*args,**kwargs):
   start=time.perf_counter();r=super().train(*args,**kwargs);torch.sdaa.synchronize()
   records.append({'cwd':os.getcwd(),'seconds':time.perf_counter()-start,'neural_calls':self.sess.calls,'device':str(self.sess.model.device),'conv_fp32':os.environ['TORCH_SDAA_CONV_USE_FP32'],'operation_evidence':self.operation_evidence});return r
 brick_linking.DenseGGNNChemModel=Observed
 f['generate_linker'](selected,'compound4.mol2','CRBN_ligand.mol2',18,1)
 from rdkit import Chem
 generated={}
 for name,_ in selected:
  p=CASE/name/'generated_smi_1'/(name+'_generated_smiles.smi')
  if p.exists():
   rows=[l.split()[-1] for l in p.read_text().splitlines() if l.strip()]; ms=[Chem.MolFromSmiles(s) for s in rows]
   assert all(m is not None for m in ms)
   generated[name]={'rows':len(rows),'unique':len(set(Chem.MolToSmiles(m) for m in ms))}
 assert records and sum(v['rows'] for v in generated.values())>0
 dump('generation-report.json',{'records':records,'generated':generated,'sampler':'unchanged upstream 50 samples per linker length','device':'sdaa','TORCH_SDAA_CONV_USE_FP32':os.environ['TORCH_SDAA_CONV_USE_FP32']})
def refine_parallel(resume_first=False):
 import concurrent.futures,shlex
 os.chdir(CASE);f=ns();jobs=CASE/'refinement-parallel';jobs.mkdir()
 def worker(i):
  work=jobs/('pd.'+str(i));work.mkdir();pdb='pd.%d.pdb'%i
  shutil.copy2(CASE/'Patchdock_Results'/pdb,work/pdb)
  for file in ['War.params','E3l.params']:shutil.copy2(CASE/file,work/file)
  command=shlex.split(f['local_docking'](pdb,'AX','BY','War.params','E3l.params',2))+['-database',os.environ['ROSETTA_FOL']+'/main/database','-constant_seed','-jran',str(1000+i)]
  return work,execute(command,work,work/'rosetta.log',allow_rejected=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:finished=list(pool.map(worker,range(2 if resume_first else 1,11)))
 if resume_first:
  first=CASE/'refinement/pd.1'
  deadline=time.monotonic()+3600
  while not (first/'rosetta.log.json').exists():
   assert time.monotonic()<deadline,'First refinement did not finish';time.sleep(1)
  finished.insert(0,(first,json.loads((first/'rosetta.log.json').read_text())))
 allrows=[];header=None;records=[]
 for work,rec in finished:
  log=(work/'rosetta.log').read_text()
  if rec['exitcode']:
   assert '2 jobs considered, 2 jobs attempted' in log and 'Mover Docking reports failure!' in log,rec
   assert 'Caught exception' not in log and 'UtilityExitException' not in log,rec
  lines=(work/'local.fasc').read_text().splitlines(True)
  rows=[l for l in lines if l.startswith('SCORE:') and 'description' not in l]
  structures=list(work.glob('*_docking_*.pdb'));assert len(rows)==len(structures)
  for p in structures:shutil.copy2(p,CASE/'Patchdock_Results'/p.name)
  if header is None:header=[l for l in lines if not l.startswith('SCORE:') or 'description' in l]
  allrows+=rows;rec['accepted']=len(rows);records.append(rec)
 assert allrows
 (CASE/'Patchdock_Results/local.fasc').write_text(''.join(header+allrows))
 os.chdir(CASE/'Patchdock_Results');selected=f['sort_docking'](10)
 (CASE/'refined-selection.json').write_text(json.dumps(selected,indent=2)+'\n')
 dump('refinement-report.json',{'attempts':20,'accepted':len(allrows),'selected':selected,'records':records,'filters':'unchanged upstream XML and flags','scheduling':'Four workers; same per-pose seeds and unchanged filters'})
def assess():
 selected=json.loads((CASE/'refined-selection.json').read_text());assessment=OUT/'assessment-case';assessment.mkdir();budget=[]
 for name,_ in selected:
  original=CASE/name/'generated_smi_1'/(name+'_generated_smiles.smi')
  if not original.exists():continue
  shutil.copytree(CASE/name,assessment/name)
  copied=assessment/name/'generated_smi_1'/original.name
  rows=copied.read_text().splitlines(True);copied.write_text(''.join(rows[:20]))
  budget.append({'pose':name,'generated_rows':len(rows),'assessment_rows':min(20,len(rows)),'selection':'first 20 in original sampler order, before chirality or quality filtering','full_generated_sha256':hashlib.sha256(original.read_bytes()).hexdigest()})
 dump('assessment-input-budget.json',budget)
 os.chdir(assessment);f=ns()
 f['evaluate_PROTACs'](selected,4);f['merge_sdf'](selected)
 counts={name:molcount(assessment/name/'final/aligned_mols.sdf') for name,_ in selected if (assessment/name/'final/aligned_mols.sdf').exists() and (assessment/name/'final/aligned_mols.sdf').stat().st_size}
 assert sum(counts.values())>0,'No candidates passed upstream filters'
 for name in counts:
  target=CASE/name/'final';target.mkdir();shutil.copy2(assessment/name/'final/aligned_mols.sdf',target/'aligned_mols.sdf')
  fragment=name+'_frag.sdf'
  shutil.copy2(CASE/name/fragment,CASE/name/(name+'_frag-before-assessment.sdf'))
  shutil.copy2(assessment/name/fragment,CASE/name/fragment)
 dump('assessment-report.json',{'aligned_molecules':counts,'filters':'unchanged upstream RMSD, pharmacophore, chirality and SA filters','budget':budget,'scope':'Bounded functional validation; original full sampler outputs retained separately'})
def evaluate():
 import shlex,torch
 import torch_sdaa
 torch.set_num_threads(1);torch.manual_seed(0)
 sys.path.insert(0,str(CASE))
 os.chdir(CASE);selected=json.loads((CASE/'refined-selection.json').read_text())
 f=runpy.run_path(str(SOURCE/'DeepPROTACs.py'),run_name='functional_evaluator')
 records=[]
 class ObservedOS:
  def __getattr__(self,name):return getattr(os,name)
  def system(self,command):
   tokens=shlex.split(command)
   if tokens[:2]!=['python','deepprotacs.py']:return os.system(command)
   oldargv=sys.argv[:];logits=[];Path('result.txt').unlink(missing_ok=True)
   def observe(module,args,output):
    if module.__class__.__name__=='ProtacModel':
     assert next(module.parameters()).device.type=='sdaa' and output.device.type=='sdaa'
     assert torch.isfinite(output).all()
     logits.append(output.detach().cpu().tolist())
   hook=torch.nn.modules.module.register_module_forward_hook(observe)
   try:
    sys.argv=['deepprotacs.py']+tokens[2:]
    if not records:
     with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.PrivateUse1]) as prof:
      runpy.run_path(str(CASE/'deepprotacs.py'),run_name='__main__');torch.sdaa.synchronize()
     prof.export_chrome_trace(str(OUT/'evaluator-trace.json'))
     assert any('privateuse1' in str(e.device_type).lower() or 'sdaa' in str(e.device_type).lower() for e in prof.events())
    else:runpy.run_path(str(CASE/'deepprotacs.py'),run_name='__main__')
   finally:hook.remove();sys.argv=oldargv
   assert len(logits)==10
   vote=float(Path('result.txt').read_text());assert vote==sum(x[0][1]>x[0][0] for x in logits)*10
   records.append({'candidate':tokens[-1],'logits':logits,'positive_vote_percent':vote})
   return 0
 f['deep_PROTACs'].__globals__['os']=ObservedOS()
 final=f['deep_PROTACs'](selected,'WDR5_CRBN')
 assert records
 # Upstream writer is returned before close; process exit flushes it. Count separately after this stage.
 dump('evaluation-report.json',{'device':'sdaa','ensemble':10,'evaluated':len(records),'records':records,'final_sdf':str(CASE/final),'scope':'Vote percentage, not calibrated biological probability'})
def refine_all():
 return refine_parallel(resume_first=False)
def aux():
 import validation_aux_tools as aux_tools
 aux_tools.main()
def aux_charge():
 import validation_aux_followup as aux_followup
 aux_followup.main()
def cpu_eval_reference():
 import validation_cpu_reference
 validation_cpu_reference.main()
def cpu_controls():
 execute([sys.executable,str(SOURCE/'sdaa/scripts/verify_cpu_tools.py'),'--source',str(SOURCE),'--native','/opt/deepdegradome','--output','/out/cpu-controls','--check-wrappers'],OUT,OUT/'cpu-controls-driver.log')
def finalize():
 import validation_finalize
 validation_finalize.main()
if __name__=='__main__':
 stage=sys.argv[1];start=time.perf_counter()
 try:globals()[stage]()
 except BaseException:
  dump(stage+'-status.json',{'stage':stage,'passed':False,'seconds':time.perf_counter()-start});raise
 dump(stage+'-status.json',{'stage':stage,'passed':True,'seconds':time.perf_counter()-start})
