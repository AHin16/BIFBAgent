import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import DATA, INPUT_EXTENSIONS, VIDEO_EXTENSIONS, local_path


class ToolError(Exception):
    pass


def clean_json(value):
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def dump_json(value):
    return json.dumps(clean_json(value), ensure_ascii=False, allow_nan=False)


def compact(value, list_limit=12):
    if isinstance(value, dict):
        result = {key: compact(item, list_limit) for key, item in value.items() if key not in {"raw_rows"}}
        return result
    if isinstance(value, list):
        result = [compact(item, list_limit) for item in value[:list_limit]]
        if len(value) > list_limit:
            result.append({"omitted_items": len(value) - list_limit, "note": "完整数据见导出文件"})
        return result
    return clean_json(value)


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    assets: list = field(default_factory=list)
    history: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    flow_configs: dict = field(default_factory=dict)
    knowledge_citations: dict = field(default_factory=dict)
    busy: bool = False

    def grant(self, path):
        path = local_path(str(path))
        if not path.exists():
            raise ToolError("路径不存在，请检查文件或文件夹地址。")
        if not path.is_dir() and path.suffix.lower() not in INPUT_EXTENSIONS:
            raise ToolError("当前支持图片、CSV 和本地视频文件。")
        existing = next((asset for asset in self.assets if asset["path"] == str(path)), None)
        if existing:
            return existing
        asset = {"id": uuid.uuid4().hex, "name": path.name, "path": str(path),
                 "kind": "folder" if path.is_dir() else "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "csv" if path.suffix.lower() == ".csv" else "image"}
        self.assets.append(asset)
        return asset

    def resolve(self, value, folder=False):
        path = local_path(value)
        permitted = any(path == Path(asset["path"]) or
                        (asset["kind"] == "folder" and path.is_relative_to(Path(asset["path"])))
                        for asset in self.assets)
        if not permitted:
            raise ToolError("请先通过上传或本地路径添加这个数据源，再让 Agent 分析。")
        if not path.exists() or (folder and not path.is_dir()) or (not folder and not path.is_file()):
            raise ToolError("输入文件或文件夹不存在，或类型不匹配。")
        if not folder and path.suffix.lower() not in INPUT_EXTENSIONS:
            raise ToolError("不支持这个文件类型。")
        return path


@dataclass
class ToolContext:
    session: Session
    settings: object
    run_id: str
    emit: object = lambda *args, **kwargs: None
    stop_event: object = None
    knowledge_scope: object = None
    citations: dict = field(default_factory=dict)

    @property
    def output_dir(self):
        path = DATA / "outputs" / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def output(self, name):
        return self.output_dir / f"{uuid.uuid4().hex[:8]}_{name}"

    def artifact(self, path, title, kind="file"):
        return {"title": title, "kind": kind,
                "url": "/artifacts/" + path.relative_to(DATA / "outputs").as_posix()}

    def result(self, result_id):
        if result_id not in self.session.results:
            raise ToolError("找不到该结果编号，请使用此前工具返回的 result_id。")
        return self.session.results[result_id]

    def store(self, tool_name, result):
        result = clean_json(result)
        result_id = uuid.uuid4().hex[:12]
        result.update(result_id=result_id, tool=tool_name)
        report = self.output(f"{tool_name}.json")
        report.write_text(dump_json(result), encoding="utf-8")
        result.setdefault("artifacts", []).append(self.artifact(report, "完整结构化结果 · JSON"))
        self.session.results[result_id] = result
        return result
