你现在负责开发一个可以立即运行和演示的“小型智能科研助手” Demo。

这是一个临时 Demo 项目。

当前目标不是做长期工程规划，也不是按照 Phase 0 / Phase 1 / Phase 2 慢慢学习。

不要提出 Phase 0。

不要要求先完成长期架构。

不要考虑 AgentArts。

不要考虑 MCP。

不要考虑 WSL。

不要考虑 Linux/ARM64。

直接在 Windows 环境下把 Demo 做出来。

---

# 一、最终目标

我要的是一个真正可以演示的：

> Intelligent Research Assistant / 智能科研助手

用户不需要知道 Tool 的名字，也不需要手动选择功能。

用户只需要用自然语言描述科研任务。

例如：

“检测这张气泡图片。”

“分析这个文件夹里的气泡图片。”

“统计这个实验批次的气泡尺寸分布。”

“分析这个 CSV。”

“看看气速和气泡直径有没有关系。”

“结合刚才的图片结果和 CSV，分析实验规律。”

Agent 自己判断：

用户要做什么
→ 需要什么 Tool
→ 调用什么 Tool
→ 是否需要下一步分析
→ 最后如何解释结果

---

# 二、必须实现的核心能力

第一版至少实现：

1. YOLO 单张图片检测。
2. 文件夹气泡图片批量检测。
3. CSV 数据输入。
4. CSV 数据分析。
5. LLM 分析和解释。
6. Tool Registry。
7. Agent 自动选择 Tool。
8. Agent 多步骤 Tool Calling。
9. Agent Activity UI。
10. 最终科研结果解释。

---

# 三、YOLO

已有 YOLO 项目：

E:\YOLOTracker

优先复用这个项目。

不要重新训练 YOLO。

不要重新实现 YOLO。

不要修改原项目，除非确实必要。

如果原项目已经存在检测、分割、跟踪、统计、速度计算等能力，优先通过 Adapter / Wrapper 调用。

目标：

Agent
→ Tool
→ YOLO Adapter
→ E:\YOLOTracker
→ Structured Result

Agent 不应该直接依赖 YOLO 内部代码。

---

# 四、必须支持 YOLO 单图

用户输入：

“检测这张气泡图片，并告诉我有多少个气泡。”

Agent 应：

1. 理解任务。
2. 自动选择 detect_bubbles。
3. 调用 YOLO。
4. 获取结构化结果。
5. 如果需要，继续调用统计 Tool。
6. 最后生成自然语言回答。

UI 至少显示：

- 原图
- 检测结果图
- 气泡数量
- 平均尺寸
- 最大/最小尺寸
- 置信度
- Agent Activity

---

# 五、必须支持文件夹批量检测

用户输入：

“分析这个文件夹里的所有气泡图片。”

Agent 自动选择：

batch_detect_bubbles

流程：

Folder
→ Images
→ YOLO
→ Detection Results
→ Statistics
→ Distribution
→ Final Answer

至少输出：

- 图片数量
- 成功处理数量
- 总气泡数量
- 平均气泡尺寸
- 尺寸统计
- 每张图片统计
- CSV
- 图表

---

# 六、必须支持 CSV

用户可以上传 CSV。

例如：

“分析这个 CSV。”

“看看不同气速下气泡直径有什么变化。”

“分析气泡速度和气泡直径的关系。”

“帮我找出异常数据。”

Agent 自动选择 CSV Tool。

CSV Tool 可以执行：

- 读取
- 列识别
- 数据类型识别
- 缺失值检查
- 描述统计
- 分组统计
- 相关性
- 趋势
- 异常值
- 基础绘图

Python 负责计算。

LLM 负责解释。

不要让 LLM 自己进行数字计算。

---

# 七、科研综合分析

这是最重要的 Demo 能力。

用户：

“分析这个文件夹里的气泡图片，再结合这个 CSV，比较不同气速下的气泡尺寸变化，并总结实验规律。”

Agent 应自动组织：

1. 检查文件。
2. 批量 YOLO 检测。
3. 提取气泡尺寸。
4. 统计不同实验组。
5. 读取 CSV。
6. 分析 CSV。
7. 比较两部分结果。
8. 必要时生成图表。
9. LLM 综合解释。
10. 输出科研结论。

用户不需要自己点击这些步骤。

---

# 八、Agent Loop

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

必须让这个过程在代码中清楚可见。

不要使用一个巨大黑盒 Agent Framework 把这些全部隐藏起来。

如果可以用简单 Python 实现，就优先简单 Python。

---

# 九、Tool Registry

实现统一 Tool Registry。

每个 Tool 至少：

name
description
input schema
callable
output

至少注册：

detect_bubbles
batch_detect_bubbles
inspect_csv
analyze_csv
calculate_bubble_statistics
calculate_bubble_velocity

如果现有 YOLOTracker 还有成熟功能，可以继续包装。

Agent 不应该把这些 Tool 写死在 if/else 中。

---

# 十、Structured Result

Tool 必须尽量返回结构化数据。

例如：

{
    "status": "success",
    "bubble_count": 37,
    "mean_diameter_mm": 2.31,
    "diameter_std_mm": 0.42,
    "result_image": "..."
}

CSV：

{
    "status": "success",
    "row_count": 1240,
    "columns": [...],
    "statistics": {...},
    "correlations": {...}
}

LLM 根据这些结果进行解释。

不要让 Tool 只返回一大段自然语言。

---

# 十一、可解释性

UI 必须让观众看见 Agent 在做什么。

例如：

