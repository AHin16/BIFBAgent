"""Check retrieval against the user's BIFB paper; optional --live checks configured MiMo.

Default uses local scripted model responses. --live sends the question, document metadata,
and retrieved excerpts of this paper to the configured LLM API; never sends the whole PDF.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent import Run, run_agent
from app.config import DATA, load_settings
from app.knowledge import knowledge_store, register_knowledge_tools
from app.registry import ToolRegistry
from app.storage import Session


async def main(live=False):
    documents = knowledge_store.documents()
    document = next((item for item in documents if "bubble" in item["title"].lower() and "inverse" in item["title"].lower()), None)
    if not document:
        raise RuntimeError("请先导入提供的 BIFB 论文。")
    checks = []
    for query, expected in (("实验装置内径和高度以及材料", 2), ("气速对气泡尺寸的影响", 6), ("不同流化状态有哪些", 9), ("上升速度怎样测量", 3)):
        pages = [hit["page"] for hit in knowledge_store.search(query, [document["id"]])["hits"]]
        checks.append({"query": query, "pages": pages, "expected_page": expected, "passed": expected in pages})
    registry = ToolRegistry()
    register_knowledge_tools(registry)
    session = Session()
    run = Run(session.id)
    question = "根据所选论文，实验装置的内径、高度，以及表观气速的操作范围分别是多少？请先检索原文，用中文简要回答并引用真实页码编号，说明这些数值是否可直接当作我当前实验参数。"
    class LocalModel:
        async def complete(self, messages, tools=None):
            observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
            if not observations:
                return {"role": "assistant", "content": None, "tool_calls": [{"id": "local-knowledge", "type": "function", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": "实验装置内径和高度以及材料"})}}]}
            citation = next(hit for hit in observations[-1]["hits"] if hit["page"] == 2)
            return {"role": "assistant", "content": "本机协议测试：已找到实验装置原文。 [" + citation["citation_id"] + "] 此处为固定测试文本，未评估真实 LLM 回答。"}
    settings = load_settings()
    if live:
        await run_agent(run, session, settings, registry, question, knowledge_mode=True, knowledge_document_ids=[document["id"]])
    else:
        with patch("app.agent.LLMClient", return_value=LocalModel()):
            await run_agent(run, session, settings, registry, question, knowledge_mode=True, knowledge_document_ids=[document["id"]])
    final = next((event for event in run.events if event["type"] == "final"), None)
    report = {"mode": "live_llm" if live else "local_protocol", "run_id": run.id, "document_id": document["id"],
              "retrieval_checks": checks, "answer": final["message"] if final else None,
              "citations": final.get("citations", []) if final else [],
              "errors": [event["message"] for event in run.events if event["type"] == "error"]}
    report["passed"] = all(check["passed"] for check in checks) and bool(report["citations"]) and not report["errors"]
    target = DATA / "validation" / ("knowledge_" + run.id + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print("Saved:", target, flush=True)
    if not report["passed"]:
        raise RuntimeError("知识问答验收未通过，请查看报告。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    options = parser.parse_args()
    asyncio.run(main(live=options.live))
