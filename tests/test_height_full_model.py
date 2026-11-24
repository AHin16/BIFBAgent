import unittest
import json
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from optimization_data.height_full.train import fit_conditions


class HeightFitTest(unittest.TestCase):
    def test_group_holdout_and_height_separation(self):
        rows=[]
        for h,intercept in [('H1',100),('H2',200),('H4',300)]:
            for q in (1.5,1.8,2.,2.3):
                rows.append({'height_id':h,'Q_m3_h':q,'Ug_m_s':q*.00325,
                             'mean_image_d50_px':intercept+q*10,'valid_images':1000})
        data=pd.DataFrame(rows)
        folds,fits=fit_conditions(data)
        self.assertEqual(len(folds),12)
        self.assertTrue(all(x['absolute_error_px'] < 1e-8 for x in folds))
        selected=next(x for x in folds if x['height_id']=='H1' and x['held_out_Q_m3_h']==2.)
        data.loc[(data.height_id=='H1') & (data.Q_m3_h==2.),'mean_image_d50_px']+=1000
        changed,_=fit_conditions(data)
        self.assertAlmostEqual(selected['prediction_px'],next(x['prediction_px'] for x in changed if x['height_id']=='H1' and x['held_out_Q_m3_h']==2.))
        self.assertAlmostEqual(fits['H2']['intercept_px'],200.)

    def test_complete_training_artifacts_are_usable_by_predictor(self):
        from optimization_data.height_full import train
        from app.ug_bubble_predictor import GasVelocityBubblePredictor
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); rows=[]
            manifest={'index_sha256':'fixture','weights_sha256':'fixture','confidence':.25,'unit':'px','backend_hash':'fixture','ultralytics_version':'fixture'}
            (directory/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with closing(sqlite3.connect(directory/'measurements.sqlite3')) as db:
                db.execute('CREATE TABLE images(image_id TEXT, metadata TEXT, status TEXT, error TEXT, result TEXT)')
                for h,offset in [('H1',100),('H2',200),('H4',300)]:
                    for q in (1.5,1.8,2.,2.3):
                        row={'image_id':f'{h}-{q}','image_path':f'{h}-{q}.png','sequence_id':f'{h}-{q}',
                             'Q_m3_h':str(q),'Ug_m_s':str(q*.00325),'height_id':h,'height_m':str({'H1':.2,'H2':.8,'H4':1.8}[h]),
                             'salinity_wt_pct':'1.0','PL_fraction':'0.1'}
                        value=offset+q*10
                        result={'clean':{'count':5,'d10_px':value,'d50_px':value,'d90_px':value,'mean_px':value},
                                'all':{'d50_px':value},'image_count':5,'edge_or_unknown':0}
                        db.execute('INSERT INTO images VALUES (?,?,?,?,?)',(row['image_id'],json.dumps(row),'success',None,json.dumps(result)))
                        rows.append(row)
                db.commit()
            with patch.object(train,'OUT',directory), patch.object(train,'selected_images',return_value=rows):
                train.main()
            self.assertEqual(len(pd.read_csv(directory/'leave_one_q_out.csv')),12)
            with patch('app.ug_bubble_predictor.HEIGHT_FULL_RUN',directory):
                prediction=GasVelocityBubblePredictor().predict(1.8,2.,1.,.1,'H2')
            self.assertAlmostEqual(prediction['predicted_d50_px'],220.)
            self.assertEqual(prediction['comparison']['evaluation_type'],'training_condition_not_independent')


if __name__=='__main__': unittest.main()
