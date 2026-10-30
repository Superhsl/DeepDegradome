"""Additional ligand-tool branch using freshly prepared WDR5 / Compound 4."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
from pathlib import Path
import ast,hashlib,json,math,os,re,shutil,subprocess,sys,time
import numpy as np
from rdkit import Chem

OUT=Path('/out');WORK=Path('/validation');SOURCE=Path('/source')
def execute(command,cwd,log,legacy=False):
 start=time.perf_counter()
 with (cwd/log).open('w') as f:r=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 record={'command':list(map(str,command)),'exitcode':r.returncode,'seconds':time.perf_counter()-start}
 (cwd/(log+'.json')).write_text(json.dumps(record,indent=2))
 assert r.returncode==0 or legacy,record
 return record
def check_mol2(path):
 blocks=['@<TRIPOS>MOLECULE'+b for b in path.read_text().split('@<TRIPOS>MOLECULE')[1:]]
 assert blocks,path
 molecules=[]
 for block in blocks:
  mol=Chem.MolFromMol2Block(block,sanitize=False,removeHs=False);assert mol is not None
  assert np.isfinite(mol.GetConformer().GetPositions()).all()
  rows=block.split('@<TRIPOS>ATOM',1)[1].split('@<TRIPOS>',1)[0].strip().splitlines()
  assert all(math.isfinite(float(row.split()[8])) for row in rows)
  molecules.append(mol)
 return molecules
def main():
 base=OUT/'auxiliary-tools';base.mkdir();records={}
 cyndi=base/'cyndi';cyndi.mkdir()
 for name in ['Cyndi.param','MMFF94.parm','MMFF94.txt','TAFF.txt']:shutil.copy2(SOURCE/'DEVELOP/analysis'/name,cyndi/name)
 cfg=(cyndi/'Cyndi.param').read_text()
 for key,value in {'MOGA_Max_Conformers':'10','MOGA_Max_Generation':'20','MOGA_Population_Size':'100','MOGA_Max_Opt_Iteration':'30'}.items():cfg=re.sub(r'(?m)^'+re.escape(key)+r'\s+[^\n]+',key+' '+value,cfg)
 (cyndi/'Cyndi.param').write_text(cfg)
 execute(['babel',str(OUT/'case/compound4_H.sdf'),'ligand.mol2','-h'],cyndi,'convert.log')
 records['Cyndi']=execute([str(WORK/'runtime/tools/cyndi/Cyndi'),'-i','ligand.mol2','-o','conformers.mol2'],cyndi,'run.log')
 molecules=check_mol2(cyndi/'conformers.mol2');assert len(molecules)>1
 original=check_mol2(cyndi/'ligand.mol2')[0]
 assert all(m.GetNumAtoms()==original.GetNumAtoms() and m.GetNumBonds()==original.GetNumBonds() for m in molecules)
 records['Cyndi'].update(conformers=len(molecules),atoms=original.GetNumAtoms(),diagnostic_rng_preload=False)
 grid=base/'ifit';shutil.copytree(SOURCE/'ifitdock/ifit_eval',grid)
 # The isolated bundle supplies the unchanged binaries and force-field resources.
 for p in (WORK/'runtime/tools/ifit_eval').iterdir():
  if p.is_file() and (p.name.endswith('.x86-original') or p.name in ['iFitDock_eval','lattice','split_grid','MMFF94.parm','MMFF94.txt','TAFF.txt','KSCORE.txt','Kscore.txt']):shutil.copy2(p,grid/p.name)
 for p in (WORK/'runtime/tools/ifit_dock').iterdir():
  if p.is_file() and p.name in ['iFitDock','iFitDock.x86-original']:shutil.copy2(p,grid/p.name)
 for src,dst in [('target.pdb','WDR5.pdb'),('target_noH.pdb','WDR5_noH.pdb'),('target.mol2','WDR5.mol2'),('target_gbsa.pdb','WDR5_gbsa.pdb')]:shutil.copy2(OUT/'preparation/WDR5'/src,grid/dst)
 shutil.copy2(cyndi/'conformers.mol2',grid/'gen_mols.mol2')
 ligand=original.GetConformer().GetPositions();center=ligand.mean(axis=0)
 (grid/'center.txt').write_text(' '.join(map(str,center))+'\n')
 os.chdir(grid)
 sys.path.insert(0,str(grid));sys.path.insert(0,str(SOURCE/'DEVELOP'))
 import ifitdock_func
 ifitdock_func.modify_mol2('WDR5.mol2')
 start=time.perf_counter();ifitdock_func.Protein('WDR5.pdb','center.txt')
 products={}
 for name in ['WDR5_1.nrg','WDR5_1.bmp','WDR5_GB_1.vdw','WDR5_GB_1.sol','WDR5_GB_1.rec','WDR5_GB_1.bmp','WDR5_SA_1.sas','WDR5_SA_1.sasmark','WDR5_SA_1.bmp']:
  p=grid/name;assert p.is_file() and p.stat().st_size>0,name
  products[name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 records['native_grid']={'seconds':time.perf_counter()-start,'products':products,'lattice_points':(grid/'outlattice_center.pdb').stat().st_size,'fresh_native_Chimera':True}
 def constants(path):
  out={}
  for node in ast.parse(path.read_text()).body:
   if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['dock_content','doc_content']:out[node.targets[0].id]=ast.literal_eval(node.value)
  return out
 for tool,script,mode in [('iFitDock_eval',SOURCE/'ifitdock/ifit_eval/Mapping_eval.py',15),('iFitDock',SOURCE/'ifitdock/ifit_dock/Mapping.py',0)]:
  c=constants(script);dock=''.join(c['dock_content']);params=''.join(c['doc_content'])
  def setting(text,key,value):return re.sub(r'(?m)^'+re.escape(key)+r'\s+[^\n]+',key+' '+str(value),text)
  for key,val in {'ligand_name':'gen_mols.mol2','grid_score_grid_prefix':'WDR5_1','gbsa_zou_gb_grid_prefix':'WDR5_GB_1','gbsa_zou_sa_grid_prefix':'WDR5_SA_1','gbsa_zou_vdw_grid_prefix':'WDR5_GB_1'}.items():dock=setting(dock,key,val)
  for key,val in {'RUN_MODE':mode,'POP_SIZE':40,'GEN':10,'ACTIVE_SITE':' '.join(map(str,center)),'OUTPUT':tool+'_result','RECEPTOR':'WDR5_noH.pdb'}.items():params=setting(params,key,val)
  (grid/'dock.in').write_text(dock);(grid/'NSGA2.param').write_text(params)
  shutil.copy2(grid/'dock.in',grid/(tool+'-dock.in'));shutil.copy2(grid/'NSGA2.param',grid/(tool+'-NSGA2.param'))
  rec=execute(['./'+tool,'-i','dock.in'],grid,tool+'.log',legacy=True)
  text=(grid/(tool+'.log')).read_text(errors='replace')
  assert rec['exitcode'] in [0,1],rec
  assert not any(s in text for s in ['Segmentation fault','Fail to open','cannot open','Error opening']),text[-2000:]
  if mode==0:assert 'Docking Finished, Thanks!' in text
  else:assert re.search(r'generated_data_size_ligand\s*=\s*\d+',text)
  outputs=[]
  for p in grid.glob(tool+'_result*.mol2'):
   if p.stat().st_size:
    ms=check_mol2(p);outputs.append({'file':p.name,'molecules':len(ms)})
  rec.update(outputs=outputs,completion_verified=True,input_conformers=len(molecules),score_cutoff_preserved=True,diagnostic_rng_preload=False)
  records[tool]=rec
 (OUT/'auxiliary-report.json').write_text(json.dumps({'scope':'Additional WDR5/Compound4 ligand-tool branch, not a substitute for the generated-PROTAC pipeline','records':records,'bounded_sampling':True},indent=2))
 print(json.dumps(records,indent=2),flush=True)
if __name__=='__main__':main()
