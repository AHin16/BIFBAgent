"""Read-only experimental image inventory. Outputs are written locally."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict

EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
NUMBER = r'(\d+(?:\.\d+)?)'


def parse(name, cfg):
    text = unicodedata.normalize('NFKC', name).upper().replace('_', ' ')
    # Some folders use a dot between Q and the following salinity token.
    text = re.sub(r'(\bQ\s*=\s*\d+\.\d+)\.(?=\d+(?:\.\d+)?\s*WT\s*%)', r'\1,', text)
    patterns = {'Q_m3_h': r'\bQ\s*=\s*' + NUMBER, 'salinity_wt_pct': NUMBER + r'\s*WT\s*%',
                'PL_fraction': NUMBER + r'\s*%\s*PL', 'height_id': r'\b(H\s*\d+)\b'}
    result, errors = {}, []
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if len(matches) > 1:
            errors.append('ambiguous ' + key)
        result[key] = matches[0] if len(matches) == 1 else None
    for key in ('Q_m3_h', 'salinity_wt_pct', 'PL_fraction'):
        if result[key] is not None:
            result[key] = float(result[key])
        else:
            errors.append('missing ' + key)
    if result['PL_fraction'] is not None:
        result['PL_fraction'] /= 100
    height = result['height_id']
    result['height_id'] = re.sub(r'\s+', '', height) if height else None
    result['height_m'] = cfg['heights_m'].get(result['height_id'])
    if height and result['height_m'] is None:
        errors.append('unknown height ' + height)
    q = result['Q_m3_h']
    result['Ug_m_s'] = q * cfg['ug_per_q'] if q is not None else None
    result['Ug_mm_s'] = result['Ug_m_s'] * 1000 if q is not None else None
    result['parse_status'] = '; '.join(errors) if errors else 'ok'
    return result


def natural(name):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', name)]


def scan(root, cfg, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if not root.is_dir():
        raise ValueError(f'无法访问源目录：{root}；请检查映射盘是否对当前用户可见。')
    if output == root or root in output.parents:
        raise ValueError('输出目录必须位于源目录之外。')
    output.mkdir(parents=True, exist_ok=True)
    rows, folders, errors = [], [], []
    def onerror(exc):
        errors.append({'path': str(exc.filename), 'error': str(exc)})
    for current, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
        dirs.sort(key=natural)
        path = Path(current)
        images = sorted((f for f in files if Path(f).suffix.lower() in EXT), key=natural)
        folders.append({'relative_path': str(path.relative_to(root)), 'image_count': len(images)})
        if not images:
            continue
        # Use the closest ancestor carrying condition metadata; never infer missing values.
        candidates = [path, *path.parents]
        source = next((p for p in candidates if p == root or root in p.parents if re.search(r'\bQ\s*=', unicodedata.normalize('NFKC', p.name), re.I)), path)
        meta = parse(source.name, cfg)
        for index, filename in enumerate(images, 1):
            image = path / filename
            relative = str(image.relative_to(root))
            rows.append({'image_id': hashlib.sha256(relative.encode('utf-8')).hexdigest(), 'image_path': str(image),
                         'relative_path': relative, 'source_folder': str(path), 'source_group': str(source.relative_to(root)),
                         'folder_name': source.name, 'sequence_folder': str(path.relative_to(root)), 'sequence_order': index,
                         **meta})
    columns = ['image_id','image_path','relative_path','source_folder','source_group','folder_name','sequence_folder','sequence_order',
               'Q_m3_h','Ug_m_s','Ug_mm_s','salinity_wt_pct','PL_fraction','height_id','height_m','parse_status']
    with (output / 'images.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
    db = sqlite3.connect(output / 'inventory.sqlite3')
    with db:
        db.execute('DROP TABLE IF EXISTS images')
        db.execute('CREATE TABLE images (' + ', '.join('"' + c + '" TEXT' for c in columns) + ')')
        db.executemany('INSERT INTO images VALUES (' + ','.join('?' for _ in columns) + ')', [[r[c] for c in columns] for r in rows])
    db.close()
    fields = ('Q_m3_h','salinity_wt_pct','PL_fraction','height_id','height_m')
    groups = Counter(tuple(r[k] for k in fields) for r in rows)
    counts = {k: dict(Counter(str(r[k]) if r[k] is not None else '(缺失)' for r in rows)) for k in fields}
    failed = {r['source_folder']: r['parse_status'] for r in rows if r['parse_status'] != 'ok'}
    missing_height = sum(r['height_id'] is None for r in rows)
    report = {'root': str(root), 'image_count': len(rows), 'folder_count': len(folders), 'folders': folders,
              'conditions': [{**dict(zip(fields, key)), 'image_count': count} for key, count in groups.items()],
              'counts': counts, 'parse_errors': failed, 'missing_height_images': missing_height, 'scan_errors': errors,
              'duplicates': '未计算内容哈希；路径标识不代表文件内容是否重复。',
              'sequence_note': '仅按每个目录的文件名自然排序；顺序不证明连续采集，不可直接用于速度计算。'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    parser.add_argument('--output', default='data/optimization_inventory'); args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    try:
        report = scan(cfg['source_root'], cfg, args.output)
        print(json.dumps({k: report[k] for k in ('image_count','folder_count','counts','parse_errors','scan_errors')}, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
