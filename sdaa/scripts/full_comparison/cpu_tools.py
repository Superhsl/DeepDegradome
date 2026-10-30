"""Three-repeat CPU checks on frozen identical molecular inputs and original tools."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
from pathlib import Path
import argparse,hashlib,json,math,os,re,shutil,subprocess,sys,time

sys.path.append('/usr/lib/python3/dist-packages')
OUT=Path('/out');FIX=Path('/fixtures');SOURCE=Path('/source')

def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def execute(command,cwd,name,stdin=None,env=None,allowed=(0,)):
    start=time.perf_counter()
    input_file=open(cwd/stdin) if stdin else None
    try:
        with (cwd/(name+'.log')).open('w') as log:
            r=subprocess.run(command,cwd=cwd,stdin=input_file,stdout=log,stderr=subprocess.STDOUT,env=env)
    finally:
        if input_file:input_file.close()
    rec={'command':list(map(str,command)),'seconds':time.perf_counter()-start,'exitcode':r.returncode}
    save(cwd/(name+'-command.json'),rec)
    assert r.returncode in allowed,rec
    return rec

def basic():
    import numpy as np
    from rdkit import Chem,rdBase
    records=[]
    for repeat in range(1,4):
        d=OUT/('repeat-%02d'%repeat);d.mkdir()
        result={'repeat':repeat,'timings':{}}
        start=time.perf_counter();canon=[]
        for p in sorted((FIX/'cpu/sdf').glob('*.sdf')):
            m=Chem.SDMolSupplier(str(p))[0];assert m is not None
            target=d/(p.stem+'.mol2')
            execute(['babel',str(p),str(target)],d,'convert-'+p.stem)
            new=Chem.MolFromMol2File(str(target));assert new is not None
            assert Chem.MolToSmiles(new)==Chem.MolToSmiles(m)
            canon.append(Chem.MolToSmiles(new))
        result['timings']['rdkit_openbabel']=time.perf_counter()-start
        result['converted_canonical_smiles']=canon
        import pymol2
        start=time.perf_counter()
        with pymol2.PyMOL() as pm:
            cmd=pm.cmd;cmd.load(str(FIX/'cpu/molecules/case0.mol2'),'ligand')
            count=cmd.count_atoms('ligand');before=cmd.get_coords('ligand').copy()
            cmd.save(str(d/'pymol-roundtrip.mol2'),'ligand');cmd.reinitialize()
            cmd.load(str(d/'pymol-roundtrip.mol2'),'ligand')
            assert cmd.count_atoms('ligand')==count
            delta=float(np.max(np.abs(before-cmd.get_coords('ligand'))))
            assert delta<=1e-3
            cmd.reinitialize()
            pdb=('HETATM    1  C1  LIG X   1       0.000   0.000   0.000  1.00  0.00           C  \n'
                 'ATOM      2  CA  ALA A   1       2.000   0.000   0.000  1.00  0.00           C  \n'
                 'ATOM      3  CB  ALA A   1       6.000   0.000   0.000  1.00  0.00           C  \n'
                 'ATOM      4  CA  GLY A   2      10.000   0.000   0.000  1.00  0.00           C  \nEND\n')
            cmd.read_pdbstr(pdb,'complex');cmd.select('ligand','organic');cmd.select('surrounding','byres ligand around 5')
            selected=sorted((a.resn,a.name) for a in cmd.get_model('surrounding').atom)
            assert selected==[('ALA','CA'),('ALA','CB')]
            cmd.save(str(d/'pymol-pocket.mol2'),'surrounding')
        result['timings']['pymol']=time.perf_counter()-start
        result['pymol']={'atoms':count,'coordinate_roundtrip_max_error':delta,'selected':selected}
        pk=os.environ.get('CPU_PKCOMBU','/cpu-pkcombu')
        values={}
        for name,other in [('identity',1),('different',2)]:
            rec=execute([pk,'-A',str(FIX/'cpu/sdf/case0.sdf'),'-B',str(FIX/('cpu/sdf/case%d.sdf'%other)),'-oAm'],d,'pkcombu-'+name,allowed=(0,1))
            text=(d/('pkcombu-'+name+'.log')).read_text();marker='#   Nmcs|tani|seldis:'
            assert marker in text and '#ERROR' not in text
            values[name]=float(text[text.index(marker):].splitlines()[1].split()[3])
            result['timings']['pkcombu-'+name]=rec['seconds']
        assert values['identity']==1 and values['different']<1
        result['pkcombu']=values
        core=SOURCE/'eMolFrag/eMolFrag/eMolFrag_2017_06_19_01'
        cfg=d/'PathConfigure.log';cfg.write_text(str(core)+'/\n'+pk+'\n')
        env=dict(os.environ,EMOLFRAG_CONFIG=str(cfg))
        rec=execute([sys.executable,str(core/'eMolFrag.py'),'-i',str(FIX/'cpu/molecules'),'-o',str(d/'fragmented'),'-p','1','-m','0','-c','0'],d,'emolfrag',env=env)
        text=(d/'emolfrag.log').read_text(errors='replace')
        assert 'Error Code:' not in text and 'Traceback' not in text
        fragments={}
        for kind in ['brick','linker','chop-comb']:
            mols=[Chem.SDMolSupplier(str(p),sanitize=False)[0] for p in sorted((d/'fragmented'/('output-'+kind)).glob('*.sdf'))]
            assert mols and all(m is not None for m in mols)
            for m in mols:Chem.SanitizeMol(m)
            fragments[kind]=sorted(Chem.MolToSmiles(m) for m in mols)
        result['emolfrag']=fragments;result['timings']['emolfrag']=rec['seconds']
        records.append(result)
        save(OUT/'report.json',{'architecture':os.uname().machine,'rdkit':rdBase.rdkitVersion,'records':records})

def dock():
    records=[]
    bin=Path(os.environ.get('CPU_DOCK6','/cpu-dock6'))/'bin'
    for repeat in range(1,4):
        d=OUT/('repeat-%02d'%repeat);d.mkdir();times={};products={}
        for name in ['grid_generation','nchemgrid_GB_grid_generation','nchemgrid_SA_grid_generation','sphere_generation']:
            shutil.copytree(FIX/'dock6'/name,d/name)
        grid=d/'grid_generation';spheres=d/'sphere_generation'
        # Delete only known generated files in this fresh copied output tree.
        for folder,names in [(grid,['box.pdb','grid.bmp','grid.cnt','grid.nrg','grid.out']),
                             (spheres,['OUTSPH','struct.sph','selected_spheres.sph','selected_cluster.pdb'])]:
            for name in names:(folder/name).unlink(missing_ok=True)
        for name in ['nchemgrid_GB_grid_generation','nchemgrid_SA_grid_generation']:
            for p in (d/name).iterdir():
                if p.name in ['OUTCHEM','OUTPARM','NEG_INVA','inva','PDBPARM'] or p.name.startswith('zou_grid.'):
                    p.unlink()
        content=(grid/'grid.in').read_text()
        content=re.sub(r'(?m)^vdw_definition_file\s+.*$','vdw_definition_file /fixtures/dock6/vdw_AMBER_parm99.defn',content)
        (grid/'grid.in').write_text(content)
        jobs=[('showbox',grid,[], 'box.in'),('grid',grid,['-i','grid.in','-o','grid.out'],None),
              ('nchemgrid_GB',d/'nchemgrid_GB_grid_generation',[],None),
              ('nchemgrid_SA',d/'nchemgrid_SA_grid_generation',[],None),
              ('sphgen',spheres,[],None),('sphere_selector',spheres,['struct.sph','lig.mol2','3.0'],None),
              ('showsphere',spheres,[],'select.in')]
        for name,cwd,args,stdin in jobs:
            rec=execute([str(bin/name)]+args,cwd,name,stdin=stdin);times[name]=rec['seconds']
        for folder,names in [(grid,['box.pdb','grid.bmp','grid.cnt','grid.nrg']),
                             (d/'nchemgrid_GB_grid_generation',['zou_grid.bmp','zou_grid.rec','zou_grid.sol','zou_grid.vdw']),
                             (d/'nchemgrid_SA_grid_generation',['zou_grid.bmp','zou_grid.sas','zou_grid.sasmark']),
                             (spheres,['struct.sph','selected_spheres.sph','selected_cluster.pdb'])]:
            for name in names:
                p=folder/name;assert p.is_file() and p.stat().st_size
                products[str(p.relative_to(d))]={'bytes':p.stat().st_size,'sha256':sha(p)}
        records.append({'repeat':repeat,'timings':times,'products':products})
        save(OUT/'report.json',{'architecture':os.uname().machine,'records':records})

def rosetta():
    records=[]
    rosetta=Path(os.environ['ROSETTA_FOL'])
    for repeat in range(1,4):
        d=OUT/('repeat-%02d'%repeat);d.mkdir()
        for name in ['pd.1.pdb','War.params','E3l.params']:shutil.copy2(FIX/'rosetta'/name,d/name)
        command=[str(rosetta/'main/source/bin/rosetta_scripts.default.linuxgccrelease'),'-s','pd.1.pdb',
                 '-parser:protocol',str(SOURCE/'Rosetta/docking.xml'),'@'+str(SOURCE/'Rosetta/docking.flags'),
                 '@'+str(SOURCE/'Rosetta/relax.flags'),'-extra_res_fa','War.params','-extra_res_fa','E3l.params',
                 '-partners','AX_BY','-scorefile','local.fasc','-nstruct','1','-overwrite',
                 '-database',str(rosetta/'main/database'),'-constant_seed','-jran','1001']
        rec=execute(command,d,'rosetta',allowed=(0,255))
        lines=[x.split()[1:] for x in (d/'local.fasc').read_text().splitlines() if x.startswith('SCORE:')]
        header=next(x for x in lines if 'description' in x)
        rows=[dict(zip(header,x)) for x in lines if 'description' not in x]
        assert len(rows)==1 and (d/'pd.1_docking_0001.pdb').is_file()
        rec.update(repeat=repeat,scores=rows[0],pdb_sha256=sha(d/'pd.1_docking_0001.pdb'))
        records.append(rec);save(OUT/'report.json',{'architecture':os.uname().machine,'records':records,'seed':1001,'nstruct':1})

def params():
    records=[]
    for repeat in range(1,4):
        d=OUT/('repeat-%02d'%repeat);d.mkdir();rows=[]
        for code,filename in [('War','compound4_H.sdf'),('E3l','CRBN_ligand_H.sdf')]:
            rec=execute(['python',os.environ['ROSETTA_FOL']+'/main/source/scripts/python/public/molfile_to_params.py',
                         str(FIX/'rosetta'/filename),'-n',code,'-p',code,'--clobber'],d,code)
            assert (d/(code+'.params')).is_file() and (d/(code+'_0001.pdb')).is_file()
            rec.update(ligand=code,params_sha256=sha(d/(code+'.params')),pdb_sha256=sha(d/(code+'_0001.pdb')))
            rows.append(rec)
        records.append({'repeat':repeat,'records':rows});save(OUT/'report.json',{'architecture':os.uname().machine,'records':records})

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('stage',choices=['basic','dock','rosetta','params']);args=a.parse_args()
    assert not Path('/dev/tcaicard0').exists(),'CPU control must not expose SDAA'
    assert os.environ.get('CUDA_VISIBLE_DEVICES','')=='','CPU control must not expose CUDA'
    globals()[args.stage]()
