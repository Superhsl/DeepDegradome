"""Exercise freshly installed wheels, without mounting the old runtime prefix."""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import docopt
import numpy as np
import pymol
import pymol2

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('/out'))
args = parser.parse_args()
OUTPUT = args.output.resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
prefix = Path(sys.prefix).resolve()
assert prefix != Path(sys.base_prefix).resolve(), 'Use the fresh validation venv'
for module in [docopt, pymol, pymol2]:
    assert Path(module.__file__).resolve().is_relative_to(prefix), module.__file__
assert metadata.version('pymol') == '3.1.0'
assert metadata.version('docopt') == '0.6.2'
parsed = docopt.docopt('Usage: command [--count=N] INPUT\n\nOptions:\n  --count=N  Count [default: 1].', argv=['--count=3', 'molecule.mol2'])
assert parsed['--count'] == '3' and parsed['INPUT'] == 'molecule.mol2'

pdb = ('HETATM    1  C1  LIG X   1       0.000   0.000   0.000  1.00  0.00           C  \n'
       'ATOM      2  CA  ALA A   1       2.000   0.000   0.000  1.00  0.00           C  \n'
       'ATOM      3  CB  ALA A   1       6.000   0.000   0.000  1.00  0.00           C  \n'
       'ATOM      4  CA  GLY A   2      10.000   0.000   0.000  1.00  0.00           C  \nEND\n')
records = []
for repeat in range(3):
    with pymol2.PyMOL() as session:
        cmd = session.cmd
        cmd.read_pdbstr(pdb, 'complex')
        assert cmd.count_atoms('complex') == 4
        cmd.select('ligand', 'organic')
        cmd.select('surrounding', 'byres ligand around 5')
        selected = sorted((atom.resn, atom.name) for atom in cmd.get_model('surrounding').atom)
        assert selected == [('ALA', 'CA'), ('ALA', 'CB')], selected
        before = cmd.get_coords('surrounding').copy()
        target = OUTPUT / ('pocket-%d.mol2' % repeat)
        cmd.save(str(target), 'surrounding')
        cmd.reinitialize()
        cmd.load(str(target), 'pocket')
        delta = float(np.abs(before - cmd.get_coords('pocket')).max())
        assert cmd.count_atoms('pocket') == 2 and delta <= 1e-3
        records.append({'repeat': repeat, 'selected': selected, 'coordinate_roundtrip_max_abs_angstrom': delta})

extensions = [p for p in Path(pymol.__file__).parent.glob('_cmd*.so')]
assert len(extensions) == 1
ldd = subprocess.check_output(['ldd', str(extensions[0])], text=True)
assert 'not found' not in ldd
result = {
    'passed': True, 'python': platform.python_version(), 'architecture': platform.machine(),
    'venv': str(prefix), 'pymol': metadata.version('pymol'), 'docopt': metadata.version('docopt'),
    'module_locations': {m.__name__: str(m.__file__) for m in [pymol, pymol2, docopt]},
    'isolated_from_previous_native_prefix': not Path('/opt/deepdegradome').exists(),
    'docopt_argument_parser_passed': True, 'pymol_cpu_trials': records,
    'display': os.environ.get('DISPLAY'), 'ldd': ldd,
    'numpy_location': np.__file__, 'numpy_version': np.__version__,
    'scope': 'Wheel installation and CPU molecular operations; no full workflow or biological accuracy claim.'
}
(OUTPUT/'validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
