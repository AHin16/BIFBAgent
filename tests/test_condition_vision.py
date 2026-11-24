import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from app import condition_vision as vision
from app.config import load_settings
from app.registry import ToolRegistry
from app.storage import Session,ToolContext


class HistoricalConditionTest(unittest.TestCase):
    def test_equal_image_weight_and_exact_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marked=root/'marked.csv';h3=root/'h3.csv'
            common={'image_path':'missing.png','sequence_id':'s1','Q_m3_h':1.5,'height_m':.2,
                    'salinity_wt_pct':1.,'PL_fraction':.1,'valid_bubbles':8,'low_quality':False}
            pd.DataFrame([{**common,'image_id':'a','d50_px':100},{**common,'image_id':'b','d50_px':200},
                          {**common,'image_id':'c','d50_px':None,'valid_bubbles':0,'low_quality':True}]).to_csv(marked,index=False)
            pd.DataFrame([{**common,'image_id':'other','height_m':1.2,'source':'盐水不同照片2','d50_px':500}]).to_csv(h3,index=False)
            registry=ToolRegistry();vision.register_condition_vision(registry)
            context=ToolContext(Session(),load_settings(),'history_test',stop_event=threading.Event())
            args={'current_q':1.5,'height_m':.2,'salinity_wt_pct':1.,'PL_fraction':.1}
            with patch.object(vision,'MARKED',marked),patch.object(vision,'H3',h3),patch.object(vision,'save_plot',return_value={}):
                result=registry.execute('lookup_condition_measurements',args,context)
                self.assertEqual(result['status'],'success')
                self.assertEqual((result['image_count'],result['valid_images'],result['low_quality_images']),(3,2,1))
                self.assertEqual(result['mean_image_d50_px'],150.)
                self.assertEqual(registry.execute('lookup_condition_measurements',{**args,'current_q':1.6},context)['status'],'error')


if __name__=='__main__':unittest.main()
