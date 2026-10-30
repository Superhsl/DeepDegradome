
from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
from pathlib import Path
import hashlib,json,math,os
import numpy as np
from rdkit import Chem

OUT=Path('/out');CASE=OUT/'case';SOURCE=Path('/source')
AUDIT=Path(os.environ.get('VALIDATION_AUDIT_OUTPUT',str(OUT)))
def read(n):return json.loads((OUT/n).read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sdf(path,allow_empty=False):
 assert path.is_file(),str(path)
 if not path.stat().st_size:assert allow_empty;return []
 mols=list(Chem.SDMolSupplier(str(path)));assert mols and all(m is not None for m in mols)
 for m in mols:
  assert len(Chem.GetMolFrags(m))==1
  assert np.isfinite(m.GetConformer().GetPositions()).all()
 return mols
def main():
 global_report=read('global-report.json');refine=read('refinement-report.json');generation=read('generation-report.json');assessment=read('assessment-report.json');evaluation=read('evaluation-report.json');parity=read('classification-parity.json');aux=read('auxiliary-report.json')
 assert global_report['count']==10 and all(4.98<=d<=15.02 for d in global_report['anchor_distances'])
 assert refine['attempts']==20 and refine['accepted']>0
 raw=0;connected=0;unique=set()
 for name,record in generation['generated'].items():
  path=CASE/name/'generated_smi_1'/(name+'_generated_smiles.smi');rows=[l.split()[-1] for l in path.read_text().splitlines() if l.strip()]
  assert len(rows)==record['rows']
  for smi in rows:
   m=Chem.MolFromSmiles(smi);assert m is not None;raw+=1;connected+=len(Chem.GetMolFrags(m))==1;unique.add(Chem.MolToSmiles(m))
 assert raw>0 and all(r['device'].startswith('sdaa') and r['operation_evidence']['device_events']>0 and r['operation_evidence']['original_weight_arrays']==123 for r in generation['records'])
 assert generation['TORCH_SDAA_CONV_USE_FP32']=='0'
 candidates={};total=0
 for name,count in assessment['aligned_molecules'].items():
  ms=sdf(CASE/name/'final/aligned_mols.sdf');assert len(ms)==count
  fragment=Chem.SDMolSupplier(str(CASE/name/(name+'_frag.sdf')))[0];assert fragment is not None
  # Audit the parent heavy-atom graphs. Upstream dummy removal can leave
  # detached explicit hydrogen markers; these are not ligand heavy atoms.
  query=Chem.RWMol(fragment)
  for i in reversed(range(query.GetNumAtoms())):
   if query.GetAtomWithIdx(i).GetAtomicNum() in (0,1):query.RemoveAtom(i)
  fragment=query.GetMol();fragment.UpdatePropertyCache(strict=False)
  assert all(m.HasSubstructMatch(fragment) for m in ms)
  candidates[name]=ms;total+=len(ms)
 assert total>0 and evaluation['ensemble']==10 and evaluation['device']=='sdaa' and evaluation['evaluated']==len(evaluation['records'])
 assert parity['passed'] and parity['candidates']==evaluation['evaluated'] and parity['vote_changes']==0
 votes=[];expected=[];audited=[];seen=set()
 for r in evaluation['records']:
  key=r['candidate'];assert key not in seen;seen.add(key)
  path=Path(key);name=path.parts[-3];index=int(path.name);mol=candidates[name][index]
  logits=np.asarray(r['logits']);assert logits.shape==(10,1,2) and np.isfinite(logits).all()
  vote=int((logits[:,0,:].argmax(axis=1)==1).sum())*10;assert vote==r['positive_vote_percent']
  smi=Chem.MolToSmiles(mol);votes.append(vote)
  if vote>50:expected.append(smi)
  audited.append({'candidate':key,'vote_percent':vote,'accepted':vote>50,'canonical_smiles':smi})
 final=sdf(CASE/'WDR5_CRBN_PROTACs.sdf',allow_empty=True)
 assert [Chem.MolToSmiles(m) for m in final]==expected
 assert len(seen)==total,'Some retained structural candidates were not evaluated'
 assert aux['records']['Cyndi']['conformers']>1 and aux['records']['native_grid']['products']
 assert all(aux['records'][name]['completion_verified'] for name in ['iFitDock','iFitDock_eval'])
 cpu_path=OUT/'cpu-controls-02/report.json'
 if not cpu_path.exists():cpu_path=OUT/'cpu-controls/report.json'
 cpu=json.loads(cpu_path.read_text());assert cpu['cpu_only'] and cpu['checks']['emolfrag']['fragments']['brick'] and cpu['checks']['emolfrag']['fragments']['linker']
 weights={str(p.relative_to(SOURCE)):sha(p) for p in sorted((SOURCE/'DEVELOP/models').rglob('*.pickle'))+sorted((SOURCE/'DeepPROTACs').glob('model_*.pth'))}
 assert len(weights)==13
 (AUDIT/'candidate-audit.json').write_text(json.dumps(audited,indent=2)+'\n')
 report={'functional_passed':True,'case':'Public PDB 9LWY WDR5 / Compound4 and 8OIZ CRBN / pomalidomide','global_poses':global_report['count'],'refinement_attempts':refine['attempts'],'accepted_refinements':refine['accepted'],'generator_eligible_poses':len(generation['generated']),'raw_sampled_smiles':raw,'parseable_smiles':raw,'connected_raw_smiles':connected,'unique_raw_smiles':len(unique),'raw_rows_entering_assessment_per_pose':20,'aligned_candidates':total,'evaluated_candidates':len(seen),'evaluator_forward_calls':len(seen)*10,'vote_above_50_candidates':len(final),'vote_percentages':votes,'evaluation_cpu_sdaa_max_logit_error':parity['maximum_logit_absolute_error'],'weight_sha256':weights,'final_sdf_sha256':sha(CASE/'WDR5_CRBN_PROTACs.sdf'),'sdaa_default_convolution':True,'traditional_tools':'Native Loong CPU plus LATX execution of unchanged x86 external cores','ifit_case_result':'No accepted scored hits at original cutoffs; execution completed. Matched x86 diagnostics are separate evidence.','limitations':['Public-PDB functional example; author-prepared inputs were not recovered.','No paper accuracy, biological activity or full-scale sampling claim.','Chimera versions remain 1.17 versus 1.20; the common deterministic policy passed four frozen inputs, not arbitrary-input or unmodified-x86 equivalence.','Default SDAA convolution retains the previously measured fixed-state probability discrepancy; strict 1e-5 generator parity is not claimed.','Inference adaptation only; original TensorFlow training was not ported.']}
 (AUDIT/'validation-summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
