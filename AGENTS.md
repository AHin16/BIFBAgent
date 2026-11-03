# Agent Project Instructions

## 1. Project Overview

本项目当前目标是快速开发一个可以直接运行和演示的“小型智能科研助手” Demo。

这不是当前阶段的长期 Agent 学习工程，也不是比赛最终版本。

当前第一优先级是：

> 在 Windows 环境下，实现一个带 UI、能实际调用 YOLO、分析科研数据、调用 LLM，并能够根据自然语言任务自主选择工具和组织分析流程的可运行 Demo。

Demo 应该让用户能够通过自然语言完成科研分析任务，而不是要求用户手动选择复杂的功能。

核心体验：

User
→ Natural Language Task
→ Agent
→ Task Understanding
→ Tool Selection
→ Tool Execution
→ Observation
→ Additional Tool Calls
→ Result Synthesis
→ Explainable Research Result

---

## 2. Current Demo Goal

最终需要形成一个可以现场展示的“智能科研助手”。

至少支持以下能力：

### 2.1 YOLO 单帧检测

用户可以直接输入：

- “检测这张气泡图片”
- “帮我分析这张图片里的气泡”
- “统计一下这张图有多少个气泡”
- “检测并给出气泡尺寸分布”

Agent 根据任务自动选择 YOLO 检测工具。

输出至少包括：

- 检测结果图
- 气泡数量
- 检测置信度
- 气泡尺寸
- 必要的统计信息

---

### 2.2 文件夹批量气泡图片分析

用户可以输入：

- “分析这个文件夹里的所有气泡图片”
- “统计这个实验批次的气泡数量和尺寸”
- “帮我分析这个文件夹里的气泡尺寸分布”
- “把这个实验批次处理一下”

Agent 自动选择文件夹批处理工具。

工具负责：

图片读取
→ YOLO 推理
→ 气泡结果提取
→ 数据汇总
→ CSV / JSON 结果

Agent 负责：

理解任务
→ 判断需要什么分析
→ 选择工具
→ 解释结果

不要让 LLM 自己执行图像处理。

---

### 2.3 CSV 科研数据分析

支持用户上传 CSV 数据。

用户可以输入：

- “分析这个实验数据”
- “看看不同工况下气泡直径有什么变化”
- “分析气泡速度和气泡直径的关系”
- “帮我找一下这个数据里的异常”
- “总结一下这个实验结果”

Agent 自动选择 CSV 分析工具。

CSV Tool 至少支持：

- 数据读取
- 列名识别
- 数据类型识别
- 描述性统计
- 分组统计
- 相关性分析
- 异常值初步检测
- 简单趋势分析
- 基础绘图

工具返回结构化数据。

LLM 根据结构化结果生成科研解释。

---

## 3. Agent Core Capability

这个 Demo 最重要的不是“有多少工具”，而是：

> 用户不需要知道工具名称。

例如用户输入：

“帮我分析这个文件夹里的气泡图片，并告诉我这个实验的气泡尺寸分布有什么特点。”

Agent 应自行判断：

1. 这是文件夹图片分析任务。
2. 需要 YOLO 批量检测。
3. 检测结果需要进行统计。
4. 可能需要生成尺寸分布。
5. 最后由 LLM 综合解释。

可能形成：

User
→ Agent
→ batch_detect_bubbles
→ calculate_bubble_statistics
→ analyze_distribution
→ Final Answer

如果用户继续问：

“那和我刚才上传的 CSV 数据相比呢？”

Agent 应能够结合：

Conversation Context
+
Previous Tool Result
+
CSV Analysis Tool

继续分析。

---

## 4. Tool Architecture

采用简单、透明的 Tool Registry。

不要把工具调用逻辑全部写死在 Agent 中。

每个 Tool 至少包含：

- name
- description
- input schema
- callable
- output

建议工具类别：

### Vision Tools

- detect_bubbles
- batch_detect_bubbles
- analyze_bubble_image

### Data Analysis Tools

- read_csv
- analyze_csv
- calculate_statistics
- analyze_correlation
- analyze_distribution

### Research Tools

