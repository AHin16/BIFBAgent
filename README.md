# BIFB 智能科研助手 Demo

这是一个 Windows 本地科研分析 Demo：用户只描述研究任务，Agent 会自动选择 YOLO 气泡检测、CSV 统计、分布分析和结果比较工具，并把工具参数、Observation、图表、结构化数据和科研解释显示在同一个网页中。

## 启动

在项目目录执行独立窗口版本：

```powershell
conda run --no-capture-output -n BIFBAgent python desktop.py
```

也可以双击 `START.bat`。独立窗口使用当前 `BIFBAgent` 环境已有的 **PySide6 / Qt WebEngine**，不依赖浏览器 App 模式。重复启动会唤起已有窗口；默认端口被其他程序占用时自动选择空闲端口；关闭窗口会结束本程序自己的本地服务。纯网页调试仍可使用 `START_WEB.bat` 或 `python run.py`。

在新环境先安装运行依赖与桌面组件，并将已有气泡权重复制到 `models/3900.pt`（或启动后选择其他权重路径）：

```powershell
conda run --no-capture-output -n BIFBAgent python -m pip install -r requirements.txt -r requirements-desktop.txt
```

使用 GPU 时需安装适合本机驱动的 CUDA 版 PyTorch；也可在运行设置中选择 CPU。安装依赖时使用正式发布的 Ultralytics 包，无需链接本地 YOLOTracker 或其他 YOLO 源码项目。

首页使用红白配色的科研 Dashboard：左侧导航、五个研究模块和自然语言任务输入。实验分析（图像与 CSV）、流态监测预警、专业知识问答已开放；气含率、参数优化点击后显示“功能正在推进中”。

第一次打开软件，点右上角「运行设置」：

1. 填写 OpenAI-compatible 的 `API Base URL` 和 API Key（本地免鉴权服务可留空）。点击「获取模型列表」会调用该服务的 `/models` 接口，模型名称可直接选择，不会自动保存新 Key。
2. 点击「选择权重」选择气泡模型，例如 `3900.pt`，也可以直接填写本地路径。YOLO 推理、图片读取和流态分析均已内置，不需要安装或指定 YOLOTracker 项目。桌面版使用原生文件选择器，网页模式使用独立 Qt 对话框。
3. 如有真实标定，在「空间标定」填写 `mm/px`；留空时只报告 `px`。
4. 点击「保存并测试 LLM」，测试模型是否真的支持标准 Tool Calling。

## 快速演示

不需要准备数据时，左侧「从示例开始」可以添加本项目自带的真实气泡测试图或示例 CSV。可直接输入：

- `检测这张气泡图片，统计气泡数量、平均直径和尺寸分布。`
- `分析这个文件夹里的全部气泡图片，统计尺寸分布并导出 CSV。`
- `分析这个 CSV，看看气速和气泡直径有什么关系，并比较不同工况。`
- `结合刚才的图像检测和 CSV 分析结果，总结实验规律，说明测量依据和局限。`

支持 JPG、PNG、TIFF、BMP、WEBP、CSV。单张图片和 CSV 可以上传；文件夹请使用「选择实验文件夹」或本地路径，系统只登记 Windows 路径，YOLO 分析时直接递归读取原文件夹，不上传图片。文件夹分析最多 500 张图片，单文件最多 50 MB，单次上传最多 250 MB。

桌面版文件夹选择通过 Qt WebChannel 交给窗口主线程；网页模式通过独立的 Qt 进程打开选择器。两种模式都正常区分取消和失败，不再从 FastAPI 工作线程调用 Tkinter。

## 流态监测预警与 LLM 分析

