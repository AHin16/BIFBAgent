# 污水处理智能分析与优化 Agent

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

首页使用红白配色的科研 Dashboard：实验分析（图像与 CSV）、气含率估算、气泡追踪与速度测量、流态监测预警、专业知识问答，以及基于模拟污水曝气实验的参数优化。

实验分析聊天支持探索性的气速变化预测：例如输入“当前 Q=1.5 m³/h，目标 Q=2.0 m³/h，盐度 1 wt%，颗粒装载量 10%，高度 1.2 m，预测气泡尺寸变化”。当前连续高度模型支持 Q 1.5–2.3 m³/h、高度 0.2–1.8 m、盐度 0.5–2.5 wt%、PL 5–15%；允许范围内组合预测，但数据覆盖之外的组合精度未验证。预测首先以 px 表示，只有确认统一空间标定后才换算为 mm；模型不能作为可靠运行优化依据。训练数据和模型文件位于 Git 忽略的 `data/h3_confirmed/continuous_height/`，迁移到其他机器时须单独复制。

点击「曝气参数优化」进入「污水曝气参数优化」工作台。实验采用配制的含盐模拟介质，观测高度 1.2 m、盐度 0.5 wt%、颗粒装载量 10%。当前和目标供气量均可在 1.5–2.3 m³/h 内输入小数。页面显示泡径、竖直上升速度、局部气含率、相对传氧效率估算和留出验证。相对传氧效率按局部估算的 KLa/Q 比值将当前工况归一化为 100%，比较结果依赖有效视野深度和氧浓度驱动力可比，以及上升速度近似滑移速度的假设。聊天中可输入「做污水曝气参数优化，Q 从 1.5 调到 2.0，看看泡径、上升速度和相对传氧效率怎么变」。

速度与传氧模块读取 `data/variation_evaluation/h3_pl10/transport_sequence_96/measurements.json`。在已有索引和原始序列可访问时，可运行 `python -m optimization_data.h3_bubble_demo.measure_flow` 提取四档各三个连续窗口，再用 `python -m optimization_data.h3_bubble_demo.transport` 导出模型结果与留出验证报告。每个窗口输出轨迹运动 CSV。

固定工况的体积气含率使用确认的 8 mm 视野深度，从真实照片的分割掩膜估算气泡等效球总体积。已拍摄档位可对照照片估算值与整档留出预测，未拍摄档位使用相邻气量插值。气含率变化量和误差以百分点表示。

迁移到另一台机器时，从团队共享位置按原相对路径放置以下统计和模型文件：

- 污水曝气参数优化使用 `data/h3_confirmed/continuous_height/conditions.csv` 和上述 `measurements.json`。
- 聊天中的多工况泡径预测使用 `data/h3_confirmed/continuous_height/` 下的模型和工况表，以及 `data/height_full/`、`data/h3_confirmed/model/` 下的模型与逐图统计。
- H1 留出模型和相应回归测试使用 `data/ug_h1_demo/20261113_130903/blind_model.json` 和同目录的 `image_statistics.csv`。

工况预览需要本机可以读取统计表指向的实验照片。统计和模型文件位于 Git 忽略的 `data/` 目录，首次克隆后可以先使用已有实验分析、追踪和气含率功能。

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

支持 JPG、PNG、TIFF、BMP、WEBP、CSV。图片和 CSV 可以上传，文件夹和视频可通过本地路径直接读取。普通批量检测最多 500 张图片，单文件上传最多 50 MB，单次上传最多 250 MB。

桌面版文件夹选择通过 Qt WebChannel 交给窗口主线程；网页模式通过独立的 Qt 进程打开选择器。两种模式都正常区分取消和失败，不再从 FastAPI 工作线程调用 Tkinter。

## 体积气含率与气泡追踪

- 在首页或侧栏打开「气含率估算」，选择已添加的图片或文件夹，也可以在页面内上传图像或添加本地目录。填写实际视野深度（mm）和空间标定（mm/px），需要时展开 ROI 与掩膜筛选。点击「开始估算」即可在同页查看进度、覆盖图和逐帧 CSV。估算使用本地 YOLO，无需 LLM。配置 LLM 后可以在同页追问结果，也可以从实验分析聊天发起气含率任务。
- 工具以 ROI 中的掩膜面积计算每个气泡的等效球体积，用气泡总体积除以 ROI 面积与视野深度的乘积。结果分别列出体积气含率与二维掩膜面积占比。坏帧与缺失掩膜的帧会标明原因。
- 通过实验工作台添加固定相机连续图像文件夹或 MP4/AVI/MOV/MKV 本地视频，再请求追踪。图像序列需提供实际采集帧率，视频可读取文件帧率或由用户明确覆盖。工具导出标注 MP4、逐帧轨迹 CSV 和筛选后的运动 CSV。无空间标定时速度以 px/s 输出。
- 追踪与预警共用气泡运动和形状关联。有效空帧推进时间，短时漏检可恢复原 ID，低分观测仅用于续接。轨迹 ID 数是关联结果，定量解释需结合有效样本数和采集条件。

## 流态监测预警与 LLM 分析

1. 点击首页「流态监测预警」，选择正常基线和待测图片目录，或直接填写 MP4/AVI/MOV/MKV 的本地路径。
2. 填写两段数据共同的实际采集帧率、空间标定和窗口长度。可设置共同 ROI、触发/恢复持续窗口数和追踪参数。模型和设备取本次运行设置，检测置信度使用预警的低分续接阈值（默认 0.1）。
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

`verify_flow.py` 使用真实权重和重复示例图检查新版流态工作流，验证模型推理和输出链路。流态测试覆盖正常/异常、缺少掩膜、末尾不足窗口、停止保留结果、配置确认及 LLM 取得 Observation 后解释。

`verify_knowledge.py` 默认本地固定模型响应，验证提供的 BIFB 论文中装置/气泡尺寸/流化状态/测速方法的页码命中和引用闭环。`--live` 会将测试问题、文档信息和检索片段发送到已配置的 LLM，仅在明确同意发送这些内容时使用。远程自动验收脚本被自动审批拦截，未重试；当前桌面会话已有一轮真实问答记录，装置 0.33 m、3.0 m 和 0–20 mm/s 已与第 2 页原文核对，这不代表其他专业问题均已验证。

## 目录

- `app/main.py`：FastAPI 路由、会话、上传、SSE 行动流。
- `desktop.py`：Qt 独立窗口、主线程文件夹选择、单实例唤起和本地服务生命周期。
- `app/folder_picker.py`：网页模式的独立 GUI 进程。
- `app/agent.py`：透明的单 Agent Loop（LLM → Tool Call → Tool Result → Observation）。
- `app/registry.py`：统一 Tool Registry、Pydantic 参数校验和错误处理。
- `app/yolo_adapter.py`：使用内置预测器和所选权重，统一输出检测、测量与统计结果。
- `app/vision/`：内置 YOLO 推理、BiFPN 权重兼容、等效球气含率、运动追踪和流态预警。迁入来源见该目录 README。
- `app/sequence_analysis.py` 与 `app/flow_warning.py`：视觉分析的 Agent 工具注册、参数校验及结果导出。
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
