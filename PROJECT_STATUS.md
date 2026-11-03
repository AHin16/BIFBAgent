# Project Status

更新时间：2026-11-03

## 本次实现与验证

### 专业知识问答演示

- 已开放专业知识问答，新增 search_knowledge、read_knowledge_excerpt、get_experiment_context，总计 13 个工具。
- 支持 PDF/TXT/Markdown 本地导入/上传、内容哈希去重、SQLite 持久化、BM25 中英文术语检索、页码片段/原始页预览。
- 提供的 Ma 等 BIFB 论文已导入：10 页、33 个片段，原始文件保留本地。装置/尺寸变化/流化状态/测速方法四类问题均检索到预期页。
- LLM 知识模式必须本轮先检索，引用编号必须来自本轮工具结果；错误编号允许修正一次，无命中时明确返回缺少依据。
- 22 项本地回归已通过（含知识、流态与桌面旧流程）。远程 MiMo 自动验收脚本被自动审批拦截，未重试。当前桌面会话已有真实知识问答的本地运行记录 e834f10536c940d2b1dd754221c7997b，装置 0.33 m、3.0 m 和气速 0–20 mm/s 与 PDF 第 2 页核对一致；仅验证这一个问题，不代表专业问答普遍正确。
- OCR、复杂表格/公式解析、联网文献检索及完整实验背景档案未实现。

### 流态监测接入

- 增加 analyze_flow_warning 与 inspect_flow_event，工具总数为 10。未改 YOLOTracker；在 Agent 的 data/backend 中加载原始工作流副本，使用现有真实预测器。
- 流态页面支持正常基线/待测文件夹或视频本地路径、真实 FPS、mm/px、共同 ROI、窗口/持续/恢复参数。正常基线与采集口径必须由用户确认，LLM 只接收配置编号。
- 原始逐帧分割、几何关联、基线拟合、持续异常和恢复规则保留；页面提供状态卡、趋势图、事件表、证据帧及 CSV/JSON。
- LLM 根据基线阈值、窗口统计、事件和数据质量做简单流动状态分析；不发送图像、不调用视觉模型、不逐帧解释，不声称识别流型或危险等级。
- 增加停止接口和停止保存结果；桌面关窗先请求停止并等待完成，避免丢失部分结果。MiMo reasoning_content 在工具回合中保留，界面不展示。
- 已通过 14 项本地回归（包含真实原始规则 + 模拟预测器/模型响应）。真实权重检查已完成：8 帧基线、8 帧待测、4 个窗口均成功，输入为重复测试图，仅验证集成，不代表预警精度。远程 LLM 解释质量仍需真实工况验收。

- 主链路已具备：13 个工具、真实 YOLO 单图/批量检测、流态预警、CSV、知识检索、Agent Loop、实时行动记录、CSV/JSON/图表/Markdown 导出。
- 桌面入口改为 PySide6 + Qt WebEngine；主线程原生文件夹对话框通过 WebChannel 连接页面。网页模式使用独立 Qt 对话框进程，取消与错误分别处理。
- 本地服务由桌面进程持有；端口冲突自动选择空闲端口；重复启动唤起已有窗口；关闭窗口停止自有服务。
- 首页为红白 Dashboard，图像/CSV 工作台、流态预警和专业知识问答已开放；气含率、参数优化仍展示“推进中”并弹出 toast。
- 修复 Windows 注册表将 SVG 标为 image/svg 导致 Chromium 不显示图标的问题。
- 已通过端口占用/关闭清理、中文路径和取消的回归测试；实际桌面已验证选择原测试图片目录、toast、单实例唤起和关窗退出。
- 本机固定模型响应 + 真实工具的三轮验收已通过：detect_bubbles → inspect_csv / analyze_csv → compare_experiments，报告在 data/validation/。这不等于真实 LLM 能力验收；本轮远程 API 验收被自动审批拦截，未发送样例。
- 文献知识库已实现轻量版；完整实验背景档案、会话持久化和独立图像流跟踪尚未实现。

下方保留原始需求和验收目标作为参考。

## 1. Project

项目名称：

Agent Learning & Multimodal Research Assistant

当前定位：

> Windows 本地可运行的“智能科研助手” Demo。

当前目标不是继续按照长期学习阶段逐步搭建，而是快速做出一个能够实际演示的完整闭环。

核心体验：

自然语言科研任务
→ Agent
→ 自动选择 Tool
→ 执行专业分析
→ Observation
→ 继续分析
→ LLM 综合
→ 可解释科研结果

---

## 2. Current Goal

当前需要完成一个带 UI 的可运行 Demo。

必须支持：

1. 自然语言驱动 YOLO 单帧检测。
2. 自然语言驱动文件夹气泡图片批量检测。
3. CSV 数据输入与分析。
4. LLM 对分析结果进行解释。
5. Agent 根据科研任务自动选择工具。
6. Agent 自动组织多步骤分析流程。
7. UI 展示 Agent Activity / Tool Calling。
8. 最终生成可解释的科研分析结果。

