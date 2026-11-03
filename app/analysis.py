import math
import threading

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.storage import ToolError, clean_json


PLOT_LOCK = threading.Lock()
plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                     "axes.unicode_minus": False, "figure.facecolor": "#ffffff",
                     "axes.spines.top": False, "axes.spines.right": False})


def read_csv(path):
    if path.suffix.lower() != ".csv":
        raise ToolError("请选择 CSV 文件。")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ToolError("Demo 单个 CSV 限制为 50 MB，请先缩小数据集。")
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            frame = pd.read_csv(path, encoding=encoding, sep=None, engine="python", nrows=100001)
            break
        except UnicodeError:
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as error:
            raise ToolError("CSV 内容为空或格式错误，请检查分隔符、表头和引号。") from error
    else:
        raise ToolError("CSV 编码无法识别，请另存为 UTF-8 CSV。")
    if frame.empty:
        raise ToolError("CSV 只有表头，没有可分析的数据行。")
    if len(frame) > 100000 or len(frame.columns) > 100:
        raise ToolError("Demo 最多分析 100,000 行、100 列，请先拆分 CSV。")
    frame.columns = [str(column).strip() for column in frame.columns]
    if frame.columns.duplicated().any():
        raise ToolError("清理空格后出现重复列名，请修改 CSV 表头。")
    return frame


def numeric_data(frame):
    return frame.select_dtypes(include="number").replace([np.inf, -np.inf], np.nan)


def describe(series):
    values = pd.Series(series, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"count": 0, "mean": None, "std": None, "min": None, "median": None, "max": None}
    return clean_json({"count": len(values), "mean": values.mean(), "std": values.std(ddof=1),
                       "min": values.min(), "q25": values.quantile(0.25), "median": values.median(),
                       "q75": values.quantile(0.75), "max": values.max()})


def save_plot(context, title, draw):
    with PLOT_LOCK:
        figure, axes = plt.subplots(figsize=(8.5, 4.8), layout="constrained")
        try:
            draw(axes)
            axes.set_title(title, loc="left", pad=18, fontsize=13, fontweight="bold")
            axes.grid(axis="y", alpha=0.15)
            path = context.output("chart.png")
            figure.savefig(path, dpi=150)
        finally:
            plt.close(figure)
    return context.artifact(path, title, "image")


def distribution(context, values, unit):
    series = pd.Series(values, dtype=float).dropna()
    if series.empty:
        return [], {"counts": [], "bin_edges": []}
    counts, edges = np.histogram(series, bins=min(15, max(1, int(math.sqrt(len(series))))))

    def draw(axes):
        axes.hist(series, bins=edges, color="#167d72", edgecolor="white")
        axes.set_xlabel(f"等效直径 ({unit})")
        axes.set_ylabel("检测次数")

    return [save_plot(context, "气泡尺寸分布", draw)], {"counts": counts.tolist(), "bin_edges": edges.tolist(), "unit": unit}


