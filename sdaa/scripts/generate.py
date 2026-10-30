"""Run the original DEVELOP autoregressive sampler through the torch backend."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import json
import hashlib
import os
import time
import sys
from pathlib import Path
import torch

p = argparse.ArgumentParser()
p.add_argument("--config",type=Path,required=True)
p.add_argument("--checkpoint",type=Path,required=True)
p.add_argument("--device",choices=["cpu","sdaa","cuda"],required=True)
a=p.parse_args()
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(0)
sys.path.insert(0,str(SOURCE_ROOT/"DEVELOP"))
from DEVELOP import DenseGGNNChemModel
args={"--dataset":"zinc","--config":a.config.read_text(),"--config-file":None,"--restore":str(a.checkpoint),
      "--torch-device":a.device,"--log_dir":".","--data_dir":"","--out_name":"torch-generation"}
model = DenseGGNNChemModel(args)
start=time.perf_counter()
model.train()
from rdkit import Chem
smiles_files=list(Path('.').glob('*_generated_smiles.smi'))
assert len(smiles_files)==1
rows=[line.split()[-1] for line in smiles_files[0].read_text().splitlines() if line.strip()]
canonical=[Chem.MolToSmiles(Chem.MolFromSmiles(s)) for s in rows]
report={"device":a.device,"torch":torch.__version__,"seed":0,"output_file":smiles_files[0].name,
        "generated":len(rows),"parseable":len(canonical),"unique":len(set(canonical)),
        "sampling_seconds_including_voxelization":time.perf_counter()-start,
        "checkpoint_sha256":hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),
        "structural_feature_count":model.sess.model.struct_data_len,
        "config_sha256":hashlib.sha256(a.config.read_bytes()).hexdigest(),"neural_calls":model.sess.calls,
        "TORCH_SDAA_CONV_USE_FP32":os.environ.get("TORCH_SDAA_CONV_USE_FP32"),
        "deterministic_cnn_features_cached":True,"dropout_resampled_each_neural_call":True,
        "scope":"Original DEVELOP sampler, fragment/valence/BFS rules; CPU Open Babel/voxelization and torch neural inference. No docking/alignment/experimental accuracy claim."}
Path('generation-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2),flush=True)
