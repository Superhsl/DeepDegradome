from pathlib import Path
import argparse,json,subprocess,os,shutil,time,ast,math,re,hashlib,sys
from rdkit import Chem
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--target',choices=['gpu1','loong'],required=True);p.add_argument('--eval-source',type=Path,required=True);p.add_argument('--extra-source',type=Path,required=True);p.add_argument('--candidates',type=Path,required=True);p.add_argument('--frozen',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--prepared-from',type=Path);p.add_argument('--population',type=int,default=500);p.add_argument('--generations',type=int,default=500);p.add_argument('--fixed-time-shim',type=Path);a=p.parse_args()
O=a.output;O.mkdir();W=O/'runtime';W.mkdir()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
records=[]
prepared_from=a.prepared_from
if prepared_from:
 assert sha(prepared_from.parent/'common-candidates/refined.sdf')==sha(a.candidates/'refined.sdf')

def run(cmd,cwd,name,timeout=1200,allowed=(0,),env=None):
 start=time.monotonic()
 with (cwd/(name+'.log')).open('wb') as f:r=subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout,env=env)
 rec={'command':cmd,'exitcode':r.returncode,'wall_seconds':time.monotonic()-start}
 save(cwd/(name+'-command.json'),rec);records.append(rec)
 print(json.dumps({'step':name,**rec}),flush=True)
 assert r.returncode in allowed,rec
 return rec
# Whitelist templates, definitions, and executables. Never copy stale grids or score caches.
names=['ifitdock_func.py','protein_template.py','ligand_template.py','Mapping_eval.py','mapping_nrg_grid_generator.pl','mapping_GB_grid_generator.pl','mapping_SA_grid_generator.pl','grid.in','box.in','INCHEM_GB','INCHEM_SA','vdw.defn','flex.defn','flex_drive.tbl','vdw_AMBER_parm99.defn','vdw.parms.amb','prot.table.ambcrg.pdb3H','screen.in','screen.para','iFitDock_eval','iFitDock_eval.x86-original','lattice','lattice.x86-original','split_grid','split_grid.x86-original','KSCORE.txt']
for n in names:
 src=a.eval_source/n
 if src.is_file():shutil.copy2(src,W/n)
for n in ['MMFF94.parm','MMFF94.txt','TAFF.txt','chem.defn','cavity.pdb']:
 for root in [a.eval_source,a.extra_source,Path('/source/DEVELOP/analysis'),Path('/source/ifitdock/ifit_eval')]:
  if (root/n).is_file():shutil.copy2(root/n,W/n);break
assert (W/'cavity.pdb').is_file(),'Upstream GB cavity resource missing'
# Empty upstream cavity.pdb means no explicit solvent-cavity points; not a score/grid placeholder.
if 'allow_non_integral_charges' not in (W/'grid.in').read_text():
 with (W/'grid.in').open('a') as f:f.write('\nallow_non_integral_charges yes\n')
for n in ['GB_grid.txt','SA_grid.txt']:assert not (W/n).exists()
box=json.loads((a.candidates/'grid-config.json').read_text());center=box['center']
# The legacy fixed 30A/20A boxes are replaced in this private copy by one frozen complete-PROTAC box.
perl=W/'mapping_nrg_grid_generator.pl';s=perl.read_text()
for old,key in [('30.0  30.0  30.0','vdw_size_A'),('20.0  20.0  20.0','gbsa_size_A')]:
 assert old in s;s=s.replace(old,'  '.join(str(v) for v in box[key]))
