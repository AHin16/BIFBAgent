"""Expose the H3 demonstration model to the Agent's chat tools."""

from app.storage import ToolError
from optimization_data.h3_bubble_demo.model import (
    BubbleDemo,
    HEIGHT_M,
    LOADING_FRACTION,
    SALINITY_WT_PCT,
    load_measurements,
)
from optimization_data.h3_bubble_demo.transport import TransportModel


def register_h3_demo_tool(registry):
    @registry.register(
        "H3 专项气泡尺寸预测。适用固定工况为高度 H3（1.2 m）、盐度 0.5 wt%、PL 10%，"
        "输入当前和目标进气量 Q，均可在 1.5–2.3 m³/h 内任取。"
        "返回目标泡径、上升速度、体积气含率、相对传氧效率及可用的照片对照。"
    )
    def predict_h3_demo_bubble_diameter(context, current_q: float, target_q: float):
        try:
            demo = BubbleDemo(load_measurements())
        except (OSError, ValueError, KeyError) as error:
            raise ToolError("H3 专项预测的四档照片统计暂不可用，请检查本地工况数据。") from error
        try:
            result = demo.predict(current_q, target_q)
        except ValueError as error:
            raise ToolError(str(error)) from error
        current = demo.measurements.get(current_q)
        observed = result["observed_d50_px"]
        try:
            result["transport"] = TransportModel.load().predict(current_q, target_q)
        except (OSError, ValueError, KeyError):
            result["transport"] = None
        if result["transport"]:
            scale = result["transport"]["mm_per_pixel"]
            for field in ("current_d50", "estimated_d50", "estimated_change"):
                result[f"{field}_mm"] = result[f"{field}_px"] * scale
        result.update(
            kind="h3_demo_bubble_prediction",
            current_q=current_q,
            target_q=target_q,
            height_m=HEIGHT_M,
            salinity_wt_pct=SALINITY_WT_PCT,
            PL_fraction=LOADING_FRACTION,
            current_valid_images=current.valid_images if current else None,
            estimated_change_percent=100 * result["estimated_change_px"] / result["current_d50_px"],
            target_absolute_error_px=(
                abs(result["estimated_d50_px"] - observed) if observed is not None else None
            ),
            leave_q_out_mae_px=demo.validation("q_m3_h")["mae_px"],
            leave_source_out_mae_px=demo.validation("source")["mae_px"],
            unit="px",
            limitations=[
                "预测指标为每张照片气泡中位径的工况均值。",
                "常规预测使用四档数据拟合，已测目标的照片对照属于拟合数据。",
                "分组留出结果来自现有四档工况，精度仍需独立实验确认。",
            ],
        )
        return result
