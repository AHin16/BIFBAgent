"""Validate delivered content, editability, and template preservation."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
import hashlib
import json
import sys
from pptx import Presentation

sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parents[1]
deck=root/'exports'/'AgentArts_BIFB_竞赛汇报_20页.pptx'
prs=Presentation(deck)

def walk(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == 6:
            yield from walk(shape.shapes)

pages=[]
for i,slide in enumerate(prs.slides,1):
    shapes=list(walk(slide.shapes))
    texts=[s.text for s in shapes if s.has_text_frame and s.text.strip()]
    note=slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''
    pages.append({'page':i,'text':'\n'.join(texts),'placeholder_count':sum(t.count('图片占位符') for t in texts),
                  'slide_local_editable_text_shapes':len(texts),'slide_local_shapes':len(shapes),
                  'speaker_notes_characters':len(note),'notes':note})
assert len(pages)==20
assert sum(p['placeholder_count'] for p in pages)==22
assert all(p['speaker_notes_characters']>30 for p in pages)
assert all(p['slide_local_editable_text_shapes']>=3 for p in pages)
assert all(word in pages[4]['text'] for word in ['0.970','0.941','6.26M','27.5','13 MB'])
assert '二维投影面积占比不等于三维真实气含率' in pages[10]['text']
assert pages[17]['text'].count('计划评估')>=4
assert '离线决策支持' in pages[12]['text']
assert '待补充' in pages[0]['text']
for p in pages:
    assert not any(s in p['text']+p['notes'] for s in ['老大','我认为初赛','这篇论文我还没看过'])

with ZipFile(root/'sources'/'original_template.pptx') as original, ZipFile(deck) as final:
    retained=[]; missing=[]; changed=[]
    for n in original.namelist():
        if n.startswith(('ppt/slideMasters/','ppt/slideLayouts/','ppt/theme/')) and n.endswith('.xml'):
            if n not in final.namelist():missing.append(n)
            elif original.read(n)==final.read(n):retained.append(n)
            else:changed.append(n)
    assert not missing and not changed, (missing,changed)
    active_ole=0
    for i in range(1,21):
        part=E.fromstring(final.read(f'ppt/slides/slide{i}.xml'))
        active_ole+=sum(e.tag.endswith('}oleObj') for e in part.iter())
    assert active_ole==0

report={'status':'passed','slides':20,'speaker_notes_pages':20,'image_placeholder_count':22,
        'editable_text_shapes':sum(p['slide_local_editable_text_shapes'] for p in pages),
        'native_master_layout_theme_xml_parts_unchanged':len(retained),
        'changed_master_layout_theme_parts':changed,'missing_master_layout_theme_parts':missing,
        'old_ole_equations_on_active_slides':active_ole,'source_template_sha256':hashlib.sha256((root/'sources'/'original_template.pptx').read_bytes()).hexdigest(),
        'output_sha256':hashlib.sha256(deck.read_bytes()).hexdigest(),
        'per_page':[ {k:v for k,v in p.items() if k not in ['text','notes']} for p in pages ]}
(root/'validation'/'content_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='per_page'},ensure_ascii=False,indent=2))
