"""Same bounded PROTAC workflow on original x86/TF1 and Loong/Torch-SDAA stacks."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
from pathlib import Path
import hashlib
import json
import math
import os
import runpy
import shutil
import sys
import time

sys.path.insert(0, '/harness')
import native_base as b

OUT=Path('/out')
CASE=OUT/'case'
SOURCE=Path('/source')
TARGET=os.environ['DD_COMPARE_TARGET']
DEVICE='cuda' if TARGET=='gpu1' else 'sdaa'

def prepare():
    CASE.mkdir()
    prep=OUT/'preparation'
    prep.mkdir()
    rows=[]
    for is_protein,file,name in [(True,'WDR5.pdb','WDR5'),(True,'CRBN.pdb','CRBN'),
                                 (False,'compound4.mol2','compound4'),(False,'CRBN_ligand.mol2','CRBN_ligand')]:
        d=prep/name;d.mkdir()
        filename='target.pdb' if is_protein else 'ligand.mol2'
        shutil.copy2(Path('/public-inputs')/file,d/filename)
        template='protein_template.py' if is_protein else 'ligand_template.py'
        shutil.copy2(SOURCE/'ifitdock/ifit_dock'/template,d/'prepare.py')
        binary='/chimera/bin/chimera' if TARGET=='gpu1' else '/opt/deepdegradome/chimera/bin/chimera'
        record=b.execute([binary,'--nogui','--nostatus','--script',str(d/'prepare.py')],d,d/'run.log')
        log=(d/'run.log').read_text(errors='replace')
        assert 'Error while processing' not in log
        expected=['target.pdb','target_noH.pdb','target.mol2','target_gbsa.pdb'] if is_protein else ['ligand.mol2']
        assert all((d/f).is_file() and (d/f).stat().st_size for f in expected)
        text=(d/('target.mol2' if is_protein else 'ligand.mol2')).read_text()
        atomrows=[r.split() for r in text.split('@<TRIPOS>ATOM',1)[1].split('@<TRIPOS>',1)[0].splitlines() if r.strip()]
        charges=[float(r[8]) for r in atomrows]
        assert all(math.isfinite(q) for q in charges)
        record.update(name=name,atoms=len(atomrows),hydrogens=sum(r[5].split('.')[0]=='H' for r in atomrows),total_charge=sum(charges))
        rows.append(record)
        shutil.copy2(d/filename,CASE/file)
    b.dump('preparation-report.json',{'target':TARGET,'records':rows,'strict_numerical_equivalence_claimed':False})

def global_dock():
    b.global_dock()
    p=OUT/'global-report.json';r=json.loads(p.read_text())
    r['inputs']='Same public-PDB raw files, fresh platform-local Chimera preparation'
    r['target']=TARGET;b.dump('global-report.json',r)

def refine():
    b.refine_parallel(resume_first=False)

def generate():
    import numpy as np
    np.random.seed(0)
    if TARGET=='loong':
        import torch,torch_sdaa
        torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    else:
        # Load the chemistry extension modules before TensorFlow/molgrid.
        # The reverse order reproducibly corrupted RDKit memory in this image.
        from pymol import cmd
        from rdkit import Chem
        import tensorflow as tf,molgrid
        molgrid.set_gpu_enabled(False)
    os.chdir(CASE)
    f=b.ns()
    selected=json.loads((CASE/'refined-selection.json').read_text())
    import brick_linking
    Original=brick_linking.DenseGGNNChemModel
    records=[]
    class Observed(Original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if TARGET=='loong':
                assert len(self.sess.model.weights)==123
                assert all(v.device.type=='sdaa' for v in self.sess.model.weights.values())
            else:
                assert len(self.graph.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES))==123
                assert any(d.device_type=='GPU' for d in self.sess.list_devices())
        def train(self,*args,**kwargs):
            start=time.perf_counter();result=super().train(*args,**kwargs)
            if TARGET=='loong':torch.sdaa.synchronize()
            records.append({'pose':Path.cwd().name,'seconds':time.perf_counter()-start,
                            'device':DEVICE,'cache_structure':TARGET=='loong',
                            'original_weight_arrays':123})
            return result
    brick_linking.DenseGGNNChemModel=Observed
    from generation_guard import install_input_guard, run_generation_pose
    install_input_guard(f['generate_linker'])
    rejected_preparation = []
    completed_pose_calls = []
    for result in selected:
        rejection = run_generation_pose(f['generate_linker'], result,
                                        'compound4.mol2', 'CRBN_ligand.mol2', 18, 1)
        if rejection is not None:
            rejected_preparation.append(rejection)
            (CASE/result[0]/'generation-rejection.json').write_text(json.dumps(rejection,indent=2)+'\n')
            print('REJECT_INVALID_PREPARATION', result[0], rejection['diagnostic']['reason'], flush=True)
        completed_pose_calls.append(result[0])
        b.dump('generation-progress.json', {'completed_pose_calls':completed_pose_calls,
               'rejected_preparation':rejected_preparation,'model_records':records})
    from rdkit import Chem
    generated={}
    for name,_ in selected:
        p=CASE/name/'generated_smi_1'/(name+'_generated_smiles.smi')
        if not p.exists():continue
        rows=[s.split()[-1] for s in p.read_text().splitlines() if s.strip()]
        ms=[Chem.MolFromSmiles(s) for s in rows]
        valid=[m for m in ms if m is not None]
        generated[name]={'rows':len(rows),'parseable':len(valid),
                         'connected':sum(len(Chem.GetMolFrags(m))==1 for m in valid),
                         'unique':len(set(Chem.MolToSmiles(m) for m in valid))}
        assert len(valid)==len(rows)
    assert records and generated,'No generation occurred'
    b.dump('generation-report.json',{'target':TARGET,'device':DEVICE,'records':records,'generated':generated,
                                    'samples_per_length':50,'maximum_probability_tolerance':1e-5,
                                    'rejected_preparation':rejected_preparation,
                                    'input_validity_policy':'RDKit default sanitized MOL2 must be readable; otherwise reject that pose explicitly',
                                    'scope':'Original sampler; framework random streams differ. Not bytewise SMILES parity.'})

def assess():
    b.assess()

def evaluate():
    import shlex,torch
    if TARGET=='loong':import torch_sdaa
    torch.set_num_threads(1);torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    sys.path.insert(0,str(CASE));os.chdir(CASE)
    selected=json.loads((CASE/'refined-selection.json').read_text())
    f=runpy.run_path(str(SOURCE/'DeepPROTACs.py'),run_name='paired_pipeline_evaluator')
    records=[]
    class ObservedOS:
        def __getattr__(self,name):return getattr(os,name)
        def system(self,command):
            tokens=shlex.split(command)
            if tokens[:2]!=['python','deepprotacs.py']:return os.system(command)
            old=sys.argv[:];logits=[];Path('result.txt').unlink(missing_ok=True)
            def observe(module,args,output):
                if module.__class__.__name__=='ProtacModel':
                    assert next(module.parameters()).device.type==DEVICE
                    assert output.device.type==DEVICE and torch.isfinite(output).all()
                    logits.append(output.detach().cpu().tolist())
            hook=torch.nn.modules.module.register_module_forward_hook(observe)
            try:
                sys.argv=['deepprotacs.py']+tokens[2:]
                runpy.run_path(str(CASE/'deepprotacs.py'),run_name='__main__')
            finally:hook.remove();sys.argv=old
            assert len(logits)==10
            vote=float(Path('result.txt').read_text())
            assert vote==sum(x[0][1]>x[0][0] for x in logits)*10
            records.append({'candidate':tokens[-1],'logits':logits,'positive_vote_percent':vote})
            return 0
    f['deep_PROTACs'].__globals__['os']=ObservedOS()
    final=f['deep_PROTACs'](selected,'WDR5_CRBN')
    assert records
    b.dump('evaluation-report.json',{'target':TARGET,'device':DEVICE,'ensemble':10,'evaluated':len(records),
                                    'records':records,'final_sdf':str(CASE/final)})

def summarize():
    from rdkit import Chem
    from rdkit.Chem import RDConfig
    sys.path.insert(0,str(SOURCE/'DEVELOP/analysis'))
    import sascorer
    p=CASE/'WDR5_CRBN_PROTACs.sdf'
    mols=list(Chem.SDMolSupplier(str(p))) if p.stat().st_size else []
    assert all(m is not None and len(Chem.GetMolFrags(m))==1 for m in mols)
    assert all(math.isfinite(float(x)) for m in mols for x in m.GetConformer().GetPositions().ravel())
    reports={name:json.loads((OUT/(name+'-report.json')).read_text()) for name in ['preparation','global','refinement','generation','assessment','evaluation']}
    rows=[m for k in reports['generation']['generated'].values() for m in [k]]
    result={'target':TARGET,'raw_inputs_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/public-inputs').iterdir() if p.name in ['WDR5.pdb','CRBN.pdb','compound4.mol2','CRBN_ligand.mol2']},
            'global_poses':reports['global']['count'],'refinement_attempts':reports['refinement']['attempts'],
            'accepted_refinements':reports['refinement']['accepted'],'eligible_generator_poses':len(rows),
            'generated':sum(v['rows'] for v in rows),'parseable':sum(v['parseable'] for v in rows),
            'connected':sum(v['connected'] for v in rows),'unique_per_pose_sum':sum(v['unique'] for v in rows),
            'assessed_raw_rows':sum(v['assessment_rows'] for v in json.loads((OUT/'assessment-input-budget.json').read_text())),
            'aligned_candidates':sum(reports['assessment']['aligned_molecules'].values()),
            'evaluated_candidates':reports['evaluation']['evaluated'],'retained_candidates':len(mols),
            'final_canonical_smiles':[Chem.MolToSmiles(m) for m in mols],
            'final_sa_scores':[sascorer.calculateScore(m) for m in mols],
            'final_sdf_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
            'functional_completed':True,'biological_accuracy_claimed':False,
            'scope':'One bounded end-to-end run per host, original thresholds, 50 samples/eligible linker length; first 20 raw rows per eligible pose assessed. Different scientific outputs are retained.'}
    b.dump('pipeline-summary.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    stage=sys.argv[1];start=time.perf_counter()
    try:globals()[stage]()
    except BaseException:
        b.dump(stage+'-status.json',{'stage':stage,'execution_completed':False,'seconds':time.perf_counter()-start});raise
    b.dump(stage+'-status.json',{'stage':stage,'execution_completed':True,'seconds':time.perf_counter()-start})
