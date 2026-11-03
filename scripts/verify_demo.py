"""Exercise real image -> CSV -> cross-turn synthesis.

Run: conda run -n BIFBAgent python scripts/verify_demo.py
Default uses scripted local model responses and real YOLO/statistics.
Add --live only to explicitly opt into sending examples to the configured LLM.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent import Run, run_agent
from app.analysis import register_data_tools
from app.config import DATA, load_settings, local_path
from app.registry import ToolRegistry
from app.storage import Session, compact
from app.yolo_adapter import register_vision_tools


class LocalDemoModel:
    """Deterministic protocol fixture. This does not validate LLM reasoning quality."""

    def __init__(self, session):
        self.session = session

    async def complete(self, messages, tools=None):
        question = next(message["content"] for message in reversed(messages) if message["role"] == "user")
        current_tools = []
        for message in reversed(messages):
            if message["role"] == "user":
                break
            if message["role"] == "tool":
                current_tools.append(json.loads(message["content"]))
        if not current_tools:
            if "合成 CSV" in question:
                name, arguments = "inspect_csv", {"csv_path": self.session.assets[-1]["path"]}
            elif "描述性比较" in question:
                image = next(value for value in self.session.results.values() if value["tool"] == "detect_bubbles")
                csv = next(value for value in self.session.results.values() if value["tool"] == "analyze_csv")
                name, arguments = "compare_experiments", {
                    "left_result_id": image["result_id"], "right_result_id": csv["result_id"],
                    "left_column": "diameter", "right_column": "bubble_diameter_mm",
                    "left_unit": image["unit"], "right_unit": "mm"}
            else:
                name, arguments = "detect_bubbles", {"image_path": self.session.assets[0]["path"]}
        elif "合成 CSV" in question and len(current_tools) == 1:
            name, arguments = "analyze_csv", {"csv_path": self.session.assets[-1]["path"],
                                             "x_column": "gas_velocity_m_s", "y_column": "bubble_diameter_mm", "group_by": "condition"}
        else:
            return {"role": "assistant", "content": "本机协议验收完成；真实计算结果见 " + ", ".join("[" + item["result_id"] + "]" for item in current_tools) + "。本段是固定测试文本，不是 LLM 科研结论。"}
        return {"role": "assistant", "content": "执行专业计算工具。", "tool_calls": [{"id": uuid.uuid4().hex, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


async def main(live=False):
    settings = load_settings()
    if live and not settings.llm_ready:
        raise RuntimeError("请先配置支持 Tool Calling 的 LLM。")
    registry = ToolRegistry()
    register_vision_tools(registry)
    register_data_tools(registry)
    session = Session()
    session.grant(local_path(settings.yolo_tracker_path) / "data/dataset/test_images/0228.tif")
    steps = [
        ("检测刚添加的气泡图片，统计数量、平均等效直径和置信度。必须调用检测工具，只使用本次工具结果。", {"detect_bubbles"}),
        ("分析刚添加的合成 CSV，先检查列名，再分析气速与气泡直径的关系，并按 condition 分组。说明它是合成教学数据。", {"inspect_csv", "analyze_csv"}),
        ("结合此前图像检测和 CSV 的结果做描述性比较，调用 compare_experiments。单位依据已有结果和列名；不重复检测或读取 CSV。两者并非同一实验，不推断因果或显著性，引用结果编号并说明不能支持的结论。", {"compare_experiments"}),
    ]
    report = {"validation_id": uuid.uuid4().hex, "mode": "live_llm" if live else "local_protocol_real_tools", "steps": [], "passed": False}
    local_model = LocalDemoModel(session)
    for index, (message, required_tools) in enumerate(steps):
        if index == 1:
            session.grant(ROOT / "examples/bubble_experiment.csv")
        run = Run(session.id)
        session.busy = True
        if live:
            await run_agent(run, session, settings, registry, message)
        else:
            with patch("app.agent.LLMClient", return_value=local_model):
                await run_agent(run, session, settings, registry, message)
        tools = {event["tool"] for event in run.events if event["type"] == "tool_start"}
        errors = [event["message"] for event in run.events if event["type"] == "error"]
        tool_errors = [event["tool"] for event in run.events if event["type"] == "tool_result" and event["result"]["status"] == "error"]
        finals = [event["message"] for event in run.events if event["type"] == "final"]
        passed = bool(finals) and not errors and not tool_errors and required_tools.issubset(tools)
        step = {"round": index + 1, "run_id": run.id, "tools": sorted(tools),
                "passed": passed, "errors": errors, "tool_errors": tool_errors,
                "final": finals[-1] if finals else None}
        report["steps"].append(step)
        print(json.dumps({key: value for key, value in step.items() if key != "final"}, ensure_ascii=False), flush=True)
        if not passed:
            break
    report["passed"] = len(report["steps"]) == 3 and all(step["passed"] for step in report["steps"])
    report["results"] = [compact(result, 3) for result in session.results.values()]
    destination = DATA / "validation" / (report["validation_id"] + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report:", destination, flush=True)
    if not report["passed"]:
        raise RuntimeError("综合验收未通过，请查看报告中的具体失败步骤。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="发送随项目提供的示例数据到已配置的外部 LLM，使用真实 API 验收")
    options = parser.parse_args()
    asyncio.run(main(live=options.live))
