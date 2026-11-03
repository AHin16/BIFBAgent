import asyncio
import io
import logging
import mimetypes
import shutil
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent import Run, run_agent
from app.analysis import register_data_tools
from app.config import DATA, INPUT_EXTENSIONS, ROOT, Settings, load_settings, local_path, save_settings
from app.llm import LLMClient
from app.folder_picker import select_folder
from app.flow_warning import FlowSettings, register_flow_tools, save_flow_config
from app.registry import ToolRegistry
from app.storage import Session, ToolError, dump_json
from app.yolo_adapter import register_vision_tools


DATA.mkdir(exist_ok=True)
(DATA / "uploads").mkdir(exist_ok=True)
(DATA / "outputs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                    handlers=[logging.FileHandler(DATA / "app.log", encoding="utf-8"), logging.StreamHandler()])
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
# Windows registry MIME entries may report image/svg, which Chromium rejects.
mimetypes.init()
mimetypes.add_type("image/svg+xml", ".svg")
app = FastAPI(title="BIFB 智能科研助手", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
app.mount("/artifacts", StaticFiles(directory=DATA / "outputs"), name="artifacts")
settings = load_settings()
sessions = {}
runs = {}
registry = ToolRegistry()
register_vision_tools(registry)
register_data_tools(registry)
register_flow_tools(registry)


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and urlsplit(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "请从本机 Demo 页面提交请求。"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(ToolError)
async def tool_error_handler(request, error):
    return JSONResponse({"detail": str(error)}, status_code=400)


@app.exception_handler(ValidationError)
async def settings_error_handler(request, error):
    return JSONResponse({"detail": "配置格式不正确，请检查地址和参数范围。"}, status_code=422)


def get_session(session_id):
    if session_id not in sessions:
        raise HTTPException(404, "会话已失效，请刷新页面创建新会话。")
    return sessions[session_id]


def ensure_idle(session):
    if session.busy:
        raise HTTPException(409, "当前分析尚未结束，请稍候。")


@app.get("/")
def index():
    return FileResponse(ROOT / "app/static/index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "settings": settings.public(), "tools": [item["function"]["name"] for item in registry.definitions()]}


@app.get("/api/settings")
def read_settings():
    return settings.public()


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None = None
    clear_api_key: bool = False
    yolo_tracker_path: str
    yolo_model_path: str
    yolo_device: str = "auto"
    confidence: float
    mm_per_pixel: float | None = None


class ModelListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_base_url: str | None = None
    llm_api_key: str | None = None


@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    global settings
    if any(session.busy for session in sessions.values()):
        raise HTTPException(409, "分析进行中，请在结束后修改运行设置。")
    values = settings.model_dump()
    values.update(payload.model_dump(exclude={"llm_api_key", "clear_api_key"}))
    if payload.clear_api_key:
        values["llm_api_key"] = ""
    elif payload.llm_api_key:
        values["llm_api_key"] = payload.llm_api_key.strip()
    updated = Settings(**values)
    save_settings(updated)
    settings = updated
    return settings.public()


@app.post("/api/settings/test")
async def test_settings():
    return await LLMClient(settings.model_copy()).test_connection()


@app.post("/api/settings/models")
async def list_models(payload: ModelListRequest):
    """Fetch model IDs from an OpenAI-compatible /models endpoint without persisting the key."""
    base_url = (payload.llm_base_url or settings.llm_base_url).strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise ToolError("API Base URL 无效，请填写例如 https://example.com/v1。")
    endpoint = base_url if base_url.endswith("/models") else base_url + "/models"
    api_key = payload.llm_api_key if payload.llm_api_key is not None and payload.llm_api_key.strip() else settings.llm_api_key
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key.strip()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
            response = await client.get(endpoint, headers=headers)
    except httpx.TimeoutException as error:
        raise ToolError("获取模型列表超时，请检查 API 地址或网络。") from error
    except httpx.RequestError as error:
        raise ToolError("无法连接模型服务，请检查 API Base URL。") from error
    if response.status_code >= 400:
        reason = {401: "API Key 无效或未填写", 403: "没有访问模型列表的权限", 404: "没有找到 /models 接口"}.get(response.status_code, "模型服务返回错误")
        raise ToolError(f"获取模型列表失败（{response.status_code}）：{reason}。")
    try:
        body = response.json()
    except ValueError as error:
        raise ToolError("模型服务返回的不是 JSON。") from error
    raw_models = body.get("data", body.get("models", [])) if isinstance(body, dict) else []
    models = sorted({str(item.get("id", item.get("name", ""))).strip() for item in raw_models
                     if isinstance(item, dict) and str(item.get("id", item.get("name", ""))).strip()})
    if not models:
        raise ToolError("模型服务返回列表为空，或响应不是标准 {data: [{id: ...}]} 格式。")
    return {"status": "success", "models": models, "count": len(models), "endpoint": endpoint}


@app.post("/api/sessions")
def create_session():
    session = Session()
    sessions[session.id] = session
    return {"session_id": session.id}


@app.get("/api/sessions/{session_id}")
def session_state(session_id: str):
    session = get_session(session_id)
    return {"session_id": session.id, "assets": session.assets, "history": session.history, "busy": session.busy,
            "flow_config": list(session.flow_configs.values())[-1] if session.flow_configs else None}


@app.post("/api/sessions/{session_id}/flow-config")
def configure_flow(session_id: str, payload: FlowSettings):
    session = get_session(session_id)
    ensure_idle(session)
    previous_assets = list(session.assets)
    try:
        session.grant(payload.baseline_path)
        session.grant(payload.input_path)
        config = save_flow_config(session, payload, settings)
    except Exception:
        session.assets = previous_assets
        raise
    return {"flow_config": config, "assets": session.assets}


class LocalInput(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@app.post("/api/sessions/{session_id}/paths")
def add_path(session_id: str, payload: LocalInput):
    session = get_session(session_id)
    ensure_idle(session)
    return session.grant(payload.path)


@app.get("/api/dialog/folder")
def choose_folder():
    """Browser mode: isolate the GUI main thread from the ASGI worker pool."""
    return select_folder()


@app.delete("/api/sessions/{session_id}/assets/{asset_id}")
def remove_asset(session_id: str, asset_id: str):
    session = get_session(session_id)
    ensure_idle(session)
    session.assets = [asset for asset in session.assets if asset["id"] != asset_id]
    return {"status": "success"}


@app.post("/api/sessions/{session_id}/uploads")
async def upload_files(session_id: str, files: list[UploadFile] = File(...), folder: bool = False):
    session = get_session(session_id)
    ensure_idle(session)
    if not files or len(files) > 500:
        raise ToolError("每次请上传 1–500 个文件。")
    upload_root = DATA / "uploads" / session.id / uuid.uuid4().hex
    upload_root.mkdir(parents=True)
    stored = []
    total = 0
    try:
        for uploaded in files:
            relative = PurePosixPath((uploaded.filename or "").replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
                raise ToolError("文件名包含无效路径。")
            if relative.suffix.lower() not in INPUT_EXTENSIONS:
                raise ToolError("仅支持图片和 CSV；请选择这些文件后重试。")
            target = upload_root.joinpath(*relative.parts).resolve()
            if not target.is_relative_to(upload_root.resolve()) or target.exists():
                raise ToolError("上传文件路径重复或无效。")
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with target.open("wb") as stream:
                while block := await uploaded.read(1024 * 1024):
                    size += len(block)
                    total += len(block)
                    if size > 50 * 1024 * 1024 or total > 250 * 1024 * 1024:
                        raise ToolError("单个文件最多 50 MB，单次上传最多 250 MB；大批次请用本地路径。")
                    stream.write(block)
            stored.append(target)
        if folder:
            roots = {PurePosixPath((item.filename or "").replace("\\", "/")).parts[0] for item in files}
            candidate = upload_root / next(iter(roots)) if len(roots) == 1 else upload_root
            asset = session.grant(candidate if candidate.is_dir() else upload_root)
            return {"assets": [asset]}
        return {"assets": [session.grant(path) for path in stored]}
    except Exception:
        shutil.rmtree(upload_root)
        raise
    finally:
        for uploaded in files:
            await uploaded.close()


@app.get("/api/sessions/{session_id}/assets/{asset_id}/preview")
def preview_asset(session_id: str, asset_id: str):
    session = get_session(session_id)
    asset = next((item for item in session.assets if item["id"] == asset_id), None)
    if not asset or asset["kind"] != "image":
        raise HTTPException(404, "没有可预览的图片。")
    try:
        with Image.open(session.resolve(asset["path"])) as image:
            image.thumbnail((1400, 1000))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ToolError("无法预览图片，请检查格式或文件完整性。") from error


@app.post("/api/sessions/{session_id}/examples/{kind}")
def add_example(session_id: str, kind: str):
    session = get_session(session_id)
    ensure_idle(session)
    if kind == "csv":
        path = ROOT / "examples/bubble_experiment.csv"
    elif kind in {"image", "folder"}:
        path = local_path(settings.yolo_tracker_path) / "data/dataset/test_images"
        if kind == "image":
            path = path / "0228.tif"
    else:
        raise HTTPException(404, "未知示例。")
    return session.grant(path)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    flow_config_id: str | None = None


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, payload: ChatInput):
    session = get_session(session_id)
    ensure_idle(session)
    if not payload.message.strip():
        raise ToolError("请输入科研任务。")
    if not settings.llm_ready:
        raise ToolError("请先在右上角「运行设置」配置 LLM 地址、模型名称和 API Key。")
    if payload.flow_config_id and payload.flow_config_id not in session.flow_configs:
        raise ToolError("流态任务配置已失效，请重新确认。")
    session.busy = True
    run = Run(session.id)
    runs[run.id] = run
    run.task = asyncio.create_task(run_agent(run, session, settings.model_copy(), registry, payload.message.strip(), payload.flow_config_id))
    return {"run_id": run.id}


@app.post("/api/sessions/{session_id}/runs/{run_id}/stop")
async def stop_run(session_id: str, run_id: str):
    session = get_session(session_id)
    run = runs.get(run_id)
    if run is None or run.session_id != session.id:
        raise HTTPException(404, "任务不存在。")
    if not run.done:
        run.stop_event.set()
        run.emit("status", {"message": "正在停止并保存已经完成的分析结果…"})
    return {"status": "stopping" if not run.done else "done"}


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str, request: Request):
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(404, "任务不存在。")
    try:
        start = max(0, int(request.headers.get("last-event-id", "-1")) + 1)
    except ValueError:
        start = 0
    async def stream():
        cursor = start
        heartbeat = 0
        while True:
            if await request.is_disconnected():
                break
            while cursor < len(run.events):
                event = run.events[cursor]
                yield f"id: {cursor}\ndata: {dump_json(event)}\n\n"
                cursor += 1
            if run.done:
                break
            heartbeat += 1
            if heartbeat % 50 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.2)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