1. 点击首页「流态监测预警」，选择正常基线和待测图片目录，或直接填写 MP4/AVI/MOV/MKV 的本地路径。
2. 填写两段数据共同的实际采集帧率、空间标定和窗口长度。需要时在高级设置中调整共同 ROI、最少样本数、触发/恢复持续窗口数。模型、置信度和设备使用本次保存配置时的运行设置。
3. 明确确认基线属于正常工况，且两段序列等间隔连续、时间口径与标定一致。Agent 无权替你确认这些实验事实。基线与待测来源不能相同或相互包含。
4. 点击「开始监测并分析」。Agent 自动调用 `analyze_flow_warning(config_id)`，执行内置的 `run_flow_warning`，再根据结构化结果生成简单流动状态解释。
5. 页面显示气泡出现量、大气泡变化、运动状态，窗口趋势、事件时间/触发原因、证据帧及 CSV/JSON 导出。后续可在聊天中询问“解释刚才第一个预警事件”，Agent 可以查询已有结果，无需重跑。

当前 LLM 只接收窗口统计、基线阈值、事件和数据质量，不发送画面，不做视觉复核。解释应引用结果编号，并说明异常方向、时段和局限；不把偏离正常基线当作具体流型、危险等级或确定机理。`large_fraction`、`down_fraction` 为 0–1，`area_ratio` 为百分数，向上速度为正。

正常基线至少需要三个完整有效窗口；默认 30 FPS、0.5 s 窗口至少需 45 帧，且尺寸/运动指标各自需足够样本。原来的三帧示例不适合做预警基线。末尾不足完整窗口、坏帧和关联不足会显示“数据不足”，没有事件不等于正常。

分析期间可以「停止并保存」；桌面关闭会先请求停止并等待已完成结果保存。数据中断、序列结束、停止不会被解释为恢复。结果输出到 Agent 的 `data/outputs/`。

## 专业知识问答

「专业知识问答」支持 PDF/TXT/Markdown 导入、本地路径导入、按资料选择范围、原文检索和带引用回答。本次提供的 Ma 等 BIFB 论文已经导入本机知识库，保留原始文件、10 页文本和 33 个片段，重启软件后仍可使用。

- 先选择参考资料，然后输入问题。点击「仅检索原文」在本机查找，不调用 LLM；点击发送会把问题所需片段和文档信息交给已配置模型。
- 回答引用按 PDF 从 1 起的页码显示，可点击打开提取片段与原始页面，也可下载原始文件。程序校验引用编号确实来自本轮检索，但不自动证明模型每句话都得到原文支持。
- 可以问“论文装置、物料和气速范围是什么”“气速怎样影响气泡尺寸与上升速度”“四种流化状态如何描述”，也可结合本会话中的实验结果继续询问。
- 论文工况不自动变为当前实验参数。扫描 PDF 会提示需要 OCR；公式、上下标和表格可能提取失真，精确表达式须查看原页。本版不做 OCR、联网检索或公式自动计算。
- `data/knowledge/library.sqlite3` 保存文档/页码/片段和词项，`data/knowledge/<内容哈希>/` 保存原始文件及按需生成的原页预览。重复文档按内容哈希去重。
- 检索采用本地 BM25、中英术语扩展和少量词组加权；返回相关度不等于可信度。当前没有向量模型或外部向量服务。资料不足时返回缺少依据，不生成伪论文引用。

## 验证

```powershell
conda run --no-capture-output -n BIFBAgent python -m unittest discover -s tests -v
conda run --no-capture-output -n BIFBAgent python scripts/verify_demo.py
conda run --no-capture-output -n BIFBAgent python scripts/verify_yolo.py
conda run --no-capture-output -n BIFBAgent python scripts/verify_flow.py
conda run --no-capture-output -n BIFBAgent python scripts/verify_knowledge.py
```

第二条命令默认使用本机固定模型响应，执行真实 YOLO、CSV 统计和跨轮比较，保存 `data/validation/*.json`。它验证工具协议和上下文，不验证 LLM 的理解与解释质量。需要验证实际模型时，明确选择 `python scripts/verify_demo.py --live`，该模式会将随项目提供的测试图片检测统计、合成 CSV 统计和任务文本发送到已配置的 LLM API。