- compare_experiments
- summarize_results
- generate_research_insight

### Utility Tools

- list_files
- inspect_file
- calculate_bubble_velocity

工具返回结构化结果。

例如：

{
    "status": "success",
    "bubble_count": 37,
    "mean_diameter_mm": 2.31,
    "diameter_std_mm": 0.42,
    "image_path": "...",
    "result_image": "..."
}

LLM 不直接执行 Python。

LLM 只决定：

“我要调用哪个工具，以及参数是什么。”

Python 程序负责：

“真正执行工具。”

---

## 5. YOLO Integration

优先复用现有 `E:\YOLOTracker` 项目的真实 YOLO 能力。

不要重新训练模型。

不要重新实现已有检测算法。

不要为了 Demo 重写整个 YOLOTracker。

Agent 项目通过 Adapter 调用现有项目能力。

目标：

Agent
→ detect_bubbles Tool
→ YOLO Adapter
→ Existing YOLO Model
→ Detection Result
→ Agent

如果原项目接口复杂，可以建立一个简单 Adapter。

Agent 不应该依赖 Ultralytics 内部对象。

统一转换为 Demo 自己的结构化结果。

---

## 6. YOLO Demo Features

第一版优先保证以下功能真正能运行：

### 单张图片

输入：

image

输出：

- 检测图片
- 气泡数量
- 气泡尺寸
- 平均尺寸
- 最大/最小尺寸
- 平均置信度

### 文件夹

输入：

folder

输出：

- 图片总数
- 成功处理数量
- 总气泡数量
- 平均气泡尺寸
- 尺寸分布
- 每张图片统计
- CSV 结果
- 可视化结果

如果现有 YOLOTracker 已经可以完成跟踪、速度计算等能力，可以进一步暴露：

- track_bubbles
- calculate_bubble_velocity
- calculate_bubble_statistics

但不要为了 Demo 强行加入复杂功能。

---

## 7. CSV Analysis

CSV 是科研助手的重要能力。

用户可以直接上传 CSV。

Agent 应能够理解自然语言分析需求。

例如：

“帮我分析不同气速下气泡直径的变化。”

Agent：

→ inspect_csv
→ identify columns
→ calculate_group_statistics
→ analyze_trend
→ generate_chart
→ LLM interpretation

又例如：

“气泡速度和直径有没有相关性？”

Agent：

→ inspect_csv
→ calculate_correlation
→ generate_scatter_plot
→ LLM interpretation

工具输出：

{
    "status": "success",
    "columns": [...],
    "row_count": 1240,
    "correlation": 0.72,
    "statistics": {...}
}

LLM 不负责计算统计量。

LLM 负责解释统计结果。

---

## 8. Research Analysis

这个 Demo 不应该只是一个“聊天机器人 + YOLO”。

需要体现：

> Agent 能够根据科研任务自动组织分析流程。

例如：

用户：

“分析这个实验文件夹里的气泡图片，比较不同工况下的气泡尺寸，并总结实验规律。”

Agent 应能够组织：

1. 检查输入文件。
2. 判断文件夹结构。
3. 批量 YOLO 检测。
4. 提取气泡尺寸。
5. 根据文件名/目录识别实验组。
6. 分组统计。
7. 生成分布图。
8. 比较不同工况。
9. LLM 综合解释。

UI 中应该把这些行动显示出来。

例如：

[Agent] 正在理解任务
↓
[Tool] 检查实验文件夹
↓
[Tool] batch_detect_bubbles
↓
[Tool] calculate_statistics
↓
[Tool] analyze_distribution
↓
[LLM] 综合实验结果
↓
[Agent] 生成科研分析

这部分是 Demo 最重要的展示效果之一。

---

## 9. Explainable Result

最终回答不能只有：

“分析完成。”

需要明确告诉用户：

### 任务理解

Agent 认为用户想做什么。

### 使用的工具

例如：

- YOLO 气泡检测
- CSV 数据分析
- 统计分析
- 分布分析

### 分析过程

展示关键步骤。

### 数据结果

展示实际计算结果。

### 科研解释

由 LLM 根据工具结果进行解释。

### 结论依据

