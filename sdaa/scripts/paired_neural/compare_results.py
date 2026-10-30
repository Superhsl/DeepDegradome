"""Recompute numerical errors and timings from the fixed paired raw evidence."""
import argparse
import json
from pathlib import Path
import statistics
import numpy as np

def read(path):
    return json.loads(path.read_text())

def timings(values):
    assert len(values) == 5 and all(np.isfinite(values))
    return {'raw_seconds': values, 'median_seconds': statistics.median(values),
            'minimum_seconds': min(values), 'maximum_seconds': max(values)}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cuda', type=Path, required=True)
    p.add_argument('--sdaa', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert not a.output.exists(), 'Use a new result filename'
    cp, sp = read(a.cuda/'protocol.json'), read(a.sdaa/'protocol.json')
    assert cp['workload_manifests'] == sp['workload_manifests']
    ca, sa = read(a.cuda/'assets-before.json'), read(a.sdaa/'assets-before.json')
    shared = sorted(ca.keys() & sa.keys())
    assert shared and all(ca[k] == sa[k] for k in shared)
    assert ca == read(a.cuda/'assets-after.json')
    assert sa == read(a.sdaa/'assets-after.json')
    result = {'scope': 'Frozen neural inputs and original weights; no biological accuracy claim.',
              'workload_manifests': cp['workload_manifests'], 'shared_assets': len(shared),
              'shared_assets_match': True, 'tolerance': 1e-5,
              'ratio_definition': 'CUDA median seconds / SDAA median seconds; below 1 means SDAA takes longer.',
              'generator': []}
    cg = a.cuda/'generator-tf1-cuda/result'
    gt = timings(read(cg/'summary.json')['raw_two_stage_sweep_seconds']) if 'raw_two_stage_sweep_seconds' in read(cg/'summary.json') else None
    if gt is None:
        summary = read(cg/'summary.json')
        values = summary.get('seconds_per_pair')
        if values is None:
            values = [x / 20 for x in summary['raw_repeat_seconds']]
        gt = timings(values)
    with np.load(cg/'raw-outputs.npz', allow_pickle=False) as baseline:
        for name in ['generator-sdaa-default', 'generator-sdaa-fp32']:
            folder = a.sdaa/name/'result'
            summary = read(folder/'report.json')
            with np.load(folder/'outputs.npz', allow_pickle=False) as migrated:
                assert set(baseline.files) == set(migrated.files)
                errors = {}
                for key in baseline.files:
                    assert baseline[key].shape == migrated[key].shape
                    assert np.isfinite(baseline[key]).all() and np.isfinite(migrated[key]).all()
                    errors[key] = float(np.max(np.abs(baseline[key] - migrated[key])))
            st = timings(summary['seconds_per_pair'])
            result['generator'].append({'mode': name, 'maximum_absolute_probability_error': max(errors.values()),
                'passed': max(errors.values()) <= result['tolerance'], 'per_output_error': errors,
                'cuda': gt, 'sdaa': st, 'cuda_over_sdaa': gt['median_seconds']/st['median_seconds']})
    ce, se = a.cuda/'evaluator-cuda/result', a.sdaa/'evaluator-sdaa/result'
    with np.load(ce/'raw-outputs.npz', allow_pickle=False) as c, np.load(se/'raw-outputs.npz', allow_pickle=False) as s:
        assert c['logits'].shape == s['logits'].shape == (5, 195, 10, 2)
        assert np.isfinite(c['logits']).all() and np.isfinite(s['logits']).all()
        maximum = float(np.max(np.abs(c['logits']-s['logits'])))
        classes = int(np.count_nonzero(c['predictions'] != s['predictions']))
        votes = int(np.count_nonzero(c['positive_vote_percent'] != s['positive_vote_percent']))
    ct, st = timings(read(ce/'summary.json')['raw_sweep_seconds']), timings(read(se/'summary.json')['raw_sweep_seconds'])
    result['evaluator'] = {'maximum_absolute_logit_error': maximum, 'changed_classes': classes,
        'changed_votes': votes, 'passed': maximum <= result['tolerance'] and classes == 0 and votes == 0,
        'cuda': ct, 'sdaa': st, 'cuda_over_sdaa': ct['median_seconds']/st['median_seconds']}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'generator_passed': [x['passed'] for x in result['generator']],
                      'evaluator_passed': result['evaluator']['passed'], 'shared_assets': len(shared)}))

if __name__ == '__main__':
    main()
