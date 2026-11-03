"""Remove obsolete source-slide OLE equations before a fresh round-trip import.

The supplied deck's legacy embedded equation objects cannot be dropped by the
round-trip exporter. This repairs the owning source artifact in a NEW package.
Masters, layouts, themes, and all non-slide parts retain their original bytes.
The source file is never overwritten. All affected slide bodies are replaced
in the confirmed content mapping; no old equation is used as new evidence.
"""
from pathlib import Path
import copy
import json
import posixpath
import sys
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as E

sys.stdout.reconfigure(encoding='utf-8')
source=Path(sys.argv[1]); target=Path(sys.argv[2])
if source.resolve()==target.resolve():
    raise SystemExit('Refusing to overwrite source')
P='http://schemas.openxmlformats.org/presentationml/2006/main'
R='http://schemas.openxmlformats.org/package/2006/relationships'
E.register_namespace('p',P)
E.register_namespace('a','http://schemas.openxmlformats.org/drawingml/2006/main')
E.register_namespace('r','http://schemas.openxmlformats.org/officeDocument/2006/relationships')
changed={}; removed_shapes=0; removed_rels=0
with ZipFile(source) as zin:
    for name in zin.namelist():
        if name.startswith('ppt/slides/slide') and name.endswith('.xml'):
            root=E.fromstring(zin.read(name)); count=0
            for parent in list(root.iter()):
                for ch in list(parent):
                    if ch.tag in {f'{{{P}}}graphicFrame',f'{{{P}}}sp',f'{{{P}}}pic'} and any(e.tag==f'{{{P}}}oleObj' for e in ch.iter()):
                        parent.remove(ch); count+=1
            if count:
                changed[name]=E.tostring(root,encoding='utf-8',xml_declaration=True);removed_shapes+=count
        elif name.startswith('ppt/slides/_rels/slide') and name.endswith('.rels'):
            root=E.fromstring(zin.read(name)); count=0
            for rel in list(root):
                if rel.get('Type','').endswith('/oleObject'):
                    root.remove(rel);count+=1
            if count:
                changed[name]=E.tostring(root,encoding='utf-8',xml_declaration=True);removed_rels+=count
    target.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(target,'w',ZIP_DEFLATED) as zout:
        for info in zin.infolist():zout.writestr(copy.copy(info),changed.get(info.filename,zin.read(info.filename)))
    protected=[n for n in zin.namelist() if n.startswith(('ppt/slideMasters/','ppt/slideLayouts/','ppt/theme/'))]
    with ZipFile(target) as zout:
        assert all(zin.read(n)==zout.read(n) for n in protected),'Template style changed'
report={'source':str(source),'prepared_copy':str(target),'removed_obsolete_equation_shapes':removed_shapes,
        'removed_ole_relationships':removed_rels,'changed_parts':list(changed),
        'master_layout_theme_parts_unchanged':len(protected)}
target.with_suffix('.preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
