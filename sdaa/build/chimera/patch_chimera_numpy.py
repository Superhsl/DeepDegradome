"""Recognize native LoongArch in the supplied NumPy 1.7.2 source."""
import hashlib
import json
from pathlib import Path

root = Path('/chimera/build/numpy-1.7.2')
records = []
for relative, needle, replacement in [
    ('numpy/core/include/numpy/npy_cpu.h',
     '#elif defined(__aarch64__)\n    #define NPY_CPU_AARCH64',
     '#elif defined(__loongarch64) || (defined(__loongarch__) && __loongarch_grlen == 64)\n'
     '    #define NPY_CPU_LOONGARCH64\n'
     '#elif defined(__aarch64__)\n    #define NPY_CPU_AARCH64'),
    ('numpy/core/include/numpy/npy_endian.h',
     '|| defined(NPY_CPU_AARCH64)',
     '|| defined(NPY_CPU_LOONGARCH64) \\\n            || defined(NPY_CPU_AARCH64)'),
]:
    path = root/relative
    original = path.read_text()
    assert original.count(needle) == 1, relative
    updated = original.replace(needle, replacement)
    path.write_text(updated)
    records.append({'path': relative, 'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
                    'after_sha256': hashlib.sha256(updated.encode()).hexdigest()})
(root.parent/'numpy-loongarch64-patch.json').write_text(json.dumps(records, indent=2)+'\n')
print(json.dumps(records, indent=2))
