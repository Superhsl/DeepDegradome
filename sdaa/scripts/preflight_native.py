"""Check actual native tools before a source-based workflow is started."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct


def executable(path):
    if not path or not Path(path).is_file():
        return {'path': str(path) if path else None, 'status': 'missing'}
    path = Path(path).resolve()
    content = path.read_bytes()[:64]
    result = {'path': str(path)}
    if content.startswith(b'\x7fELF'):
        endian = '<' if content[5] == 1 else '>'
        machine = struct.unpack(endian+'H', content[18:20])[0]
        result.update(elf_machine=machine, status='native' if machine == 258 else 'foreign_architecture')
    elif content.startswith(b'#!'):
        result['status'] = 'script'
    else:
        result['status'] = 'unrecognized'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['models', 'cpu', 'all'], default='all')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = Path(os.environ.get('AutoFBDD_FOL', '/source'))
    prefix = Path(os.environ.get('DEEPDEGRADOME_NATIVE_PREFIX', '/opt/deepdegradome'))
    report = {'scope': args.scope, 'architecture': platform.machine(), 'python': platform.python_version(),
              'source_checkout': str(source), 'neural_device': os.environ.get('DEEPDEGRADOME_DEVICE'),
              'components': {}, 'limitations': []}
    if platform.machine() != 'loongarch64':
        raise SystemExit('Expected a native loongarch64 runtime')
    components = report['components']
    failed = False
    if args.scope in ['models', 'all']:
        import torch
        import torch_sdaa
        available = torch.sdaa.is_available()
        components['torch_sdaa'] = {'torch': torch.__version__, 'available': available,
                                    'fp32_convolution': os.environ.get('TORCH_SDAA_CONV_USE_FP32')}
        conv_fp32 = os.environ.get('TORCH_SDAA_CONV_USE_FP32', '0')
        components['torch_sdaa']['convolution_path'] = {'0': 'sdaa_default', '1': 'force_fp32'}.get(conv_fp32, 'invalid')
        failed |= not available or conv_fp32 not in ['0', '1']
        if conv_fp32 == '0':
            report['limitations'].append('Default convolution is selected for routine inference. Previous fixed-state probability error 4.982436075806618e-5 exceeded the original 1e-5 tolerance; this availability check does not assert numerical equivalence.')
        report['limitations'].append('Inference only; fixed-state numerical agreement does not establish biological accuracy or sampling-distribution equivalence.')
    if args.scope in ['cpu', 'all']:
        for name in ['rdkit', 'openbabel', 'pymol']:
            module = importlib.import_module(name)
            components[name] = {'module': module.__file__, 'status': 'imported'}
        for name in ['obabel', 'babel', 'pkcombu', 'showbox', 'grid', 'nchemgrid_GB', 'nchemgrid_SA', 'rosetta_scripts.default.linuxgccrelease', 'chimera']:
            result = executable(shutil.which(name))
            components[name] = result
            failed |= result['status'] not in ['native', 'script']
        for name in ['antechamber', 'sqm', 'am1bcc']:
            result = executable(prefix/'chimera/bin/amber18/bin'/name)
            components['Amber18_'+name] = result
            failed |= result['status'] != 'native'
        policy_path = prefix/'chimera/chimera-determinism.json'
        policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
        report['chimera_determinism_policy'] = policy
        report['limitations'].append('Availability check only. The common deterministic Chimera policy has passed four frozen public inputs, not arbitrary molecules or unmodified-x86 equivalence.' if policy else 'No deterministic Chimera policy is installed; original preparation discrepancies remain.')
    if args.scope == 'all':
        for name, path in {
            'PatchDock': source/'PatchDock/patch_dock.Linux',
            'pdb_trans': source/'PatchDock/pdb_trans',
            'iFitDock': source/'ifitdock/ifit_dock/iFitDock',
            'iFitDock_eval': source/'ifitdock/ifit_eval/iFitDock_eval',
            'lattice': source/'ifitdock/ifit_dock/lattice',
            'split_grid': source/'ifitdock/ifit_eval/split_grid',
            'Cyndi': source/'DEVELOP/analysis/Cyndi',
            'Chimera_classic': prefix/'chimera/bin/chimera',
        }.items():
            result = executable(path)
            components[name] = result
            failed |= result['status'] not in ['native', 'script']
        report['limitations'].append('Protein-start and complete ligand-design pipelines require all corresponding native external cores. No emulation or algorithm substitution is performed.')
    report['passed'] = not failed
    text = json.dumps(report, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')
    raise SystemExit(2 if failed else 0)


if __name__ == '__main__':
    main()
