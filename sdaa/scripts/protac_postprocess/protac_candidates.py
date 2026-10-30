from pathlib import Path
import argparse,json,hashlib,time,math
import numpy as np
from rdkit import Chem,rdBase
from rdkit.Chem import AllChem,Descriptors
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--fragments',type=Path,required=True);p.add_argument('--receptor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=int,default=2);p.add_argument('--max-iters',type=int,default=1000);p.add_argument('--reembed',action='store_true');p.add_argument('--conformer-trials',type=int,default=16);p.add_argument('--upstream-source',type=Path,default=Path('/source/DeepDegradome_PROTACs.py'));a=p.parse_args()
O=a.output;O.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
q=Chem.SDMolSupplier(str(a.fragments))[0];assert q is not None and len(Chem.GetMolFrags(q))==2
q=Chem.RemoveHs(q);qx=np.array(q.GetConformer().GetPositions());qgroups=Chem.GetMolFrags(q)
rx=[]
for l in a.receptor.read_text().splitlines():
 if l.startswith(('ATOM  ','HETATM')):
  elem=l[76:78].strip() or l[12:16].strip().lstrip('0123456789')[0]
  if elem.upper()!='H':rx.append([float(l[j:j+8]) for j in [30,38,46]])
rx=np.array(rx);assert len(rx)>5000
def metrics(m):
 m=Chem.RemoveHs(m)
 matches=m.GetSubstructMatches(q,uniquify=False,useChirality=True,maxMatches=1000)
 if not matches:return None
 xyz=np.array(m.GetConformer().GetPositions())
 match=min(matches,key=lambda z:float(np.sum((xyz[list(z)]-qx)**2)))
 dif=xyz[list(match)]-qx
 rms=[float(np.sqrt(np.mean(np.sum(dif[list(g)]**2,axis=1)))) for g in qgroups]
 closest=float(np.sqrt(np.min(np.sum((xyz[:,None,:]-rx[None,:,:])**2,axis=2))))
 return {'fragment_match':list(match),'fragment_rmsds_A':rms,'max_fragment_rmsd_A':max(rms),'min_receptor_heavy_distance_A':closest}
def ff(m):
 prop=AllChem.MMFFGetMoleculeProperties(m,mmffVariant='MMFF94')
 return AllChem.MMFFGetMoleculeForceField(m,prop,nonBondedThresh=100.0)
# Raw generation SMILES and prepared SDF are explicit, separate entry modes.
input_sha=sha(a.input)
legal={'input_sha256':input_sha,'input_format':a.input.suffix.lower(),'records':[]}
if a.input.suffix.lower() in ['.smi','.smiles']:
 assert a.reembed,'Raw SMILES requires --reembed for joint fixed-fragment coordinates'
 import ast
 from copy import deepcopy
 raw=[]
 for source_index,line in enumerate(a.input.read_text().splitlines()):
  if not line.strip():continue
  fields=line.split()
  m=Chem.MolFromSmiles(fields[-1])
  valid=m is not None;connected=valid and len(Chem.GetMolFrags(m))==1
  legal['records'].append({'source_index':source_index,'parseable':valid,'single_connected':bool(connected)})
  if connected:
   assert len(fields)==3,'Original DEVELOP output must contain 3 SMILES columns'
   raw.append(' '.join(fields)+'\n')
 if raw:
  source=a.upstream_source;tree=ast.parse(source.read_text())
  node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='keep_chirality')
  ns={'Chem':Chem,'deepcopy':deepcopy};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
  stereo=O/'stereochemistry.smi';stereo.write_text(''.join(raw))
  ns['keep_chirality'](str(stereo))
  # Upstream enumeration uses sets; canonical sorting makes the processing budget reproducible.
  selected=sorted({line.split()[-1] for line in stereo.read_text().splitlines() if line.strip()})
  inputs=[Chem.MolFromSmiles(s) for s in selected]
  legal.update(stereochemistry_source_sha256=sha(source),stereochemistry_function='Unchanged upstream keep_chirality, applied only after parse/connected checks',stereo_unique_candidates=len(inputs),processing_order='Sorted canonical stereo SMILES; full run uses --limit 0')
 else:inputs=[]
else:
 inputs=list(Chem.SDMolSupplier(str(a.input)))
 for source_index,m in enumerate(inputs):
  legal['records'].append({'source_index':source_index,'parseable':m is not None,'single_connected':bool(m is not None and len(Chem.GetMolFrags(m))==1)})
