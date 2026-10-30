"""Launch the fixed existing DeepDegradome inference workloads, without installing anything."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import time

TF_IMAGE = 'sha256:71e9f83f87a749592ca628a6e1460000350a29660521bb2e8bab3d6a3347dcaf'
CUDA_IMAGE = 'sha256:a0ed27920bd1b82c70624ecb3da1ea1ba62c2f13c0a284b7ac2cbd5885369e8a'
SDAA_IMAGE = 'sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3'
KIT_NAME = 'DeepDegradome-migration-kit-20261016-02'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def capture(command):
    return subprocess.check_output(command, text=True, timeout=60)

def asset_state(root):
    kit = root / 'migration' / KIT_NAME
    files = set()
    gen = json.loads((kit / 'generator/manifest.json').read_text())
    ev = json.loads((kit / 'evaluator/manifest.json').read_text())
    for rel in ['generator/manifest.json', 'evaluator/manifest.json', 'evaluator/source/model.py',
                'evaluator/official-cuda-reference.npz', 'benchmarks/benchmark_eval.py',
                'benchmarks/benchmark_generator_tf1.py']:
        files.add(kit / rel)
    for rel in gen['files']:
        files.add(kit / 'generator' / rel)
    for rel in ev['weight_sha256']:
        files.add(kit / 'evaluator/weights' / rel)
    for item in ev['items']:
        files.add(kit / 'evaluator' / item['features'])
    if platform.machine() == 'loongarch64':
        for rel in ['sdaa/scripts/benchmark_generator.py', 'sdaa/runtime/torch_inference.py',
                    'DeepPROTACs/model.py']:
            files.add(SOURCE_ROOT / rel)
    return {str(p.relative_to(root)): sha(p) for p in sorted(files)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['gpu1', 'loong'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gpu-index', type=int, default=7)
    args = parser.parse_args()
    root = PROJECT_ROOT
    expected_arch = 'x86_64' if args.target == 'gpu1' else 'loongarch64'
    assert platform.machine() == expected_arch
    out = args.output.resolve()
    assert out.is_relative_to(root / 'outputs'), out
    out.mkdir(parents=True, exist_ok=False)
    kit = root / 'migration' / KIT_NAME
    source = SOURCE_ROOT
    asset_before = asset_state(root)
    save(out / 'assets-before.json', asset_before)
    kit_manifests = {kind: asset_before['migration/' + KIT_NAME + '/' + kind + '/manifest.json']
                     for kind in ['generator', 'evaluator']}
    metadata = {'target': args.target, 'architecture': platform.machine(),
                'host': platform.node(), 'uid': os.getuid(), 'gid': os.getgid(),
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'runner_sha256': sha(Path(__file__)), 'command': sys.argv,
                'workload_manifests': kit_manifests,
                'thresholds_declared_before_execution': {'generator_max_probability_absolute_error': 1e-5,
                                                        'evaluator_max_logit_absolute_error': 1e-5,
                                                        'evaluator_class_and_vote_changes': 0},
                'sampling_scope': 'Frozen neural inputs; not docking, feature reconstruction or full molecule sampling.',
                'generator_cache': False, 'generator_warmup_pairs': 5,
                'generator_repeats': 5, 'generator_pairs_per_repeat': 20,
                'evaluator_candidates': 195, 'evaluator_checkpoints': 10,
                'evaluator_warmup_sweeps': 1, 'evaluator_timed_sweeps': 5,
                'cpu_quota': 4, 'torch_threads': 1}
    gpu_uuid = None
    if args.target == 'gpu1':
        before = capture(['nvidia-smi', '--query-gpu=index,uuid,name,memory.used,utilization.gpu',
                          '--format=csv,noheader,nounits'])
        (out / 'device-before.txt').write_text(before)
        rows = list(csv.reader(before.splitlines(), skipinitialspace=True))
        row = next(r for r in rows if int(r[0]) == args.gpu_index)
        assert int(row[3]) < 1024 and int(row[4]) == 0, 'Selected GPU is occupied: ' + str(row)
        gpu_uuid = row[1]
        metadata['gpu_uuid'] = gpu_uuid
        metadata['gpu_index'] = args.gpu_index
        stages = [('generator-tf1-cuda', TF_IMAGE, 'cuda', None),
                  ('evaluator-cuda', CUDA_IMAGE, 'cuda', None)]
    else:
        (out / 'device-before.txt').write_text(capture(['/opt/tecoai/bin/teco-smi']))
        assert Path('/dev/tcaicard0').exists()
        stages = [('generator-sdaa-default', SDAA_IMAGE, 'sdaa', '0'),
                  ('generator-sdaa-fp32', SDAA_IMAGE, 'sdaa', '1'),
                  ('evaluator-sdaa', SDAA_IMAGE, 'sdaa', '0')]
    save(out / 'protocol.json', metadata)
    failures = []
    records = []
    for stage, image, device, conv in stages:
        actual_id = capture(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']).strip()
        assert actual_id == image
        phase = out / stage
        phase.mkdir()
        common = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '4', '--memory', '32g',
                  '--shm-size', '4g', '--name', 'dd-neural-' + stage + '-' + str(os.getpid()),
                  '--user', str(os.getuid()) + ':' + str(os.getgid())]
        for key, value in [('HOME', '/tmp'), ('PYTHONUNBUFFERED', '1'), ('PYTHONDONTWRITEBYTECODE', '1'),
                           ('PYTHONHASHSEED', '0'), ('OMP_NUM_THREADS', '1'), ('OPENBLAS_NUM_THREADS', '1'),
                           ('MKL_NUM_THREADS', '1'), ('NVIDIA_TF32_OVERRIDE', '0')]:
            common += ['-e', key + '=' + value]
        common += ['-v', str(source) + ':/source:ro', '-v', str(kit) + ':/kit:ro', '-v', str(phase) + ':/out', '-w', '/out']
        if args.target == 'gpu1':
            common += ['--gpus', 'device=' + gpu_uuid, '--entrypoint', 'python']
            env_code = ('import tensorflow as f;print(f.__version__)' if 'tf1' in stage else
                        'import torch,torch_geometric,platform,json;print(json.dumps(dict(python=platform.python_version(),torch=torch.__version__,pyg=torch_geometric.__version__,cuda=torch.version.cuda)))')
        else:
            common += ['--device', '/dev/tcaicard0', '-e', 'TORCH_SDAA_CONV_USE_FP32=' + conv,
                       '--entrypoint', 'python3.12']
            env_code = 'import torch,torch_sdaa,torch_geometric,platform,json;print(json.dumps(dict(python=platform.python_version(),torch=torch.__version__,torch_sdaa=torch_sdaa.__version__,pyg=torch_geometric.__version__)))'
        env_command = common + [image, '-c', env_code]
        with (phase / 'environment.log').open('w') as log:
            subprocess.run(env_command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        save(phase / 'environment-command.json', env_command)
        if stage.startswith('generator'):
            script = '/source/sdaa/scripts/benchmarks/benchmark_generator_tf1.py' if args.target == 'gpu1' else '/source/sdaa/scripts/benchmark_generator.py'
            bench = [script, '--workload', '/kit/generator', '--output', '/out/result',
                     '--device', device, '--warmup', '5', '--repeats', '5', '--iterations', '20']
            report_path = phase / ('result/summary.json' if args.target == 'gpu1' else 'result/report.json')
        else:
            bench = ['/source/sdaa/scripts/benchmarks/benchmark_eval.py', '--workload', '/kit/evaluator',
                     '--output', '/out/result', '--device', device, '--warmup', '1', '--repeats', '5']
            if args.target == 'loong':
                bench += ['--model-source', '/source/DeepPROTACs/model.py']
            else:
                bench += ['--profile-once']
            report_path = phase / 'result/summary.json'
        command = common + [image] + bench
        save(phase / 'command.json', command)
        (phase / 'command.sh').write_text(shlex.join(command) + '\n')
        print('START ' + stage, flush=True)
        start = time.monotonic()
        with (phase / 'run.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        elapsed = time.monotonic() - start
        (phase / 'exitcode.txt').write_text(str(result.returncode) + '\n')
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        # Default convolution may legitimately fail the unchanged numerical threshold.
        known_numeric_failure = (stage == 'generator-sdaa-default' and result.returncode == 1
                                 and report is not None and report.get('passed') is False
                                 and len(report.get('seconds_per_pair', [])) == 5
                                 and (phase / 'result/outputs.npz').is_file())
        completed = result.returncode == 0 or known_numeric_failure
        record = {'stage': stage, 'exitcode': result.returncode, 'wall_seconds': elapsed,
                  'execution_completed': completed,
                  'numerical_passed': report.get('passed', report.get('status') == 'passed') if report else False,
                  'report': str(report_path.relative_to(out)), 'image_id': image}
        records.append(record)
        save(out / 'progress.json', records)
        print(json.dumps(record), flush=True)
        if not completed:
            failures.append(stage)
            print((phase / 'run.log').read_text()[-3000:], flush=True)
    after = asset_state(root)
    save(out / 'assets-after.json', after)
    assert after == asset_before, 'Read-only source or benchmark assets changed'
    if args.target == 'gpu1':
        (out / 'device-after.txt').write_text(capture(['nvidia-smi', '--query-gpu=index,uuid,name,memory.used,utilization.gpu', '--format=csv,noheader,nounits']))
    else:
        (out / 'device-after.txt').write_text(capture(['/opt/tecoai/bin/teco-smi']))
    summary = {'execution_completed': not failures, 'stages': records, 'assets_unchanged': True,
               'all_numerical_thresholds_passed': all(r['numerical_passed'] for r in records),
               'workload_manifests': kit_manifests, 'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(out / 'run-summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    if failures:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
