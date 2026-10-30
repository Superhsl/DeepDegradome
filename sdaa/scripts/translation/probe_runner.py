"""Run original CPU binaries on frozen small inputs; preserve failed attempts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import threading
import time

p = argparse.ArgumentParser()
p.add_argument('--backend', required=True, choices=['x86', 'qemu', 'latx'])
p.add_argument('--tools', nargs='+', default=['patchdock', 'cyndi'])
p.add_argument('--repeats', type=int, default=1)
p.add_argument('--label', required=True)
p.add_argument('--timeout', type=int, default=300)
p.add_argument('--freeze-seed-time', action='store_true')
p.add_argument('--freeze-cyndi-seed', action='store_true')
args = p.parse_args()
assets = Path('/assets')
out = Path('/out') / args.label
out.mkdir(exist_ok=False)
prefix = [] if args.backend == 'x86' else ['/translator', '-L', '/assets/sysroot']
state = {'backend': args.backend, 'label': args.label, 'status': 'running', 'jobs': [],
         'timing_scope': 'Popen to blocking wait completion, including translator initialization; excludes Docker startup and input copy. A separate timeout watchdog avoids wait(timeout) polling latency.',
         'scope': 'Reduced frozen functional workloads, not complete DeepDegradome screening.'}

def save():
    (out / 'progress.json').write_text(json.dumps(state, indent=2)+'\n')

save()
for tool in args.tools:
    for repeat in range(args.repeats):
        case = out / ('%s-%02d' % (tool, repeat+1))
        shutil.copytree(assets / 'cases' / tool, case)
        if tool == 'patchdock':
            cmd = prefix + ['/assets/tools/patchdock/patch_dock.Linux', 'params.txt', 'result.txt']
        elif tool == 'cyndi':
            cmd = prefix + ['/assets/tools/cyndi/Cyndi', '-i', 'ligand.mol2', '-o', 'result.mol2']
        elif tool in ('ifit_dock', 'ifit_eval'):
            exe = 'iFitDock' if tool == 'ifit_dock' else 'iFitDock_eval'
            cmd = prefix + ['/assets/tools/'+tool+'/'+exe, '-i', 'dock.in']
        else:
            raise ValueError(tool)
        env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', HOME='/tmp')
        freeze = args.freeze_seed_time and tool.startswith('ifit_')
        freeze_cyndi = args.freeze_cyndi_seed and tool == 'cyndi'
        if freeze or freeze_cyndi:
            preload = ('LD_PRELOAD=/assets/clock/libfixedtime.so' if freeze else
                       'LD_PRELOAD=/assets/seed/libfixedseed.so')
            if args.backend == 'x86':
                env['LD_PRELOAD'] = preload.split('=', 1)[1]
            else:
                cmd = prefix + ['-E', preload] + cmd[len(prefix):]
        (case / 'command.json').write_text(json.dumps({'argv': cmd, 'cwd': str(case),
                                                     'timeout_s': args.timeout}, indent=2)+'\n')
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.monotonic()
        timed_out = False
        with (case / 'stdout.log').open('w') as stdout, (case / 'stderr.log').open('w') as stderr:
            proc = subprocess.Popen(cmd, cwd=str(case), env=env, stdout=stdout, stderr=stderr)
            expired = threading.Event()
            def terminate_expired_process():
                if proc.poll() is None:
                    expired.set()
                    proc.kill()
            watchdog = threading.Timer(args.timeout, terminate_expired_process)
            watchdog.daemon = True
            watchdog.start()
            try:
                rc = proc.wait()
            finally:
                watchdog.cancel()
            timed_out = expired.is_set()
            if timed_out:
                rc = 124
        elapsed = time.monotonic()-start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        valid = False
        details = {}
        if tool == 'patchdock' and (case / 'result.txt').exists():
            lines = (case / 'result.txt').read_text(errors='replace').splitlines()
            rows = [line for line in lines if re.match(r'^\s*\d+\s*\|', line)]
            details = {'transformation_rows': len(rows), 'first_transformations': rows[:10]}
            valid = len(rows) > 0
        elif tool == 'cyndi' and (case / 'result.mol2').exists():
            text = (case / 'result.mol2').read_text(errors='replace')
            blocks = text.split('@<TRIPOS>MOLECULE')[1:]
            counts = []
            for b in blocks:
                header = [x for x in b.split('@<TRIPOS>ATOM')[0].splitlines() if x.strip()]
                try:
                    counts.append([int(x) for x in header[1].split()[:2]])
                except (ValueError, IndexError):
                    counts.append([])
            details = {'conformers': len(blocks), 'atom_bond_counts': counts,
                       'header_preview': text[:1000]}
            valid = bool(blocks) and all(c == [47, 50] for c in counts)
        elif tool in ('ifit_dock', 'ifit_eval'):
            files = [f for f in case.glob('probe*') if f.is_file()]
            details = {'outputs': [{'name': f.name, 'size': f.stat().st_size} for f in files]}
            valid = any(f.stat().st_size > 0 and f.suffix == '.mol2' for f in files)
        row = {'tool': tool, 'repeat': repeat+1, 'exitcode': rc, 'timed_out': timed_out,
               'diagnostic_seed_time_frozen': freeze,
               'diagnostic_cyndi_seed_frozen': freeze_cyndi,
               'seconds': elapsed, 'child_cpu_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
               'functional_output_present': valid, 'details': details,
               'files': [{'path': f.name, 'size': f.stat().st_size,
                          'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                         for f in sorted(case.iterdir()) if f.is_file()]}
        state['jobs'].append(row)
        save()
        print(json.dumps({k: row[k] for k in ['tool', 'repeat', 'exitcode', 'seconds', 'functional_output_present']}), flush=True)
state['status'] = 'complete'
save()
