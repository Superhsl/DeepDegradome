"""Create fixed prepared-pose and upstream example generation configurations."""

from pathlib import Path
import sys
SOURCE_ROOT = next(p for p in [*Path(__file__).resolve().parents, Path('/source')] if (p/'DEVELOP').is_dir() and (p/'sdaa').is_dir())
sys.path.insert(0, str(SOURCE_ROOT))
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--project',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
common={'generation':True,'batch_size':1,'number_of_generation_per_valid':50,'num_epochs':1,'epoch_to_generate':1,'random_seed':0}
for pose in ['pd.1_docking_0001','pd.5_docking_0006']:
    raw=Path('/kit/inputs/generation-poses')/pose
    host=a.project/'migration/DeepDegradome-migration-kit-20261016-02/inputs/generation-poses'/pose
    name='molecules_'+pose+'_out.json'
    dist=float(json.loads((host/name).read_text())[0]['abs_dist'][0])
    config=dict(common,train_file=str(raw/name),valid_file=str(raw/name),train_struct_file=str(raw/(pose+'.types')),
                valid_struct_file=str(raw/(pose+'.types')),struct_data_root=str(raw),output_name=pose,
                min_atoms=max(0,round(dist)-2),max_atoms=round(dist)+2)
    (a.output/(pose+'.json')).write_text(json.dumps(config,indent=2)+'\n')
raw=Path('/source/DEVELOP/examples')
config=dict(common,train_file=str(raw/'molecules_linker_design_test.json'),valid_file=str(raw/'molecules_linker_design_test.json'),
            train_struct_file=str(raw/'linker_design_example.types'),valid_struct_file=str(raw/'linker_design_example.types'),
            struct_data_root=str(raw),output_name='official_linker_design')
(a.output/'official.json').write_text(json.dumps(config,indent=2)+'\n')
