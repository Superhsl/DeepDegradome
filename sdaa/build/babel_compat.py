#!/usr/bin/env python3.12
"""Open Babel 2 positional-output CLI on the installed native Open Babel 3."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

args = sys.argv[1:]
binary = os.environ.get('DEEPDEGRADOME_OBABEL') or shutil.which('obabel')
if not binary:
    raise SystemExit('Native obabel executable is missing')
if len(args) >= 2 and not args[0].startswith('-') and not args[1].startswith('-'):
    source, destination = Path(args[0]), Path(args[1])
    if source.resolve() == destination.resolve():
        # Original scripts convert MOL2 files in place. Do not truncate input.
        with tempfile.TemporaryDirectory(prefix='.babel-', dir=destination.parent) as folder:
            temporary = Path(folder)/destination.name
            result = subprocess.run([binary, str(source), '-O', str(temporary), *args[2:]])
            if result.returncode:
                raise SystemExit(result.returncode)
            if not temporary.is_file() or not temporary.stat().st_size:
                raise SystemExit('Open Babel produced no output')
            os.replace(temporary, destination)
        raise SystemExit(0)
    args = [str(source), '-O', str(destination), *args[2:]]
os.execv(binary, [binary, *args])
