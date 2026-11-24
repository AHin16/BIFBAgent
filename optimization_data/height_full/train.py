"""Fit per-height Ug/d50 lines from all images; leave the entire Q out in validation."""
import csv
from contextlib import closing
import json
import math
import sqlite3
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from optimization_data.height_full.extract import OUT, selected_images

SCALE=.00325
QS=(1.5,1.8,2.,2.3)
HEIGHTS=('H1','H2','H4')


def fit_conditions(grouped):
    folds=[]; fits={}
    for height in HEIGHTS:
        h=grouped[grouped.height_id==height].sort_values('Q_m3_h')
        if len(h)!=4 or set(h.Q_m3_h)!=set(QS): raise ValueError(f'Expected four Q values for {height}')
        for target in QS:
            training=h[h.Q_m3_h!=target]; test=h[h.Q_m3_h==target].iloc[0]
            slope,intercept=np.polyfit(training.Ug_m_s,training.mean_image_d50_px,1)
            pred=float(slope*test.Ug_m_s+intercept); baseline=float(training.mean_image_d50_px.mean()); actual=float(test.mean_image_d50_px)
            folds.append({'height_id':height,'held_out_Q_m3_h':target,'held_out_Ug_m_s':float(test.Ug_m_s),
                'training_q':json.dumps(training.Q_m3_h.tolist()),'mode':'interpolation' if training.Q_m3_h.min()<target<training.Q_m3_h.max() else 'extrapolation',
                'prediction_px':pred,'actual_yolo_px':actual,'absolute_error_px':abs(pred-actual),
                'baseline_prediction_px':baseline,'baseline_absolute_error_px':abs(baseline-actual),
                'validation_images':int(test.valid_images)})
        slope,intercept=np.polyfit(h.Ug_m_s,h.mean_image_d50_px,1)
        fits[height]={'slope_px_per_m_s':float(slope),'intercept_px':float(intercept),'q_min':float(h.Q_m3_h.min()),'q_max':float(h.Q_m3_h.max()),'training_Q':h.Q_m3_h.tolist()}
    return folds,fits


