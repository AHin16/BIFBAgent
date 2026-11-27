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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent import Run, run_agent, run_holdup
from app.analysis import register_data_tools
from app.config import DATA, IMAGE_EXTENSIONS, INPUT_EXTENSIONS, ROOT, Settings, load_settings, local_path, save_settings
from app.llm import LLMClient
from app.folder_picker import select_folder, select_model
from app.flow_warning import FlowSettings, register_flow_tools, save_flow_config
from app.h3_demo_tool import register_h3_demo_tool
from app.knowledge import knowledge_store, register_knowledge_tools
from app.registry import ToolRegistry
from app.sequence_analysis import register_sequence_tools
from app.storage import Session, ToolError, compact, dump_json
from app.yolo_adapter import register_vision_tools
from app.ug_bubble_predictor import available_prediction_heights, register_ug_prediction_tool
from app.condition_vision import available_conditions, register_condition_vision
from optimization_data.h3_bubble_demo.build_demo import render_demo_html
from optimization_data.h3_bubble_demo.model import validate_flow
from optimization_data.h3_bubble_demo.transport import TransportModel


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
app = FastAPI(title="污水处理智能分析与优化 Agent", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
app.mount("/artifacts", StaticFiles(directory=DATA / "outputs"), name="artifacts")
settings = load_settings()
sessions = {}
runs = {}
registry = ToolRegistry()
register_vision_tools(registry)
register_sequence_tools(registry)
register_condition_vision(registry)
register_data_tools(registry)
register_flow_tools(registry)
register_knowledge_tools(registry)
register_ug_prediction_tool(registry)
register_h3_demo_tool(registry)
HoldupRequest = registry.tools["estimate_gas_holdup"].schema


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


@app.get("/optimization/h3-demo", response_class=HTMLResponse)
def h3_bubble_demo():
    try:
        return render_demo_html(with_transport=True)
    except (OSError, ValueError, KeyError):
        logger.exception("Unable to load H3 bubble demo")
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<p role="alert">污水曝气参数优化暂不可用，请检查本地四档照片统计。'
            '<a href="/optimization/h3-demo">重新加载</a></p></html>',
            status_code=503,
        )


@app.get("/api/optimization/h3-transport")
def h3_transport(current_q: float, target_q: float):
    try:
        validate_flow(current_q, "当前")
        validate_flow(target_q, "目标")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        return TransportModel.load().predict(current_q, target_q)
    except (OSError, ValueError, KeyError) as error:
        logger.warning("H3 transport measurements unavailable: %s", error)
        raise HTTPException(503, "上升速度与传氧数据暂不可用。") from error


@app.get("/api/health")
def health():
    return {"status": "ok", "settings": settings.public(), "tools": [item["function"]["name"] for item in registry.definitions()],
            "prediction_heights": available_prediction_heights()}


@app.get("/api/settings")
def read_settings():
    return settings.public()


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None = None
    clear_api_key: bool = False
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
    if payload.mm_per_pixel != settings.mm_per_pixel:
        values['prediction_calibration_confirmed'] = False
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


@app.get("/api/knowledge/documents")
def knowledge_documents():
    return {"documents": knowledge_store.documents()}


