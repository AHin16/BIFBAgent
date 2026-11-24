import threading
import unittest
from unittest.mock import patch
from app.config import load_settings
from app.registry import ToolRegistry
from app.storage import Session,ToolContext
from app.ug_bubble_predictor import register_ug_prediction_tool


class PredictionCalibrationTest(unittest.TestCase):
    def test_conversion_requires_confirmation_and_uses_given_scale(self):
        registry=ToolRegistry();register_ug_prediction_tool(registry)
        context=ToolContext(Session(),load_settings(),'test_calibration',stop_event=threading.Event())
        base={'current_q':1.5,'target_q':1.8,'salinity_wt_pct':1.,'PL_fraction':.1,'height_m':.7}
        result={'current_predicted_d50_px':104.28,'predicted_d50_px':208.56,'change_px':104.28,
                'comparison':None,'target_data_available':False}
        with patch('app.ug_bubble_predictor.GasVelocityBubblePredictor.predict',return_value=result), patch('app.ug_bubble_predictor.save_plot',return_value={}):
            missing=registry.execute('predict_ug_bubble_diameter',{**base,'prediction_mm_per_pixel':1/104.28},context)
            self.assertEqual(missing['status'],'error')
            converted=registry.execute('predict_ug_bubble_diameter',{**base,'prediction_mm_per_pixel':1/104.28,'calibration_confirmed':True},context)
            self.assertEqual(converted['status'],'success')
            self.assertAlmostEqual(converted['current_predicted_d50_mm'],1.)
            self.assertAlmostEqual(converted['predicted_d50_mm'],2.)


if __name__=='__main__':unittest.main()
