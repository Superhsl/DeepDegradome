from pathlib import Path
import argparse,json,math
import numpy as np
from scipy.spatial import cKDTree
p=argparse.ArgumentParser();p.add_argument('--full',type=Path,required=True);p.add_argument('--used',type=Path,required=True);p.add_argument('--mol2',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
def load(prefix):
 lines=Path(str(prefix)+'.bmp').read_text().splitlines();f=lines[1].split();origin=np.array([float(x) for x in f[1:4]]);n=int(lines[2].split()[2]);nt=int(lines[2].split()[-1])
 lines=Path(str(prefix)+'.sas').read_text().splitlines()
 atoms=np.array([[float(x) for x in l.split()] for l in lines[:n]])
 types=np.array([[int(x) for x in l.split()] for l in lines[n:n+nt]])
 toks=Path(str(prefix)+'.sasmark').read_text().split();head=[float(x) for x in toks[:6]];nsph=types[:,0];total=int(nsph.sum())
 sph=np.array([float(x) for x in toks[6:6+3*total]],dtype=np.float32)
 rest=np.array([int(x) for x in toks[6+3*total:]],dtype=np.int8);marks=[];offset=0
 for row in atoms:
  count=int(nsph[int(row[4])-1]);marks.append(rest[offset:offset+count]);offset+=count
 assert offset==len(rest)
 return {'n':n,'origin':origin,'xyz':atoms[:,:3]+origin,'props':atoms[:,3:],'types':types,'sphere':sph,'marks':marks,'r2cut':head[5],'probe':head[3],'spacing':head[4]}
F=load(a.full);U=load(a.used);dist,idx=cKDTree(F['xyz']).query(U['xyz']);assert np.max(dist)<.005
assert len(set(idx))==len(idx)
mapped={int(j):i for i,j in enumerate(idx)}
sphere_equal=np.array_equal(F['sphere'],U['sphere']) and np.array_equal(F['types'],U['types'])
different_marks=[j for j,i in mapped.items() if not np.array_equal(F['marks'][j],U['marks'][i])]
poses=[]
for path in a.mol2:
 for i,part in enumerate(path.read_text().split('@<TRIPOS>MOLECULE\n')[1:]):
  txt=part.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0]
  xyz=np.array([[float(x) for x in l.split()[2:5]] for l in txt.splitlines() if l.strip()])
  distance=cKDTree(xyz).query(F['xyz'])[0]
  near=np.nonzero(distance**2<F['r2cut'])[0].tolist()
  missing=[j for j in near if j not in mapped];changed=[j for j in near if j in different_marks]
  poses.append({'file':str(path),'pose':i,'ligand_atoms_conservative_all_H_included':len(xyz),'full_sa_potential_neighbor_atoms':len(near),'omitted_potential_neighbors':len(missing),'changed_precomputed_surface_masks_of_potential_neighbors':len(changed),'nearest_omitted_atom_distance_A':min((float(distance[j]) for j in range(F['n']) if j not in mapped),default=None),'coverage_and_surface_masks_supported':not missing and not changed and sphere_equal})
report={'full_sa_atoms':F['n'],'used_sa_atoms':U['n'],'cutoff_A':math.sqrt(F['r2cut']),'matched_world_coordinate_max_difference_A':float(np.max(dist)),'same_sphere_sampling_and_atom_types':sphere_equal,'all_retained_atom_surface_masks_changed':len(different_marks),'poses':poses,'scope':'Conservative neighbor/mask coverage diagnostic using the documented DOCK6 SA representation. Does not prove binary bitwise energy equality or search-trajectory equivalence.'}
a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