`verify_yolo.py` 使用真实权重验证中文路径单图、按目录分组批处理、损坏图片容错及 CSV/图表导出，禁止读取旧 YOLOTracker 源码目录，不调用 LLM。通过 `--ultralytics-path <包所在目录>` 可以指定隔离安装的官方 Ultralytics；通过 `--block-path <目录>` 可以额外禁止读取其他源码目录。报告保存包版本、实际模块路径及被禁止的读取尝试。2026-11-10 已用官方 8.3.63 验证：同时禁止访问 `E:\YOLOTracker` 和 `E:\yolov12`，单图检测 24 个、两张重复图合计 48 次检测，损坏图片单独报错。重复图只验证集成，不代表不同实验工况。

`verify_flow.py` 使用真实权重、原始流态算法和重复示例图检查集成，不调用 LLM API；重复图仅为接口检查，不代表真实连续实验或预警精度。流态测试覆盖正常/异常、缺少掩膜、末尾不足窗口、停止保留结果、配置确认及 LLM 取得 Observation 后解释。

`verify_knowledge.py` 默认本地固定模型响应，验证提供的 BIFB 论文中装置/气泡尺寸/流化状态/测速方法的页码命中和引用闭环。`--live` 会将测试问题、文档信息和检索片段发送到已配置的 LLM，仅在明确同意发送这些内容时使用。远程自动验收脚本被自动审批拦截，未重试；当前桌面会话已有一轮真实问答记录，装置 0.33 m、3.0 m 和 0–20 mm/s 已与第 2 页原文核对，这不代表其他专业问题均已验证。

## 目录

- `app/main.py`：FastAPI 路由、会话、上传、SSE 行动流。
- `desktop.py`：Qt 独立窗口、主线程文件夹选择、单实例唤起和本地服务生命周期。
- `app/folder_picker.py`：网页模式的独立 GUI 进程。
- `app/agent.py`：透明的单 Agent Loop（LLM → Tool Call → Tool Result → Observation）。
- `app/registry.py`：统一 Tool Registry、Pydantic 参数校验和错误处理。
- `app/yolo_adapter.py`：使用内置预测器和所选权重，统一输出检测、测量与统计结果。
- `app/vision/`：从 YOLOTracker 迁入的推理、BiFPN 权重兼容、图片读取及流态工作流；保留原有检测与预警算法，来源及原始文件哈希见该目录 README。
- `app/flow_warning.py`：确认后的流态任务配置、原始工作流适配、窗口/事件摘要及工具注册。
- `app/knowledge.py`：文档解析、SQLite 持久化、本地检索、引用核验及知识工具。
- `app/static/knowledge.js`：资料选择、问答、本地检索及可点击原文证据。
- `app/analysis.py`：CSV 读取、描述统计、分组、Pearson 相关、线性趋势、IQR 异常候选、图表。
- `app/static/`：原生 HTML/CSS/JavaScript UI。
- `examples/images/`：内置真实气泡示例图，单图和文件夹演示不依赖外部项目。
- `data/outputs/`：每次运行的图表、检测图、CSV、JSON、Markdown 报告和 activity trace。

## 说明

模型权重单独配置，不随源代码提交。新配置默认路径为 `models/3900.pt`；也可选择其他目录中的权重文件。升级时保留已有模型路径、设备、标定和 LLM 配置，旧 `yolo_tracker_path` / `YOLO_TRACKER_PATH` 会被忽略，下一次保存设置后从本地配置中移除。旧 `data/backend/` 缓存不再使用。移走旧 YOLOTracker 目录前，若模型权重仍保存在其中，请先将权重复制到其他位置并重新选择。

YOLO 结果中的直径是二维等效圆直径；掩膜不存在时会明确标记为检测框面积估计。批量结果的气泡总数是跨图片的检测次数，不是跟踪去重后的独立气泡数。CSV 相关性描述关联，不代表因果关系；工具会把这些限制带入最终回答。

LLM 不执行 Python、不计算统计量，也不能访问未添加的数据源。所有文件内容都按数据处理，工具参数由 Pydantic 校验；详细错误写入 `data/app.log`，页面只显示可操作的友好提示。
