import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from app.storage import ToolError
from app.ug_bubble_predictor import GasVelocityBubblePredictor, available_prediction_heights


class HeightPredictorTest(unittest.TestCase):
    def test_separate_height_models_and_training_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            fits={h:{'intercept_px':v,'slope_px_per_m_s':100.,'q_min':1.5,'q_max':2.3,'training_Q':[1.5,1.8,2.,2.3]} for h,v in [('H1',100),('H2',200),('H4',300)]}
            metric={'mae_px':5,'baseline_mae_px':4,'per_height':{h:{'mae_px':5,'baseline_mae_px':4} for h in fits}}
            (directory/'model.json').write_text(json.dumps({'heights':fits,'metrics':metric}),encoding='utf-8')
            pd.DataFrame([{'height_id':h,'Q_m3_h':2.,'d50_px':v} for h,v in [('H1',105),('H2',205),('H4',305)]]).to_csv(directory/'image_statistics.csv',index=False)
            with patch('app.ug_bubble_predictor.HEIGHT_FULL_RUN',directory), patch('app.ug_bubble_predictor.h3_ready',return_value=False):
                self.assertEqual(available_prediction_heights(),['H1','H2','H4'])
                result=GasVelocityBubblePredictor().predict(1.8,2.,1.,.1,'H2')
                self.assertAlmostEqual(result['predicted_d50_px'],200.65)
                self.assertEqual(result['comparison']['evaluation_type'],'training_condition_not_independent')
                self.assertEqual(result['conditions']['height_m'],.8)
                with self.assertRaises(ToolError): GasVelocityBubblePredictor().predict(1.8,2.,1.5,.1,'H2')
                with self.assertRaises(ToolError): GasVelocityBubblePredictor().predict(1.8,2.4,1.,.1,'H2')


if __name__=='__main__': unittest.main()