# Some prepared native copies omit the line terminator and concatenate the next parameter.
line='$grd_content[17] = "score_grid_prefix        ".$ARGV[0]."_".$k."\\n";'
s,count=re.subn(r'\$grd_content\[17\]\s*=\s*"score_grid_prefix[^;]*;',lambda m:line,s)
assert count==1
perl.write_text(s)
(W/'center.txt').write_text(' '.join(str(v) for v in center)+'\n')
shutil.copy2(a.frozen/'receptor.pdb',W/'receptor.pdb')
chimera='/chimera/bin/chimera' if a.target=='gpu1' else '/opt/deepdegradome/chimera/bin/chimera'
t=(W/'protein_template.py').read_text().replace('target','receptor');(W/'prepare_receptor.py').write_text(t)
run([chimera,'--nogui','--nostatus','--script',str(W/'prepare_receptor.py')],W,'prepare-receptor',1800)
assert all((W/('receptor'+ext)).is_file() for ext in ['.mol2','_noH.pdb','_gbsa.pdb'])
prepared=[]
for i,m in enumerate(Chem.SDMolSupplier(str(a.candidates/'accepted.sdf'),removeHs=False)):
 assert m is not None
 cid=m.GetProp('_Name');L=O/cid;L.mkdir()
 writer=Chem.SDWriter(str(L/'ligand.sdf'));writer.write(m);writer.close()
 if prepared_from:
  old=prepared_from/cid
  assert sha(old/'ligand.sdf')==sha(L/'ligand.sdf')
  assert json.loads((old/('charge-'+cid+'-command.json')).read_text())['exitcode']==0
  assert 'Error while processing' not in (old/('charge-'+cid+'.log')).read_text(errors='replace')
  shutil.copy2(old/'charged.mol2',L/'ligand.mol2')
 else:
  run(['babel','ligand.sdf','ligand.mol2'],L,'convert-'+cid,120)
  (L/'prepare_ligand.py').write_bytes((W/'ligand_template.py').read_bytes())
  run([chimera,'--nogui','--nostatus','--script',str(L/'prepare_ligand.py')],L,'charge-'+cid,1800)
  assert 'Error while processing' not in (L/('charge-'+cid+'.log')).read_text(errors='replace')
 t=(L/'ligand.mol2').read_text();lines=t.splitlines(True);j=lines.index('@<TRIPOS>MOLECULE\n');lines[j+1]=cid+'\n'
 t=''.join(lines);(L/'charged.mol2').write_text(t);prepared.append(t)
assert prepared
(W/'gen_mols.mol2').write_text(''.join(prepared))
# Reuse official Protein/modify_mol2 wrappers and native DOCK grid executables.
assert len(prepared)==1,'This experimental entry currently validates one complete PROTAC at a time'
# Make an independent SA box. Keep the full receptor and the original large GB/VDW grids.
input_lines=(W/'gen_mols.mol2').read_text().split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0].splitlines()
input_xyz=np.array([[float(v) for v in l.split()[2:5]] for l in input_lines if l.strip()])
sa_size=[max(v-20.4,math.ceil((2*float(np.max(np.abs(input_xyz[:,i]-center[i])))+4)/.8)*.8) for i,v in enumerate(box['vdw_size_A'])]
sa_in='N\nU\n'+' '.join(str(x) for x in center)+'\n'+' '.join(str(x) for x in sa_size)+'\nreceptor_grid_sa_box_1.pdb\n'
(W/'sa-box.in').write_text(sa_in)
showbox='showbox'
with (W/'sa-box.in').open('rb') as inp,(W/'sa-box.log').open('wb') as log:
 rc=subprocess.run([showbox],cwd=W,stdin=inp,stdout=log,stderr=subprocess.STDOUT).returncode
assert rc==0
pl=W/'mapping_SA_grid_generator.pl';pl.write_text(pl.read_text().replace('_grid_gbsa_box_','_grid_sa_box_'))
helper=O/'build_grid.py';helper.write_text("import sys,os\nsys.path.insert(0,"+repr(str(W))+")\nos.chdir("+repr(str(W))+")\nimport ifitdock_func as f\nf.modify_mol2('receptor.mol2')\nf.Protein('receptor.pdb','center.txt')\n")
run([sys.executable,str(helper)],W,'build-grid',2400)
products={}
for pattern in ['receptor_1.*','receptor_GB_1.*','receptor_SA_1.*']:
 for p in W.glob(pattern):
  if p.is_file():products[p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
assert (W/'receptor_1.nrg').is_file() and any(W.glob('receptor_GB_1.*')) and any(W.glob('receptor_SA_1.*')),products
sa_atoms=int((W/'receptor_SA_1.bmp').read_text().splitlines()[2].split()[2])
ligand_atoms=len(input_xyz)
assert sa_atoms+ligand_atoms<=2000,('Old iFit SA workspace capacity exceeded',sa_atoms,ligand_atoms)
save(O/'grid-products.json',{'products':products,'box':box,'receptor_sha256':sha(a.frozen/'receptor.pdb'),'stale_grid_or_score_cache_copied':False,'sa_size_A':sa_size,'sa_receptor_atoms':sa_atoms,'combined_sa_atoms':sa_atoms+ligand_atoms,'scope':'Full receptor; smaller SA grid avoids legacy fixed workspace. Full-size versus smaller-SA energy equivalence is not asserted.'})
# Only load the two upstream parameter-list assignments, never execute its hard-coded launcher.
tree=ast.parse((W/'Mapping_eval.py').read_text());assign=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ['dock_content','doc_content'] for t in n.targets)]
ns={};exec(compile(ast.Module(body=assign,type_ignores=[]),'upstream-parameters','exec'),ns)
dock=ns['dock_content'];params=ns['doc_content']
def update(lines,values):
 return [str(l.split()[0])+' '+str(values[l.split()[0]])+'\n' if l.strip() and not l.lstrip().startswith('#') and l.split()[0] in values else l for l in lines]
