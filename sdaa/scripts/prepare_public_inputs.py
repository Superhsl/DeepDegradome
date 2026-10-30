"""Prepare transparent PDB-derived functional inputs, not author-supplied files."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from rdkit import Chem
from pymol import cmd

root = Path('/project')
out = root / 'runs/pdb-derived-input-preparation'
out.mkdir(exist_ok=True)
if cmd._COb is None:
    import pymol2
    import pymol.invocation
    pymol.invocation.parse_args(['pymol', '-cq'])
    pymol2.SingletonPyMOL().start()

record = {'scope': 'PDB-derived functional input preparation; not the missing author-prepared WDR5/CRBN example',
          'structures': {}}
for pdb_id in ('9lwy', '8oiz'):
    path = root / 'assets' / (pdb_id + '.cif')
    cmd.load(str(path), pdb_id)
    chains = cmd.get_chains(pdb_id + ' and polymer.protein')
    residues = set()
    cmd.iterate(pdb_id + ' and organic', 'residues.add((chain,resn,resi))', space={'residues': residues})
    info = {'raw_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'protein_chains': chains, 'organic_residues': sorted(residues)}
    print(pdb_id, json.dumps(info), flush=True)
    record['structures'][pdb_id] = info
    if pdb_id == '9lwy':
        # The deposition has one WDR5 protein chain; exclude glycerol and solvent.
        assert len(chains) == 1, chains
        chain = chains[0]
        organic = [x for x in residues if x[1] not in ('GOL','EDO','PEG','DMS')]
        assert len(organic) == 1, organic
        lig_chain, resn, resi = organic[0]
        cmd.alter(pdb_id + ' and polymer.protein', 'chain="A"')
        cmd.save(str(out / 'WDR5.pdb'), pdb_id + ' and polymer.protein and not hydro')
        sel = '%s and chain %s and resn %s and resi %s' % (pdb_id, lig_chain, resn, resi)
        cmd.save(str(out / 'compound4.mol2'), sel)
        cmd.save(str(out / 'compound4.sdf'), sel)
    else:
        # 8OIZ's author chain B is human CRBN and Y70 is its bound pomalidomide.
        assert ('B', 'Y70', '502') in residues, residues
        cmd.save(str(out / 'CRBN.pdb'), pdb_id + ' and chain B and polymer.protein and not hydro')
        cmd.save(str(out / 'CRBN_ligand.mol2'), pdb_id + ' and chain B and resn Y70 and resi 502')
        cmd.save(str(out / 'CRBN_ligand.sdf'), pdb_id + ' and chain B and resn Y70 and resi 502')
    cmd.delete('all')
for name, source in [('compound4','compound4-instance.sdf'), ('CRBN_ligand','pomalidomide-instance.sdf')]:
    mol2 = out / (name+'.mol2')
    original = out / (name+'-pymol-original.mol2')
    if not original.exists():
        shutil.copy(mol2, original)
    shutil.copy(root/'assets'/source, out/(name+'.sdf'))
    sdf_mol = Chem.SDMolSupplier(str(out/(name+'.sdf')))[0]
    assert sdf_mol is not None
    Chem.AssignAtomChiralTagsFromStructure(sdf_mol, replaceExistingTags=False)
    Chem.AssignStereochemistry(sdf_mol, cleanIt=True, force=True)
    subprocess.run(['babel', str(out/(name+'.sdf')), str(mol2), '-h'], check=True)
    # RDKit's Mol2 reader expects pyrrole-like neutral nitrogen as N.pl3.
    # Open Babel exports N.ar for these atoms. Keep all coordinates and bonds.
    pyrrole_ids = {a.GetIdx()+1 for a in sdf_mol.GetAtoms()
                   if a.GetAtomicNum()==7 and a.GetIsAromatic()
                   and a.GetTotalDegree()==3 and a.GetFormalCharge()==0}
    lines = mol2.read_text().splitlines(True)
    in_atoms = False
    for i,line in enumerate(lines):
        if line.startswith('@<TRIPOS>'):
            in_atoms = line.startswith('@<TRIPOS>ATOM')
        elif in_atoms and line.strip():
            parts=line.split()
            if int(parts[0]) in pyrrole_ids and parts[5]=='N.ar':
                lines[i]=line.replace('N.ar','N.pl3')
    mol2.write_text(''.join(lines))
    mol = Chem.MolFromMol2File(str(mol2))
    assert mol is not None
    assert all(a.GetNumRadicalElectrons()==0 for a in mol.GetAtoms())
    assert Chem.GetFormalCharge(mol) == 0
    assert Chem.MolToSmiles(mol) == Chem.MolToSmiles(Chem.RemoveHs(sdf_mol)), (Chem.MolToSmiles(mol), Chem.MolToSmiles(sdf_mol))
    record[name] = {'coordinate_and_bond_order_source':source, 'smiles':Chem.MolToSmiles(mol),
                    'atoms':mol.GetNumAtoms(), 'formal_charge':Chem.GetFormalCharge(mol),
                    'stereocentres':Chem.FindMolChiralCenters(mol)}
    print(name,record[name],flush=True)
(out / 'structure-inventory.json').write_text(json.dumps(record, indent=2) + '\n')