明确哪些结论来自：

- YOLO 检测
- 统计计算
- CSV 数据
- LLM 综合解释

不要让 LLM 编造不存在的数据。

---

## 10. LLM

LLM 使用 OpenAI-compatible API。

配置：

LLM_BASE_URL
LLM_API_KEY
LLM_MODEL

业务代码不要绑定某个具体模型厂商。

Agent Runtime 只依赖统一的 LLM Client。

LLM 主要负责：

- 理解自然语言
- 判断任务类型
- 选择工具
- 生成 Tool Call
- 根据 Tool Result 决定下一步
- 综合多个工具结果
- 生成最终科研解释

LLM 不负责：

- YOLO 推理
- CSV 数值计算
- 图片处理
- 任意 Python 执行

---

## 11. Agent Loop

采用简单 Single Agent Loop。

核心流程：

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

第一版不要使用复杂 Agent Framework 隐藏这个过程。

代码应该足够透明，可以清楚看到：

- Tool Schema 如何提供给 LLM
- LLM 如何选择 Tool
- Tool 如何执行
- Tool Result 如何返回
- Agent 如何继续
- 最终结果如何生成

---

## 12. UI

Demo 必须带 UI。

优先使用：

FastAPI + HTML/CSS/JavaScript

不要第一版引入 React/Vue。

UI 目标是：

> 看起来像一个真正的科研 AI 助手，而不是 API 测试页面。

建议布局：

左侧：

- 文件上传
- 图片预览
- 检测结果
- CSV 文件
- 图表

右侧：

- Chat
- 用户输入
- Agent 回复

中间或底部：

Agent Activity

例如：

┌──────────────────────────────┐
│       智能科研助手            │
├──────────────┬───────────────┤
│              │               │
│  图片/数据    │    对话区      │
│              │               │
│  检测结果     │   Agent回答    │
│              │               │
├──────────────┴───────────────┤
│ Agent Activity               │
│ ✓ 理解科研任务               │
│ ✓ 调用 YOLO                  │
│ ✓ 完成 125 张图片分析        │
│ ✓ 统计气泡尺寸               │
│ ✓ 生成实验结论               │
└──────────────────────────────┘

UI 应该能明显展示：

“Agent 正在行动”。

---

## 13. File Input

Demo 至少支持：

- JPG
- PNG
- JPEG
- MP4（如果原项目支持）
- CSV

支持：

- 单文件上传
- 文件夹选择/路径输入
- CSV 上传

对于本地 Windows Demo，可以允许输入 Windows 本地路径。

例如：

E:\experiment\data

不要为了 Demo 强行设计云端文件系统。

---

## 14. Demo Priority

优先级严格按照：

1. UI 能打开
2. Chat 能工作
3. LLM 能调用
4. Tool Registry 能工作
5. YOLO 单图检测能工作
6. YOLO 文件夹批量检测能工作
7. CSV 分析能工作
8. Agent 能自动选择 Tool
9. Agent 能组织多步骤分析
10. UI 能显示 Tool Calling
11. 最终结果可解释
12. 再考虑视频、VLM 等增强功能

如果时间有限，宁可把视频/VLM砍掉，也必须保证前面的科研助手主流程完整。

---

## 15. VLM

VLM 属于增强能力，不是当前 Demo 的硬性阻塞项。

如果现有环境已经有可调用的 VLM，可以接入：

analyze_image_with_vlm

用于：

- 图像语义解释
- 检测结果辅助解释
- 异常现象描述

但是：

YOLO 负责检测。

VLM 负责解释。

不要让 VLM 替代 YOLO。

如果 VLM 接入会明显拖慢 Demo 开发，允许暂时使用 Mock / Optional Tool，但不得影响 YOLO + CSV + LLM 主流程。

---

## 16. RAG / Literature Analysis

当前 Demo 支持 CSV 数据分析是硬性要求。

文献分析能力可以采用轻量实现。

如果时间允许，可以支持：

- TXT
- PDF
- CSV
- Markdown

LLM 可以对用户上传的科研文献进行：

- 内容总结
- 实验条件提取
- 方法对比
- 数据解释
- 与当前实验数据对照

