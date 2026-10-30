"""Fresh DEVELOP sampling on frozen, matched fixed-complex features."""
from pathlib import Path
import json,os,sys,time,hashlib,shutil,runpy
import numpy as np
target=os.environ['DD_COMPARE_TARGET']
np.random.seed(0)
if target=='gpu1':
 assert (Path(os.environ['BABEL_DATADIR'])/'superatom.txt').is_file(), 'Pinned Open Babel data directory missing'
 from pymol import cmd
 from rdkit import Chem
 import tensorflow as tf,molgrid
 molgrid.set_gpu_enabled(False)
else:
 import torch,torch_sdaa
 torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
sys.path.insert(0,'/harness')
import native_base as b
f=b.ns()
import brick_linking
original=brick_linking.DenseGGNNChemModel
records=[]
class Observed(original):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  if target=='gpu1':
   assert len(self.graph.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES))==123
   assert any(d.device_type=='GPU' for d in self.sess.list_devices())
  else:
   assert len(self.sess.model.weights)==123
   assert all(v.device.type=='sdaa' for v in self.sess.model.weights.values())
 def train(self,*args,**kwargs):
  start=time.perf_counter();result=super().train(*args,**kwargs)
  if target=='loong':torch.sdaa.synchronize()
  records.append({'seconds':time.perf_counter()-start,'device':'cuda' if target=='gpu1' else 'sdaa','weight_arrays':123})
  return result
brick_linking.DenseGGNNChemModel=Observed
out=Path('/out');os.chdir(out)
seed=Path('/fixed')
for name in ['molecules_pd.10_docking_0002_out.json','pd.10_docking_0002_frag.sdf','pd.10_docking_0002_linker_pharma.sdf','pd.10_docking_0002.types']:
 shutil.copy2(seed/name,out/name)
weight=Path('/source/DEVELOP/models/linker_design/pretrained_DEVELOP_model.pickle')
os.symlink(str(weight),str(out/'pretrained_DEVELOP_model.pickle'))
(out/'generated_smi_1').mkdir()
brick_linking.linking_bricks('molecules_pd.10_docking_0002_out.json','pd.10_docking_0002.types','pd.10_docking_0002','7','11','1')
path=out/'generated_smi_1/pd.10_docking_0002_generated_smiles.smi'
from rdkit import Chem
rows=[x.split()[-1] for x in path.read_text().splitlines() if x.strip()]
mols=[Chem.MolFromSmiles(s) for s in rows]
assert records and len(rows)>0 and all(m is not None and len(Chem.GetMolFrags(m))==1 for m in mols)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(out/'generation-report.json').write_text(json.dumps({'fresh_neural_generation_executed':True,'target':target,'model_records':records,'generated':len(rows),'parseable_single_connected':len(rows),'unique':len({Chem.MolToSmiles(m) for m in mols}),'weights_sha256':sha(weight),'fixed_input_sha256':{p.name:sha(p) for p in seed.iterdir() if p.is_file()},'min_atoms':7,'max_atoms':11,'samples_per_length':50,'scope':'Fresh neural generation from frozen features for the fixed WDR5-CRBN complex; independent platform sampling streams'},indent=2)+'\n')
