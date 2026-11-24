"""H3 exploratory predictor; requires a confirmed matching image source."""
import json
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from app.config import ROOT
from app.storage import ToolError

H3_RUN = ROOT / 'data/h3_confirmed/model'
SOURCES = ('盐水不同气泡1', '盐水不同照片2')


def ready():
    return all((H3_RUN / name).is_file() for name in ('enabled.json','model.json','condition_statistics.csv','image_statistics.csv'))


def _inside_coverage(frame, q, salinity, pl):
    points = frame[['Q_m3_h','salinity_wt_pct','PL_fraction']].to_numpy(dtype=float)
    # Scale coordinates before the convex-hull feasibility test.
    scale = np.array([1.,1.,.1])
    matrix = np.vstack([np.ones(len(points)), (points / scale).T])
    goal = np.r_[1., np.array([q,salinity,pl]) / scale]
    return bool(linprog(np.zeros(len(points)), A_eq=matrix, b_eq=goal,
                        bounds=(0,None), method='highs').success)


def predict_h3(current_q, target_q, salinity, pl, source):
    if not ready():
        raise ToolError('H3 模型尚未完成验证，暂不可用。')
    if source not in SOURCES:
        raise ToolError('请选择与当前相机视野匹配的 H3 数据来源；高度相同不代表视野相同。')
    if not all(math.isfinite(float(x)) for x in (current_q,target_q,salinity,pl)):
        raise ToolError('气速、盐度和颗粒装载量必须是有效数值。')
    try:
        model = json.loads((H3_RUN/'model.json').read_text(encoding='utf-8'))
        enabled = json.loads((H3_RUN/'enabled.json').read_text(encoding='utf-8'))
        conditions = pd.read_csv(H3_RUN/'condition_statistics.csv')
        images = pd.read_csv(H3_RUN/'image_statistics.csv')
        subset = conditions[conditions.source == source]
        for label,q in (('当前',current_q),('目标',target_q)):
            if not _inside_coverage(subset,q,salinity,pl):
                raise ToolError(f'{label}工况超出该来源的联合实验覆盖范围，不能可靠预测。')
        forest = None
        if enabled.get('model') == 'random_forest':
            forest=json.loads((H3_RUN/'forest_model.json').read_text(encoding='utf-8'))
            if forest['condition_csv_sha256'] != hashlib.sha256((H3_RUN/'condition_statistics.csv').read_bytes()).hexdigest():
                raise ToolError('H3 模型与工况数据不匹配，请重新验证。')
        coefficients = model['coefficients']
        def estimate(q):
            features=np.asarray([q,salinity,pl,float(source==SOURCES[1])],dtype=np.float32)
            if forest is None:
                return float(np.dot(coefficients,[1,*features]))
            values=[]
            for tree in forest['trees']:
                node=0
                while tree['left'][node] != -1:
                    node=tree['left'][node] if float(features[tree['feature'][node]]) <= tree['threshold'][node] else tree['right'][node]
                values.append(tree['value'][node])
            if not values: raise ToolError('H3 模型内容不完整。')
            return float(np.mean(values))
        def observed(q):
            frame = images[(images.source==source) & np.isclose(images.Q_m3_h,q,atol=1e-9,rtol=0)
                           & np.isclose(images.salinity_wt_pct,salinity,atol=1e-9,rtol=0)
                           & np.isclose(images.PL_fraction,pl,atol=1e-9,rtol=0)].dropna(subset=['d50_px'])
            if frame.empty: return None
            return {'Q_m3_h':q,'Ug_m_s':q*.00325,'image_count':len(frame),
                    'mean_image_d50_px':float(frame.d50_px.mean()),
                    'image_d50_p10_px':float(frame.d50_px.quantile(.1)),
                    'image_d50_p90_px':float(frame.d50_px.quantile(.9)),
                    'used_in_model_training':True,'basis':'训练数据的 YOLO 图像测量，不是独立测试或人工标注真值。'}
        current = estimate(current_q); target = estimate(target_q); measurement = observed(target_q)
        comparison = None
        if measurement:
            actual=measurement['mean_image_d50_px']
            comparison={'measured':measurement,'absolute_error_px':abs(target-actual),
                        'relative_error_percent':abs(target-actual)/abs(actual)*100 if actual else None,
                        'evaluation_type':'training_condition_not_independent','camera_conditions_confirmed':False}
        metrics=model['metrics']; diff=target-current
        summary=f"探索性 H3 线性模型：留一工况 MAE {metrics['mae_px']:.2f} px，同来源均值基准 {metrics['baseline_mae_px']:.2f} px；并非独立重复实验验证。"
        if forest is not None:
            comparison_metrics=json.loads((H3_RUN/'model_comparison.json').read_text(encoding='utf-8'))['models']
            summary=f"探索性 H3 随机森林：28 个留出工况 MAE {comparison_metrics['RandomForest']['mae_px']:.2f} px，线性模型 {comparison_metrics['Linear']['mae_px']:.2f} px；模型比较与选择使用相同数据，尚无独立重复实验验证。"
        return {'kind':'ug_bubble_prediction','model_version':'h3_random_forest_exploratory' if forest is not None else 'h3_exploratory_linear',
                'conditions':{'salinity_wt_pct':salinity,'PL_fraction':pl,'height_id':'H3','height_m':1.2,'source':source},
                'current_Q_m3_h':current_q,'current_Ug_m_s':current_q*.00325,
                'current_predicted_d50_px':current,'current':observed(current_q),
                'target_Q_m3_h':target_q,'target_Ug_m_s':target_q*.00325,'predicted_d50_px':target,
                'change_px':diff,'change_percent':diff/current*100 if current else None,'unit':'px',
                'applicable_Q_m3_h':[float(subset.Q_m3_h.min()),float(subset.Q_m3_h.max())],
                'validation_summary':summary,
                'target_data_available':bool(measurement),'comparison':comparison,
                'limitations':['随机森林在连续参数变化时的预测可能呈阶梯状，并非连续物理曲线。' if forest is not None else '当前是探索性线性模型，未估计参数之间的交互作用。',
                               '相机视野和物理比例尺尚未确认；仅输出 px。',
                               '来源需与当前相机条件匹配；高度一致不代表视野一致。',
                               '历史 YOLO 测量参与训练，不是独立验证；模型不根据上传图片重新拟合。',
                               '实验序列内连续帧相关，不能当作独立重复实验。']}
    except ToolError:
        raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ToolError('H3 模型或本地统计数据无法读取。') from exc
