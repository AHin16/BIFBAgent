"""Fit an exploratory H3 model after the complete, resumable extraction.

Condition means are equal-weighted; folds with the same Q/S/PL are held out
together even if present in both source roots. Never modifies existing models.
"""
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from optimization_data.h3.extract import OUT, selected_images
from optimization_data.h3.extract_incomplete import selected_images as incomplete_images

DB = OUT / 'full' / 'measurements.sqlite3'
INCOMPLETE_DB = OUT / 'incomplete' / 'measurements.sqlite3'
OUTPUT = OUT / 'model'


def design(frame):
    return np.column_stack((np.ones(len(frame)), frame.Q_m3_h, frame.salinity_wt_pct,
                            frame.PL_fraction, (frame.source == '盐水不同照片2').astype(float)))


def main():
    full_manifest = extra_manifest = None
    complete = selected_images()
    additional = incomplete_images()
    expected = {r['image_id']: r for r in complete + additional}
    if len(expected) != len(complete) + len(additional):
        raise ValueError('Image ID repeated across input batches')
    for row in additional:
        folder = Path(row['image_path']).parent.name
        confirmed = {'Q=1.8,2.5WT%,15%_files': .15, 'Q=1.5,2.5WT%,10%_files': .10}
        if folder not in confirmed or row['PL_fraction']:
            raise ValueError(f'Unexpected unconfirmed missing PL folder: {folder}')
        row['PL_fraction'] = str(confirmed[folder])
        row['PL_source'] = 'user_confirmation_2026-11-15'
    if not DB.is_file():
        raise RuntimeError('H3 extraction database is missing')
    with closing(sqlite3.connect(DB)) as conn:
        rows = conn.execute('SELECT image_id,metadata,status,result FROM images').fetchall()
    if additional:
        if not INCOMPLETE_DB.is_file():
            raise RuntimeError('Additional H3 extraction database is missing')
        full_manifest = json.loads((DB.parent / 'manifest.json').read_text(encoding='utf-8'))
        extra_manifest = json.loads((INCOMPLETE_DB.parent / 'manifest.json').read_text(encoding='utf-8'))
        for key in ('index_sha256','weights_sha256','confidence','unit','backend_hash','ultralytics_version','height_source'):
            if full_manifest.get(key) != extra_manifest.get(key):
                raise ValueError(f'Inconsistent extraction configuration: {key}')
        with closing(sqlite3.connect(INCOMPLETE_DB)) as conn:
            rows.extend(conn.execute('SELECT image_id,metadata,status,result FROM images').fetchall())
    success = {image_id: (json.loads(meta), json.loads(result)) for image_id, meta, status, result in rows if status == 'success'}
    if set(success) != set(expected):
        raise RuntimeError(f'H3 extraction incomplete: {len(set(success) & set(expected))}/{len(expected)} images')
    records = []
    for image_id, meta in expected.items():
        saved, result = success[image_id]
        if meta.get('PL_source'):
            if saved.get('PL_fraction'):
                raise ValueError(f'Unexpected original PL: {image_id}')
            saved['PL_fraction'] = meta['PL_fraction']
        if any(saved.get(k) != meta.get(k) for k in ('image_path', 'source_root', 'Q_m3_h', 'salinity_wt_pct', 'PL_fraction', 'height_id', 'height_source')):
            raise ValueError(f'Metadata mismatch: {image_id}')
        clean = result['clean']
        records.append({'image_id': image_id, 'image_path': meta['image_path'], 'sequence_id': meta['sequence_id'],
                        'source': meta['source_root'].replace('/', '\\').rstrip('\\').split('\\')[-1],
                        'Q_m3_h': float(meta['Q_m3_h']), 'Ug_m_s': float(meta['Ug_m_s']),
                        'salinity_wt_pct': float(meta['salinity_wt_pct']), 'PL_fraction': float(meta['PL_fraction']),
                        'height_id': 'H3', 'height_m': 1.2, 'height_source': meta['height_source'],
                        'PL_source': meta.get('PL_source', 'folder_name'),
                        'width_px': result.get('width'), 'height_px': result.get('height'),
                        'd50_px': clean['d50_px'], 'valid_bubbles': clean['count'],
                        'low_quality': clean['count'] < 5, 'bubble_count': result['image_count'],
                        'edge_or_unknown': result['edge_or_unknown'], 'all_d50_px': result['all']['d50_px']})
    frame = pd.DataFrame(records)
    grouped = frame.groupby(['source', 'Q_m3_h', 'salinity_wt_pct', 'PL_fraction'], as_index=False).agg(
        mean_d50_px=('d50_px', 'mean'), images=('image_id', 'size'), valid_images=('d50_px', 'count'),
        low_quality_images=('low_quality', 'sum'), sequences=('sequence_id', 'nunique'))
    if grouped.mean_d50_px.isna().any():
        raise RuntimeError('A condition has no usable bubble measurements')
    folds = []
    for key, held in grouped.groupby(['Q_m3_h', 'salinity_wt_pct', 'PL_fraction']):
        training = grouped.drop(index=held.index)
        x = design(training)
        if np.linalg.matrix_rank(x) < x.shape[1]:
            raise RuntimeError(f'Unidentifiable held-out model: {key}')
        coeff = np.linalg.lstsq(x, training.mean_d50_px, rcond=None)[0]
        for index, row in held.iterrows():
            pred = float((design(held.loc[[index]]) @ coeff)[0])
            reference = training[training.source == row.source].mean_d50_px
            if reference.empty:
                raise RuntimeError('No training data for held-out source')
            baseline = float(reference.mean())
            folds.append({'source': row.source, 'Q_m3_h': row.Q_m3_h, 'salinity_wt_pct': row.salinity_wt_pct,
                          'PL_fraction': row.PL_fraction, 'prediction_px': pred, 'observed_yolo_px': row.mean_d50_px,
                          'absolute_error_px': abs(pred-row.mean_d50_px), 'baseline_prediction_px': baseline,
                          'baseline_absolute_error_px': abs(baseline-row.mean_d50_px)})
    x = design(grouped)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        raise RuntimeError('Training design is rank deficient')
    coefficients = np.linalg.lstsq(x, grouped.mean_d50_px, rcond=None)[0]
    evaluation = pd.DataFrame(folds)
    metrics = {'image_count': len(frame), 'usable_images': int(frame.d50_px.notna().sum()),
               'source_conditions': len(grouped), 'condition_combinations': len(grouped.groupby(['Q_m3_h','salinity_wt_pct','PL_fraction'])),
               'mae_px': float(evaluation.absolute_error_px.mean()),
               'rmse_px': float(np.sqrt(np.mean((evaluation.prediction_px-evaluation.observed_yolo_px)**2))),
               'baseline_mae_px': float(evaluation.baseline_absolute_error_px.mean()),
               'validation': 'Leave all identical Q/S/PL combinations out across sources; per-source mean baseline.',
               'limitations': ['Exploratory additive linear model; interactions between parameters are not estimated.',
                               'Exploratory pixel measurements; calibration and camera field of view not confirmed.',
                               'Source is modelled separately, not evidence of equivalent camera geometry.',
                               'Images in a sequence are correlated, and held-out conditions are not independent experimental repeats.']}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT/'image_statistics.csv', index=False, encoding='utf-8-sig')
    grouped.to_csv(OUTPUT/'condition_statistics.csv', index=False, encoding='utf-8-sig')
    frame.groupby(['source','Q_m3_h','salinity_wt_pct','PL_fraction','width_px','height_px'],dropna=False).size().rename('image_count').reset_index().to_csv(OUTPUT/'image_resolutions.csv', index=False, encoding='utf-8-sig')
    evaluation.to_csv(OUTPUT/'leave_one_condition_out.csv', index=False, encoding='utf-8-sig')
    (OUTPUT/'model.json').write_text(json.dumps({'name':'h3_exploratory_linear', 'features':['intercept','Q_m3_h','salinity_wt_pct','PL_fraction','source_盐水不同照片2'],
        'coefficients':coefficients.tolist(), 'height_m':1.2, 'height_source':'user_confirmation_2026-11-15',
        'training_bounds':{col:[float(grouped[col].min()),float(grouped[col].max())] for col in ['Q_m3_h','salinity_wt_pct','PL_fraction']},
        'metrics':metrics, 'extraction_manifests':{'complete':full_manifest,'confirmed_PL':extra_manifest}}, ensure_ascii=False, indent=2),encoding='utf-8')
    (OUTPUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(evaluation.observed_yolo_px, evaluation.prediction_px, alpha=.75)
    low = min(evaluation.observed_yolo_px.min(), evaluation.prediction_px.min())
    high = max(evaluation.observed_yolo_px.max(), evaluation.prediction_px.max())
    ax.plot([low,high],[low,high],linestyle='--',color='gray')
    ax.set_xlabel('Held-out YOLO condition mean d50 (px)')
    ax.set_ylabel('Predicted condition mean d50 (px)')
    ax.set_title('Leave-one-condition-out evaluation')
    fig.tight_layout(); fig.savefig(OUTPUT/'held_out_predictions.png',dpi=150); plt.close(fig)
    print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()
    from optimization_data.h3.compare import compare_models
    compare_models()
