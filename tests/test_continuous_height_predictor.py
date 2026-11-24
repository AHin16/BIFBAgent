import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from app import continuous_height_predictor as predictor
from app.bubble_kernel import FEATURES, fit_kernel, predict_kernel
from app.storage import ToolError


class ContinuousHeightTest(unittest.TestCase):
    def test_numeric_height_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            model={'selected_model':'Linear','coefficients':[100,2,10,0,0],
                   'metrics':{'Linear':{'mae_px':9},'ConditionMean':{'mae_px':10}},'trees':[]}
            (root/'model.json').write_text(json.dumps(model),encoding='utf-8')
            frame=pd.DataFrame([{'Q_m3_h':q,'height_m':h,'salinity_wt_pct':1.,'PL_fraction':.1,'valid_images':10,'mean_d50_px':100+10*h} for q in (1.5,2.3) for h in (.2,1.8)])
            frame.to_csv(root/'conditions.csv',index=False)
            with patch.object(predictor,'RUN',root):
                result=predictor.predict_continuous(1.5,1.7,1.,.1,.7)
                self.assertAlmostEqual(result['predicted_d50_px'],110.4)
                self.assertEqual(result['target_height_m'],.7)
                self.assertFalse(result['height_changed'])
                self.assertFalse(result['target_data_available'])
                self.assertEqual(result['target_q_support']['kind'], 'no_matching_group')
                bracketed = predictor.predict_continuous(1.5, 1.7, 1., .1, .2)
                self.assertEqual(bracketed['target_q_support'],
                                 {'kind': 'bracketed', 'measured_q_levels': [1.5, 2.3]})
                alternate=predictor.predict_continuous(1.5,2.3,1.,.1,.2,1.8)
                self.assertTrue(alternate['height_changed'])
                self.assertAlmostEqual(alternate['current_predicted_d50_px'],105.)
                self.assertAlmostEqual(alternate['predicted_d50_px'],122.6)
                self.assertAlmostEqual(alternate['comparison']['measured']['mean_image_d50_px'],118.)
                self.assertAlmostEqual(alternate['comparison']['observed_change_px'], 16.)
                self.assertAlmostEqual(alternate['comparison']['change_absolute_error_px'], 1.6)
                self.assertEqual(alternate['target_q_support']['kind'], 'measured')
                self.assertTrue(result['target_within_joint_coverage'])
                outside=predictor.predict_continuous(1.5,1.7,1.5,.1,.7)
                self.assertFalse(outside['target_within_joint_coverage'])
                with self.assertRaises(ToolError): predictor.predict_continuous(1.5,1.7,1.,.1,1.9)
                with self.assertRaises(ToolError): predictor.predict_continuous(1.5,1.7,1.,.1,.7,1.9)
                with self.assertRaises(ToolError): predictor.predict_continuous(1.5,1.7,2.6,.1,.7)
                frame.loc[~(frame.height_m.eq(.2) & frame.Q_m3_h.eq(2.3))].to_csv(
                    root/'conditions.csv', index=False)
                single = predictor.predict_continuous(1.5, 1.7, 1., .1, .2)
                self.assertEqual(single['target_q_support'],
                                 {'kind': 'outside_group_q', 'measured_q_levels': [1.5]})

    def test_matching_rbf_artifact_is_used_and_stale_artifact_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = pd.DataFrame([
                (q, 1.2, 1., .1, diameter, 25)
                for q, diameter in [(1.5, 140.), (1.8, 144.), (2.3, 153.)]
            ], columns=[*FEATURES, 'mean_d50_px', 'valid_images'])
            training = root / 'conditions.csv'
            frame.to_csv(training, index=False)
            kernel = fit_kernel(frame[list(FEATURES)].to_numpy(), frame.mean_d50_px, 'RBF')
            kernel.update(conditions_sha256=hashlib.sha256(training.read_bytes()).hexdigest(),
                          q_change_mae_px=5.7, source_change_mae_px=5.8)
            artifact = root / 'rbf_model.json'
            artifact.write_text(json.dumps(kernel), encoding='utf-8')
            legacy = {'selected_model': 'Linear', 'coefficients': [130, 0, 0, 0, 0],
                      'metrics': {'Linear': {'mae_px': 9}, 'ConditionMean': {'mae_px': 10}}}
            (root / 'model.json').write_text(json.dumps(legacy), encoding='utf-8')
            with patch.object(predictor, 'RUN', root):
                result = predictor.predict_continuous(1.5, 2., 1., .1, 1.2)
                self.assertEqual(result['prediction_model'], 'RBF')
                self.assertAlmostEqual(result['predicted_d50_px'],
                                       predict_kernel(kernel, [2., 1.2, 1., .1])[0])
                self.assertFalse(result['target_data_available'])
                kernel['conditions_sha256'] = 'stale'
                artifact.write_text(json.dumps(kernel), encoding='utf-8')
                self.assertEqual(predictor.predict_continuous(1.5, 2., 1., .1, 1.2)
                                 ['prediction_model'], 'Linear')


if __name__=='__main__':unittest.main()