[Agent] 理解任务
[Agent] 选择 batch_detect_bubbles
[Tool] 正在运行 YOLO
[Tool] 检测完成：125 张图片
[Agent] 获取 Observation
[Agent] 判断需要统计分析
[Tool] calculate_bubble_statistics
[Tool] 生成尺寸分布
[Agent] 综合实验结果
[LLM] 生成科研解释

最终回答需要区分：

任务理解
工具调用
实际数据
分析结果
科研解释

不要只显示：

“分析完成。”

---

# 十二、UI

直接做一个 Windows 本地 Web UI。

推荐：

FastAPI
+
HTML
+
CSS
+
JavaScript

不要引入 React/Vue。

UI 至少包含：

左侧：

- 文件选择/上传
- 图片预览
- 检测结果
- CSV 文件
- 图表

右侧：

- Chat
- 用户消息
- Agent 回复

底部：

- Agent Activity
- Tool Calls
- Tool Results

目标视觉效果：

像一个真正的 AI 科研助手。

不是 API 测试页面。

---

# 十三、LLM

统一使用 OpenAI-compatible API。

环境变量：

LLM_BASE_URL
LLM_API_KEY
LLM_MODEL

LLM 负责：

- 理解任务
- 选择 Tool
- Tool Calling
- 根据 Observation 决定下一步
- 综合结果
- 生成科研解释

LLM 不负责：

- YOLO
- 数值统计
- 图片处理
- 任意 Python 执行

---

# 十四、CSV + YOLO 综合 Demo

这是最终现场演示最重要的流程之一。

演示：

第一步：

上传气泡图片。

输入：

“帮我检测这张图里的气泡。”

Agent：

detect_bubbles
→ result
→ final answer

第二步：

继续输入：

“再帮我分析这个 CSV，看看气速和气泡直径有什么关系。”

Agent：

inspect_csv
→ analyze_csv
→ correlation
→ chart
→ final answer

第三步：

继续：

“结合刚才的图片检测结果和 CSV，帮我总结一下这个实验。”

Agent：

previous context
+
YOLO result
+
CSV result
→ synthesis
→ research insight

这样可以直接体现：

Agent Memory / Context
+
Tool Calling
+
YOLO
+
Data Analysis
+
LLM Reasoning

---

# 十五、VLM

VLM 是增强功能。

如果环境方便，可以加入：

analyze_image_with_vlm

用于：

- 图像语义解释
- 异常现象分析
- YOLO 结果辅助解释

但不要让 VLM 阻塞整个 Demo。

如果 VLM 难以接入：

先完成：

LLM
+
YOLO
+
CSV
+
Analysis
+
UI

这是第一优先级。

---

# 十六、文献分析

如果时间允许，增加：

PDF / TXT / Markdown

上传文献后：

文本提取
→ LLM
→ 总结 / 实验条件 / 方法 / 结论提取

可以进一步做简单 RAG。

但不要为了这个 Demo 搭建复杂知识库。

---

# 十七、错误处理

至少处理：

- 图片不存在
- 文件夹不存在
- CSV 无法读取
- CSV 格式错误
- YOLO 模型不存在
- LLM API 错误
- Tool 参数错误
- Tool 执行失败

用户看到友好错误。

开发日志保留详细 traceback。

---

# 十八、开发原则

现在最重要的是：

> 先跑起来。

优先级：

可运行
>
可演示
>
真实工具
>
自然语言自动编排
>
UI
>
美化
>
额外功能

不要为了架构完美拖慢 Demo。

不要写无关代码。

不要做复杂工程化。

不要做 Multi-Agent。

不要做 MCP。

不要做 AgentArts。

不要做 WSL。

不要做 Docker。

不要做 Kubernetes。

不要做复杂数据库。

---

# 十九、最终验收

必须可以完成：

### Demo A

用户：

“检测这张气泡图片。”

Agent 自动调用 YOLO。

页面显示：

检测结果
+
统计
+
Tool Calling
+
最终解释。

### Demo B

用户：

“分析这个文件夹里的气泡图片，并统计尺寸分布。”

Agent 自动：

batch YOLO
→ statistics
→ distribution
→ answer

页面显示：

检测图
+
统计
+
图表
+
CSV
+
Agent Activity。

### Demo C

用户：

“分析这个 CSV，看看气速和气泡直径有没有关系。”

Agent 自动：

inspect_csv
→ analyze_csv
→ correlation
→ chart
→ answer

### Demo D

用户：

“结合刚才的气泡检测和这个 CSV，分析一下实验规律。”

Agent 自动：

Previous Observation
+
CSV
+
Analysis Tools
→ Research Synthesis

---

# 二十、现在应该怎么做

不要先写长篇规划。

不要先讨论未来架构。

不要先做理论学习。

直接：

1. 查看当前项目目录。
2. 查看当前代码。
3. 查看 E:\YOLOTracker。
4. 找到真实 YOLO 推理入口。
5. 找到可以复用的检测接口。
6. 建立 Tool Registry。
7. 建立最小 Agent Loop。
8. 接入 YOLO。
9. 接入 CSV。
10. 建 UI。
11. 打通完整 Demo。
12. 实际运行测试。

如果发现原 YOLOTracker 接口与预期不同，以实际代码为准。

不要猜。

如果某个功能暂时无法实现，优先做一个真实可运行的替代方案，而不是停下来等待完美架构。

最终目标只有一个：

> 做出一个能够在浏览器中打开、能够通过自然语言调用 YOLO 和数据分析工具、能够自动组织科研分析流程，并能现场演示的“智能科研助手”。