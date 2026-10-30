"""Make the unrelated CPPTRAJ configure step optional for a charge-only build."""
import hashlib
import json
from pathlib import Path

path = Path('/chimera/build/amber18/AmberTools/src/configure2')
original = path.read_text()
if 'CHIMERA_CHARGE_ONLY' not in original:
    start = 'printf "Configuring CPPTRAJ..."'
    end = 'echo "complete."\n\n#    Test if mpi_cxx is needed.'
    assert original.count(start) == original.count(end) == 1
    updated = original.replace(start, 'if [ "${CHIMERA_CHARGE_ONLY:-no}" != yes ]; then\n'+start)
    updated = updated.replace(end, 'echo "complete."\nelse\n'
        '    echo "CPPTRAJ omitted from explicit Antechamber/SQM-only build profile."\nfi\n\n'
        '#    Test if mpi_cxx is needed.')
    path.write_text(updated)
    (path.parents[3]/'chimera-charge-only-configure-patch.json').write_text(json.dumps({
        'before_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256':hashlib.sha256(updated.encode()).hexdigest(),
        'scope':'Only the unrelated CPPTRAJ configuration is conditional; compiler/library tests and Antechamber/SQM code are retained.'},indent=2)+'\n')
print('Antechamber/SQM-only configure profile available; CPPTRAJ is not built or installed.')
