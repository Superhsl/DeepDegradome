"""Portable FP32 DeepPROTACs forward benchmark: CPU, CUDA, or torch_sdaa.

Pure-model timing uses preloaded weights and device-resident frozen features.
All ten checkpoints and all cases are exercised with batch size one per repeat.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np
import torch
import torch_geometric
from torch_geometric.data import Batch,Data

p=argparse.ArgumentParser()
p.add_argument('--workload',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--device',choices=['cpu','cuda','sdaa'],required=True)
p.add_argument('--warmup',type=int,default=1)
p.add_argument('--repeats',type=int,default=5)
p.add_argument('--profile-once',action='store_true')
p.add_argument('--model-source',type=Path,help='Explicit migrated model.py; retains official weights and frozen inputs')
a=p.parse_args()
assert a.warmup>=1 and a.repeats>=3
a.output.mkdir(parents=True,exist_ok=False)
torch_sdaa=None
if a.device=='sdaa':import torch_sdaa
device=torch.device(a.device if a.device=='cpu' else a.device+':0')
accelerator=getattr(torch,a.device,None) if a.device!='cpu' else None
if accelerator is not None:assert accelerator.is_available()
def sync():
 if accelerator is not None:accelerator.synchronize()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
manifest=json.loads((a.workload/'manifest.json').read_text())
assert sha(a.workload/'source/model.py')==manifest['model_source_sha256']
assert sha(a.workload/'official-cuda-reference.npz')==manifest['reference_sha256']
for name,expected in manifest['weight_sha256'].items():assert sha(a.workload/'weights'/name)==expected,name
torch.manual_seed(0);np.random.seed(0)
torch.set_num_threads(1);torch.set_num_interop_threads(1)
torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
torch.backends.cudnn.benchmark=False
torch.set_float32_matmul_precision('highest')
source=a.model_source or a.workload/'source/model.py'
assert source.is_file(),str(source)
actual_model_sha256=sha(source)
spec=importlib.util.spec_from_file_location('official_deepprotacs_model',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
start=time.perf_counter()
models=[]
for i in range(1,11):
 model=module.ProtacModel(module.GraphConv(10),module.GraphConv(5),module.GraphConv(10),module.GraphConv(5),module.SmilesNet())
 model.load_state_dict(torch.load(a.workload/'weights'/('model_'+str(i)+'.pth'),map_location='cpu',weights_only=False),strict=True)
 model.eval();models.append(model)
model_load_seconds=time.perf_counter()-start
start=time.perf_counter()
features=[]
for item in manifest['items']:
 path=a.workload/item['features'];assert sha(path)==item['features_sha256']
 with np.load(path,allow_pickle=False) as arrays:
  graphs=[]
  for name in ['ligase_ligand','ligase_pocket','target_ligand','target_pocket']:
   fields={field:torch.from_numpy(arrays[name+'__'+field].copy()) for field in ['x','edge_index','edge_attr']}
   graphs.append(Batch.from_data_list([Data(**fields)]))
  smiles=torch.from_numpy(arrays['smiles'].copy())
 features.append(tuple(graphs)+ (smiles,[int(smiles.shape[1])]))
feature_load_seconds=time.perf_counter()-start
sync();start=time.perf_counter()
models=[model.to(device) for model in models]
features=[tuple(x.to(device) for x in item[:5])+(item[5],) for item in features]
sync();device_transfer_seconds=time.perf_counter()-start
assert all(str(next(m.parameters()).device)==str(device) for m in models)
@torch.inference_mode()
def compute_all():
 return torch.stack([torch.cat([m(*item) for m in models],dim=0) for item in features],dim=0)
for _ in range(a.warmup):result=compute_all();sync()
if a.device=='cuda':torch.cuda.reset_peak_memory_stats()
times=[];outputs=[]
for repeat in range(a.repeats):
 sync();start=time.perf_counter();result=compute_all();sync()
 times.append(time.perf_counter()-start)
 assert str(result.device)==str(device)
 outputs.append(result.detach().cpu().numpy())
 print(json.dumps({'repeat':repeat,'pure_model_sweep_seconds':times[-1]}),flush=True)
peak_memory=int(torch.cuda.max_memory_allocated()) if a.device=='cuda' else None
out=np.asarray(outputs,dtype=np.float32)
reference=np.load(a.workload/'official-cuda-reference.npz',allow_pickle=False)
assert out.shape==(a.repeats,len(features),10,2),out.shape
assert np.isfinite(out).all()
error=np.abs(out-reference['logits'][None,...])
maximum=float(error.max())
classes=out.argmax(axis=-1)
class_equal=bool(np.all(classes==reference['predictions'][None,...]))
vote_equal=bool(np.all(classes.sum(axis=-1)*10==reference['positive_vote_percent'][None,...]))
passed=maximum<=manifest['predeclared_acceptance']['maximum_absolute_logit_error'] and class_equal and vote_equal
np.savez_compressed(a.output/'raw-outputs.npz',logits=out,predictions=classes,positive_vote_percent=classes.sum(axis=-1)*10)
profile_events=None
if a.profile_once and a.device=='cuda':
 with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA]) as profiler:
  with torch.inference_mode():profile_result=models[0](*features[0]);sync()
 profile_events=sum('CUDA' in str(x.device_type) for x in profiler.events())
 assert profile_events>0
 profiler.export_chrome_trace(str(a.output/'untimed-first-candidate-trace.json'))
median=statistics.median(times)
summary={'status':'passed' if passed else 'failed','device':str(device),'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'workload_manifest_sha256':sha(a.workload/'manifest.json'),'command':sys.argv,'architecture':platform.machine(),
 'actual_model_source_sha256':actual_model_sha256,'official_model_source_sha256':manifest['model_source_sha256'],
 'explicit_model_source_override':str(a.model_source) if a.model_source else None,
 'python':platform.python_version(),'torch':torch.__version__,'torch_geometric':torch_geometric.__version__,
 'torch_sdaa':getattr(torch_sdaa,'__version__',None),'cuda_runtime':torch.version.cuda,
 'device_name':accelerator.get_device_name(0) if accelerator is not None and hasattr(accelerator,'get_device_name') else platform.processor(),
 'precision':'FP32; TF32 disabled','batch_size':1,'torch_threads':torch.get_num_threads(),
 'candidate_count':len(features),'checkpoint_count':10,'inferences_per_sweep':len(features)*10,
 'load_checkpoint_models_cpu_seconds':model_load_seconds,'load_and_construct_features_cpu_seconds':feature_load_seconds,
 'transfer_models_and_features_to_device_seconds':device_transfer_seconds,
 'warmup_complete_sweeps':a.warmup,'timed_complete_sweeps':a.repeats,'raw_sweep_seconds':times,
 'median_sweep_seconds':median,'minimum_sweep_seconds':min(times),'maximum_sweep_seconds':max(times),
 'iqr_sweep_seconds':float(np.percentile(times,75)-np.percentile(times,25)),
 'mean_candidate_ensemble_seconds_from_sweep':median/len(features),
 'candidate_ensembles_per_second':len(features)/median,'peak_device_allocated_bytes':peak_memory,
 'maximum_absolute_logit_error_vs_official_cuda':maximum,'all_checkpoint_classes_equal':class_equal,
 'all_positive_votes_equal':vote_equal,'maximum_absolute_error_between_repeats':float(np.max(np.abs(out-out[0]))),
 'predeclared_acceptance':manifest['predeclared_acceptance'],'untimed_cuda_profile_events':profile_events,
 'timing_boundary':'Only model forward calls and output tensor stacking; all ten checkpoint models and all features preloaded on device. Device synchronization before and after each timed sweep. Weight loading, feature construction, transfer, CPU docking, profiling and output serialization excluded.',
 'sdaa_status':'Not tested on SDAA by this CUDA baseline run' if a.device!='sdaa' else 'SDAA actually executed'}
(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2),flush=True)
if not passed:raise SystemExit('Precision acceptance failed; see saved raw outputs')
