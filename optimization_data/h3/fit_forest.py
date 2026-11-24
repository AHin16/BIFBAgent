"""Refit the evaluated random forest on all H3 conditions for the demo."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'data/diameter_model_dependencies'))
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GridSearchCV, GroupKFold
from optimization_data.h3.compare import OUT, features


def main():
    data=pd.read_csv(OUT/'condition_statistics.csv')
    group=pd.factorize(pd.MultiIndex.from_frame(data[['Q_m3_h','salinity_wt_pct','PL_fraction']]))[0]
    x=features(data); y=data.mean_d50_px.to_numpy(dtype=float)
    search=GridSearchCV(RandomForestRegressor(n_estimators=60,random_state=42,n_jobs=1),
        {'max_depth':[2,4,None],'min_samples_leaf':[1,2]},scoring='neg_mean_absolute_error',
        cv=GroupKFold(n_splits=5),n_jobs=1,error_score='raise')
    search.fit(x,y,groups=group)
    trees=[]
    for estimator in search.best_estimator_.estimators_:
        tree=estimator.tree_
        trees.append({'feature':tree.feature.tolist(),'threshold':tree.threshold.tolist(),
                      'left':tree.children_left.tolist(),'right':tree.children_right.tolist(),
                      'value':tree.value[:,0,0].tolist()})
    result={'name':'h3_random_forest_exploratory','features':['Q_m3_h','salinity_wt_pct','PL_fraction','source_盐水不同照片2'],
            'best_params':search.best_params_,'training_conditions':len(data),
            'condition_csv_sha256':hashlib.sha256((OUT/'condition_statistics.csv').read_bytes()).hexdigest(),
            'trees':trees,'limits':'Piecewise constant predictions; condition-level validation and model selection share the same dataset; not independent prospective validation.'}
    (OUT/'forest_model.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'best_params':search.best_params_,'training_conditions':len(data),'trees':len(trees)},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
