
from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
from pathlib import Path
import json,os,runpy,sys,time
import numpy as np
import torch

OUT=Path('/out');CASE=OUT/'case'
def main():
 torch.set_num_threads(1);torch.manual_seed(0)
 sys.path.insert(0,str(CASE));os.chdir(CASE)
 original=json.loads((OUT/'evaluation-report.json').read_text())
 module=runpy.run_path(str(CASE/'deepprotacs.py'),run_name='current_candidate_cpu_reference')
 records=[];maximum=0.0;changed=0
 for candidate in original['records']:
  outputs=[]
  def observe(model,args,value):
   if model.__class__.__name__=='ProtacModel':
    assert next(model.parameters()).device.type=='cpu' and value.device.type=='cpu'
    outputs.append(value.detach().cpu().numpy().copy())
  hook=torch.nn.modules.module.register_module_forward_hook(observe)
  start=time.perf_counter()
  try:vote=module['inference'](str(CASE/candidate['candidate']),device_name='cpu',prepared_mol2=True)
  finally:hook.remove()
  assert len(outputs)==10
  gold=np.asarray(candidate['logits']);actual=np.asarray(outputs);assert actual.shape==gold.shape and np.isfinite(actual).all()
  error=float(np.max(np.abs(actual-gold)));maximum=max(maximum,error)
  changed+=int(vote!=candidate['positive_vote_percent'])
  records.append({'candidate':candidate['candidate'],'maximum_logit_absolute_error':error,'cpu_vote_percent':vote,'sdaa_vote_percent':candidate['positive_vote_percent'],'seconds':time.perf_counter()-start,'cpu_logits':actual.tolist()})
 report={'candidates':len(records),'ensemble_size':10,'maximum_logit_absolute_error':maximum,'predeclared_absolute_tolerance':1e-5,'vote_changes':changed,'records':records,'passed':maximum<=1e-5 and changed==0,'scope':'Same newly generated candidates and unchanged processed graph inputs; all ten original evaluator weights on Loong CPU versus SDAA. No biological accuracy claim.'}
 (OUT/'classification-parity.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2),flush=True)
 assert report['passed']
if __name__=='__main__':main()
