"""Experimental pooled height model, with leave-one-height-out validation."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'data/diameter_model_dependencies'))
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

OUT=ROOT/'data/h3_confirmed/continuous_height'


def main():
    marked=pd.read_csv(ROOT/'data/height_full/condition_statistics.csv')
    marked=marked.assign(height_m=marked.height_id.map({'H1':.2,'H2':.8,'H4':1.8}),salinity_wt_pct=1.,PL_fraction=.1,source='高度照片')
    marked=marked.rename(columns={'mean_image_d50_px':'mean_d50_px','image_count':'images'})
    h3=pd.read_csv(ROOT/'data/h3_confirmed/model/condition_statistics.csv').assign(height_m=1.2,height_id='H3')
    cols=['height_id','height_m','Q_m3_h','salinity_wt_pct','PL_fraction','source','mean_d50_px','images','valid_images']
    data=pd.concat([marked[cols],h3[cols]],ignore_index=True)
    if len(data)!=40 or data.mean_d50_px.isna().any(): raise ValueError('Expected complete condition summaries')
    x=data[['Q_m3_h','height_m','salinity_wt_pct','PL_fraction']].to_numpy(dtype=float)
    y=data.mean_d50_px.to_numpy(dtype=float); folds=[]
    for h in (.2,.8,1.2,1.8):
        train=data.height_m.to_numpy()!=h
        test=(data.height_m.to_numpy()==h)&np.isclose(data.salinity_wt_pct,1.)&np.isclose(data.PL_fraction,.1)
        coef=np.linalg.lstsq(np.column_stack([np.ones(train.sum()),x[train]]),y[train],rcond=None)[0]
        linear=np.column_stack([np.ones(test.sum()),x[test]])@coef
        forest=RandomForestRegressor(n_estimators=100,min_samples_leaf=2,random_state=42,n_jobs=1).fit(x[train],y[train]).predict(x[test])
        reference=train&np.isclose(data.salinity_wt_pct,1.)&np.isclose(data.PL_fraction,.1)
        baseline=float(y[reference].mean())
        for idx,lp,fp in zip(np.flatnonzero(test),linear,forest):
            for name,pred in [('Linear',lp),('RandomForest',fp),('ConditionMean',baseline)]:
                folds.append({'height_m':h,'mode':'interpolation' if h in (.8,1.2) else 'extrapolation',
                    'Q_m3_h':float(data.iloc[idx].Q_m3_h),'model':name,'prediction_px':float(pred),
                    'observed_yolo_px':float(y[idx]),'absolute_error_px':float(abs(pred-y[idx]))})
    evaluation=pd.DataFrame(folds)
    metrics={name:{'mae_px':float(g.absolute_error_px.mean()),'max_error_px':float(g.absolute_error_px.max())} for name,g in evaluation.groupby('model')}
    selected=min(('Linear','RandomForest'),key=lambda k:metrics[k]['mae_px'])
    coef=np.linalg.lstsq(np.column_stack([np.ones(len(x)),x]),y,rcond=None)[0]
    trees=[]
    if selected=='RandomForest':
        forest=RandomForestRegressor(n_estimators=100,min_samples_leaf=2,random_state=42,n_jobs=1).fit(x,y)
        for e in forest.estimators_:
            t=e.tree_; trees.append({'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),'left':t.children_left.tolist(),'right':t.children_right.tolist(),'value':t.value[:,0,0].tolist()})
    OUT.mkdir(parents=True,exist_ok=True)
    data.to_csv(OUT/'conditions.csv',index=False,encoding='utf-8-sig')
    evaluation.to_csv(OUT/'leave_one_height_out.csv',index=False,encoding='utf-8-sig')
    model={'name':'continuous_height_exploratory','selected_model':selected,'features':['Q_m3_h','height_m','salinity_wt_pct','PL_fraction'],
           'coefficients':coef.tolist(),'trees':trees,'metrics':metrics,
           'limits':'Height and acquisition source are confounded. Different camera scales and fields of view are unverified. Leave-one-height-out evaluates only salinity 1 wt% and PL 10%; endpoints are extrapolation. Model selection shares these folds.'}
    (OUT/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'conditions':len(data),'images':int(data.images.sum()),'selected_model':selected,'metrics':metrics},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
