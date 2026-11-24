# 已标记高度照片：全量探索模型

输入来自既有 `data/ug_match_planning/20261113_125912/image_sequence_manifest.csv`，选择 H1/H2/H4、盐度 1 wt%、PL 0.10、Q=1.5/1.8/2.0/2.3 的 12,000 张路径。既有 SHA-256 去重标记排除 `数据集` 中的副本；未标高度的数据不参与。训练前会核对图片 ID、工况、提取参数和重复标记。

`extract.py` 复用内置 `YoloAdapter.detect`、原有模型和 0.25 置信度，保存每个气泡及边缘状态到独立 SQLite。批处理阶段只关闭当前进程的预览图片编码，不修改 YOLO 算法或源图片；像素口径固定，不写回 NAS。

每张图用非边缘且掩膜边缘状态已知的目标计算 d50；没有有效目标的图保留为无标签记录，每图少于 5 个有效目标标记为低质量。先计算每个 Q/高度工况内的图片 d50 均值；再对每个高度分别用 4 个 Q 工况等权拟合直线。留一 Q 验证仅用其余 3 档拟合，同高度训练工况均值用作基准。每个工况只有一条采集序列，连续帧不是独立实验重复。

完整处理结束后运行：

```powershell
conda run --no-capture-output -n BIFBAgent python -X utf8 optimization_data\height_full\train.py
```

输出位于 `data/height_full`，包括独立的各批次 SQLite、`image_statistics.csv`、`condition_statistics.csv`、`leave_one_q_out.csv`、`metrics.json` 和 `model.json`。训练要求所有 12,000 张有成功处理记录，否则停止并生成 `incomplete.json`。断点续跑时使用各 `worker0`–`worker3` 对应的 `--shard-count 4 --shard-index 0`（其余改为 1、2、3）与对应输出目录；配置和模型哈希变化时拒绝混用。

新模型可预测 H1/H2/H4、Q 1.5–2.3 m³/h 范围内的像素尺寸；盐度和 PL 固定。拍摄视野与物理比例尺尚未核实，各高度不能直接作物理尺寸比较。工具以完整训练数据拟合的模型给出预测，历史目标工况测量是训练数据，不是独立验证；用户上传的单张照片不会用于模型重新拟合。
