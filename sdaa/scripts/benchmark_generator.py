"""Compare source-based PyTorch DEVELOP inference with fixed official TF1 forwards."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch

p = argparse.ArgumentParser()
p.add_argument("--workload", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--device", choices=["cpu", "sdaa", "cuda"], required=True)
p.add_argument("--warmup", type=int, default=5)
p.add_argument("--repeats", type=int, default=5)
p.add_argument("--iterations", type=int, default=20)
a = p.parse_args()
if a.device == "sdaa":
    import torch_sdaa
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(0)
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
sys.path.insert(0, str(SOURCE_ROOT/"DEVELOP"))
from sdaa.runtime.torch_inference import DevelopInference, captured_feed

a.output.mkdir(parents=True, exist_ok=False)
manifest = json.loads((a.workload/"manifest.json").read_text())
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
for file, expected in manifest["files"].items():
    assert sha(a.workload/file) == expected["sha256"], file
checkpoint = a.workload/"weights/pretrained_DEVELOP_model.pickle"
assert sha(checkpoint) == manifest["checkpoint_sha256"]
model = DevelopInference(checkpoint, a.device)
weight_map=json.loads((a.workload/"weights/variable-map.json").read_text())
with np.load(a.workload/"weights/variables.npz") as arrays:
    assert len(weight_map)==len(model.weights)==123
    for entry in weight_map:
        assert np.array_equal(model.weights[entry["tensorflow_variable"]].cpu().numpy(),arrays[entry["array"]])
frames = []
for frame in manifest["captured_frames"]:
    with np.load(a.workload/frame["inputs"]) as arrays:
        feed = captured_feed(frame, arrays)
    with np.load(a.workload/frame["outputs"]) as arrays:
        reference = [arrays[x["array"]].copy() for x in frame["output_bindings"]]
    frames.append((frame["kind"], feed, reference))

def sync():
    if a.device != "cpu":
        getattr(torch, a.device).synchronize()

def run():
    return {kind: model.predict(feed, kind) for kind, feed, _ in frames}

for _ in range(a.warmup):
    run()
times, saved, errors = [], {}, []
for repeat in range(a.repeats):
    sync()
    start = time.perf_counter()
    for _ in range(a.iterations):
        results = run()
    sync()
    times.append((time.perf_counter()-start)/a.iterations)
    for kind, _, reference in frames:
        for i, (actual, expected) in enumerate(zip(results[kind], reference)):
            assert actual.shape == expected.shape and np.isfinite(actual).all()
            err = float(np.max(np.abs(actual-expected)))
            errors.append(err)
            saved[f"repeat_{repeat}_{kind}_{i}"] = actual
    print(json.dumps({"repeat": repeat, "seconds_per_node_edge_pair": times[-1], "max_error": max(errors)}), flush=True)
np.savez_compressed(a.output/"outputs.npz", **saved)
report = {"device": a.device, "architecture": platform.machine(), "torch": torch.__version__,
          "source_sha256": sha(SOURCE_ROOT/"sdaa/runtime/torch_inference.py"),
          "checkpoint_sha256": sha(checkpoint), "warmup": a.warmup, "repeats": a.repeats,
          "TORCH_SDAA_CONV_USE_FP32":os.environ.get("TORCH_SDAA_CONV_USE_FP32"),"convolution_cache":False,
          "pairs_per_repeat": a.iterations, "seconds_per_pair": times, "median_seconds": statistics.median(times),
          "maximum_probability_error": max(errors), "predeclared_tolerance": 1e-5,
          "scope": "One node-symbol and one edge/type forward, fixed latent, voxel and original dropout uniform; host feeds/outputs included.",
          "passed": max(errors) <= 1e-5}
(a.output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
print(json.dumps(report, indent=2), flush=True)
assert report["passed"], "Original TF1 probability tolerance exceeded"
