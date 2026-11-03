"""Package the complete authoring workspace, excluding obsolete draft exports."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parents[1]
target=root.parent/'AgentArts_BIFB_完整源文件与代码.zip'
primary='AgentArts_BIFB_竞赛汇报_20页.pptx'
files=[]
for p in sorted(root.rglob('*')):
    if not p.is_file():continue
    rel=p.relative_to(root)
    if '__pycache__' in rel.parts or p.suffix in {'.tmp','.pyc'}:continue
    if rel.parts[0]=='exports' and p.name!=primary:continue
    if rel.parts[0]=='validation' and p.name.startswith('agentarts_bifb_20261103_final_'):continue
    if p.name=='delivery_manifest.json':continue
    files.append(p)
manifest={'project':'AgentArts × BIFB 20页竞赛汇报','primary_pptx':'exports/'+primary,
          'files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,
                    'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
manifest_path=root/'delivery_manifest.json'
manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
files.append(manifest_path)
with ZipFile(target,'w',ZIP_DEFLATED,compresslevel=6) as z:
    for p in files:z.write(p,'AgentArts_BIFB_Source/'+p.relative_to(root).as_posix())
with ZipFile(target) as z:assert z.testzip() is None
print(json.dumps({'archive':str(target),'files':len(files),'bytes':target.stat().st_size},ensure_ascii=False,indent=2))
