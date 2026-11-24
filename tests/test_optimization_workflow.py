import asyncio
import json
import unittest
from unittest.mock import patch

from app.agent import Run, run_agent
from app.config import ROOT, load_settings
from app.registry import ToolRegistry
from app.storage import Session
from app.ug_bubble_predictor import register_ug_prediction_tool


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.session=Session()
        self.image=self.session.grant(ROOT/'examples/images/0228.tif')
        self.config={'image_path':self.image['path'],'current_q':1.5,'target_q':2.0,'salinity_wt_pct':1.0,'PL_fraction':.1,'height_id':'H1'}
        self.registry=ToolRegistry()
        @self.registry.register('test fixture')
        def detect_bubbles(context, image_path: str):
            return {'bubble_count':2,'statistics_px':{'mean':10.,'median':10.},'artifacts':[]}
        register_ug_prediction_tool(self.registry)

    def test_agent_executes_selected_photo_then_prediction(self):
        cfg=self.config
        class Model:
            async def complete(self, messages, tools):
                results=[x for x in messages if x['role']=='tool']
                if not results:
                    name='detect_bubbles'; arguments={'image_path':cfg['image_path']}
                elif len(results)==1:
                    name='predict_ug_bubble_diameter'; arguments={k:cfg[k] for k in ('current_q','target_q','salinity_wt_pct','PL_fraction','height_id')}
                else:
                    self_observations=[json.loads(item['content']) for item in results]
                    assert self_observations[0]['statistics_px']['median']==10
                    assert self_observations[1]['unit']=='px'
                    return {'role':'assistant','content':'当前检测和探索性预测已完成。'}
                return {'role':'assistant','content':None,'tool_calls':[{'id':str(len(results)),'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}
        run=Run(self.session.id)
        with patch('app.agent.LLMClient',return_value=Model()), patch('app.agent.knowledge_store.documents',return_value=[]):
            asyncio.run(run_agent(run,self.session,load_settings(),self.registry,'分析图片与目标气速',optimization=cfg))
        results=[event for event in run.events if event['type']=='tool_result']
        self.assertEqual([e['tool'] for e in results],['detect_bubbles','predict_ug_bubble_diameter'])
        self.assertTrue(all(e['result']['status']=='success' for e in results))
        self.assertTrue(any(e['type']=='final' for e in run.events))

    def test_missing_required_tools_cannot_claim_completion(self):
        class Model:
            async def complete(self, messages, tools): return {'role':'assistant','content':'分析完成。'}
        run=Run(self.session.id)
        with patch('app.agent.LLMClient',return_value=Model()), patch('app.agent.knowledge_store.documents',return_value=[]):
            asyncio.run(run_agent(run,self.session,load_settings(),self.registry,'分析图片与目标气速',optimization=self.config))
        self.assertFalse(any(e['type']=='final' for e in run.events))
        self.assertTrue(any(e['type']=='error' for e in run.events))

    def test_chat_rejects_unconfirmed_conditions(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions
        from app import main
        with TestClient(app) as client:
            sessions[self.session.id]=self.session
            base={'asset_id':self.image['id'],'current_ug_m_s':.004875,'target_q':2.,'salinity_wt_pct':1.,'height_id':'H1','pl_confirmed':True}
            for update in ({'height_id':'H5'},{'salinity_wt_pct':1.5},{'pl_confirmed':False},{'target_q':2.5},{'current_ug_m_s':.02},{'asset_id':'missing'}):
                with patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
                    response=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':{**base,**update}})
                self.assertEqual(response.status_code,400, response.text)
            sessions.pop(self.session.id,None)

    def test_upload_chat_and_sse_workflow(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions, registry
        from app import main
        class Model:
            async def complete(self, messages, tools):
                observations=[m for m in messages if m['role']=='tool']
                if not observations:
                    info=json.loads(messages[1]['content'].split('\n',1)[1]); name='detect_bubbles'; args={'image_path':info['assets'][-1]['path']}
                elif len(observations)==1:
                    name='predict_ug_bubble_diameter'; args={'current_q':1.5,'target_q':2.,'salinity_wt_pct':1.,'PL_fraction':.1,'height_id':'H1'}
                else: return {'role':'assistant','content':'已完成检测和探索性预测。'}
                return {'role':'assistant','content':None,'tool_calls':[{'id':str(len(observations)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
        def detection(context,image_path):
            return {'status':'success','bubble_count':2,'statistics_px':{'mean':10.,'median':10.},'artifacts':[]}
        with TestClient(app) as client, patch('app.agent.LLMClient',return_value=Model()), patch('app.agent.knowledge_store.documents',return_value=[]), patch.object(registry.tools['detect_bubbles'],'callable',detection), patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
            sid=client.post('/api/sessions').json()['session_id']
            try:
                data=(ROOT/'examples/images/0228.tif').read_bytes()
                upload=client.post(f'/api/sessions/{sid}/uploads',files={'files':('test.tif',data,'image/tiff')})
                self.assertEqual(upload.status_code,200,upload.text)
                asset=upload.json()['assets'][0]
                payload={'asset_id':asset['id'],'current_ug_m_s':.004875,'target_q':2.,'salinity_wt_pct':1.,'height_id':'H1','pl_confirmed':True}
                response=client.post(f'/api/sessions/{sid}/chat',json={'message':'分析','optimization':payload})
                self.assertEqual(response.status_code,200,response.text)
                response=client.get(f"/api/runs/{response.json()['run_id']}/events")
                events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                done=[e for e in events if e['type']=='tool_result' and e['result']['status']=='success']
                self.assertEqual([e['tool'] for e in done],['detect_bubbles','predict_ug_bubble_diameter'])
                self.assertTrue(any(e['type']=='done' and e['success'] for e in events))
            finally: sessions.pop(sid,None)

    def test_confirmed_height_is_forwarded_when_model_supports_it(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions
        from app import main
        from unittest.mock import AsyncMock
        fake=AsyncMock()
        with TestClient(app) as client, patch.object(main,'available_prediction_heights',return_value=['H1','H2','H4']), patch.object(main,'run_agent',fake), patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
            sessions[self.session.id]=self.session
            try:
                config={'asset_id':self.image['id'],'current_ug_m_s':.004875,'target_q':1.7,'salinity_wt_pct':1.,'height_id':'H2','pl_confirmed':True}
                response=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':config})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(fake.call_args.args[-1]['height_id'],'H2')
                self.assertEqual(fake.call_args.args[-1]['target_q'],1.7)
            finally: sessions.pop(self.session.id,None)

    def test_h3_parameters_and_source_are_forwarded(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions
        from app import main
        from unittest.mock import AsyncMock
        fake=AsyncMock()
        with TestClient(app) as client, patch.object(main,'available_prediction_heights',return_value=['H1','H3']), patch('app.h3_bubble_predictor.predict_h3',return_value={}) as predict, patch.object(main,'run_agent',fake), patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
            sessions[self.session.id]=self.session
            try:
                config={'asset_id':self.image['id'],'current_q':1.5,'target_q':1.8,'salinity_wt_pct':1.5,'height_id':'H3','PL_fraction':.075,'source_root_name':'盐水不同照片2'}
                response=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':config})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(fake.call_args.args[-1]['source_root_name'],'盐水不同照片2')
                self.assertEqual(fake.call_args.args[-1]['PL_fraction'],.075)
                self.assertEqual(fake.call_args.args[-1]['current_q'],1.5)
                predict.assert_called_once()
            finally: sessions.pop(self.session.id,None)

    def test_numeric_target_height_is_forwarded(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions
        from app import main
        from unittest.mock import AsyncMock
        fake=AsyncMock()
        with TestClient(app) as client, patch('app.continuous_height_predictor.predict_continuous',return_value={}) as predict, patch.object(main,'run_agent',fake), patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
            sessions[self.session.id]=self.session
            try:
                config={'asset_id':self.image['id'],'current_q':1.5,'target_q':1.8,'salinity_wt_pct':1.,'height_m':.8,'target_height_m':1.2,'PL_fraction':.1}
                response=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':config})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(fake.call_args.args[-1]['target_height_m'],1.2)
                self.assertEqual(predict.call_args.args[-1],1.2)
            finally:sessions.pop(self.session.id,None)

    def test_history_mode_accepts_exact_current_condition_without_image(self):
        from fastapi.testclient import TestClient
        from app.main import app,sessions
        from app import main
        from unittest.mock import AsyncMock
        fake=AsyncMock();conditions=[{'current_q':1.5,'height_m':.2,'salinity_wt_pct':1.,'PL_fraction':.1}]
        with TestClient(app) as client, patch.object(main,'available_conditions',return_value=conditions), patch('app.continuous_height_predictor.predict_continuous',return_value={}), patch.object(main,'run_agent',fake), patch.object(main,'settings',load_settings().model_copy(update={'llm_model':'fixture'})):
            sessions[self.session.id]=self.session
            try:
                config={'use_history':True,'current_q':1.5,'target_q':1.7,'salinity_wt_pct':1.,'height_m':.2,'PL_fraction':.1}
                response=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':config})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(fake.call_args.args[-1]['use_history'])
                self.assertNotIn('image_path',fake.call_args.args[-1])
                self.session.busy=False
                missing=client.post(f'/api/sessions/{self.session.id}/chat',json={'message':'分析','optimization':{**config,'current_q':1.6}})
                self.assertEqual(missing.status_code,400,missing.text)
            finally:sessions.pop(self.session.id,None)


if __name__=='__main__': unittest.main()
