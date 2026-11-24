import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from app.storage import ToolError
from app import h3_bubble_predictor as h3


class H3PredictorTest(unittest.TestCase):
    def test_rejects_outside_joint_coverage_and_reports_training_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/'enabled.json').write_text('{}',encoding='utf-8')
            (path/'model.json').write_text(json.dumps({'coefficients':[100,2,3,4,5],
                'metrics':{'mae_px':3,'baseline_mae_px':2}}),encoding='utf-8')
            points=[(1.5,1,.1),(2.,1,.1),(1.5,1.5,.1),(1.5,1,.15)]
            conditions=pd.DataFrame([{'source':h3.SOURCES[0],'Q_m3_h':q,'salinity_wt_pct':s,'PL_fraction':pl} for q,s,pl in points])
            conditions.to_csv(path/'condition_statistics.csv',index=False)
            conditions.assign(d50_px=123).to_csv(path/'image_statistics.csv',index=False)
            with patch.object(h3,'H3_RUN',path):
                result=h3.predict_h3(1.5,2.,1.,.1,h3.SOURCES[0])
                self.assertAlmostEqual(result['predicted_d50_px'],107.4)
                self.assertEqual(result['comparison']['evaluation_type'],'training_condition_not_independent')
                with self.assertRaises(ToolError): h3.predict_h3(1.5,2.3,1.,.1,h3.SOURCES[0])
                with self.assertRaises(ToolError): h3.predict_h3(1.5,2.,1.,.1,'')

    def test_portable_tree_threshold_uses_full_precision(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/'enabled.json').write_text('{"model":"random_forest"}',encoding='utf-8')
            (path/'model.json').write_text(json.dumps({'coefficients':[0]*5,'metrics':{'mae_px':2,'baseline_mae_px':3}}),encoding='utf-8')
            (path/'model_comparison.json').write_text(json.dumps({'models':{'RandomForest':{'mae_px':1},'Linear':{'mae_px':2}}}),encoding='utf-8')
            frame=pd.DataFrame([{'source':h3.SOURCES[0],'Q_m3_h':q,'salinity_wt_pct':1.,'PL_fraction':.1,'d50_px':100} for q in (1.5,2.)])
            frame.to_csv(path/'condition_statistics.csv',index=False)
            frame.to_csv(path/'image_statistics.csv',index=False)
            tree={'feature':[0,-2,-2],'threshold':[1.49999999,-2,-2],'left':[1,-1,-1],'right':[2,-1,-1],'value':[0,100,200]}
            forest={'condition_csv_sha256':hashlib.sha256((path/'condition_statistics.csv').read_bytes()).hexdigest(),'trees':[tree]}
            (path/'forest_model.json').write_text(json.dumps(forest),encoding='utf-8')
            with patch.object(h3,'H3_RUN',path):
                result=h3.predict_h3(1.5,2.,1.,.1,h3.SOURCES[0])
                self.assertEqual(result['current_predicted_d50_px'],200)


if __name__=='__main__': unittest.main()
