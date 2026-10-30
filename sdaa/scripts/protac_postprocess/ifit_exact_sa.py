from pathlib import Path
import argparse,subprocess,json,os,shutil,time,hashlib
p=argparse.ArgumentParser();p.add_argument('--target',required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--full-sa-prefix',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--score-prefix',default='probe');a=p.parse_args()
a.output.mkdir();w=a.output/'runtime';w.mkdir()
names=['gen_mols.mol2','receptor.pdb','receptor.mol2','receptor_noH.pdb','receptor_gbsa.pdb','vdw.defn','flex.defn','flex_drive.tbl','screen.in','screen.para','MMFF94.txt','MMFF94.parm','TAFF.txt','KSCORE.txt','Kscore.txt','dock.in','NSGA2.param','iFitDock_eval','iFitDock_eval.x86-original']
names += [p.name for p in a.source.glob('receptor_1.*')]+[p.name for p in a.source.glob('receptor_GB_1.*')]
for n in names:
 if (a.source/n).is_file():shutil.copy2(a.source/n,w/n)
# Seed, search budget and input molecule remain exactly the previous run.
positions=(a.source/(a.score_prefix+'_scored.mol2')).read_text().split('@<TRIPOS>MOLECULE\n')[1:];assert positions
atoms=max(len([l for l in p.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0].splitlines() if l.strip()]) for p in positions)
cmd=[os.sys.executable,str(Path(__file__).resolve().parent/'sa_exact_subset.py'),'--full',str(a.full_sa_prefix),'--mol2',str(a.source/'gen_mols.mol2'),str(a.source/(a.score_prefix+'_scored.mol2')),'--output-prefix',str(w/'receptor_SA_1'),'--max-ligand-atoms',str(atoms)]
r=subprocess.run(cmd,capture_output=True,text=True);(a.output/'subset.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
cmd=[str(w/'iFitDock_eval'),'-i','dock.in'] if a.target=='gpu1' else ['/validation/lat64','-E','LD_PRELOAD=/work/parameters/libfixedtime.so','-L','/validation/runtime/sysroot',str(w/'iFitDock_eval.x86-original'),'-i','dock.in']
shim=Path('/inputs/libfixedtime.so') if Path('/inputs/libfixedtime.so').exists() else Path('/work/parameters/libfixedtime.so')
if a.target!='gpu1':cmd[2]='LD_PRELOAD='+str(shim)
env=dict(os.environ,LD_PRELOAD=str(shim)) if a.target=='gpu1' else None;t=time.monotonic()
with (w/'driver.log').open('wb') as log:r=subprocess.run(cmd,cwd=w,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
rec={'command':cmd,'exitcode':r.returncode,'seconds':time.monotonic()-t}
(a.output/'core-status.json').write_text(json.dumps(rec,indent=2)+'\n');print(json.dumps(rec),flush=True)
assert r.returncode in (0,1)
scores=(w/(a.score_prefix+'_scored.list')).read_text();assert len(scores.splitlines())>1
(a.output/'scores.json').write_text(json.dumps({'scores':scores},indent=2)+'\n')
# Verify support after the actual rerun, not just the initial approximation.
cmd=[os.sys.executable,str(Path(__file__).resolve().parent/'sa_coverage.py'),'--full',str(a.full_sa_prefix),'--used',str(w/'receptor_SA_1'),'--mol2',str(w/(a.score_prefix+'_scored.mol2')),'--output',str(a.output/'coverage.json')]
r=subprocess.run(cmd,capture_output=True,text=True);(a.output/'coverage.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
coverage=json.loads((a.output/'coverage.json').read_text());assert all(p['coverage_and_surface_masks_supported'] for p in coverage['poses']),'Output left exact SA support; expand union and retry'
def atom_fingerprint(path):
 blocks=[]
 for part in path.read_text().split('@<TRIPOS>MOLECULE\n')[1:]:
  body=part.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0]
  blocks.append([line.split()[:6] for line in body.splitlines() if line.strip()])
 return blocks
same=atom_fingerprint(a.source/(a.score_prefix+'_scored.mol2'))==atom_fingerprint(w/(a.score_prefix+'_scored.mol2'))
done={'valid_scoring':True,'output_pose_coordinates_identical_at_file_precision_to_first_pass':same,'full_SA_neighbor_and_mask_coverage_verified':True,'score_list':scores,'scope':'Exact SA neighbor support for actual reported poses; full receptor/GB/VDW unchanged; does not prove every hidden search state equivalent'}
(a.output/'completion.json').write_text(json.dumps(done,indent=2)+'\n');print(json.dumps(done),flush=True)