legal.update(total=len(legal['records']),parseable=sum(r['parseable'] for r in legal['records']),single_connected=sum(r['single_connected'] for r in legal['records']))
(O/'legality-report.json').write_text(json.dumps(legal,indent=2)+'\n')
rows=[];writer=Chem.SDWriter(str(O/'refined.sdf'));accepted_writer=Chem.SDWriter(str(O/'accepted.sdf'))
for i,m in enumerate(inputs):
 if a.limit and i>=a.limit:break
 start=time.monotonic();r={'id':'c%04d'%i,'source_index':i}
 if m is None:r.update(status='invalid_sdf',accepted=False);rows.append(r);continue
 Chem.SanitizeMol(m)
 r.update(parseable=True,single_connected=len(Chem.GetMolFrags(m))==1,canonical_smiles=Chem.MolToSmiles(m),molecular_weight=Descriptors.MolWt(m),heavy_atoms=m.GetNumHeavyAtoms())
 if not r['single_connected']:r.update(status='disconnected',accepted=False);rows.append(r);continue
 if a.reembed:
  attempts=[];choices=[]
  for trial in range(a.conformer_trials):
   seed=1000+i*a.conformer_trials+trial
   htrial=Chem.AddHs(Chem.MolFromSmiles(Chem.MolToSmiles(m)))
   try:
    AllChem.ConstrainedEmbed(htrial,q,randomseed=seed,useTethers=True,maxAttempts=20,useRandomCoords=True,ignoreSmoothingFailures=True)
    geometry=metrics(htrial)
    if geometry is not None:
     choices.append((geometry['max_fragment_rmsd_A']>1.0 or geometry['min_receptor_heavy_distance_A']<1.5,-geometry['min_receptor_heavy_distance_A'],trial,htrial,geometry))
     attempts.append({'trial':trial,'seed':seed,'embedded':True,'geometry':geometry})
    else:attempts.append({'trial':trial,'seed':seed,'embedded':False,'reason':'missing_fragment_stereochemistry'})
   except Exception as e:attempts.append({'trial':trial,'seed':seed,'embedded':False,'reason':str(e)})
  r['embedding_attempts']=attempts
  if not choices:r.update(status='no_joint_fragment_conformer',refine_accepted=False);rows.append(r);continue
  choice=min(choices,key=lambda x:x[:3]);m=Chem.RemoveHs(choice[3]);r['selected_embedding_trial']=choice[2]
 before=metrics(m);r['before']=before
 if before is None:r.update(status='missing_input_fragments_or_stereochemistry',accepted=False);rows.append(r);continue
 h=Chem.AddHs(m,addCoords=True)
 if not AllChem.MMFFHasAllMoleculeParams(h):r.update(status='mmff_parameters_unavailable',accepted=False);rows.append(r);continue
 bound=ff(h);r['initial_energy_kcal_mol']=float(bound.CalcEnergy())
 for atom in before['fragment_match']:bound.AddFixedPoint(int(atom))
 bound.Initialize();r['refine_status']=int(bound.Minimize(maxIts=a.max_iters,forceTol=1e-4,energyTol=1e-6))
 r['refined_energy_kcal_mol']=float(ff(h).CalcEnergy())
 r['after']=metrics(h)
 free=Chem.Mol(h);freeff=ff(free);r['free_relax_status']=int(freeff.Minimize(maxIts=a.max_iters,forceTol=1e-4,energyTol=1e-6))
 r['free_local_energy_kcal_mol']=float(freeff.CalcEnergy())
 r['local_strain_estimate_kcal_mol']=r['refined_energy_kcal_mol']-r['free_local_energy_kcal_mol']
 assert math.isfinite(r['local_strain_estimate_kcal_mol'])
 r['initial_screen_pass']=before['max_fragment_rmsd_A']<=1.0 and before['min_receptor_heavy_distance_A']>=1.5
 r['refine_accepted']=r['initial_screen_pass'] and r['refine_status']==0 and r['after']['max_fragment_rmsd_A']<=1.0 and r['after']['min_receptor_heavy_distance_A']>=1.5
 r.update(status='parameterized_and_refined',seconds=time.monotonic()-start,energy_model='MMFF94')
 h.SetProp('_Name',r['id'])
 for k in ['refined_energy_kcal_mol','free_local_energy_kcal_mol','local_strain_estimate_kcal_mol']:h.SetDoubleProp(k,r[k])
 writer.write(h)
 if r['refine_accepted'] and r['free_relax_status']==0 and r['local_strain_estimate_kcal_mol']>=-1e-3:accepted_writer.write(h)
 rows.append(r)
writer.close();accepted_writer.close()
box={'center':((qx.min(axis=0)+qx.max(axis=0))/2).tolist(),'gbsa_size_A':[float(math.ceil(x)+20) for x in np.ptp(qx,axis=0)],'vdw_size_A':[float(math.ceil(x)+30) for x in np.ptp(qx,axis=0)],'source':'Two fixed fragments, geometry frozen independently of platform-local optimization; dynamic coverage for complete PROTAC'}
(O/'grid-config.json').write_text(json.dumps(box,indent=2)+'\n')
report={'rdkit':rdBase.rdkitVersion,'platform':__import__('platform').machine(),'input_sha256':{str(n):sha(n) for n in [a.input,a.fragments,a.receptor]},'records':rows,
'policy':{'max_fragment_rmsd_A':1.0,'min_heavy_protein_distance_A':1.5,'max_refinement_iterations':a.max_iters,
'force_field':'MMFF94, fixed heavy atoms of both fragments; fixed receptor used for clash filtering, not explicit MMFF receptor interactions',
'strain_definition':'Internal energy of bound constrained pose minus unconstrained local relaxation from that same pose; local estimate, not global-minimum strain',
'candidate_budget':a.limit,'joint_embedding_trials':a.conformer_trials if a.reembed else 0,'refined_sdf_is_diagnostic_all_parameterizable_candidates':True,'accepted_sdf_requires_geometry_and_converged_local_refinements':True,'fixed_16_accepted_rounds':False}}
(O/'candidate-report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(json.dumps({'processed':len(rows),'refine_accepted':sum(r.get('refine_accepted',False) for r in rows),'records':rows},indent=2),flush=True)