class KnowledgeImport(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@app.post("/api/knowledge/import")
def import_knowledge(payload: KnowledgeImport):
    return knowledge_store.import_document(payload.path)


@app.post("/api/knowledge/uploads")
async def upload_knowledge(file: UploadFile = File(...)):
    name = PurePosixPath((file.filename or "").replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise ToolError("知识库支持文本型 PDF、TXT 和 Markdown。")
    temporary = DATA / "knowledge" / "imports"
    temporary.mkdir(parents=True, exist_ok=True)
    path = temporary / (uuid.uuid4().hex + suffix)
    try:
        size = 0
        with path.open("wb") as stream:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > 50 * 1024 * 1024:
                    raise ToolError("单篇文档最多 50 MB。")
                stream.write(block)
        return await asyncio.to_thread(knowledge_store.import_document, path, name)
    finally:
        path.unlink(missing_ok=True)
        await file.close()


class KnowledgeSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] | None = None


@app.post("/api/knowledge/search")
def search_knowledge_local(payload: KnowledgeSearch):
    return knowledge_store.search(payload.query, payload.document_ids)


@app.get("/api/knowledge/documents/{document_id}/pages/{page}")
def knowledge_page(document_id: str, page: int):
    return knowledge_store.page(document_id, page)


@app.get("/api/knowledge/documents/{document_id}/pages/{page}/image")
def knowledge_page_image(document_id: str, page: int):
    return FileResponse(knowledge_store.page_image(document_id, page), media_type="image/png")


@app.get("/api/knowledge/documents/{document_id}/file")
def knowledge_file(document_id: str):
    document, path = knowledge_store.source_file(document_id)
    return FileResponse(path, media_type="application/pdf" if document["format"] == "pdf" else "text/plain; charset=utf-8",
                        filename=document["filename"])


@app.get("/api/sessions/{session_id}")
def session_state(session_id: str):
    session = get_session(session_id)
    holdup = next((value for value in reversed(list(session.results.values()))
                   if value.get("kind") == "gas_holdup"), None)
    return {"session_id": session.id, "assets": session.assets, "history": session.history, "busy": session.busy,
            "flow_config": list(session.flow_configs.values())[-1] if session.flow_configs else None,
            "holdup_result": compact(holdup) if holdup is not None else None,
            "knowledge_citations": list(session.knowledge_citations.values())}


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
    image_only: bool = False


@app.get('/api/optimization/conditions')
def optimization_conditions():
    return {'conditions':available_conditions()}


@app.post("/api/sessions/{session_id}/paths")
def add_path(session_id: str, payload: LocalInput):
    session = get_session(session_id)
    ensure_idle(session)
    if payload.image_only:
        path = local_path(payload.path)
        if path.is_file() and path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ToolError("气含率估算需要图片文件或图片文件夹。")
    return session.grant(payload.path)


@app.post("/api/sessions/{session_id}/optimization-image")
def add_optimization_image(session_id: str, payload: LocalInput):
    from app.optimization_metadata import metadata_from_path
    session = get_session(session_id)
    ensure_idle(session)
    path = local_path(payload.path)
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ToolError('请选择存在的图片文件。')
    asset = session.grant(str(path))
    asset['optimization_metadata'] = metadata_from_path(path)
    return asset


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


@app.get("/api/dialog/model")
def choose_model():
    return select_model()


@app.post("/api/sessions/{session_id}/examples/{kind}")
def add_example(session_id: str, kind: str):
    session = get_session(session_id)
    ensure_idle(session)
    if kind == "csv":
        path = ROOT / "examples/bubble_experiment.csv"
    elif kind in {"image", "folder"}:
        path = ROOT / "examples/images"
        if kind == "image":
            path = path / "0228.tif"
    else:
        raise HTTPException(404, "未知示例。")
    return session.grant(path)


class OptimizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = ''
    current_q: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    current_ug_m_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_q: float = Field(allow_inf_nan=False)
    salinity_wt_pct: float = Field(allow_inf_nan=False)
    height_id: str = ''
    height_m: float | None = Field(default=None, allow_inf_nan=False)
    target_height_m: float | None = Field(default=None, allow_inf_nan=False)
    pl_confirmed: bool = False
    PL_fraction: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    source_root_name: str = ''
    prediction_mm_per_pixel: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    calibration_confirmed: bool = False
    use_history: bool = False


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    flow_config_id: str | None = None
    knowledge_mode: bool = False
    knowledge_document_ids: list[str] | None = None
    optimization: OptimizationInput | None = None
    holdup_result_id: str | None = None


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
    optimization = None
    if payload.optimization:
        config = payload.optimization
        asset=None
        if not config.use_history:
            asset=next((a for a in session.assets if a['id']==config.asset_id and a['kind']=='image'),None)
            if not asset: raise ToolError('请先添加一张当前工况图片。')
            session.resolve(asset['path'])
        if config.current_q is None and config.current_ug_m_s is None:
            raise ToolError('请输入当前气体流量 Q。')
        if config.current_q is not None and config.current_ug_m_s is not None:
            raise ToolError('请只提供当前 Q 或 Ug 中的一项。')
        if (config.prediction_mm_per_pixel is not None) != config.calibration_confirmed:
            raise ToolError('显示毫米需要填写比例尺，并确认它适用于当前照片及模型训练照片。')
        current_q = config.current_q if config.current_q is not None else config.current_ug_m_s / 0.00325
        heights = available_prediction_heights()
        if config.target_height_m is not None and config.height_m is None:
            raise ToolError('输入目标高度时也必须输入数值型当前高度。')
        if config.height_m is not None:
            from app.continuous_height_predictor import predict_continuous
            if config.PL_fraction is None: raise ToolError('请输入颗粒装载量 PL。')
            predict_continuous(current_q,config.target_q,config.salinity_wt_pct,config.PL_fraction,config.height_m,config.target_height_m)
        elif config.height_id not in heights:
            raise ToolError(f'当前预测模型支持高度 {"、".join(heights)}。')
        elif config.height_id == 'H3':
            from app.h3_bubble_predictor import predict_h3
            if config.PL_fraction is None:
                raise ToolError('请输入颗粒装载量 PL。')
            predict_h3(current_q, config.target_q, config.salinity_wt_pct, config.PL_fraction, config.source_root_name)
        elif abs(config.salinity_wt_pct - 1.0) > 1e-9 or not config.pl_confirmed:
            raise ToolError(f'当前预测模型支持高度 {"、".join(heights)}、盐度 1 wt%、PL 10%；请核对并确认实际工况。')
        if not 1.5 - 1e-9 <= current_q <= 2.3 + 1e-9:
            raise ToolError('当前 Q 超出模型范围 1.5–2.3 m³/h。')
        if not 1.5 - 1e-9 <= config.target_q <= 2.3 + 1e-9:
            raise ToolError('目标 Q 超出模型范围 1.5–2.3 m³/h。')
        source={'use_history':True} if config.use_history else {'image_path':asset['path']}
        if config.use_history:
            if config.height_m is None:raise ToolError('请选择历史工况的拍摄高度。')
            if not any(abs(row['current_q']-current_q)<1e-9 and abs(row['height_m']-config.height_m)<1e-9 and abs(row['salinity_wt_pct']-config.salinity_wt_pct)<1e-9 and abs(row['PL_fraction']-config.PL_fraction)<1e-9 for row in available_conditions()):
                raise ToolError('没有严格匹配的历史工况，请选择数据库中已有的当前工况。')
        optimization = {**source, 'current_q': current_q,
                        'target_q': config.target_q, 'salinity_wt_pct': config.salinity_wt_pct,
                        'PL_fraction': config.PL_fraction if config.height_m is not None or config.height_id == 'H3' else .1}
        if config.height_m is not None: optimization['height_m'] = config.height_m
        else: optimization['height_id'] = config.height_id
        if config.target_height_m is not None: optimization['target_height_m'] = config.target_height_m
        if config.height_m is None and config.height_id == 'H3': optimization['source_root_name'] = config.source_root_name
        if config.prediction_mm_per_pixel is not None:
            optimization['prediction_mm_per_pixel'] = config.prediction_mm_per_pixel
            optimization['calibration_confirmed'] = True
    if payload.holdup_result_id and session.results.get(payload.holdup_result_id, {}).get("kind") != "gas_holdup":
        raise ToolError("找不到本会话的气含率结果，请重新估算。")
    available_ids = {document["id"] for document in knowledge_store.documents()}
    if payload.knowledge_mode and not available_ids:
        raise ToolError("请先导入至少一篇知识文档。")
    if payload.knowledge_document_ids is not None and (not payload.knowledge_document_ids or not set(payload.knowledge_document_ids).issubset(available_ids)):
        raise ToolError("所选知识资料为空或已失效，请刷新资料列表。")
    session.busy = True
    run = Run(session.id)
    runs[run.id] = run
    run.task = asyncio.create_task(run_agent(run, session, settings.model_copy(), registry, payload.message.strip(), payload.flow_config_id,
                                           payload.knowledge_mode, payload.knowledge_document_ids, optimization,
                                           holdup_result_id=payload.holdup_result_id))
    return {"run_id": run.id}


@app.post("/api/sessions/{session_id}/holdup")
async def estimate_holdup(session_id: str, payload: HoldupRequest):
    session = get_session(session_id)
    ensure_idle(session)
    session.busy = True
    run = Run(session.id)
    runs[run.id] = run
    run.task = asyncio.create_task(run_holdup(run, session, settings.model_copy(), registry, payload.model_dump()))
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