dock=update(dock,{'ligand_name':'gen_mols.mol2','grid_score_grid_prefix':'receptor_1','gbsa_zou_gb_grid_prefix':'receptor_GB_1','gbsa_zou_sa_grid_prefix':'receptor_SA_1','gbsa_zou_vdw_grid_prefix':'receptor_GB_1'})
atomlines=(W/'gen_mols.mol2').read_text().split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>')[0].splitlines()
xyz=np.array([[float(v) for v in l.split()[2:5]] for l in atomlines if l.strip()])
site=xyz.mean(axis=0).tolist()
assert min(min(v[i]-(center[i]-sa_size[i]/2),(center[i]+sa_size[i]/2)-v[i]) for v in xyz for i in range(3))>=1.0,'Candidate extends beyond safe SA grid domain'
params=update(params,{'OUTPUT':'protac','RECEPTOR':'receptor_noH.pdb','ACTIVE_SITE':' '.join(str(v) for v in site),'INDUCEFIT':0,'POP_SIZE':a.population,'GEN':a.generations,'NUM_CONF_PER_LIG':2,'SCORE_CUTOFF':1000000})
params+=['\nRandom_Seed 0.789\n']
(W/'dock.in').write_text(''.join(dock));(W/'NSGA2.param').write_text(''.join(params))
exe=W/('iFitDock_eval' if a.target=='gpu1' else 'iFitDock_eval.x86-original')
cmd=[str(exe),'-i','dock.in'] if a.target=='gpu1' else ['/validation/lat64','-L','/validation/runtime/sysroot',str(exe),'-i','dock.in']
exe_env=None
if a.fixed_time_shim:
 assert a.fixed_time_shim.is_file()
 if a.target=='gpu1':exe_env=dict(os.environ,LD_PRELOAD=str(a.fixed_time_shim))
 else:cmd=cmd[:1]+['-E','LD_PRELOAD='+str(a.fixed_time_shim)]+cmd[1:]
run(cmd,W,'ifit-evaluate',3600,allowed=(0,1),env=exe_env)
path=W/'protac_scored.list';assert path.is_file() and path.stat().st_size
lines=[l.split() for l in path.read_text().splitlines() if l.strip()];header=lines[0];scores=[]
for fields in lines[1:]:
 assert len(fields)==len(header),(header,fields)
 row={k:(v if i==0 else float(v)) for i,(k,v) in enumerate(zip(header,fields))}
 assert all(math.isfinite(v) for v in row.values() if isinstance(v,float))
 scores.append(row)
engine_no_pose=not scores
if engine_no_pose:
 log=(W/'ifit-evaluate.log').read_text(errors='replace')
 assert 'generated_data_size_ligand = 0' in log and 'None candidate was found' in log,'Header-only output without explicit normal no-pose termination'
 assert (W/'protac_scored.mol2').exists() and (W/'protac_scored.mol2').stat().st_size==0
meta={'target':a.target,'engine_no_pose':engine_no_pose,'numeric_score_rows':len(scores),'preparation_reused_from':str(prepared_from) if prepared_from else None,'scores':scores,'steps':records,'ifit_binary_sha256':sha(exe),'fixed_receptor_sha256':sha(a.frozen/'receptor.pdb'),
'grid_config':box,'policy':'Experimental fixed-receptor PROTAC: RUN_MODE15; IND0; explicit seed; two scored poses; uncensored internal cutoff 1e6, final external cutoff -10. Grid-domain and post-docking fragment checks are required. No biological calibration or full-grid equivalence claim',
'complete_protac_input':True,'diagnostic_same_input_sdf':True}
save(O/'ifit-report.json',meta)
print(json.dumps({'complete':True,'scores':scores}),flush=True)
