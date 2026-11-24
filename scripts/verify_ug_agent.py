"""Run one real configured LLM conversation for the synthetic H1 prediction request."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import Run, run_agent
from app.config import load_settings
from app.main import registry
from app.storage import Session


async def main():
    settings=load_settings(); session=Session(); run=Run(session.id)
    message='当前气体流量是1.5 m³/h，盐度1 wt%，颗粒装载量10%，高度H1；如果提高到2.0 m³/h，预测气泡尺寸如何变化？请说明依据和模型局限。'
    # No unrelated local document names are sent during this synthetic check.
    with patch('app.agent.knowledge_store.documents', return_value=[]):
        await run_agent(run, session, settings, registry, message)
    events=[event for event in run.events if event['type'] in ('tool_start','tool_result','error','final','done')]
    for event in events:
        if event['type']=='tool_result':
            result=event.get('result',{})
            print(json.dumps({'type':'tool_result','tool':event.get('tool'),'status':result.get('status'),'message':result.get('message')},ensure_ascii=False))
        else:
            print(json.dumps(event,ensure_ascii=False))
    ok=any(e['type']=='tool_result' and e.get('tool')=='predict_ug_bubble_diameter' and e.get('result',{}).get('status')=='success' for e in events)
    ok=ok and any(e['type']=='final' for e in events)
    if not ok: raise SystemExit('Live Agent prediction workflow did not complete')


if __name__=='__main__': asyncio.run(main())
