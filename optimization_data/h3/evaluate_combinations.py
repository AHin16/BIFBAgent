"""Evaluate the selected pooled model by holding out complete conditions."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'data/diameter_model_dependencies'))
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from sklearn.ensemble import RandomForestRegressor

OUT=ROOT/'data/h3_confirmed/continuous_height'


def main():
    data=pd.read_csv(OUT/'conditions.csv')
    features=['Q_m3_h','height_m','salinity_wt_pct','PL_fraction']
    x=data[features].to_numpy(dtype=float); y=data.mean_d50_px.to_numpy(dtype=float)
    rows=[]
    for i in range(len(data)):
        mask=np.ones(len(data),dtype=bool); mask[i]=False
        model=RandomForestRegressor(n_estimators=100,min_samples_leaf=2,random_state=42,n_jobs=1)
        pred=float(model.fit(x[mask],y[mask]).predict(x[i:i+1])[0])
        scale=np.array([1.,1.,1.,.1]); matrix=np.vstack([np.ones(mask.sum()),(x[mask]/scale).T])
        inside=bool(linprog(np.zeros(mask.sum()),A_eq=matrix,b_eq=np.r_[1.,x[i]/scale],bounds=(0,None),method='highs').success)
        rows.append({**{name:float(x[i,j]) for j,name in enumerate(features)},'source':data.iloc[i].source,
                     'observed_yolo_px':float(y[i]),'prediction_px':pred,'absolute_error_px':abs(y[i]-pred),
                     'relative_error_pct':abs(y[i]-pred)/abs(y[i])*100 if y[i] else None,
                     'within_training_joint_coverage':inside})
    result=pd.DataFrame(rows)
    result.to_csv(OUT/'leave_one_condition_out.csv',index=False,encoding='utf-8-sig')
    print(result.groupby('within_training_joint_coverage').agg(n=('absolute_error_px','size'),mae_px=('absolute_error_px','mean'),mape_pct=('relative_error_pct','mean')).to_string())


if __name__=='__main__':main()
