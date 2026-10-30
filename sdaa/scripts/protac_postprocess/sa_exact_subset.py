"""Prune only SA work records that cannot be neighbors of any supplied scored pose."""
from pathlib import Path
import argparse,json,hashlib,math
import numpy as np
from scipy.spatial import cKDTree
p=argparse.ArgumentParser();p.add_argument('--full',type=Path,required=True);p.add_argument('--mol2',type=Path,nargs='+',required=True);p.add_argument('--output-prefix',type=Path,required=True);p.add_argument('--max-ligand-atoms',type=int,required=True);a=p.parse_args()
bmp=Path(str(a.full)+'.bmp');sas=Path(str(a.full)+'.sas');mark=Path(str(a.full)+'.sasmark')
blines=bmp.read_text().splitlines(True);f=blines[1].split();origin=np.array([float(x) for x in f[1:4]]);meta=blines[2].split();n=int(meta[2]);nt=int(meta[-1])
slines=sas.read_text().splitlines(True);atoms=np.array([[float(x) for x in l.split()] for l in slines[:n]]);xyz=atoms[:,:3]+origin
types=np.array([[int(x) for x in l.split()] for l in slines[n:n+nt]])
tokens=mark.read_text().split();r2cut=float(tokens[5]);cut=math.sqrt(r2cut);pre=6+3*int(types[:,0].sum());offset=pre;marks=[]
for atom in atoms:
 count=int(types[int(atom[4])-1,0]);marks.append(tokens[offset:offset+count]);offset+=count
assert offset==len(tokens)
keep=np.zeros(n,dtype=bool);poses=[]
for path in a.mol2:
 for i,part in enumerate(path.read_text().split('@<TRIPOS>MOLECULE\n')[1:]):
  txt=part.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0]
  positions=np.array([[float(x) for x in l.split()[2:5]] for l in txt.splitlines() if l.strip()])
  near=cKDTree(positions).query(xyz)[0] <= cut+.005
  keep |= near;poses.append({'file':str(path),'pose':i,'potential_neighbor_records_with_0p005A_guard':int(near.sum())})
indices=np.nonzero(keep)[0].tolist()
assert len(indices)+a.max_ligand_atoms<=2000,('Exact per-pose SA support still exceeds legacy capacity',len(indices),a.max_ligand_atoms)
prefix=a.output_prefix;assert not Path(str(prefix)+'.sas').exists()
meta[2]=str(len(indices));blines[2]=' '.join(meta)+'\n';Path(str(prefix)+'.bmp').write_text(''.join(blines))
Path(str(prefix)+'.sas').write_text(''.join(slines[i] for i in indices)+''.join(slines[n:]))
out=[' '.join(tokens[:3])+'\n',' '.join(tokens[3:6])+'\n']
for i in range(6,pre,3):out.append(' '.join(tokens[i:i+3])+'\n')
for i in indices:out.append(' '.join(marks[i])+'\n')
Path(str(prefix)+'.sasmark').write_text(''.join(out))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
report={'full_sa_records':n,'kept_sa_records':len(indices),'max_ligand_atoms':a.max_ligand_atoms,'combined_workspace_records':len(indices)+a.max_ligand_atoms,'cutoff_A':cut,'floating_boundary_guard_A':.005,'kept_full_record_indices':indices,'poses':poses,'full_files_sha256':{str(q):sha(q) for q in [bmp,sas,mark]},'semantics':'Only SA neighbor work records outside the 8A cutoff of every supplied pose are omitted; preserve original grid origin, atom coordinates/radii/types, sphere sampling, all retained atom global SAS masks and full GB/VDW. For these poses, removed records have no SA neighbor contributions in the documented GB_Pairwise routine. Must recheck every actual output pose after rerun; not a general search-trajectory equivalence claim.'}
Path(str(prefix)+'-subset.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='kept_full_record_indices'}),flush=True)
