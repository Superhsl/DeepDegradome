from pathlib import Path
import argparse,subprocess,json,shutil,time,os
p=argparse.ArgumentParser();p.add_argument('--target',required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir()
for n in ['receptor_gbsa.pdb','prot.table.ambcrg.pdb3H','vdw.parms.amb','receptor_grid_gbsa_box_1.pdb','INCHEM_SA']:shutil.copy2(a.source/n,a.output/n)
lines=(a.output/'INCHEM_SA').read_text().splitlines();lines[3]='receptor_grid_gbsa_box_1.pdb';lines[8]='full_SA_1';(a.output/'INCHEM').write_text('\n'.join(lines)+'\n')
exe='/cpu-dock6/bin/nchemgrid_SA' if a.target=='gpu1' else '/opt/deepdegradome/dock6/bin/nchemgrid_SA';t=time.monotonic()
with (a.output/'build.log').open('wb') as log:r=subprocess.run([exe],cwd=a.output,stdout=log,stderr=subprocess.STDOUT,timeout=300)
assert r.returncode==0 and all((a.output/('full_SA_1.'+s)).is_file() for s in ['bmp','sas','sasmark'])
(a.output/'reference.json').write_text(json.dumps({'exitcode':r.returncode,'seconds':time.monotonic()-t,'scope':'Full original SA grid representation, built for safe external neighbor/mask filtering; not loaded unfiltered into capacity-limited iFit core'},indent=2)+'\n')
