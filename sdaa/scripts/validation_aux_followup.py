
from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
from pathlib import Path
import json,os,re,shutil,subprocess,sys,time
import validation_aux_tools as aux_tools

OUT=Path('/out');SOURCE=Path('/source')
def main():
 base=OUT/'auxiliary-charge-followup';base.mkdir()
 before=OUT/'auxiliary-tools/cyndi/conformers.mol2'
 block='@<TRIPOS>MOLECULE'+before.read_text().split('@<TRIPOS>MOLECULE')[1]
 (base/'first-conformer.mol2').write_text(block)
 aux_tools.execute([sys.executable,str(SOURCE/'sdaa/scripts/native_pipeline.py'),'prepare-ligand','--input',str(base/'first-conformer.mol2'),'--output',str(base/'charged')],base,'charge.log')
 grid=base/'ifit';shutil.copytree(OUT/'auxiliary-tools/ifit',grid)
 shutil.copy2(base/'charged/ligand.mol2',grid/'gen_mols.mol2')
 records={}
 for tool,pop,gen in [('iFitDock_eval',500,500),('iFitDock',2000,200)]:
  for original,target in [(tool+'-dock.in','dock.in'),(tool+'-NSGA2.param','NSGA2.param')]:shutil.copy2(grid/original,grid/target)
  params=(grid/'NSGA2.param').read_text()
  params=re.sub(r'(?m)^POP_SIZE\s+[^\n]+','POP_SIZE '+str(pop),params)
  params=re.sub(r'(?m)^GEN\s+[^\n]+','GEN '+str(gen),params)
  params=re.sub(r'(?m)^OUTPUT\s+[^\n]+','OUTPUT '+tool+'_charged',params)
  (grid/'NSGA2.param').write_text(params)
  shutil.copy2(grid/'NSGA2.param',grid/(tool+'-full-NSGA2.param'))
  rec=aux_tools.execute(['./'+tool,'-i','dock.in'],grid,tool+'-charged.log',legacy=True)
  log=(grid/(tool+'-charged.log')).read_text(errors='replace')
  assert rec['exitcode'] in [0,1]
  if tool=='iFitDock':assert 'Docking Finished, Thanks!' in log
  else:assert re.search(r'generated_data_size_ligand\s*=\s*\d+',log)
  rec.update(population=pop,generations=gen,score_cutoff_unchanged=True,outputs=[])
  for p in grid.glob(tool+'_charged*.mol2'):
   if p.stat().st_size:rec['outputs'].append({'file':p.name,'molecules':len(aux_tools.check_mol2(p))})
  records[tool]=rec
 (OUT/'auxiliary-charge-followup-report.json').write_text(json.dumps({'scope':'Original iFit ligand AM1-BCC preparation and original default per-ligand optimization budgets, same freshly generated native grids, first retained Cyndi conformer','records':records},indent=2))
 print(json.dumps(records,indent=2),flush=True)
if __name__=='__main__':main()
