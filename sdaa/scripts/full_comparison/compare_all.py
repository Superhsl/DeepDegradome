"""Compare retained raw outputs, without suppressing scientific mismatches."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import os
PROJECT_ROOT = Path(os.environ.get('DEEPDEGRADOME_PROJECT', SOURCE_ROOT.parent)).resolve()
import argparse,itertools,json,math,re,statistics,subprocess,sys
from pathlib import Path

def read(p):return json.loads(p.read_text())
def med(x):return statistics.median(x)
def pair(a,b):return {'gpu1_seconds':med(a),'loong_seconds':med(b),'loong_over_gpu1':med(b)/med(a)}
def timing_reports(a,b):
    keys=a[0]['timings'].keys()
    return {k:pair([r['timings'][k] for r in a],[r['timings'][k] for r in b]) for k in keys}
def pdb(p):
    result=[]
    for line in p.read_text().splitlines():
        if line.startswith(('ATOM  ','HETATM')):
            result.append((line[12:27],tuple(float(line[i:i+8]) for i in [30,38,46])))
    return result
def pdb_delta(p,q):
    a,b=pdb(p),pdb(q);same=[r[0] for r in a]==[r[0] for r in b]
    d=[sum((x-y)**2 for x,y in zip(u[1],v[1])) for u,v in zip(a,b)] if same else []
    return {'atoms_gpu1':len(a),'atoms_loong':len(b),'atom_keys_equal':same,
            'rmsd_angstrom':math.sqrt(sum(d)/len(d)) if d else None,
            'max_angstrom':math.sqrt(max(d)) if d else None,'alignment':'none'}
def mol2_records(p):
    records=[]
    for chunk in p.read_text().split('@<TRIPOS>MOLECULE')[1:]:
        atoms=chunk.split('@<TRIPOS>ATOM',1)[1].split('@<TRIPOS>',1)[0]
        bonds=chunk.split('@<TRIPOS>BOND',1)[1].split('@<TRIPOS>',1)[0] if '@<TRIPOS>BOND' in chunk else ''
        aa=[r.split() for r in atoms.splitlines() if r.strip()]
        records.append({'labels':[(r[0],r[1],*r[5:8]) for r in aa],
                        'values':[[float(v) for v in r[2:5]+r[8:9]] for r in aa],
                        'bonds':[r.split()[1:] for r in bonds.splitlines() if r.strip()]})
    return records
def mol2_delta(p,q):
    a,b=mol2_records(p),mol2_records(q)
    labels=len(a)==len(b) and all(x['labels']==y['labels'] and x['bonds']==y['bonds'] for x,y in zip(a,b))
    err=max((abs(u-v) for x,y in zip(a,b) for xx,yy in zip(x['values'],y['values']) for u,v in zip(xx,yy)),default=0) if labels else None
    return {'molecules_gpu1':len(a),'molecules_loong':len(b),'atom_types_and_bonds_equal':labels,'max_coordinate_or_charge_error':err,'passed':labels and err<=1e-5}

def main():
    p=argparse.ArgumentParser();p.add_argument('--gpu',type=Path,required=True);p.add_argument('--loong',type=Path,required=True)
    p.add_argument('--gpu-cpu',default='cpu-controls');p.add_argument('--loong-cpu',default='cpu-controls')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    g,l=a.gpu,a.loong;gc,lc=g/a.gpu_cpu,l/a.loong_cpu
    report={'scope':'Current representative tool cases (3 repetitions), bounded public-PDB workflow (1 per host), no experimental accuracy claim.',
            'numerical_tolerances':{'general_mol2':1e-5,'pdb_rmsd_angstrom':1e-3,'pdb_max_angstrom':2e-3,'charge_e':1e-4},
            'cpu_execution_completed':all(read(x/'completion.json')['execution_completed'] for x in [gc,lc]),'tools':{}}
    # All output transformation rows, not only the ten-row preview.
    gp,lp=[read(x/'translation-three-repeats/progress.json') for x in [g,l]]
    for tool in ['patchdock','cyndi','ifit_eval','ifit_dock']:
        ga=[r for r in gp['jobs'] if r['tool']==tool];la=[r for r in lp['jobs'] if r['tool']==tool]
        r={'timing':pair([x['seconds'] for x in ga],[x['seconds'] for x in la]),'comparisons':[]}
        for x,y in zip(ga,la):
            gd=g/'translation-three-repeats'/('%s-%02d'%(tool,x['repeat']));ld=l/'translation-three-repeats'/('%s-%02d'%(tool,y['repeat']))
            d={'repeat':x['repeat'],'execution_ok':all(z['functional_output_present'] and not z['timed_out'] for z in [x,y])}
            if tool=='patchdock':
                rows=lambda f:[r.strip() for r in f.read_text().splitlines() if re.match(r'^\s*\d+\s*\|',r)]
                xx,yy=rows(gd/'result.txt'),rows(ld/'result.txt');d.update(rows_gpu1=len(xx),rows_loong=len(yy),all_transformation_rows_equal=xx==yy)
                d['passed']=xx==yy and len(xx)>0
            else:
                names={'cyndi':['result.mol2'],'ifit_eval':['probe_scored.mol2','probe_sorted.mol2'],'ifit_dock':['probe.mol2']}[tool]
                d['mol2']={n:mol2_delta(gd/n,ld/n) for n in names}
                lists=['probe_scored.list'] if tool!='cyndi' else []
                d['score_rows_equal']={n:[x.split() for x in (gd/n).read_text().splitlines()]==[x.split() for x in (ld/n).read_text().splitlines()] for n in lists}
                d['passed']=all(x['passed'] for x in d['mol2'].values()) and all(d['score_rows_equal'].values())
            r['comparisons'].append(d)
        r['passed']=all(x['passed'] for x in r['comparisons']);report['tools'][tool]=r
    report['closed_tool_scope']='Identical unmodified x86 programs, native x86 versus LATX on Loong CPU. iFit positive controls have relaxed score cutoff; no production hit claim. Seeds/time fixed for diagnostic Cyndi/iFit controls.'
    for stage in ['basic','dock','params','rosetta']:
        xx,yy=[read(x/stage/'report.json')['records'] for x in [gc,lc]]
        if stage=='basic':
            keys=['converted_canonical_smiles','pkcombu','emolfrag']
            checks=[{k:x[k]==y[k] for k in keys} for x,y in zip(xx,yy)]
            pm=[x['pymol']['atoms']==y['pymol']['atoms'] and x['pymol']['selected']==y['pymol']['selected'] for x,y in zip(xx,yy)]
            report['tools'][stage]={'timing':timing_reports(xx,yy),'chemical_outputs_equal':checks,'pymol_counts_selection_equal':pm,'passed':all(all(c.values()) for c in checks) and all(pm)}
        elif stage=='dock':
            checks=[{k:x['products'][k]==y['products'][k] for k in x['products']} for x,y in zip(xx,yy)]
            report['tools'][stage]={'timing':timing_reports(xx,yy),'product_hashes_equal':checks,'passed':all(all(c.values()) for c in checks)}
        elif stage=='params':
            checks=[{x['ligand']:all(x[k]==y[k] for k in ['params_sha256','pdb_sha256']) for x,y in zip(u['records'],v['records'])} for u,v in zip(xx,yy)]
            tm={name:pair([next(z['seconds'] for z in r['records'] if z['ligand']==name) for r in xx],[next(z['seconds'] for z in r['records'] if z['ligand']==name) for r in yy]) for name in ['War','E3l']}
            report['tools'][stage]={'timing':tm,'product_hashes_equal':checks,'passed':all(all(c.values()) for c in checks)}
        else:
            scorekeys=[k for k in xx[0]['scores'] if k!='description']
            checks=[]
            for i,j in itertools.product(range(3),repeat=2):
                delta=pdb_delta(gc/stage/('repeat-%02d'%(i+1))/'pd.1_docking_0001.pdb',lc/stage/('repeat-%02d'%(j+1))/'pd.1_docking_0001.pdb')
                err=max(abs(float(xx[i]['scores'][k])-float(yy[j]['scores'][k])) for k in scorekeys)
                checks.append({'gpu_repeat':i+1,'loong_repeat':j+1,'max_printed_score_error':err,'pdb':delta,
                               'passed':err<=1e-3 and delta['atom_keys_equal'] and delta['rmsd_angstrom']<=1e-3 and delta['max_angstrom']<=2e-3})
            report['tools'][stage]={'timing':pair([x['seconds'] for x in xx],[x['seconds'] for x in yy]),'cross_nine_pairs':checks,'passed':all(c['passed'] for c in checks)}
    chim=[];helper=Path(__file__).with_name('compare_chimera_preparation.py')
    for scope in ['cross','within-gpu','within-loong']:
        pairs=list(itertools.product(range(1,4),repeat=2)) if scope=='cross' else list(itertools.combinations(range(1,4),2))
        for i,j in pairs:
            left,right=(gc,lc) if scope=='cross' else (gc,gc) if scope=='within-gpu' else (lc,lc)
            for cases,filename in [(['WDR5','CRBN'],'target.mol2'),(['compound4','CRBN_ligand'],'ligand.mol2')]:
                name='%s-%d-%d-%s.json'%(scope,i,j,filename)
                command=[sys.executable,str(helper),'--reference',str(left/('chimera-%02d'%i)/'preparation'),
                         '--native',str(right/('chimera-%02d'%j)/'preparation'),'--cases',*cases,'--filename',filename,'--output',str(a.output/name)]
                r=subprocess.run(command,capture_output=True,text=True);assert r.returncode in [0,1],r.stderr
                data=read(a.output/name);data.update(scope=scope,repeat_left=i,repeat_right=j);chim.append(data)
    report['tools']['chimera']={'comparisons':chim,'cross_passed':all(x['passed'] for x in chim if x['scope']=='cross'),
                               'within_gpu_passed':all(x['passed'] for x in chim if x['scope']=='within-gpu'),
                               'within_loong_passed':all(x['passed'] for x in chim if x['scope']=='within-loong'),
                               'timing':pair([read(gc/('chimera-%02d'%i)/'launcher-status.json')['wall_seconds'] for i in range(1,4)],[read(lc/('chimera-%02d'%i)/'launcher-status.json')['wall_seconds'] for i in range(1,4)])}
    report['pipelines']={}
    for name,root in [('gpu1',g),('loong',l)]:
        complete=root/'pipeline-completion.json';summary=root/'end-to-end/pipeline-summary.json'
        report['pipelines'][name]={'execution_completed':complete.exists(),'completion':read(complete) if complete.exists() else None,
                                   'summary':read(summary) if summary.exists() else None,'completed_stages':read(root/'pipeline-progress.json')}
    protocol=[read(x/'pipeline-protocol.json') for x in [g,l]]
    report['raw_inputs_equal']=protocol[0]['raw_inputs_sha256']==protocol[1]['raw_inputs_sha256']
    gw,lw=[x['source_assets_sha256'] for x in protocol]
    shared_weights=sorted(k for k in gw.keys()&lw.keys() if Path(k).suffix in ['.pickle','.pth'])
    report['shared_model_weight_files']=len(shared_weights)
    report['shared_model_weights_equal']=bool(shared_weights) and all(gw[k]==lw[k] for k in shared_weights)
    report['differing_shared_weight_files']=[k for k in shared_weights if gw[k]!=lw[k]]
    assert report['shared_model_weights_equal'],'Model weight mismatch'
    report['fixtures_equal']=read(gc/'protocol.json')['fixture_manifest']==read(lc/'protocol.json')['fixture_manifest']
    variants=l/'generator-variants/completion.json'
    if variants.exists():report['three_generator_checkpoints']=read(variants)
    report['all_execution_completed']=report['cpu_execution_completed'] and all(v['execution_completed'] for v in report['pipelines'].values())
    (a.output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'all_execution_completed':report['all_execution_completed'],'tools':{k:v.get('passed',v.get('cross_passed')) for k,v in report['tools'].items()},'raw_inputs_equal':report['raw_inputs_equal'],'fixtures_equal':report['fixtures_equal']},indent=2))

if __name__=='__main__':main()