增强功能：

- 气泡统计
- 气泡尺寸分布
- 速度分析
- 图表生成
- VLM
- 文献分析
- 多轮上下文

---

## 3. Development Environment

Operating System：

Windows

IDE：

VS Code

Development Agent：

Codex

Conda环境：

BIFBAgent

Existing YOLOTracker：

E:\YOLOTracker

当前明确：

不使用 WSL。

不要求 Linux。

不考虑 AgentArts 部署。

不考虑 ARM64。

不考虑 MCP。

不要求当前 Demo 为未来比赛做复杂架构预留。

---

## 4. Target Demo Architecture

整体：

User
↓
Web UI
↓
Agent Runtime
↓
LLM
↓
Tool Registry
↓
┌───────────────┬────────────────┬────────────────┐
│               │                │                │
YOLO Tools   Data Tools     Research Tools   Utility Tools
│               │                │                │
↓               ↓                ↓                ↓
YOLOTracker     CSV/DataFrame    Analysis       Calculation
│
↓
Structured Observation
↓
Agent
↓
Final Research Result

核心原则：

Agent 是任务规划和决策层。

Tool 是专业执行层。

LLM 是自然语言理解、工具选择和结果综合层。

---

## 5. Core Tools

目标 Tool：

### Vision

detect_bubbles

输入：

image_path

输出：

- detection image
- bubble count
- bubble measurements
- confidence
- statistics

---

batch_detect_bubbles

输入：

folder_path

输出：

- image count
- processed count
- total bubbles
- per-image results
- aggregate statistics
- CSV result
- visualization

---

### Data

inspect_csv

输入：

csv_path

输出：

- columns
- dtypes
- row count
- missing values
- sample

---

analyze_csv

输入：

csv_path
analysis_request

输出：

- descriptive statistics
- grouping
- correlations
- trends
- anomalies
- charts

---

### Research

compare_experiments

用于：

- 不同工况比较
- 不同实验组比较
- YOLO 结果与 CSV 数据比较

---

generate_research_insight

输入：

结构化分析结果

输出：

科研解释。

---

### Utility

calculate_bubble_velocity

用于验证最基本的 Tool Calling。

---

## 6. Agent Behavior

Agent 不要求用户选择 Tool。

例如：

用户：

“分析这个文件夹里的气泡图片。”

Agent 自动：

→ 判断为批量视觉分析
→ 调用 batch_detect_bubbles
→ 获取结构化结果
→ 必要时调用统计分析
→ 综合回答

用户：

“看看这个 CSV 中气速和气泡直径有没有关系。”

Agent 自动：

→ inspect_csv
→ analyze_csv
→ correlation
→ chart
→ final explanation

用户：

“结合刚才的气泡图片结果和这个 CSV，分析一下实验规律。”

Agent 自动：

→ 使用 previous observation
→ 分析 CSV
→ compare
→ final synthesis

---

## 7. UI

UI 目标：

一个网页即可完成 Demo。

主要区域：

### Chat

用户自然语言输入。

### Files

支持：

- 图片
- 文件夹路径
- CSV
- 文献文件

### Result

显示：

- 检测图片
- 图表
- CSV 结果
- 统计数据

### Agent Activity

显示：

- Task Understanding
- Tool Call
- Tool Parameters
- Tool Result
- Observation
- Final Synthesis

例如：

[14:35:01] Understanding task
[14:35:01] Selecting batch_detect_bubbles
[14:35:02] Running YOLO
[14:35:08] 125 images processed
[14:35:08] Calculating bubble statistics
[14:35:09] Generating distribution
[14:35:10] Synthesizing research result

---

## 8. Agent Loop

当前采用最简单 Single Agent Loop：

User
↓
LLM
↓
Tool Call
↓
Tool Execution
↓
Tool Result
↓
Observation
↓
LLM
↓
Tool Call / Final Answer

必须能够在代码和 UI 中观察到这一过程。

不要把整个 Agent Loop 隐藏在复杂框架里。

---

## 9. YOLO Integration

已有专业项目：

E:\YOLOTracker

当前策略：

优先复用已有 YOLO 能力。

不要重新训练。

不要重复实现检测算法。

建立 Adapter：

Agent
→ YOLO Tool
→ YOLO Adapter
→ E:\YOLOTracker
→ Standardized Result

如果原项目存在成熟：

- detection
- segmentation
- tracking
- bubble statistics
- velocity calculation

优先直接包装。

---

## 10. CSV Analysis

CSV 分析是当前 Demo 的核心能力之一。

至少支持：

- 数据读取
- 列识别
- 缺失值检查
- 描述统计
- 分组统计
- 相关性
- 趋势
- 简单异常值分析
- 图表

LLM 不直接计算数字。

Python Tool 计算。

LLM 解释。

---

## 11. Research Insight

