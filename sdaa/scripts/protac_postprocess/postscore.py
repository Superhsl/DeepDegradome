"""Check scored full PROTAC poses against both frozen fragment frames, then retain by explicit criteria."""
from pathlib import Path
import argparse,json,math,hashlib
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True);p.add_argument('--charged-input',type=Path,required=True);p.add_argument('--candidate-sdf',type=Path,required=True);p.add_argument('--fragments',type=Path,required=True);p.add_argument('--receptor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--max-delta-g',type=float,default=-10);p.add_argument('--max-local-strain',type=float);p.add_argument('--score-prefix',default='probe');a=p.parse_args()
a.output.mkdir()
def mol2blocks(text):
 out=[]
 for part in text.split('@<TRIPOS>MOLECULE\n')[1:]:
  atompart=part.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0]
  atoms={}
  for line in atompart.splitlines():
   if not line.strip():continue
   f=line.split();assert f[0] not in atoms
   atoms[f[0]]={'label':f[1],'xyz':np.array([float(x) for x in f[2:5]]),'element':f[5].split('.')[0].upper()}
  out.append((part.splitlines()[0].strip(),atoms))
 return out
original=mol2blocks(a.charged_input.read_text());assert len(original)==1
cid,sourceatoms=original[0]
mols=[m for m in Chem.SDMolSupplier(str(a.candidate_sdf),removeHs=False) if m is not None]
base=next(m for m in mols if m.GetProp('_Name')==cid)
sx=np.array(base.GetConformer().GetPositions());mapping={}
for atom in base.GetAtoms():
 idx=atom.GetIdx();choices=[(float(np.linalg.norm(v['xyz']-sx[idx])),name) for name,v in sourceatoms.items() if v['element']==atom.GetSymbol().upper()]
 dist,name=min(choices);assert dist<.01,(idx,name,dist)
 assert name not in mapping.values();mapping[idx]=name
assert len(mapping)==len(sourceatoms)
q=Chem.RemoveHs(Chem.SDMolSupplier(str(a.fragments))[0]);qx=np.array(q.GetConformer().GetPositions());groups=Chem.GetMolFrags(q)
rx=[]
for line in a.receptor.read_text().splitlines():
 if line.startswith(('ATOM  ','HETATM')):
  elem=line[76:78].strip() or line[12:16].strip().lstrip('0123456789')[0]
  if elem.upper()!='H':rx.append([float(line[i:i+8]) for i in [30,38,46]])
rx=np.array(rx)
def geometry(m):
 h=Chem.RemoveHs(m);xyz=np.array(h.GetConformer().GetPositions());matches=h.GetSubstructMatches(q,uniquify=False,useChirality=True,maxMatches=1000)
 if not matches:return {'fragment_match':False}
 match=min(matches,key=lambda z:float(np.sum((xyz[list(z)]-qx)**2)));dif=xyz[list(match)]-qx
 rms=[float(np.sqrt(np.mean(np.sum(dif[list(g)]**2,axis=1)))) for g in groups]
 return {'fragment_match':True,'fragment_rmsds_A':rms,'max_fragment_rmsd_A':max(rms),'min_receptor_heavy_distance_A':float(np.sqrt(np.min(np.sum((xyz[:,None,:]-rx[None,:,:])**2,axis=2))))}
def field(m):
 prop=AllChem.MMFFGetMoleculeProperties(m,mmffVariant='MMFF94');return AllChem.MMFFGetMoleculeForceField(m,prop,nonBondedThresh=100)
scorepath=a.runtime/(a.score_prefix+'_scored.list');posespath=a.runtime/(a.score_prefix+'_scored.mol2')
assert scorepath.exists() and posespath.exists()
lines=[line.split() for line in scorepath.read_text().splitlines() if line.strip()]
header=lines[0];assert len(header)==12
scores=[{k:(v if i==0 else float(v)) for i,(k,v) in enumerate(zip(header,l))} for l in lines[1:]]
poses=mol2blocks(posespath.read_text());assert len(scores)==len(poses)
writer=Chem.SDWriter(str(a.output/'all-scored-poses.sdf'));final=Chem.SDWriter(str(a.output/'retained.sdf'));rows=[]
for i,(score,(name,atoms)) in enumerate(zip(scores,poses)):
 assert name==cid and set(atoms)==set(sourceatoms)
 assert all(math.isfinite(v) for v in score.values() if isinstance(v,float))
 m=Chem.Mol(base);conf=m.GetConformer()
 for idx,label in mapping.items():
  assert atoms[label]['element']==sourceatoms[label]['element'] and atoms[label]['label']==sourceatoms[label]['label'];conf.SetAtomPosition(idx,atoms[label]['xyz'])
 g=geometry(m);ff=field(m);bound=float(ff.CalcEnergy())
 free=Chem.Mol(m);f=field(free);status=int(f.Minimize(maxIts=1000,forceTol=1e-4,energyTol=1e-6));free_energy=float(f.CalcEnergy());strain=bound-free_energy
 reasons=[]
 if not g['fragment_match']:reasons.append('original_fragment_stereochemistry_or_graph_missing')
 else:
  if g['max_fragment_rmsd_A']>1.0:reasons.append('fragment_rmsd_over_1A')
  if g['min_receptor_heavy_distance_A']<1.5:reasons.append('protein_clash_below_1p5A')
 if score['deltaG']>a.max_delta_g:reasons.append('ifit_deltaG_over_cutoff')
 if status!=0:reasons.append('local_free_relaxation_not_converged')
 if a.max_local_strain is not None and strain>a.max_local_strain:reasons.append('local_strain_over_user_cutoff')
 row={'id':cid,'pose':i,'ifit':score,'geometry':g,'mmff_bound_pose_energy_kcal_mol':bound,'mmff_free_local_energy_kcal_mol':free_energy,'local_strain_estimate_kcal_mol':strain,'free_relax_status':status,'retained':not reasons,'rejection_reasons':reasons}
 m.SetProp('_Name',cid+'-pose-'+str(i));m.SetDoubleProp('ifit_deltaG',score['deltaG']);m.SetDoubleProp('local_strain_estimate_kcal_mol',strain);m.SetProp('retained',str(not reasons));writer.write(m)
 if not reasons:final.write(m)
 rows.append(row)
writer.close();final.close()
report={'candidate':cid,'poses_with_numeric_scores':len(rows),'retained_poses':sum(r['retained'] for r in rows),'rows':rows,'policy':{'max_ifit_deltaG':a.max_delta_g,'max_fragment_rmsd_A':1.0,'min_protein_heavy_distance_A':1.5,'max_local_strain_kcal_mol':a.max_local_strain,'local_strain':'MMFF94 internal bound-pose energy minus unconstrained local relaxation, not a global strain/experimental affinity','same_full_receptor_for_geometry':True,'threshold_scope':'Experimental complete-PROTAC workflow; -10 inherited from the small-molecule branch, not biologically calibrated for complete PROTACs'},'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [scorepath,posespath,a.charged_input,a.candidate_sdf,a.fragments,a.receptor]}}
(a.output/'postscore-report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report,indent=2),flush=True)
