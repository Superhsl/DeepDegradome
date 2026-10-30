#!/usr/bin/env python3.12
"""Launch the source checkout's eMolFrag with native pkcombu paths."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = Path(os.environ.get('AutoFBDD_FOL', '/source'))
core = source/'eMolFrag/eMolFrag/eMolFrag_2017_06_19_01'
pkcombu = shutil.which('pkcombu')
if not pkcombu or not (core/'eMolFrag.py').is_file():
    raise SystemExit('eMolFrag source checkout or native pkcombu is missing')
with tempfile.TemporaryDirectory(prefix='deepdegradome-emolfrag-') as directory:
    config = Path(directory)/'PathConfigure.log'
    config.write_text(str(core)+'/'+'\n'+pkcombu+'\n')
    env = {**os.environ, 'EMOLFRAG_CONFIG': str(config)}
    process = subprocess.Popen([sys.executable, str(core/'eMolFrag.py'), *sys.argv[1:]],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env=env)
    failed = False
    for line in process.stdout:
        print(line, end='', flush=True)
        failed |= 'Error Code:' in line or 'Traceback' in line
    code = process.wait()
    raise SystemExit(code or (1 if failed else 0))