最终回答应该包含：

任务理解

工具使用

关键数据

分析结果

科研解释

结论依据

限制与不确定性

例如：

“本次分析首先使用 YOLO 对 125 张图片进行气泡检测，共识别 XXX 个气泡。随后根据实验工况进行分组统计。CSV 数据显示……两者结合后可以观察到……”

如果数据无法支持某个结论，必须明确说明。

不要让 LLM 编造实验结果。

---

## 12. VLM

VLM 当前属于可选增强能力。

如果现有环境方便接入：

analyze_image_with_vlm

可以用于：

- 图片语义解释
- 异常现象描述
- YOLO 结果辅助解释

但 VLM 不是当前 Demo 的阻塞条件。

核心 Demo 即使没有 VLM，也必须完整运行：

LLM
+
YOLO
+
CSV
+
Analysis
+
UI

---

## 13. Literature / RAG

文献分析为增强能力。

优先支持：

- PDF
- TXT
- Markdown

可以实现：

上传文献
→ 文本提取
→ LLM 分析

如果时间充足，再加入轻量 RAG。

当前不要求复杂向量数据库。

---

## 14. Current Development State

当前状态：

> Demo 重构阶段，优先级已经从“学习 Agent 基础”切换为“快速完成可运行智能科研助手”。

原有 Phase 0 / Phase 1 / Phase 2 等长期开发阶段不再作为当前执行计划。

之前的长期规划仅作为参考，不限制当前 Demo。

---

## 15. Immediate Development Order

现在直接按以下顺序开发：

1. 检查当前 Demo 项目代码。
2. 检查 Windows Python 环境。
3. 检查 LLM 配置。
4. 检查 E:\YOLOTracker。
5. 建立最小 Agent Runtime。
6. 建立 Tool Registry。
7. 接入 YOLO 单图检测。
8. 接入文件夹批量检测。
9. 接入 CSV 分析。
10. 实现多 Tool 调用。
11. 实现 Agent Activity。
12. 建立 Web UI。
13. 打通自然语言 → Tool → Result。
14. 完成一个完整演示流程。
15. 最后再补充 VLM / 文献 / RAG 等增强能力。

---

## 16. Demo Acceptance

### Demo 1：YOLO 单图

用户：

“检测这张气泡图片，并统计气泡数量和平均直径。”

Agent：

detect_bubbles
→ statistics
→ final answer

UI：

显示检测结果图 + 数据 + Agent Activity。

---

### Demo 2：文件夹批量

用户：

“分析这个实验文件夹里的所有气泡图片，统计气泡尺寸分布。”

Agent：

batch_detect_bubbles
→ statistics
→ distribution
→ final answer

UI：

显示：

- 图片数量
- 气泡总数
- 平均直径
- 尺寸分布
- 图表
- CSV

---

### Demo 3：CSV

用户：

“分析这个 CSV，看看气速和气泡直径有什么关系。”

Agent：

inspect_csv
→ analyze_csv
→ correlation
→ chart
→ final answer

---

### Demo 4：综合科研任务

用户：

“分析这个文件夹里的气泡图片，再结合 CSV 数据，比较不同气速下的气泡尺寸变化，并总结实验规律。”

Agent：

Folder
→ YOLO
→ Statistics
→ CSV
→ Comparison
→ Research Insight

这是最终 Demo 的核心展示。

---

## 17. What This Demo Should Demonstrate

这个 Demo 最终要证明：

用户不需要知道工具名称。

用户只需要描述科研任务。

Agent 能够：

理解任务
→ 判断需要什么能力
→ 自动选择工具
→ 执行专业计算
→ 读取真实数据
→ 根据 Observation 决定下一步
→ 综合多个来源
→ 生成科研解释

因此它不是：

“一个带聊天框的 YOLO 软件”。

而是：

> 一个可以调用专业视觉与数据分析能力的智能科研 Agent。

---

## 18. Current Non-Goals

当前不做：

- Multi-Agent
- MCP
- AgentArts 部署
- WSL
- ARM64
- Docker
- Kubernetes
- 微服务集群
- 复杂数据库
- Redis
- MQ
- React/Vue
- 复杂 Memory
- 复杂权限
- 实时视频流媒体系统

除非后续实际需求发生变化。

---

## 19. Current Definition of Success

只要能够现场完成以下流程，就认为第一版 Demo 成功：

用户上传一张气泡图片。

输入：

“帮我检测这张图片中的气泡。”

Agent 自动调用 YOLO。

页面显示：

检测结果
+
气泡统计
+
Tool Calling
+
最终解释。

随后用户上传 CSV。

输入：

“分析这个 CSV，并结合刚才的检测结果看看有没有值得关注的规律。”

Agent 自动：

读取 CSV
→ 分析数据
→ 调用统计工具
→ 结合前一轮结果
→ 生成科研解释。

最终让演示者能够用自然语言连续指挥整个科研分析过程。
