"""Install original Python modules for an explicitly labeled source-snapshot build."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

src = Path('/chimera/src/chimera.src')
prefix = Path('/chimera/install')
share = prefix/'share'
shutil.copy2(src/'foreign/colorbrewer/colorbrewer.py', prefix/'lib/python2.7/site-packages/colorbrewer.py')
shutil.copytree(src/'libs', share, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('*.o', '*.so', '*.a', '*.cpp', '*.c', '*.h',
                                             '*.pyc', '*.pyo', 'GNUmakefile', '*.in',
                                             'SpaceNavigatorDual', 'Dome', 'DBPuppet'))
# This intentionally empty module is supplied by upstream's OSMESA build.
shutil.copy2(src/'libs/Pmw_dummy/Pmw.py', share/'Pmw.py')
# These integrations are outside the headless structure-preparation profile.
# Preserve existing copies outside automatic extension discovery.
optional = ['SpaceNavigatorDual', 'Dome', 'DBPuppet']
for name in optional:
    installed = share/name
    if installed.exists():
        saved = prefix/'optional-extensions'/name
        saved.parent.mkdir(exist_ok=True)
        assert not saved.exists(), saved
        shutil.move(str(installed), str(saved))
# The exported public archive has no SVN revision metadata. Preserve the
# upstream version API, but explicitly distinguish its numeric ordering
# sentinel from an official build/revision number.
version = (src/'libs/chimera/version.py.in').read_text()
version = version.replace('TYPE', 'native-source-snapshot').replace('BUILD', '0').replace('DAYTIME', '2022-09-29 UTC')
version += "\nsource_revision = None\nbuild_number_is_compatibility_sentinel = True\n"
version += "source_archive_sha256 = '1c38a887acae01e1a904288bb9abd0f5140a78802d3a4cb781392d8f35479b39'\n"
version += "version = 'native-source-snapshot version 1.17 (build unknown) 2022-09-29 UTC'\n"
(share/'chimera/version.py').write_text(version)
launcher = prefix/'bin/chimera'
launcher.write_text('''#!/bin/sh
set -eu
CHIMERA=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
export CHIMERA
export PYTHONHOME="$CHIMERA"
export PYTHONPATH="$CHIMERA/lib:$CHIMERA/share"
export LD_LIBRARY_PATH="$CHIMERA/lib:${LD_LIBRARY_PATH:-}"
export PYTHONNOUSERSITE=1
exec "$CHIMERA/bin/python2.7" "$CHIMERA/share/__main__.py" "$@"
''')
launcher.chmod(0o755)
(prefix/'source-snapshot.json').write_text(json.dumps({
    'upstream_version_template': '1.17', 'upstream_revision': None,
    'excluded_optional_extensions': optional,
    'official_binary_baseline_version': '1.20', 'same_official_release': False,
    'releaseNum_build_0': 'Compatibility ordering sentinel, not an official SVN build number',
    'source_archive_sha256': '1c38a887acae01e1a904288bb9abd0f5140a78802d3a4cb781392d8f35479b39',
    'scope': 'Experimental headless source build; validate AddH/AddCharge separately.'}, indent=2)+'\n')
subprocess.run([sys.executable, '/task/apply_determinism.py', '--share', str(share),
                '--patch', '/patches/chimera-determinism.patch'], check=True)
print('Installed explicitly labeled headless source build at', prefix)
