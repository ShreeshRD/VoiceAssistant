"""Explicit developer model acquisition for local smoke tests. No audio is sent."""
import hashlib,json,subprocess,sys,uuid,shutil
from pathlib import Path
catalog=json.loads(Path('Sources/DictateCore/Resources/models.json').read_text()) + json.loads(Path('Sources/DictateCore/Resources/whisper-models.json').read_text())
m=next(x for x in catalog if x['id']==sys.argv[1])
root=Path.home()/'Library/Application Support/DOO MADE/Dictate Unlimited/Models'
root.mkdir(parents=True,exist_ok=True)
final=root/(m['id']+'-'+m['revision'])
if (final/'.complete').exists(): print(final);sys.exit(0)
staging=root/('.partial-'+str(uuid.uuid4()));staging.mkdir()
try:
 for f in m['files']:
  dest=staging/f['path'];dest.parent.mkdir(parents=True,exist_ok=True)
  repo=f.get('sourceRepository',m['repository']);rev=f.get('sourceRevision',m['revision']);remote=f.get('sourcePath',m['prefix']+f['path'])
  url=f"https://huggingface.co/{repo}/resolve/{rev}/{remote}"
  subprocess.run(['curl','-fL','--retry','2','--max-time','600',url,'-o',str(dest)],check=True)
  assert dest.stat().st_size==f['size'],f['path']
  if f['sha256']:
   with dest.open('rb') as handle: actual=hashlib.file_digest(handle,'sha256').hexdigest()
   assert actual==f['sha256'],f['path']
 (staging/'.complete').write_text(m['revision'])
 staging.rename(final);print(final)
finally:
 if staging.exists():shutil.rmtree(staging)