def main():
    selected=selected_images(); selected_ids={r['image_id'] for r in selected}
    database=OUT/'measurements.sqlite3'
    if not database.exists(): raise RuntimeError('Full extraction database not found')
    manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    stored=[]
    for directory in (OUT,OUT/'shard0',OUT/'shard1',OUT/'worker0',OUT/'worker1',OUT/'worker2',OUT/'worker3'):
        path=directory/'measurements.sqlite3'
        if not path.exists(): continue
        config=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if any(config[k]!=manifest[k] for k in ('index_sha256','weights_sha256','confidence','unit','backend_hash','ultralytics_version')):
            raise ValueError('Extraction configurations are not consistent')
        with closing(sqlite3.connect(path)) as conn:
            stored.extend(conn.execute('SELECT image_id,metadata,status,error,result FROM images').fetchall())
    success={r[0]:r for r in stored if r[2]=='success'}
    if set(success)!=selected_ids:
        failures=[{'image_id':r[0],'error':r[3]} for r in stored if r[2]!='success']
        (OUT/'incomplete.json').write_text(json.dumps({'expected':len(selected_ids),'success':len(success),'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
        raise RuntimeError(f'Extraction incomplete: {len(success)}/{len(selected_ids)} successful; see incomplete.json')
    records=[]
    for meta in selected:
        saved=success[meta['image_id']]
        actual=json.loads(saved[1]); result=json.loads(saved[4]); clean=result['clean']
        if actual['image_path']!=meta['image_path'] or actual['Q_m3_h']!=meta['Q_m3_h'] or actual['height_id']!=meta['height_id']:
            raise ValueError('Extraction metadata mismatch')
        records.append({'image_id':meta['image_id'],'image_path':meta['image_path'],'sequence_id':meta['sequence_id'],
                        'Q_m3_h':float(meta['Q_m3_h']),'Ug_m_s':float(meta['Ug_m_s']),'height_id':meta['height_id'],
                        'height_m':float(meta['height_m']),'salinity_wt_pct':float(meta['salinity_wt_pct']),
                        'PL_fraction':float(meta['PL_fraction']),'bubble_count':result['image_count'],
                        'edge_or_unknown':result['edge_or_unknown'],'valid_bubbles':clean['count'],
                        'low_quality':clean['count']<5,'d10_px':clean['d10_px'],'d50_px':clean['d50_px'],
                        'd90_px':clean['d90_px'],'mean_px':clean['mean_px'],'all_d50_px':result['all']['d50_px']})
    frame=pd.DataFrame(records); frame.to_csv(OUT/'image_statistics.csv',index=False,encoding='utf-8-sig')
    grouped=frame.groupby(['height_id','Q_m3_h'],as_index=False).agg(
        Ug_m_s=('Ug_m_s','first'),image_count=('image_id','size'),valid_images=('d50_px','count'),
        low_quality_images=('low_quality','sum'),mean_image_d50_px=('d50_px','mean'),
        median_image_d50_px=('d50_px','median'),image_d50_p10_px=('d50_px',lambda x:x.quantile(.1)),
        image_d50_p90_px=('d50_px',lambda x:x.quantile(.9)))
    if len(grouped)!=12 or grouped.valid_images.eq(0).any(): raise RuntimeError('Missing usable observations in a condition')
    grouped.to_csv(OUT/'condition_statistics.csv',index=False,encoding='utf-8-sig')
    folds,fits=fit_conditions(grouped)
    evaluation=pd.DataFrame(folds); evaluation.to_csv(OUT/'leave_one_q_out.csv',index=False,encoding='utf-8-sig')
    metrics={'condition_count':12,'extraction_images':len(frame),'usable_images':int(frame.d50_px.notna().sum()),
        'no_valid_bubbles':int(frame.d50_px.isna().sum()),'low_quality_images':int(frame.low_quality.sum()),
        'mae_px':float(evaluation.absolute_error_px.mean()),'rmse_px':float(np.sqrt(np.mean((evaluation.prediction_px-evaluation.actual_yolo_px)**2))),
        'baseline_mae_px':float(evaluation.baseline_absolute_error_px.mean()),
        'per_height':{h:{'mae_px':float(g.absolute_error_px.mean()),'baseline_mae_px':float(g.baseline_absolute_error_px.mean())} for h,g in evaluation.groupby('height_id')},
        'independent_sequences_per_condition':1,'validation':'Leave one Q out, equal weight per experimental condition; image frames are correlated.',
        'limits':'Exploratory pixels only; physical calibration, field of view and cross-Q camera consistency not established; no independent experiment validation.'}
    bundle={'name':'height_full_exploratory_linear','conditions':{'salinity_wt_pct':1.,'PL_fraction':.1},
            'unit':'px','target':'mean of per-image d50 from non-edge detections','q_to_ug':SCALE,
            'heights':fits,'metrics':metrics,'provenance':manifest}
    (OUT/'model.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (OUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    fig,axes=plt.subplots(1,3,figsize=(13,4),sharey=True)
    for ax,h in zip(axes,HEIGHTS):
        subset=grouped[grouped.height_id==h].sort_values('Q_m3_h'); fit=fits[h]
        ax.scatter(subset.Ug_m_s,subset.mean_image_d50_px,label='YOLO condition mean')
        grid=np.linspace(subset.Ug_m_s.min(),subset.Ug_m_s.max(),100)
        ax.plot(grid,fit['intercept_px']+fit['slope_px_per_m_s']*grid,label='Full-data fitted line')
        ax.set_title(h);ax.set_xlabel('Ug (m/s)'); ax.legend(fontsize=7)
    axes[0].set_ylabel('Mean image d50 (px)'); fig.tight_layout(); fig.savefig(OUT/'fitted_curves.png',dpi=150);plt.close(fig)
    print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
