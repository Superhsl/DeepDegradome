"""Functional checks for the native CPU tools, run without an accelerator device.

Outputs are fresh directories. Exit status alone is never used as scientific
validation: eMolFrag can swallow failures and DOCK's dockdif can return zero
after reporting a difference.
"""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from openbabel import openbabel as ob


def run(command, log, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    text = result.stdout + result.stderr
    log.write_text(text)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}; see {log}")
    return text


def mol2_atoms(path):
    text = path.read_text()
    atoms = text.split('@<TRIPOS>ATOM\n')[1].split('@<TRIPOS>BOND')[0]
    return [line.split() for line in atoms.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-wrappers', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    out, native = args.output, args.native
    report = {'cpu_only': True, 'architecture': os.uname().machine, 'checks': {}}
    assert not Path('/dev/tcaicard0').exists(), 'CPU test must not expose an SDAA card'
    assert os.uname().machine == 'loongarch64'

    inputs = out / 'molecules'
    inputs.mkdir()
    sdf = out / 'sdf'
    sdf.mkdir()
    smiles = ['CC(=O)Oc1ccccc1C(=O)O', 'CC(=O)Oc1ccccc1C(=O)O', 'CC(=O)Nc1ccccc1']
    for i, smi in enumerate(smiles):
        mol = Chem.AddHs(Chem.MolFromSmiles(smi))
        assert AllChem.EmbedMolecule(mol, randomSeed=2303) == 0
        block = Chem.MolToMolBlock(mol)
        (sdf / f'case{i}.sdf').write_text(block + '\n$$$$\n')
        conversion = ob.OBConversion()
        assert conversion.SetInAndOutFormats('sdf', 'mol2')
        obmol = ob.OBMol()
        assert conversion.ReadString(obmol, block)
        assert conversion.WriteFile(obmol, str(inputs / f'case{i}.mol2'))
        conversion.CloseOutFile()
        parsed = Chem.MolFromMol2File(str(inputs / f'case{i}.mol2'))
        assert parsed is not None and parsed.GetNumHeavyAtoms() == Chem.MolFromSmiles(smi).GetNumHeavyAtoms()
    report['checks']['rdkit_openbabel'] = {'molecules': 3, 'heavy_atom_counts_preserved': True}
    if args.check_wrappers:
        converted = out/'in-place.mol2'
        shutil.copy2(inputs/'case0.mol2', converted)
        run(['babel', str(converted), str(converted)], out/'babel-in-place.log')
        mol = Chem.MolFromMol2File(str(converted))
        assert mol is not None and mol.GetNumHeavyAtoms() == 13
        report['checks']['babel_compat'] = {'in_place_conversion': 'passed', 'heavy_atoms': 13}

    import pymol2
    with pymol2.PyMOL() as pymol:
        cmd = pymol.cmd
        cmd.load(str(inputs / 'case0.mol2'), 'ligand')
        count = cmd.count_atoms('ligand')
        before = cmd.get_coords('ligand').copy()
        cmd.save(str(out / 'pymol-roundtrip.mol2'), 'ligand')
        cmd.reinitialize()
        cmd.load(str(out / 'pymol-roundtrip.mol2'), 'ligand')
        assert cmd.count_atoms('ligand') == count
        error = float(np.max(np.abs(before - cmd.get_coords('ligand'))))
        assert error <= 1e-3
        cmd.reinitialize()
        # Two protein residues: only ALA is within 5 A of the organic ligand.
        pdb = ('HETATM    1  C1  LIG X   1       0.000   0.000   0.000  1.00  0.00           C  \n'
               'ATOM      2  CA  ALA A   1       2.000   0.000   0.000  1.00  0.00           C  \n'
               'ATOM      3  CB  ALA A   1       6.000   0.000   0.000  1.00  0.00           C  \n'
               'ATOM      4  CA  GLY A   2      10.000   0.000   0.000  1.00  0.00           C  \nEND\n')
        cmd.read_pdbstr(pdb, 'complex')
        cmd.select('ligand', 'organic')
        cmd.select('surrounding', 'byres ligand around 5')
        selected = [(a.resn, a.name) for a in cmd.get_model('surrounding').atom]
        assert sorted(selected) == [('ALA', 'CA'), ('ALA', 'CB')], selected
        cmd.save(str(out / 'pymol-pocket.mol2'), 'surrounding')
    report['checks']['pymol'] = {'roundtrip_atoms': count, 'coordinate_max_error': error,
                                 'byres_5A_selected': selected, 'exported_pocket_atoms': len(mol2_atoms(out/'pymol-pocket.mol2'))}

    prefix = native/'install' if (native/'install').is_dir() else native
    pkcombu = prefix/'kcombu/bin/pkcombu'
    similarity = {}
    for name, other in [('identity', 1), ('different', 2)]:
        text = run([str(pkcombu), '-A', str(sdf/'case0.sdf'), '-B', str(sdf/f'case{other}.sdf'), '-oAm'], out/f'pkcombu-{name}.log')
        marker = '#   Nmcs|tani|seldis:'
        assert marker in text, 'eMolFrag requires the original alignment table format'
        line = text[text.index(marker):].splitlines()[1]
        similarity[name] = float(line.split()[3])
    assert similarity['identity'] == 1.0 and similarity['different'] < 1.0, similarity
    report['checks']['pkcombu'] = similarity

    core = args.source/'eMolFrag/eMolFrag/eMolFrag_2017_06_19_01'
    config = out/'PathConfigure.log'
    config.write_text(str(core)+'/'+'\n'+str(pkcombu)+'\n')
    env = {**os.environ, 'EMOLFRAG_CONFIG': str(config)}
    text = run([sys.executable, str(core/'eMolFrag.py'), '-i', str(inputs), '-o', str(out/'fragmented'), '-p', '1', '-m', '0', '-c', '0'], out/'emolfrag.log', env=env)
    assert 'Error Code:' not in text and 'Traceback' not in text, 'eMolFrag swallowed an error; see emolfrag.log'
    fragments = {}
    for kind in ['brick', 'linker', 'chop-comb']:
        values = []
        for path in sorted((out/f'fragmented/output-{kind}').glob('*.sdf')):
            mol = Chem.SDMolSupplier(str(path), sanitize=False)[0]
            assert mol is not None, path
            Chem.SanitizeMol(mol)
            values.append(Chem.MolToSmiles(mol))
        fragments[kind] = sorted(values)
    assert fragments['brick'] and fragments['linker'] and fragments['chop-comb'], fragments
    report['checks']['emolfrag'] = {'input_molecules': 3, 'fragments': fragments,
                                  'note': 'Original fragmentation and redundancy removal; paths configured externally.'}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
