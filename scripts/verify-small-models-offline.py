"""Verify the packaged lazy-load path; requires installed models and local WAV fixtures.
No download or system-service changes. Each owned process is bounded to 240 seconds.
"""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--short',required=True,type=Path)
p.add_argument('--long',required=True,type=Path,help='Same phrase repeated three times, over 7.75 seconds')
p.add_argument('--output',required=True,type=Path)
a=p.parse_args();root=Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
binary=root/'dist/Dictate Unlimited.app/Contents/MacOS/DictateUnlimited'
profile=out/'offline.sb';profile.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny mach-lookup (global-name "com.apple.nsurlsessiond"))\n(deny mach-lookup (global-name "com.apple.nsurlsessiond_privileged"))\n(deny file-read* (subpath '+json.dumps(str(root/'.build'))+'))\n')
expected='this is a local dictation test for dictate unlimited'.split()
catalog=json.loads((root/'Sources/DictateCore/Resources/models.json').read_text())
summary={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'fixtures':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.short,a.long]},'runs':[]}
for mid in ['bark','bark-plus']:
 m=next(x for x in catalog if x['id']==mid);folder=Path.home()/'Library/Application Support/DOO MADE/Dictate Unlimited/Models'/f"{mid}-{m['revision']}"
 for case,files,answers,loads in [('short',[a.short],[expected],['w8']),('long-reuse',[a.short,a.long,a.long],[expected,expected*3,expected*3],['w8','w15']),('warm-short',[a.short],[expected],['w8'])]:
  cmd=['/usr/bin/sandbox-exec','-f',str(profile),str(binary),'--transcribe',mid,str(folder),*[str(f.resolve()) for f in files]]
  env=dict(os.environ,DU_MODEL_LOAD_TIMINGS='1');start=time.monotonic()
  with (out/f'{mid}-{case}.out').open('wb') as stdout,(out/f'{mid}-{case}.err').open('wb') as stderr:
   try: status=subprocess.run(cmd,stdout=stdout,stderr=stderr,env=env,timeout=240).returncode
   except subprocess.TimeoutExpired: status='timeout240s'
  output=(out/f'{mid}-{case}.out').read_text();trace=(out/f'{mid}-{case}.err').read_text()
  actual=[re.findall(r'[a-z0-9]+',line.lower()) for line in output.splitlines() if line.strip()]
  observed=re.findall(r'\[model-load\] begin (w\d+)',trace)
  row={'model':mid,'case':case,'seconds':time.monotonic()-start,'exit':status,'transcript_match':actual==answers,'encoder_loads':observed,'expected_loads':loads}
  row['passed']=status==0 and actual==answers and observed==loads
  summary['runs'].append(row);(out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(row),flush=True)
  if not row['passed']: raise SystemExit('Verification failed; inspect retained output')
