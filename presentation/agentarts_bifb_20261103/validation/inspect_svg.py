from pathlib import Path
from xml.etree import ElementTree as E
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

base = Path(__file__).resolve().parents[1]
for p in sorted((base/'authoring-svg-flat').glob('slide_*.svg')):
    root = E.parse(p).getroot()
    print('\n'+p.name, {k:v for k,v in root.attrib.items() if not k.startswith('data-pptx-')})
    for child in root:
        if child.tag.endswith('defs'):
            continue
        text = ' | '.join(''.join(t.itertext()).strip() for t in child.iter() if t.tag.endswith('}text'))
        print(json.dumps({'tag':child.tag.split('}')[-1], 'attrs':{k:v for k,v in child.attrib.items() if len(v)<200},'text':text[:800]},ensure_ascii=False))
