"""Developer-only: resolve official metadata; does not download model weights."""
import json, subprocess
from pathlib import Path
models=[]
for id, suffix, prefix, precision in [('bark','', 'coreml/ane/', 'Core ML quantized encoder'),('bark-plus','-Plus','coreml/ane/','Core ML mixed-precision encoder'),('bark-pro','-Pro','coreml/','Core ML FP16 export (BF16 original)')]:
    repo='ConwayResearch/Underdog-Bark-3.0'+suffix
    def get(url): return json.loads(subprocess.check_output(['curl','-fsSL','--max-time','60',url]))
    api=get('https://huggingface.co/api/models/'+repo)
    revision=api['sha']
    tree=get('https://huggingface.co/api/models/'+repo+'/tree/'+revision+'/'+prefix.rstrip('/')+'?recursive=true&expand=true&limit=100')
    files=[]
    for row in tree:
        if row['type']!='file' or row['path'].endswith('.py'):continue
        rel=row['path'][len(prefix):]
        files.append({'path':rel,'size':row['size'],'sha256':row.get('lfs',{}).get('oid')})
    models.append({'id':id,'name':'Bark 3.0'+suffix.replace('-',' '),'repository':repo,'revision':revision,'prefix':prefix,'precision':precision,'files':files})
Path('Sources/DictateCore/Resources/models.json').write_text(json.dumps(models,indent=2)+'\n')
for m in models: print(m['name'],m['revision'],len(m['files']),sum(f['size'] for f in m['files']))
