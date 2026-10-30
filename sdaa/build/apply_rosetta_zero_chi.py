"""Apply the pinned Rosetta non-Pro zero-chi classification fix."""
import argparse,hashlib,json
from pathlib import Path
BEFORE='b9a853a217bbc4b9090ec18538f5e9decbefab94216717cf3985d3a6bc13fccf'
AFTER='c69c96fb1eb2dcf78ab12fdee44c61311a993ee5352cf2ef64c64d264e1a2d60'
RELATIVE='src/core/pack/dunbrack/SingleResidueDunbrackLibrary.hh'
MARKER='\t\tif ( ( chi >= 0.0 ) && ( chi <= 120.0 ) ) { return 1; }'
INSERT=('\t\t// Canonicalize sub-roundoff non-Pro chi to the existing exact-zero bin.\n'
        '\t\t// Only the local classification angle changes; coordinates are untouched.\n'
        '\t\tconstexpr Real chi_zero_tolerance = 1e-10; // degrees\n'
        '\t\tif ( std::abs( chi ) < chi_zero_tolerance ) { chi = 0.0; }\n\n')
def apply(source):
    path=Path(source)/RELATIVE
    content=path.read_bytes();before=hashlib.sha256(content).hexdigest()
    if before==AFTER:
        return {'file':RELATIVE,'changed':False,'before_sha256':before,'after_sha256':AFTER,'tolerance_degrees':1e-10}
    if before!=BEFORE:
        raise RuntimeError('Unexpected Rosetta header; refusing to overwrite existing changes: '+str(path))
    text=content.decode()
    if text.count(MARKER)!=1:raise RuntimeError('Ambiguous zero-chi patch location')
    fixed=text.replace(MARKER,INSERT+MARKER).encode()
    if hashlib.sha256(fixed).hexdigest()!=AFTER:raise RuntimeError('Patched source hash mismatch')
    path.write_bytes(fixed)
    return {'file':RELATIVE,'changed':True,'before_sha256':before,'after_sha256':AFTER,'tolerance_degrees':1e-10}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);args=p.parse_args()
    print(json.dumps(apply(args.source),indent=2))
