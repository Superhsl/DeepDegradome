"""Compare chemical identity, charges and coordinates with declared tolerances."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import argparse
from collections import defaultdict
import itertools
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--reference',type=Path,required=True)
parser.add_argument('--native',type=Path,required=True)
parser.add_argument('--cases',nargs='+',required=True)
parser.add_argument('--filename',default='target.mol2')
parser.add_argument('--output',type=Path,required=True)
args = parser.parse_args()
CHARGE_ATOL, RMSD_ATOL, MAX_COORD_ATOL = 1e-4, 1e-3, 2e-3


def read(path):
    text = path.read_text()
    section = text.split('@<TRIPOS>ATOM\n',1)[1].split('@<TRIPOS>',1)[0]
    groups = defaultdict(list)
    for row in section.splitlines():
        if not row.strip(): continue
        fields = row.split()
        atom = {'id':int(fields[0]),'name':fields[1],
                'xyz':tuple(float(x) for x in fields[2:5]),'type':fields[5],
                'resid':fields[6],'resname':fields[7],'charge':float(fields[8])}
        groups[(atom['resid'],atom['resname'],atom['name'])].append(atom)
    atoms,by_id = {},{}
    # Coordinate ordering disambiguates retained alternate conformations with
    # identical residue and atom names; it is not a structure fit.
    for group,rows in groups.items():
        rows.sort(key=lambda x:x['xyz'])
        for occurrence,atom in enumerate(rows):
            label = group+(occurrence,)
            atoms[label] = atom
            by_id[atom['id']] = label
    neighbors = defaultdict(list)
    edges = set()
    for row in text.split('@<TRIPOS>BOND\n',1)[1].split('@<TRIPOS>',1)[0].splitlines():
        if not row.strip(): continue
        fields = row.split(); a,b = by_id[int(fields[1])],by_id[int(fields[2])]
        edges.add(tuple(sorted((a,b)))+(fields[3],))
        neighbors[a].append(b); neighbors[b].append(a)
    hgroups = defaultdict(list)
    for label,atom in atoms.items():
        if atom['type'].split('.')[0] == 'H':
            assert len(neighbors[label]) == 1
            hgroups[(neighbors[label][0],atom['type'])].append(atom)
    return atoms,edges,hgroups


def distance2(a,b):
    return sum((x-y)**2 for x,y in zip(a['xyz'],b['xyz']))


def metric(values):
    return {'atoms':len(values),'rmsd_angstrom':math.sqrt(sum(values)/len(values)) if values else 0,
            'max_displacement_angstrom':math.sqrt(max(values)) if values else 0}


results = []
for name in args.cases:
    a,abonds,ah = read(args.reference/name/args.filename)
    b,bbonds,bh = read(args.native/name/args.filename)
    record = {'case':name,'reference_atoms':len(a),'native_atoms':len(b),
              'atom_labels_equal':a.keys()==b.keys(),'bond_graph_equal':abonds==bbonds}
    record['passed'] = record['atom_labels_equal'] and record['bond_graph_equal']
    if record['atom_labels_equal']:
        record['atom_types_equal'] = all(a[k]['type']==b[k]['type'] for k in a)
        record['max_charge_error'] = max(abs(a[k]['charge']-b[k]['charge']) for k in a)
        record['heavy_coordinates'] = metric([distance2(a[k],b[k]) for k in a if a[k]['type'].split('.')[0]!='H'])
        record['named_hydrogen_coordinates'] = metric([distance2(a[k],b[k]) for k in a if a[k]['type'].split('.')[0]=='H'])
        symmetric = []
        hmatched = ah.keys()==bh.keys()
        if hmatched:
            for key,rows in ah.items():
                other = bh[key]
                if len(rows)!=len(other) or len(rows)>6:
                    hmatched = False; break
                choices = []
                for order in itertools.permutations(other):
                    if all(abs(x['charge']-y['charge'])<=CHARGE_ATOL for x,y in zip(rows,order)):
                        values = [distance2(x,y) for x,y in zip(rows,order)]
                        choices.append((sum(values),values))
                if not choices:
                    hmatched = False; break
                symmetric.extend(min(choices,key=lambda x:x[0])[1])
        record['equivalent_hydrogens_matched'] = hmatched
        record['equivalent_hydrogen_coordinates'] = metric(symmetric)
        record['passed'] &= record['atom_types_equal'] and record['max_charge_error']<=CHARGE_ATOL and hmatched
        for group in ['heavy_coordinates','equivalent_hydrogen_coordinates']:
            record['passed'] &= (record[group]['rmsd_angstrom']<=RMSD_ATOL
                                  and record[group]['max_displacement_angstrom']<=MAX_COORD_ATOL)
    results.append(record)
report = {'charge_atol':CHARGE_ATOL,'coordinate_rmsd_atol_angstrom':RMSD_ATOL,
          'coordinate_max_atol_angstrom':MAX_COORD_ATOL,'alignment':'none',
          'hydrogen_symmetry':'Only H atoms with the same bonded heavy atom/type and compatible charge may be permuted.',
          'reference':str(args.reference),'native':str(args.native),'cases':results,
          'passed':all(x['passed'] for x in results)}
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
