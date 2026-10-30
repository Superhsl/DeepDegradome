"""Source-based entry points for the independently runnable native stages."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys


SOURCE = Path(os.environ.get('AutoFBDD_FOL', '/source'))


def execute(command, output, *, env=None):
    (output/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    with (output/'stage.log').open('w') as log:
        result = subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT)
    (output/'exitcode.txt').write_text(str(result.returncode)+'\n')
    if result.returncode:
        raise SystemExit(f'Stage failed with exit {result.returncode}; see {output / "stage.log"}')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='stage', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--task', choices=['linker', 'pharmacophore', 'scaffold'], required=True)
    generate.add_argument('--config', type=Path, required=True)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--input', type=Path, required=True)
    fragment = sub.add_parser('fragment')
    fragment.add_argument('--input', type=Path, required=True)
    fragment.add_argument('--processes', type=int, default=1)
    refine = sub.add_parser('refine')
    refine.add_argument('--input', type=Path, required=True)
    refine.add_argument('--nstruct', type=int, default=1)
    refine.add_argument('--seed', type=int, default=1001)
    refine.add_argument('--partners', default='AX_BY')
    protein = sub.add_parser('prepare-protein')
    protein.add_argument('--input', type=Path, required=True)
    ligand = sub.add_parser('prepare-ligand')
    ligand.add_argument('--input', type=Path, required=True)
    for stage in [generate, evaluate]:
        stage.add_argument('--device', choices=['sdaa', 'cpu'], default=os.environ.get('DEEPDEGRADOME_DEVICE', 'sdaa'))
    for stage in [generate, evaluate, fragment, refine, protein, ligand]:
        stage.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    if args.stage == 'generate':
        checkpoints = {'linker': 'linker_design/pretrained_DEVELOP_model.pickle',
                       'pharmacophore': 'linker_design/pretrained_DEVELOP_model_pharms.pickle',
                       'scaffold': 'scaffold_elaboration/pretrained_DEVELOP_model.pickle'}
        checkpoint = SOURCE/'DEVELOP/models'/checkpoints[args.task]
        # Checkpoint task paths are resolved from the source checkout itself.
        if not checkpoint.is_file():
            raise SystemExit(f'Missing original checkpoint: {checkpoint}')
        shutil.copy2(args.config, out/'config.json')
        execute([sys.executable, str(SOURCE/'sdaa/scripts/generate.py'), '--config', str(out/'config.json'),
                 '--checkpoint', str(checkpoint), '--device', args.device], out)
    elif args.stage == 'evaluate':
        data = out/'input'
        data.mkdir()
        for name in ['ligase_ligand.mol2', 'ligase_pocket.mol2', 'target_ligand.mol2', 'target_pocket.mol2', 'linker.smi']:
            shutil.copy2(args.input/name, data/name)
        execute([sys.executable, str(SOURCE/'DeepPROTACs/deepprotacs.py'), '-p', str(data),
                 '--device', args.device], out)
        percentage = float((out/'result.txt').read_text())
        assert 0 <= percentage <= 100
        (out/'evaluation-report.json').write_text(json.dumps({'device': args.device, 'ensemble_size': 10,
                                                             'positive_vote_percent': percentage,
                                                             'scope': 'Ten original weights; vote percentage is not calibrated biological probability.'}, indent=2)+'\n')
    elif args.stage == 'fragment':
        assert 1 <= args.processes <= 16
        execute(['emolfrag', '-i', str(args.input), '-o', str(out/'fragmented'),
                 '-p', str(args.processes), '-m', '0', '-c', '0'], out)
    elif args.stage in ['prepare-protein', 'prepare-ligand']:
        is_protein = args.stage == 'prepare-protein'
        filename = 'target.pdb' if is_protein else 'ligand.mol2'
        template = 'protein_template.py' if is_protein else 'ligand_template.py'
        shutil.copy2(args.input, out/filename)
        shutil.copy2(SOURCE/'ifitdock/ifit_dock'/template, out/'prepare.py')
        binary = shutil.which('chimera')
        if not binary:
            raise SystemExit('Native headless Chimera is missing')
        execute([binary, '--nogui', '--nostatus', '--script', str(out/'prepare.py')], out)
        # Chimera can return 0 after a script error: check the products and log.
        log = (out/'stage.log').read_text()
        assert 'Error while processing' not in log, 'Chimera script failed; see stage.log'
        names = (['target_noH.pdb', 'target.pdb', 'target.mol2', 'target_gbsa.pdb']
                 if is_protein else ['ligand.mol2'])
        assert all((out/name).is_file() and (out/name).stat().st_size for name in names)
        mol2 = out/('target.mol2' if is_protein else 'ligand.mol2')
        text = mol2.read_text().split('@<TRIPOS>ATOM\n', 1)[1].split('@<TRIPOS>', 1)[0]
        atoms = [line.split() for line in text.splitlines() if line.strip()]
        charges = [float(row[8]) for row in atoms]
        assert atoms and all(math.isfinite(x) for x in charges)
        policy_path = Path(binary).parent.parent/'chimera-determinism.json'
        policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
        (out/'preparation-report.json').write_text(json.dumps({
            'native_cpu': True, 'functional_passed': True, 'atoms': len(atoms),
            'hydrogens': sum(row[5].split('.')[0] == 'H' for row in atoms),
            'total_charge': sum(charges), 'upstream_template_unchanged': True,
            'determinism_policy': policy, 'numerical_equivalence_validated_for_this_input': False,
            'scope': 'Public Chimera source snapshot 1.17; x86 reference is 1.20. The common deterministic policy has passed four frozen inputs; arbitrary inputs require their own validation. See sdaa/SDAA_ADAPTATION.md.'}, indent=2)+'\n')
    else:
        for name in ['pd.1.pdb', 'War.params', 'E3l.params']:
            shutil.copy2(args.input/name, out/name)
        binary = shutil.which('rosetta_scripts.default.linuxgccrelease')
        if not binary:
            raise SystemExit('Native rosetta_scripts is missing')
        database = Path(os.environ['ROSETTA_FOL'])/'main/database'
        command = [binary, '-s', 'pd.1.pdb', '-parser:protocol', str(SOURCE/'Rosetta/docking.xml'),
                   '@'+str(SOURCE/'Rosetta/docking.flags'), '@'+str(SOURCE/'Rosetta/relax.flags'),
                   '-extra_res_fa', 'War.params', '-extra_res_fa', 'E3l.params', '-partners', args.partners,
                   '-scorefile', 'local.fasc', '-nstruct', str(args.nstruct), '-overwrite',
                   '-database', str(database), '-constant_seed', '-jran', str(args.seed)]
        execute(command, out)
        score = out/'local.fasc'
        rows = [line for line in score.read_text().splitlines() if line.startswith('SCORE:') and 'description' not in line]
        structures = list(out.glob('*_docking_*.pdb'))
        assert rows and len(rows) == len(structures), 'No accepted refinement structures'
        (out/'refinement-report.json').write_text(json.dumps({'native_cpu': True, 'attempted': args.nstruct,
                                                            'accepted': len(structures), 'seed': args.seed,
                                                            'scope': 'Prepared input poses and unchanged upstream XML/flags. Does not run PatchDock or iFitDock.'}, indent=2)+'\n')


if __name__ == '__main__':
    main()
