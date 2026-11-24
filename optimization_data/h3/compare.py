"""Nested condition-level evaluation of regression models, not picture-level splitting."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'data/diameter_model_dependencies'))
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, GridSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.ensemble import RandomForestRegressor
from app.h3_bubble_predictor import _inside_coverage

OUT=ROOT/'data/h3_confirmed/model'


def features(frame):
    return np.column_stack([frame.Q_m3_h,frame.salinity_wt_pct,frame.PL_fraction,
                            (frame.source=='盐水不同照片2').astype(float)])


def compare_models():
    data=pd.read_csv(OUT/'condition_statistics.csv')
    if data.empty or data.mean_d50_px.isna().any():
        raise ValueError('Complete H3 condition statistics are required')
    group_keys=list(zip(data.Q_m3_h,data.salinity_wt_pct,data.PL_fraction))
    ids=pd.factorize(pd.MultiIndex.from_tuples(group_keys))[0]
    unique=np.unique(ids)
    if len(unique)<6: raise ValueError('Not enough independent condition groups')
    x=features(data); y=data.mean_d50_px.to_numpy(dtype=float)
    rows=[]; robustness=[]; rng=np.random.default_rng(42)
    for group in unique:
        test=ids==group; train=~test
        cv=GroupKFold(n_splits=min(5,len(np.unique(ids[train]))))
        configs={
            'SVR_RBF':(make_pipeline(StandardScaler(),SVR(kernel='rbf')),
                       {'svr__C':[1.,10.,100.], 'svr__epsilon':[1.,5.]}),
            'RandomForest':(RandomForestRegressor(n_estimators=60,random_state=42,n_jobs=1),
                            {'max_depth':[2,4,None], 'min_samples_leaf':[1,2]})}
        fitted={}
        for name,(estimator,params) in configs.items():
            search=GridSearchCV(estimator,params,scoring='neg_mean_absolute_error',cv=cv,n_jobs=1,refit=True,error_score='raise')
            search.fit(x[train],y[train],groups=ids[train])
            fitted[name]=(search.predict(x[test]),search.best_params_,search.best_estimator_)
        linear=np.linalg.lstsq(np.column_stack([np.ones(train.sum()),x[train]]),y[train],rcond=None)[0]
        fitted['Linear']=(np.column_stack([np.ones(test.sum()),x[test]])@linear,{},None)
        held=data.loc[test]
        for j,(index,row) in enumerate(held.iterrows()):
            source_train=data.loc[train & (data.source==row.source),'mean_d50_px']
            if source_train.empty: raise ValueError('No source-matched baseline')
            source_conditions=data.loc[train & (data.source==row.source)]
            within=_inside_coverage(source_conditions,row.Q_m3_h,row.salinity_wt_pct,row.PL_fraction)
            candidates={**fitted,'SourceMean':(np.array([source_train.mean()]),{},None)}
            for name,(predictions,params,estimator) in candidates.items():
                pred=float(predictions[0] if name=='SourceMean' else predictions[j]); actual=float(row.mean_d50_px)
                rows.append({'model':name,'source':row.source,'Q_m3_h':row.Q_m3_h,
                             'salinity_wt_pct':row.salinity_wt_pct,'PL_fraction':row.PL_fraction,
                             'prediction_px':pred,'observed_yolo_px':actual,'absolute_error_px':abs(pred-actual),
                             'relative_error_pct':abs(pred-actual)/abs(actual)*100 if actual else None,
                             'within_source_training_hull':within,
                             'parameters':json.dumps(params,ensure_ascii=False,sort_keys=True)})
                for level in (.03,.10):
                    noisy=np.repeat(x[test][j:j+1],30,axis=0)
                    noisy[:,:3] *= 1+rng.uniform(-level,level,size=(30,3))
                    if name=='SourceMean': noisy_prediction=np.full(30,pred)
                    elif name=='Linear': noisy_prediction=np.column_stack([np.ones(len(noisy)),noisy])@linear
                    else: noisy_prediction=estimator.predict(noisy)
                    robustness.append({'model':name,'source':row.source,'Q_m3_h':row.Q_m3_h,
                        'salinity_wt_pct':row.salinity_wt_pct,'PL_fraction':row.PL_fraction,'input_error_fraction':level,
                        'mean_absolute_prediction_change_px':float(np.mean(np.abs(noisy_prediction-pred))),
                        'mean_absolute_error_vs_yolo_px':float(np.mean(np.abs(noisy_prediction-actual)))})
    folds=pd.DataFrame(rows)
    folds.to_csv(OUT/'model_comparison_predictions.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(robustness).to_csv(OUT/'input_perturbation.csv',index=False,encoding='utf-8-sig')
    summary={}
    for name,part in folds.groupby('model'):
        residual=part.prediction_px-part.observed_yolo_px
        summary[name]={'mae_px':float(part.absolute_error_px.mean()),'rmse_px':float(np.sqrt(np.mean(residual**2))),
                       'conditions':len(part)}
    result={'validation':'Outer leave-one-Q/S/PL-group-out across both sources; inner five-fold grouped search on training groups only.',
            'features':'Q, salinity, PL and acquisition source; H3 height is fixed.',
            'inner_search':'Small predefined grid; no automatic removal of inputs.',
            'input_perturbation':'30 uniformly sampled simultaneous perturbations of Q/S/PL at ±3% and ±10% per held-out row; may leave observed coverage; illustrative stress test, not a measured uncertainty interval.',
            'limits':'Model comparisons and hyperparameter selection on the same outer folds are exploratory; no independent repeat experiments or confirmed physical calibration.',
            'models':summary}
    (OUT/'model_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


if __name__=='__main__': compare_models()