不要为了 Demo 建立复杂向量数据库。

优先实现：

上传文献
→ 提取文本
→ 分块
→ LLM 分析

如果需要检索，再加入轻量 RAG。

---

## 17. Research Workflow

Agent 应能够自动组织流程。

例如：

用户：

“分析这个实验文件夹里的气泡，并结合 CSV 数据告诉我气泡尺寸有什么变化。”

Agent 应自动组织：

Folder
→ YOLO Detection
→ Bubble Statistics
→ CSV Analysis
→ Compare
→ LLM Synthesis

而不是要求用户：

“先点击 YOLO，再点击统计，再上传 CSV。”

这体现的是 Agent，而不是传统工具箱。

---

## 18. Error Handling

Demo 必须对常见错误进行友好处理。

例如：

- 文件不存在
- 图片格式错误
- CSV 无法读取
- CSV 缺少目标列
- YOLO 模型不存在
- LLM API 不可用
- Tool 参数错误
- Tool 执行失败

Agent 应该告诉用户：

发生了什么。

而不是直接显示 Python Traceback。

开发阶段仍然保留详细日志。

---

## 19. Development Environment

当前 Demo 直接运行于：

Windows

主要环境：

- Windows
- VS Code
- Codex
- Python
- Git
- PyTorch
- CUDA
- OpenCV

不要要求 WSL。

不要为了这个 Demo 设计 Linux/ARM64 兼容。

不要考虑 AgentArts 部署。

不要考虑 MCP 迁移。

不要为了未来架构增加当前没有必要的复杂度。

---

## 20. Existing YOLOTracker

已有项目：

E:\YOLOTracker

原则：

- 优先复用。
- 不重复实现。
- 不随意修改。
- 不破坏原项目。
- 通过 Adapter / Wrapper 调用。

如果必须修改原项目：

必须先说明：

1. 为什么需要修改。
2. 修改什么。
3. 对原项目有什么影响。

优先在 Agent Demo 项目中建立适配层。

---

## 21. Engineering Style

这是一个“快速可运行 Demo”。

因此：

> 可运行 > 完美架构  
> 可演示 > 过度工程化  
> 真实功能 > Mock  
> 清晰 Agent Loop > 大型 Framework

暂时不要：

- Multi-Agent
- Kubernetes
- 微服务集群
- Redis
- MQ
- MCP
- 复杂权限系统
- React
- Vue
- Docker
- 分布式任务系统

除非实际开发过程中确实发现必须使用。

---

## 22. Coding Rules

修改代码前先读取现有代码。

不要猜测接口。

优先复用。

不要大规模重构。

不要删除已有功能。

每完成一个核心功能，都立即运行验证。

重点验证：

- UI 是否能打开
- LLM 是否能调用
- Tool 是否能调用
- YOLO 是否能实际推理
- CSV 是否能实际分析
- Agent 是否能根据自然语言自动选择工具
- 多步骤任务是否能执行

---

## 23. Definition of Done

这个 Demo 至少需要做到：

用户打开网页。

输入：

“检测这张气泡图片。”

Agent 自动调用 YOLO。

页面显示：

- 原图
- 检测图
- 气泡数量
- 气泡统计
- Agent 行动过程
- 最终解释

然后用户输入：

“再分析这个 CSV，看看气泡直径和气速有什么关系。”

Agent 自动：

→ 读取 CSV
→ 分析数据
→ 计算关系
→ 生成图表
→ 结合上一轮 YOLO 结果
→ 给出科研解释

这时才算真正形成：

> 智能科研助手 Demo。

---

## 24. Important Principle

不要把这个项目做成：

“ChatGPT + 几个按钮”。

真正需要展示的是：

> 用户只提出科研任务，Agent 自己理解任务、选择专业工具、组织分析流程、读取真实数据、获得结构化结果，再由 LLM 对结果进行解释。

最终核心链路：

自然语言任务
→ Agent
→ Tool Selection
→ YOLO / CSV / Analysis
→ Observation
→ Multi-step Reasoning
→ Research Insight

这就是当前 Demo 的核心。