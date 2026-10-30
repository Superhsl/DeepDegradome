"""Report an unreadable dummy-surround MOL2 as a per-pose input rejection."""
import hashlib
import os
from pathlib import Path


class InvalidPreparedMolecule(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('RDKit rejected prepared dummy-surround MOL2: ' + diagnostic['path'])


def read_prepared_dummy(path):
    from rdkit import Chem
    path = Path(path)
    molecule = Chem.MolFromMol2File(str(path))
    if molecule is not None:
        return molecule
    diagnostic = {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'reason': 'RDKit MolFromMol2File returned None with default sanitization',
                  'chemistry_problems': []}
    # Unsanitized reading is diagnostic only, never used for distance or inference.
    raw = Chem.MolFromMol2File(str(path), sanitize=False, removeHs=False)
    if raw is not None:
        try:
            raw.UpdatePropertyCache(strict=False)
            for problem in Chem.DetectChemistryProblems(raw):
                item = {'type': problem.GetType(), 'message': problem.Message()}
                if hasattr(problem, 'GetAtomIdx'):
                    item['atom_index'] = problem.GetAtomIdx()
                diagnostic['chemistry_problems'].append(item)
        except RuntimeError as error:
            diagnostic['additional_diagnostic_error'] = str(error)
    raise InvalidPreparedMolecule(diagnostic)


def install_input_guard(generate_function):
    """Preserve the upstream distance calculation for every readable input."""
    namespace = generate_function.__globals__
    original = namespace['cal_dummy_dist']

    def checked_cal_dummy_dist(path):
        read_prepared_dummy(path)
        return original(path)

    namespace['cal_dummy_dist'] = checked_cal_dummy_dist


def run_generation_pose(generate_function, result, *arguments):
    """Reject only a known unreadable input; let every other error propagate."""
    directory = Path.cwd()
    try:
        generate_function([result], *arguments)
    except InvalidPreparedMolecule as error:
        return {'pose': result[0], 'status': 'rejected_preparation',
                'diagnostic': error.diagnostic}
    finally:
        os.chdir(directory)
    return None
