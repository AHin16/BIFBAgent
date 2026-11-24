"""Verify the optimization flow with the built-in image, real YOLO and configured LLM.

This sends the sample detection statistics and task parameters to the configured LLM.
"""
import asyncio
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.agent import Run, run_agent
from app.config import ROOT, load_settings
from app.main import registry
from app.storage import Session


async def main(height):
    session=Session(); asset=session.grant(ROOT/'examples/images/0228.tif'); run=Run(session.id)
    config={'image_path':asset['path'],'current_q':1.5,'target_q':2.0,'salinity_wt_pct':1.,'PL_fraction':.1,'height_id':height}
    with patch('app.agent.knowledge_store.documents',return_value=[]):
        await run_agent(run,session,load_settings(),registry,'请检测当前图片并预测目标气速的气泡尺寸，说明依据与局限。',optimization=config)
    events=[event for event in run.events if event['type'] in ('tool_start','tool_result','final','error','done')]
    for e in events:
        if e['type']=='tool_result':
            result=e['result']; print(json.dumps({'type':e['type'],'tool':e['tool'],'status':result.get('status'),
              'message':result.get('message'),'bubble_count':result.get('bubble_count'),
              'statistics_px':result.get('statistics_px'),'prediction_px':result.get('predicted_d50_px')},ensure_ascii=False),flush=True)
        else: print(json.dumps(e,ensure_ascii=False),flush=True)
    successful=[e['tool'] for e in events if e['type']=='tool_result' and e['result'].get('status')=='success']
    if not ('detect_bubbles' in successful and 'predict_ug_bubble_diameter' in successful and any(e['type']=='final' for e in events)):
        raise SystemExit('Optimization workflow did not complete')


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--height',choices=('H1','H2','H4'),default='H1')
    asyncio.run(main(parser.parse_args().height))
