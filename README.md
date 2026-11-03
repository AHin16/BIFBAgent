# BIFB 智能科研助手 Demo

这是一个 Windows 本地科研分析 Demo：用户只描述研究任务，Agent 会自动选择 YOLO 气泡检测、CSV 统计、分布分析和结果比较工具，并把工具参数、Observation、图表、结构化数据和科研解释显示在同一个网页中。

## 启动

在项目目录执行独立窗口版本：

```powershell
conda run --no-capture-output -n BIFBAgent python desktop.py
```

也可以双击 `START.bat`。独立窗口使用当前 `BIFBAgent` 环境已有的 **PySide6 / Qt WebEngine**，不依赖浏览器 App 模式。重复启动会唤起已有窗口；默认端口被其他程序占用时自动选择空闲端口；关闭窗口会结束本程序自己的本地服务。纯网页调试仍可使用 `START_WEB.bat` 或 `python run.py`。

在新环境安装桌面组件时使用：

```powershell
conda run --no-capture-output -n BIFBAgent python -m pip install -r requirements-desktop.txt
```

首页使用红白配色的科研 Dashboard：左侧导航、五个研究模块和自然语言任务输入。图像与 CSV 分析进入工作台；流态监测预警进入专用配置与结果页面；气含率、参数优化、专业知识问答等未接入模块点击后显示“功能正在推进中”。

第一次打开软件，点右上角「运行设置」：

1. 填写 OpenAI-compatible 的 `API Base URL` 和 API Key（本地免鉴权服务可留空）。点击「获取模型列表」会调用该服务的 `/models` 接口，模型名称可直接选择，不会自动保存新 Key。
2. 确认 `YOLOTracker` 项目路径和 `3900.pt` 气泡模型路径；默认值是 `E:\YOLOTracker` 和 `E:\YOLOTracker\3900.pt`。
3. 如有真实标定，在「空间标定」填写 `mm/px`；留空时只报告 `px`。
4. 点击「保存并测试 LLM」，测试模型是否真的支持标准 Tool Calling。

## 快速演示

不需要准备数据时，左侧「从示例开始」可以添加 YOLOTracker 的真实测试图或示例 CSV。可直接输入：

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
4. 点击「开始监测并分析」。Agent 自动调用 `analyze_flow_warning(config_id)`，复用 YOLOTracker 原始 `run_flow_warning`，再根据结构化结果生成简单流动状态解释。
5. 页面显示气泡出现量、大气泡变化、运动状态，窗口趋势、事件时间/触发原因、证据帧及 CSV/JSON 导出。后续可在聊天中询问“解释刚才第一个预警事件”，Agent 可以查询已有结果，无需重跑。

当前 LLM 只接收窗口统计、基线阈值、事件和数据质量，不发送画面，不做视觉复核。解释应引用结果编号，并说明异常方向、时段和局限；不把偏离正常基线当作具体流型、危险等级或确定机理。`large_fraction`、`down_fraction` 为 0–1，`area_ratio` 为百分数，向上速度为正。

正常基线至少需要三个完整有效窗口；默认 30 FPS、0.5 s 窗口至少需 45 帧，且尺寸/运动指标各自需足够样本。原来的三帧示例不适合做预警基线。末尾不足完整窗口、坏帧和关联不足会显示“数据不足”，没有事件不等于正常。

分析期间可以「停止并保存」；桌面关闭会先请求停止并等待已完成结果保存。数据中断、序列结束、停止不会被解释为恢复。结果输出到 Agent 的 `data/outputs/`，不修改 YOLOTracker 源代码。

## 验证

```powershell
conda run --no-capture-output -n BIFBAgent python -m unittest discover -s tests -v
conda run --no-capture-output -n BIFBAgent python scripts/verify_demo.py
conda run --no-capture-output -n BIFBAgent python scripts/verify_flow.py
```

第二条命令默认使用本机固定模型响应，执行真实 YOLO、CSV 统计和跨轮比较，保存 `data/validation/*.json`。它验证工具协议和上下文，不验证 LLM 的理解与解释质量。需要验证实际模型时，明确选择 `python scripts/verify_demo.py --live`，该模式会将随项目提供的测试图片检测统计、合成 CSV 统计和任务文本发送到已配置的 LLM API。

`verify_flow.py` 使用真实权重、原始流态算法和重复示例图检查集成，不调用 LLM API；重复图仅为接口检查，不代表真实连续实验或预警精度。流态测试覆盖正常/异常、缺少掩膜、末尾不足窗口、停止保留结果、配置确认及 LLM 取得 Observation 后解释。

## 目录

- `app/main.py`：FastAPI 路由、会话、上传、SSE 行动流。
- `desktop.py`：Qt 独立窗口、主线程文件夹选择、单实例唤起和本地服务生命周期。
- `app/folder_picker.py`：网页模式的独立 GUI 进程。
- `app/agent.py`：透明的单 Agent Loop（LLM → Tool Call → Tool Result → Observation）。
- `app/registry.py`：统一 Tool Registry、Pydantic 参数校验和错误处理。
- `app/yolo_adapter.py`：不修改 `E:\YOLOTracker`，动态复用其 `PredictorYolo11` 和图像读取模块。
- `app/flow_warning.py`：确认后的流态任务配置、原始工作流适配、窗口/事件摘要及工具注册。
- `app/analysis.py`：CSV 读取、描述统计、分组、Pearson 相关、线性趋势、IQR 异常候选、图表。
- `app/static/`：原生 HTML/CSS/JavaScript UI。
- `data/outputs/`：每次运行的图表、检测图、CSV、JSON、Markdown 报告和 activity trace。

## 说明

YOLO 结果中的直径是二维等效圆直径；掩膜不存在时会明确标记为检测框面积估计。批量结果的气泡总数是跨图片的检测次数，不是跟踪去重后的独立气泡数。CSV 相关性描述关联，不代表因果关系；工具会把这些限制带入最终回答。

LLM 不执行 Python、不计算统计量，也不能访问未添加的数据源。所有文件内容都按数据处理，工具参数由 Pydantic 校验；详细错误写入 `data/app.log`，页面只显示可操作的友好提示。
