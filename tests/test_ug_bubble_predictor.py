import unittest
import asyncio
import json
from unittest.mock import patch
from app.storage import ToolError
from app.storage import Session
from app.agent import Run, run_agent
from app.config import ROOT, load_settings
from app.ug_bubble_predictor import GasVelocityBubblePredictor, register_ug_prediction_tool
from app.registry import ToolRegistry


class UgPredictorTest(unittest.TestCase):
    def setUp(self):
        fallback=patch('app.ug_bubble_predictor.HEIGHT_FULL_RUN', ROOT / 'data/nonexistent_height_model_test')
        fallback.start(); self.addCleanup(fallback.stop)

    def test_held_out_result_and_interpolation(self):
        result = GasVelocityBubblePredictor().predict(1.8, 2.0, 1.0, .1, 'H1')
        self.assertAlmostEqual(result['predicted_d50_px'],129.47762765417835)
        self.assertEqual(result['comparison']['evaluation_type'],'held_out_Q_2.0')
        self.assertFalse(result['comparison']['camera_conditions_confirmed'])
        self.assertEqual(result['current']['image_count'],25)
        self.assertAlmostEqual(result['change_px'], result['predicted_d50_px'] - result['current_predicted_d50_px'])
        self.assertNotAlmostEqual(result['change_px'], result['predicted_d50_px'] - result['current']['mean_image_d50_px'])

    def test_training_comparison_not_called_independent(self):
        result = GasVelocityBubblePredictor().predict(1.8,1.5,1.0,.1,'H1')
        self.assertEqual(result['comparison']['evaluation_type'],'training_condition_not_independent')

    def test_unsupported_inputs_and_no_ground_truth_for_intermediate_q(self):
        predictor = GasVelocityBubblePredictor()
        self.assertFalse(predictor.predict(1.8,1.9,1.0,.1,'H1')['target_data_available'])
        for args in [(1.8,2.4,1.,.1,'H1'), (1.4,2.,1.,.1,'H1'), (1.8,2.,1.,.1,'H2'), (1.8,2.,2.,.1,'H1'), (1.8,2.,1.,.15,'H1')]:
            with self.assertRaises(ToolError): predictor.predict(*args)
        self.assertIsNone(predictor.predict(1.9,2.,1.,.1,'H1')['current'])

    def test_registered(self):
        registry=ToolRegistry(); register_ug_prediction_tool(registry)
        self.assertIn('predict_ug_bubble_diameter',registry.tools)

    def test_agent_loop_delivers_observation(self):
        class StubModel:
            async def complete(self, messages, tools):
                observations = [m for m in messages if m['role'] == 'tool']
                if not observations:
                    args = {'current_q':1.5,'target_q':2.,'salinity_wt_pct':1.,'PL_fraction':.1,'height_id':'H1'}
                    return {'role':'assistant','content':None,'tool_calls':[{'id':'q1','type':'function','function':{'name':'predict_ug_bubble_diameter','arguments':json.dumps(args)}}]}
                result = json.loads(observations[-1]['content'])
                assert result['unit'] == 'px' and result['current_predicted_d50_px'] and result['limitations']
                return {'role':'assistant','content':'已根据工具返回结果完成预测。'}
        registry=ToolRegistry(); register_ug_prediction_tool(registry)
        session=Session(); run=Run(session.id)
        with patch('app.agent.LLMClient',return_value=StubModel()), patch('app.agent.knowledge_store.documents',return_value=[]):
            asyncio.run(run_agent(run,session,load_settings(),registry,'H1 盐度1% PL10%，Q从1.5变到2.0，预测气泡直径'))
        self.assertTrue(any(e['type']=='tool_result' and e['tool']=='predict_ug_bubble_diameter' and e['result']['status']=='success' for e in run.events))
        self.assertTrue(any(e['type']=='final' for e in run.events))


if __name__ == '__main__': unittest.main()
