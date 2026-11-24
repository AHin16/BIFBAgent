"""Tentative experiment metadata extracted from the selected original path."""
from pathlib import Path
import re
from optimization_data.scan import parse

CFG={'ug_per_q':.00325,'heights_m':{'H1':.2,'H2':.8,'H3':1.2,'H4':1.8}}
CONFIRMED_H3={'盐水不同气泡1','盐水不同照片2'}
CONFIRMED_PL={'q=1.8,2.5wt%,15%_files':.15,'q=1.5,2.5wt%,10%_files':.10}


def metadata_from_path(path):
    path=Path(path)
    parts=[p.name for p in path.parents]
    condition=next((name for name in parts if re.search(r'\bQ\s*=',name,re.I)),None)
    if not condition:
        return {'values':{},'message':'原路径中未找到实验工况文件夹，请手动填写。','source':'unavailable'}
    meta=parse(condition,CFG)
    roots={name.casefold() for name in parts}
    h3=bool(roots & {name.casefold() for name in CONFIRMED_H3})
    values={}
    for src,dst in [('Q_m3_h','current_q'),('salinity_wt_pct','salinity_wt_pct'),('PL_fraction','PL_fraction'),('height_m','height_m')]:
        if meta.get(src) is not None and ('ambiguous '+src) not in meta['parse_status']:
            values[dst]=meta[src]
    if h3 and not meta.get('height_id') and 'ambiguous height_id' not in meta['parse_status']:
        values['height_m']=1.2
    if h3 and 'PL_fraction' not in values and condition.casefold() in CONFIRMED_PL:
        values['PL_fraction']=CONFIRMED_PL[condition.casefold()]
    missing=[label for key,label in [('current_q','Q'),('height_m','高度'),('salinity_wt_pct','盐度'),('PL_fraction','PL')] if key not in values]
    message='已按原路径识别工况，请核对，可手动修改。'
    if missing: message+=' 未识别：'+'、'.join(missing)+'，请手动填写。'
    return {'values':values,'message':message,'source':'folder_name','condition_folder':condition,
            'height_source':'用户确认的 H3 目录' if h3 and not meta.get('height_id') else '文件夹标记'}
