"""Resumable image-level extraction using the existing YOLO adapter, no NAS writes."""
import argparse
import csv
from contextlib import closing
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
from app.config import load_settings, local_path
from app.yolo_adapter import YoloAdapter
from app.vision import source_hash
from optimization_data.extract_pilot import Capture

INDEX=ROOT/'data/ug_match_planning/20261113_125912/image_sequence_manifest.csv'
OUT=ROOT/'data/h3_confirmed'


def stats(values):
    if not values: return {'count':0,'d10_px':None,'d50_px':None,'d90_px':None,'mean_px':None}
    a=np.asarray(values,dtype=float)
    return {'count':len(a),'d10_px':float(np.percentile(a,10)),'d50_px':float(np.median(a)),
            'd90_px':float(np.percentile(a,90)),'mean_px':float(a.mean())}


def selected_images():
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        rows=[]
        for original in csv.DictReader(stream):
            root=original["source_root"].replace("/", "\\").rstrip("\\")
            if root.split("\\")[-1] not in ("盐水不同气泡1", "盐水不同照片2"):
                continue
            if original["height_id"] or original["height_m"]:
                raise ValueError("Unexpected existing height; inspect before applying H3")
            if original["parse_status"] != "ok" or original["dedup_keep"].lower() != "true":
                continue
            row=dict(original)
            row.update(height_id="H3", height_m="1.2", height_source="user_confirmation_2026-11-15")
            rows.append(row)
    if not rows or len({r["image_id"] for r in rows}) != len(rows):
        raise ValueError("Empty index or duplicate image IDs")
    hashes=[r["sha256_duplicate"] for r in rows if r["sha256_duplicate"]]
    if len(hashes) != len(set(hashes)):
        raise ValueError("Duplicate content in selected images")
    return rows


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--limit',type=int); parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--shard-index',type=int,default=0); parser.add_argument('--shard-count',type=int,default=1)
    args=parser.parse_args(); output=args.output.resolve()
    if not output.is_relative_to(OUT.resolve()): parser.error('output must be inside data/h3_confirmed')
    output.mkdir(parents=True,exist_ok=True)
    rows=selected_images()
    if args.limit: rows=rows[:args.limit]
    if args.shard_count<1 or not 0<=args.shard_index<args.shard_count: parser.error('invalid shard')
    rows=rows[args.shard_index::args.shard_count]
    settings=load_settings().model_copy(update={'mm_per_pixel':None,'confidence':.25})
    weights=local_path(settings.yolo_model_path)
    with weights.open('rb') as f: weight_hash=hashlib.file_digest(f,'sha256').hexdigest()
    import ultralytics
    manifest={'index_sha256':hashlib.sha256(INDEX.read_bytes()).hexdigest(), 'weights_sha256':weight_hash,
              'confidence':.25,'unit':'px','backend_hash':source_hash('predictor.py','image_io.py'),
              'ultralytics_version':ultralytics.__version__, 'height_source':'user_confirmation_2026-11-15', 'scope_count':len(rows), 'limit':args.limit,
              **({'shard_index':args.shard_index,'shard_count':args.shard_count} if args.shard_count>1 else {})}
    old=ROOT/'data/optimization_pilot/multi_20261112/manifest.json'
    if json.loads(old.read_text(encoding='utf-8'))['weights_sha256']!=weight_hash: raise ValueError('YOLO weight differs from previous pilot')
    manifest_path=output/'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8'))!=manifest:
        raise ValueError('Configuration differs from existing run; choose another output directory')
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    conn=sqlite3.connect(output/'measurements.sqlite3')
    conn.execute('CREATE TABLE IF NOT EXISTS images (image_id TEXT PRIMARY KEY, metadata TEXT NOT NULL, status TEXT NOT NULL, error TEXT, result TEXT, seconds REAL)')
    done={r[0] for r in conn.execute("SELECT image_id FROM images WHERE status='success'")}
    if output!=OUT.resolve() and args.shard_count>1 and args.limit is None:
        for previous_dir in (OUT,OUT/'shard0',OUT/'shard1'):
            base=previous_dir/'measurements.sqlite3'
            if not base.exists() or previous_dir.resolve()==output: continue
            baseline=json.loads((previous_dir/'manifest.json').read_text(encoding='utf-8'))
            if any(manifest[k]!=baseline[k] for k in ('index_sha256','weights_sha256','confidence','unit','backend_hash','ultralytics_version')):
                raise ValueError('Previous extraction configuration differs')
            with closing(sqlite3.connect(base)) as previous:
                done.update(r[0] for r in previous.execute("SELECT image_id FROM images WHERE status='success'"))
    adapter=YoloAdapter(); adapter.load(settings); capture=Capture(adapter.predictor); adapter.predictor=capture
    # Images are read-only, and this bulk job stores structured data rather than 24,000 previews.
    # Replace preview encoding only in this process; all detections and measurements remain in YoloAdapter.
    adapter.image_io.write_image=lambda path,image: True
    start=time.monotonic(); failures=0
    with tempfile.TemporaryDirectory(prefix='bifb_yolo_',dir=output) as tmp:
        root=Path(tmp)
        def output_path(name):
            return root / ('detected.png' if name.endswith('_detected.png') else 'original.png')
        context=SimpleNamespace(settings=settings,output=output_path,artifact=lambda path,title,kind='file':{'title':title})
        for number,row in enumerate(rows,1):
            if row['image_id'] in done: continue
            tick=time.monotonic()
            try:
                detected=adapter.detect(context,Path(row['image_path']),row['sequence_id'])
                info=capture.info; height,width=info['height'],info['width']; masks=info.get('mask_arrays',[])
                bubbles=[]
                for i,item in enumerate(detected['measurements']):
                    x1,y1,x2,y2=item['bbox_xyxy']; bbox_edge=x1<=0 or y1<=0 or x2>=width-1 or y2>=height-1
                    mask_edge=None
                    if i<len(masks) and masks[i].shape==(height,width) and np.any(masks[i]):
                        m=masks[i]; mask_edge=bool(m[0].any() or m[-1].any() or m[:,0].any() or m[:,-1].any())
                    bubbles.append({'diameter_px':item['diameter_px'],'confidence':item['confidence'],
                                    'area_px2':item['area_px2'],'method':item['method'],'bbox_xyxy':item['bbox_xyxy'],
                                    'bbox_edge':bool(bbox_edge),'mask_edge':mask_edge})
                clean=[b['diameter_px'] for b in bubbles if not b['bbox_edge'] and b['mask_edge'] is False]
                result={'image_count':len(bubbles),'clean':stats(clean),'all':stats([b['diameter_px'] for b in bubbles]),
                        'edge_or_unknown':len(bubbles)-len(clean),'bubbles':bubbles,'unit':'px','width':width,'height':height}
                conn.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?)',(row['image_id'],json.dumps(row,ensure_ascii=False),'success',None,json.dumps(result,allow_nan=False),time.monotonic()-tick))
            except Exception as error:
                failures+=1
                conn.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?)',(row['image_id'],json.dumps(row,ensure_ascii=False),'error',str(error),None,time.monotonic()-tick))
                if 'out of memory' in str(error).lower():
                    conn.commit(); raise
            if number%10==0: conn.commit()
            if number%50==0 or number==len(rows):
                conn.commit(); elapsed=time.monotonic()-start
                total=conn.execute("SELECT count(*) FROM images WHERE status='success'").fetchone()[0]
                print(json.dumps({'index':number,'selected':len(rows),'success':total,'new_failures':failures,'seconds':round(elapsed,1),
                                  'device':str(capture.model.predictor.device)},ensure_ascii=False),flush=True)
    conn.commit(); conn.close()


if __name__=='__main__': main()