def register_data_tools(registry):
    @registry.register("检查已添加的 CSV 列名、类型、缺失值、样本。分析 CSV 前先调用此工具，不猜测列名或单位。")
    def inspect_csv(context, csv_path: str):
        path = context.session.resolve(csv_path)
        frame = read_csv(path)
        numeric = numeric_data(frame)
        return {"source": str(path), "row_count": len(frame), "columns": list(frame.columns),
                "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
                "numeric_columns": list(numeric.columns), "missing_values": frame.isna().sum().to_dict(),
                "non_finite_values": {column: int(np.isinf(frame[column]).sum()) for column in numeric},
                "duplicate_rows": int(frame.duplicated().sum()), "sample": frame.head(6).to_dict("records")}

    @registry.register("分析 CSV：描述统计、缺失值、分组、Pearson 相关性、线性趋势、IQR 异常、直方图及散点图。先 inspect_csv 获取准确列名；x_column/y_column 指定相关性变量，group_by 指定工况列；无需参数的计算在 Python 完成。")
    def analyze_csv(context, csv_path: str, x_column: str | None = None,
                    y_column: str | None = None, group_by: str | None = None):
        path = context.session.resolve(csv_path)
        frame = read_csv(path)
        numeric = numeric_data(frame)
        for column in (x_column, y_column, group_by):
            if column and column not in frame:
                raise ToolError(f"CSV 缺少列 {column}。实际列名：{', '.join(frame.columns)}")
        for column in (x_column, y_column):
            if column and column not in numeric:
                raise ToolError(f"列 {column} 不是数值列，无法计算相关性。")
        if bool(x_column) != bool(y_column):
            raise ToolError("相关性分析需同时指定 x_column 和 y_column。")
        if x_column and x_column == y_column:
            raise ToolError("请选择两个不同的变量进行相关性分析。")
        statistics = {column: describe(numeric[column]) for column in numeric}
        anomalies = {}
        outlier_rows = []
        for column in numeric:
            series = numeric[column].dropna()
            lower_quartile, upper_quartile = series.quantile([0.25, 0.75])
            spread = upper_quartile - lower_quartile
            lower, upper = lower_quartile - 1.5 * spread, upper_quartile + 1.5 * spread
            selected = series[(series < lower) | (series > upper)]
            anomalies[column] = {"count": len(selected), "lower": lower, "upper": upper,
                                 "data_rows": [int(index) + 1 for index in selected.index[:30]],
                                 "method": "1.5 × IQR；仅异常候选，不自动剔除"}
            outlier_rows.extend({"data_row": int(index) + 1, "column": column, "value": value}
                                for index, value in selected.items())
        artifacts = []
        target = y_column or (str(numeric.columns[0]) if len(numeric.columns) else None)
        if target and numeric[target].notna().any():
            def histogram(axes):
                axes.hist(numeric[target].dropna(), bins="auto", color="#167d72", edgecolor="white")
                axes.set_xlabel(target)
                axes.set_ylabel("样本数")
            artifacts.append(save_plot(context, f"{target} · 分布", histogram))
        pair = None
        if x_column and y_column:
            paired = numeric[[x_column, y_column]].dropna()
            valid = len(paired) >= 3 and paired[x_column].nunique() > 1 and paired[y_column].nunique() > 1
            pair = {"x": x_column, "y": y_column, "n": len(paired),
                    "excluded_rows": len(frame) - len(paired), "pearson_r": None, "linear_trend": None}
            if valid:
                correlation = paired[x_column].corr(paired[y_column])
                slope, intercept = np.polyfit(paired[x_column], paired[y_column], 1)
                pair.update(pearson_r=correlation,
                            linear_trend={"slope": slope, "intercept": intercept, "r_squared": correlation ** 2})
            else:
                pair["warning"] = "有效配对少于 3 个或变量为常数，不报告相关性和趋势。"
            def scatter(axes):
                axes.scatter(paired[x_column], paired[y_column], color="#167d72", alpha=0.65, s=25)
                if valid:
                    limits = np.array([paired[x_column].min(), paired[x_column].max()])
                    axes.plot(limits, slope * limits + intercept, color="#ce8b46", label="线性拟合")
                    axes.legend()
                axes.set_xlabel(x_column)
                axes.set_ylabel(y_column)
            artifacts.append(save_plot(context, "变量关系 · 观测与线性趋势", scatter))
        groups = []
        if group_by:
            if frame[group_by].nunique(dropna=False) > 60:
                raise ToolError("分组列超过 60 个取值，请使用离散工况列。")
            for label, subset in frame.groupby(group_by, dropna=False, sort=False):
                values = numeric_data(subset)
                groups.append({"group": str(label), "row_count": len(subset),
                               "statistics": {column: describe(values[column]) for column in values if column != group_by}})
            if target and target != group_by:
                def grouped_plot(axes):
                    labels = [item["group"] for item in groups]
                    means = [item["statistics"][target]["mean"] for item in groups]
                    axes.bar(labels, [value if value is not None else np.nan for value in means], color="#167d72")
                    axes.tick_params(axis="x", labelrotation=35)
                    axes.set_xlabel(group_by)
                    axes.set_ylabel(f"{target} 均值")
                artifacts.append(save_plot(context, "不同工况 · 均值比较", grouped_plot))
        summary_path = context.output("statistics.csv")
        pd.DataFrame(statistics).T.rename_axis("column").to_csv(summary_path, encoding="utf-8-sig")
        artifacts.append(context.artifact(summary_path, "描述统计 · CSV"))
        if outlier_rows:
            anomaly_path = context.output("outliers.csv")
            pd.DataFrame(outlier_rows).to_csv(anomaly_path, index=False, encoding="utf-8-sig")
            artifacts.append(context.artifact(anomaly_path, "异常候选 · CSV"))
        return {"source": str(path), "row_count": len(frame), "columns": list(frame.columns),
                "statistics": statistics, "missing_values": frame.isna().sum().to_dict(),
                "non_finite_values": {column: int(np.isinf(frame[column]).sum()) for column in numeric},
                "duplicate_rows": int(frame.duplicated().sum()),
                "correlation": pair, "groups": groups, "anomalies": anomalies, "artifacts": artifacts,
                "limitations": ["相关性不代表因果关系；线性趋势是描述性拟合，未做显著性检验。",
                                "统计忽略缺失和非有限数值；不自动删除重复行或异常候选。",
                                "单位按 CSV 表头解释；未给出单位的列不能擅自认定为 mm。"]}

    @registry.register("根据此前 YOLO 结果编号 result_id 计算气泡统计及直径分布。返回每组均值及真实分布图。")
    def calculate_bubble_statistics(context, result_id: str):
        result = context.result(result_id)
        if "measurements" not in result:
            raise ToolError("该结果不是气泡检测结果，请传入 detect_bubbles 或 batch_detect_bubbles 的 result_id。")
        unit = result["unit"]
        measurements = pd.DataFrame(result["measurements"])
        values = measurements["diameter"].tolist() if not measurements.empty else []
        artifacts, histogram = distribution(context, values, unit)
        groups = []
        if not measurements.empty:
            for group, subset in measurements.groupby("group"):
                groups.append({"group": group, "statistics": describe(subset["diameter"])})
        return {"source_result_id": result_id, "unit": unit, "statistics": describe(values),
                "groups": groups, "distribution": histogram, "artifacts": artifacts,
                "measurement_method": result["measurement_method"], "limitations": result["limitations"]}

    @registry.register("比较两个已分析结果中的指定数值列。YOLO 检测结果列用 diameter；CSV 分析结果用真实列名。双方单位必须明确相同才能计算差异；未知单位传 unknown。")
    def compare_experiments(context, left_result_id: str, right_result_id: str,
                            left_column: str, right_column: str, left_unit: str, right_unit: str):
        left = context.result(left_result_id)
        right = context.result(right_result_id)
        def select(result, column):
            if "measurements" in result and column == "diameter":
                return describe([row["diameter"] for row in result["measurements"]])
            statistics = result.get("statistics", {})
            if column not in statistics:
                raise ToolError(f"结果中没有 {column} 的统计数据，请先分析该列。")
            return statistics[column]
        left_summary, right_summary = select(left, left_column), select(right, right_column)
        left_unit = left.get("unit", left_unit).strip().lower()
        right_unit = right.get("unit", right_unit).strip().lower()
        comparable = left_unit == right_unit and left_unit not in {"", "unknown", "未知"}
        difference = None
        relative = None
        if comparable and left_summary["mean"] is not None and right_summary["mean"] is not None:
            difference = right_summary["mean"] - left_summary["mean"]
            if left_summary["mean"] != 0:
                relative = difference / left_summary["mean"] * 100
        return {"left_result_id": left_result_id, "right_result_id": right_result_id,
                "left": {"column": left_column, "unit": left_unit, **left_summary},
                "right": {"column": right_column, "unit": right_unit, **right_summary},
                "comparable_units": comparable, "mean_difference_right_minus_left": difference,
                "relative_difference_percent": relative,
                "limitations": ["这是描述性样本比较，不代表显著差异；需核对采样工况和测量方法。",
                                "跨帧检测次数不等于独立气泡数；像素和物理长度不能直接比较。"]}

    @registry.register("计算已知两次位置观测的位移速度。需要真实时间间隔，不能从单张图推断速度；未标定则输出 px/s。")
    def calculate_bubble_velocity(context, start_x: float, start_y: float, end_x: float,
                                  end_y: float, time_seconds: float, mm_per_pixel: float | None = None):
        if time_seconds <= 0 or (mm_per_pixel is not None and mm_per_pixel <= 0):
            raise ToolError("时间间隔和标定比例必须大于 0。")
        scale = mm_per_pixel if mm_per_pixel is not None else 1
        velocity_x = (end_x - start_x) * scale / time_seconds
        velocity_y = (end_y - start_y) * scale / time_seconds
        return {"vx": velocity_x, "vy": velocity_y, "speed": math.hypot(velocity_x, velocity_y),
                "unit": "mm/s" if mm_per_pixel is not None else "px/s", "time_seconds": time_seconds,
                "basis": "用户提供的两次位置观测与时间间隔；图像 y 轴向下为正。"}
