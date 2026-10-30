"""Verify all original checkpoints against captured TF1 CPU predictions."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch
import torch_sdaa

torch.set_num_threads(1)
torch.manual_seed(0)
SOURCE = SOURCE_ROOT
sys.path.insert(0, str(SOURCE / 'DEVELOP'))
from sdaa.runtime.torch_inference import DevelopInference, captured_feed
from sdaa.runtime.structure_voxel import grid

parser = argparse.ArgumentParser()
parser.add_argument('--reference', type=Path, required=True)
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(exist_ok=False)
tasks = json.loads((args.inputs / 'manifest.json').read_text())['tasks']
reports = []

for task, setting in tasks.items():
    reference = args.reference / task
    manifest = json.loads((reference / 'manifest.json').read_text())
    for name, wanted in manifest['files'].items():
        assert hashlib.sha256((reference / name).read_bytes()).hexdigest() == wanted
    checkpoint = SOURCE / 'DEVELOP/models' / setting['checkpoint']
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == manifest['checkpoint_sha256']
    model = DevelopInference(checkpoint, 'sdaa')
    assert model.struct_data_len == setting['struct_data_len']
    errors, arrays_out = [], {}
    cached_hash, cached_input = None, None
    first_feed = None
    for index, frame in enumerate(manifest['captured_frames']):
        with np.load(reference / frame['inputs']) as arrays:
            feed = captured_feed(frame, arrays)
        if first_feed is None:
            first_feed = (frame['kind'], feed.copy())
        digest = hashlib.sha256(feed['cnn_input'].tobytes()).hexdigest()
        if digest != cached_hash:
            cached_input = feed['cnn_input']
            model.cache_structure(cached_input)
            cached_hash = digest
        feed['cnn_input'] = cached_input
        values = model.predict(feed, frame['kind'])
        with np.load(reference / frame['outputs']) as expected:
            for number, value in enumerate(values):
                gold = expected['output_' + str(number)]
                assert value.shape == gold.shape and np.isfinite(value).all()
                errors.append(dict(frame=index, kind=frame['kind'], output=number,
                                   maximum_absolute_error=float(np.max(np.abs(value - gold)))))
                arrays_out['frame_' + str(index) + '_output_' + str(number)] = value
    config = json.loads((args.inputs / setting['config']).read_text())
    types = args.inputs / Path(config['valid_struct_file']).name
    current_grid = grid(types.read_text().splitlines()[0], args.inputs)
    original_grid = first_feed[1]['cnn_input'][0]
    voxel_error = float(np.max(np.abs(current_grid - original_grid)))
    report = dict(task=task, device='sdaa', struct_data_len=model.struct_data_len,
                  checkpoint_sha256=manifest['checkpoint_sha256'],
                  reference_device=manifest['reference_device'],
                  frame_count=len(manifest['captured_frames']), errors=errors,
                  maximum_probability_error=max(item['maximum_absolute_error'] for item in errors),
                  predeclared_probability_tolerance=manifest['predeclared_tolerance'],
                  voxel_maximum_error=voxel_error, predeclared_voxel_tolerance=1e-6)
    report['passed'] = (report['maximum_probability_error'] <= report['predeclared_probability_tolerance']
                        and voxel_error <= report['predeclared_voxel_tolerance'])
    np.savez_compressed(args.output / (task + '-outputs.npz'), **arrays_out)
    model.cached_input = None
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                           torch.profiler.ProfilerActivity.PrivateUse1]) as profile:
        model.predict(first_feed[1], first_feed[0])
        torch.sdaa.synchronize()
    profile.export_chrome_trace(str(args.output / (task + '-sdaa-trace.json')))
    events = [event for event in profile.events()
              if 'privateuse1' in str(event.device_type).lower()
              or 'sdaa' in str(event.device_type).lower()]
    report['device_events'] = len(events)
    report['device_event_examples'] = [event.name for event in events[:15]]
    report['passed'] = report['passed'] and bool(events)
    (args.output / (task + '-report.json')).write_text(json.dumps(report, indent=2) + '\n')
    reports.append(report)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ['errors', 'device_event_examples']}, indent=2), flush=True)
    del model
    torch.sdaa.empty_cache()

summary = {'passed': all(report['passed'] for report in reports), 'tasks': reports,
           'scope': 'Original-weight fixed-forward parity, CPU voxelization, actual SDAA kernels; '
                    'not a task-quality equivalence or biological activity claim'}
(args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
assert summary['passed']
