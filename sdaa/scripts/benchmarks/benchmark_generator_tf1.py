"""Replay fixed generation neural boundaries; host input/output transfers included."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time
import numpy as np
import tensorflow as tf

p=argparse.ArgumentParser()
p.add_argument('--workload',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--device',choices=['cpu','cuda'],required=True)
p.add_argument('--warmup',type=int,default=5)
p.add_argument('--repeats',type=int,default=5)
p.add_argument('--iterations',type=int,default=20)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
manifest=json.loads((a.workload/'manifest.json').read_text())
for name,record in manifest['files'].items():
 assert hashlib.sha256((a.workload/name).read_bytes()).hexdigest()==record['sha256'],name
start=time.perf_counter()
definition=tf.GraphDef();definition.ParseFromString((a.workload/manifest['frozen_graph']).read_bytes())
graph=tf.Graph()
with graph.as_default(),tf.device('/GPU:0' if a.device=='cuda' else '/CPU:0'):tf.import_graph_def(definition,name='')
config=tf.ConfigProto(allow_soft_placement=True,intra_op_parallelism_threads=1,inter_op_parallelism_threads=1)
config.gpu_options.allow_growth=True
if a.device=='cpu':config.device_count['GPU']=0
session=tf.Session(graph=graph,config=config)
if a.device=='cuda':assert any('GPU'==d.device_type for d in session.list_devices())
frames=[]
for item in manifest['captured_frames']:
 arrays=np.load(a.workload/item['inputs'],allow_pickle=False)
 feed={graph.get_tensor_by_name(x['tensor']):arrays[x['array']] for x in item['input_bindings']}
 fetches=[graph.get_tensor_by_name(x['tensor']) for x in item['output_bindings']]
 expected=np.load(a.workload/item['outputs'],allow_pickle=False)
 reference=[expected[x['array']] for x in item['output_bindings']]
 frames.append((item,feed,fetches,reference))
load_seconds=time.perf_counter()-start
def compute():return [session.run(fetches,feed_dict=feed) for _,feed,fetches,_ in frames]
for _ in range(a.warmup):result=compute()
times=[];maximum=0.0;outputs={}
for i in range(a.repeats):
 start=time.perf_counter()
 for _ in range(a.iterations):result=compute()
 times.append(time.perf_counter()-start)
 for (item,_,_,reference),values in zip(frames,result):
  for j,(value,ref) in enumerate(zip(values,reference)):
   assert np.isfinite(value).all()
   maximum=max(maximum,float(np.abs(value-ref).max()))
   outputs['repeat_'+str(i)+'_'+item['kind']+'_'+str(j)]=value
 print(json.dumps({'repeat':i,'seconds':times[-1]}),flush=True)
metadata=tf.RunMetadata()
if a.device=='cuda':
 _,feed,fetches,_=frames[0]
 session.run(fetches,feed_dict=feed,options=tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE),run_metadata=metadata)
 gpu_nodes=sum(len(d.node_stats) for d in metadata.step_stats.dev_stats if 'gpu:' in d.device.lower())
 assert gpu_nodes>0
 (a.output/'untimed-run-metadata.pb').write_bytes(metadata.SerializeToString())
else:gpu_nodes=0
np.savez_compressed(a.output/'raw-outputs.npz',**outputs)
passed=maximum<=manifest['predeclared_acceptance']['maximum_absolute_probability_error']
summary={'status':'passed' if passed else 'failed','device':a.device,'tensorflow':tf.__version__,
 'python':platform.python_version(),'architecture':platform.machine(),'precision':'FP32; TF32 disabled',
 'workload_manifest_sha256':hashlib.sha256((a.workload/'manifest.json').read_bytes()).hexdigest(),
 'load_graph_and_inputs_seconds':load_seconds,'warmup_sweeps':a.warmup,'repeats':a.repeats,
 'two_stage_sweeps_per_repeat':a.iterations,'raw_repeat_seconds':times,
 'median_repeat_seconds':statistics.median(times),'min_repeat_seconds':min(times),'max_repeat_seconds':max(times),
 'median_two_stage_sweep_seconds':statistics.median(times)/a.iterations,
 'iqr_repeat_seconds':float(np.percentile(times,75)-np.percentile(times,25)),
 'maximum_absolute_probability_error_vs_original_cuda':maximum,'untimed_gpu_profile_nodes':gpu_nodes,
 'predeclared_acceptance':manifest['predeclared_acceptance'],
 'timing_boundary':'Repeated exact node-symbol and edge/edge-type neural forwards; NumPy host feeds (including fixed CNN dropout random tensors) and returned host outputs included. Session.run blocks for returned values. Graph loading, molgrid, docking, chemical sampling, random-number generation for the fixed CNN mask and profiling excluded.',
 'scope':'Neural boundary replay; not full molecule generation throughput. SDAA port must match these host input/output timing boundaries before a speed ratio is meaningful.'}
(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2),flush=True)
session.close()
if not passed:raise SystemExit('Frozen forward replay failed precision acceptance')
