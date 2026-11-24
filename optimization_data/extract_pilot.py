"""Independent, resumable 40-image pilot. Does not scan the NAS."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import sys
import time
from datetime import datetime
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import torch
from PIL import Image
from app.config import load_settings, local_path
from app.yolo_adapter import YoloAdapter


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def table(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Capture:
    def __init__(self, predictor):
        self.predictor = predictor
        self.model = predictor.model
        self.info = None

    def predict(self, image):
        detections, self.info = self.predictor.predict(image)
        return detections, self.info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=Path, default=ROOT / 'data/optimization_inventory/images.csv')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--multi', action='store_true')
    args = parser.parse_args()
    output = args.output or ROOT / 'data/optimization_pilot' / datetime.now().strftime('%Y%m%d_%H%M%S')
    output = output.resolve()
    if not output.is_relative_to(ROOT / 'data/optimization_pilot'):
        parser.error('Output must be inside data/optimization_pilot')
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with args.index.open(encoding='utf-8-sig', newline='') as stream:
        index = list(csv.DictReader(stream))
    expected = {'Q_m3_h': 1.5, 'Ug_m_s': .004875, 'salinity_wt_pct': 1., 'PL_fraction': .1, 'height_m': .2}
    def matches(row):
        try:
            return row['height_id'] == 'H1' and row['parse_status'] == 'ok' and all(abs(float(row[k])-v) < 1e-10 for k,v in expected.items())
        except (ValueError, KeyError):
            return False
    selected = [row for row in index if matches(row)][:40]
    if args.multi:
        groups = {}
        for row in index:
            if row['parse_status'] == 'ok' and all(row[k] for k in ('Q_m3_h', 'Ug_m_s', 'salinity_wt_pct', 'PL_fraction', 'height_id', 'height_m')):
                key = tuple(row[k] for k in ('Q_m3_h', 'salinity_wt_pct', 'PL_fraction', 'height_id', 'height_m'))
                groups.setdefault(key, []).append(row)
        selected = []
        for group in groups.values():
            n = min(25, len(group))
            selected.extend(group[i] for i in np.linspace(0, len(group)-1, n, dtype=int))
    if not selected or len({row['image_id'] for row in selected}) != len(selected):
        raise ValueError('Expected unique indexed images')
    settings = load_settings().model_copy(update={'mm_per_pixel': None, 'confidence': .25})
    weights = local_path(settings.yolo_model_path)
    if args.multi:
        reference = json.loads((ROOT / 'data/optimization_pilot/20261112_152020/manifest.json').read_text(encoding='utf-8'))
        with weights.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != reference['weights_sha256']:
                raise ValueError('Model weights differ from the first pilot')
    manifest = {'index_sha256': hashlib.sha256(args.index.read_bytes()).hexdigest(),
                'weights_sha256': hashlib.file_digest(weights.open('rb'), 'sha256').hexdigest(),
                'confidence': .25, 'unit': 'px', 'mm_per_pixel': None,
                'selection': [r['image_id'] for r in selected], 'device_requested': settings.yolo_device}
    manifest_path = output / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
        raise ValueError('Resume configuration differs; use a new output directory')
    save(manifest_path, manifest)
    table(output / 'selected_images.csv', selected)
    adapter = YoloAdapter()
    adapter.load(settings)
    capture = Capture(adapter.predictor)
    adapter.predictor = capture
    state_path = output / 'state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    for number, meta in enumerate(selected, 1):
        image_id = meta['image_id']
        if state.get(image_id, {}).get('status') == 'success':
            continue
        directory = output / image_id
        directory.mkdir(exist_ok=True)
        context = SimpleNamespace(settings=settings, output=lambda name: directory / name,
                                  artifact=lambda path, title, kind='file': {'path': str(path), 'title': title, 'kind': kind})
        tick = time.perf_counter()
        try:
            result = adapter.detect(context, Path(meta['image_path']), meta['source_group'])
            width, height = capture.info['width'], capture.info['height']
            masks = capture.info.get('mask_arrays', [])
            details = []
            for i, item in enumerate(result['measurements']):
                x1,y1,x2,y2 = item['bbox_xyxy']
                mask_edge = 'unknown'
                if i < len(masks) and np.any(masks[i]) and masks[i].shape == (height,width):
                    mask = masks[i].astype(bool)
                    mask_edge = bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any())
                details.append({**meta, 'bubble_id': item['bubble_id'], 'confidence': item['confidence'],
                    'area_px2': item['area_px2'], 'diameter_px': item['diameter_px'],
                    'measurement_method': item['method'], 'bbox_xyxy': json.dumps(item['bbox_xyxy']),
                    'bbox_touches_edge': bool(x1 <= 0 or y1 <= 0 or x2 >= width-1 or y2 >= height-1),
                    'mask_touches_edge': mask_edge, 'unit': 'px'})
            values = [item['diameter_px'] for item in details]
            counts, edges = np.histogram(values, bins=10) if values else ([], [])
            summary = {**meta, 'status': 'success', 'error': '', 'bubble_count': len(values),
                **{k + '_diameter_px': result['statistics'][k] for k in ('mean','median','std','min','max')},
                'histogram': json.dumps({'counts': list(map(int,counts)), 'edges_px': list(map(float,edges))}),
                'width_px': width, 'height_px': height, 'seconds': time.perf_counter()-tick,
                'annotation': str(directory / (Path(meta['image_path']).stem + '_detected.png'))}
            if not Path(summary['annotation']).is_file():
                raise OSError('Annotation was not written')
            save(directory / 'result.json', {'details': details, 'summary': summary})
            state[image_id] = {'status': 'success', 'seconds': summary['seconds'],
                               'inference_device': str(capture.model.predictor.device)}
        except Exception as exc:
            state[image_id] = {'status': 'failed', 'error': str(exc), 'image_path': meta['image_path']}
        save(state_path, state)
        print(f'{number}/{len(selected)} {state[image_id]["status"]}', flush=True)
    details, summaries = [], []
    for meta in selected:
        if state[meta['image_id']]['status'] == 'success':
            result = json.loads((output / meta['image_id'] / 'result.json').read_text(encoding='utf-8'))
            details.extend(result['details']); summaries.append(result['summary'])
    table(output / 'bubble_details.csv', details)
    table(output / 'image_summary.csv', summaries)
    failures = [dict(image_id=k, **v) for k,v in state.items() if v['status'] != 'success']
    save(output / 'failures.json', failures)
    resolution = []
    for height in ('H1','H2','H4'):
        row = next(r for r in index if r['height_id'] == height and r['Q_m3_h'] == selected[0]['Q_m3_h'])
        try:
            with Image.open(row['image_path']) as image:
                resolution.append({'height_id': height, 'path': row['image_path'], 'size': list(image.size),
                    'camera_datetime': str(image.getexif().get(306, 'unknown')), 'fps': None, 'mm_per_pixel': None})
        except Exception as exc:
            resolution.append({'height_id': height, 'error': str(exc)})
    save(output / 'height_audit.json', resolution)
    report = {'selected': len(selected), 'success': len(summaries), 'success_rate': len(summaries)/len(selected),
              'bubble_count': len(details), 'failures': failures, 'unit': 'px',
              'bbox_edge_count': sum(r['bbox_touches_edge'] for r in details),
              'mask_edge_count': sum(r['mask_touches_edge'] is True for r in details),
              'fallback_count': sum('bounding_box' in r['measurement_method'] for r in details),
              'elapsed_seconds': time.perf_counter()-started, 'cuda_available': torch.cuda.is_available(),
              'actual_inference_devices': sorted({v.get('inference_device', 'not_recorded') for v in state.values() if v['status'] == 'success'}),
              'gpu_name': torch.cuda.get_device_name() if torch.cuda.is_available() else None,
              'peak_allocated_gpu_mb': torch.cuda.max_memory_allocated()/1024**2 if torch.cuda.is_available() else 0}
    save(output / 'report.json', report)
    if args.multi:
        dimensions = [('condition', ('Q_m3_h','salinity_wt_pct','PL_fraction','height_id','height_m')), ('Q', ('Q_m3_h',)), ('salinity', ('salinity_wt_pct',)), ('PL', ('PL_fraction',)), ('height', ('height_id','height_m'))]
        statistics = []
        for label, keys in dimensions:
            keys_values = sorted({tuple(row[k] for k in keys) for row in selected})
            for key in keys_values:
                subset = [r for r in selected if tuple(r[k] for k in keys) == key]
                ids = {r['image_id'] for r in subset}
                detected = [r for r in details if r['image_id'] in ids]
                clean = [r for r in detected if not r['bbox_touches_edge'] and r['mask_touches_edge'] is False]
                result = {'dimension': label, 'group': json.dumps(dict(zip(keys,key)), ensure_ascii=False), 'selected_images': len(subset), 'success_images': sum(state[r['image_id']]['status'] == 'success' for r in subset), 'detections': len(detected), 'edge_or_unknown': len(detected)-len(clean)}
                result['success_rate'] = result['success_images']/len(subset)
                result['edge_or_unknown_fraction'] = (len(detected)-len(clean))/len(detected) if detected else None
                for name, records in [('all', detected), ('non_edge', clean)]:
                    vals = [r['diameter_px'] for r in records]
                    conf = [r['confidence'] for r in records]
                    result[name+'_count'] = len(vals)
                    result[name+'_diameter_mean_px'] = float(np.mean(vals)) if vals else None
                    result[name+'_diameter_median_px'] = float(np.median(vals)) if vals else None
                    result[name+'_diameter_p10_px'] = float(np.percentile(vals,10)) if vals else None
                    result[name+'_diameter_p90_px'] = float(np.percentile(vals,90)) if vals else None
                    result[name+'_confidence_mean'] = float(np.mean(conf)) if conf else None
                statistics.append(result)
        table(output / 'condition_statistics.csv', statistics)
    entries = ['<meta charset="utf-8"><title>40张检测人工核验</title><h1>像素直径人工核验</h1><p>未经物理标定；边缘目标仍保留，连续性尚未确认。</p>']
    for row in summaries:
        relative = Path(row['annotation']).relative_to(output).as_posix()
        entries.append(f'<h2>{html.escape(row["relative_path"])}</h2><p>气泡数 {row["bubble_count"]}</p><a href="{relative}"><img width="700" src="{relative}"></a>')
    (output / 'review.html').write_text('\n'.join(entries), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)); print(output)


if __name__ == '__main__':
    main()
