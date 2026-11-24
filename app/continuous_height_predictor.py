"""Experimental pooled model using height as a continuous numeric feature."""
import hashlib
from io import BytesIO
import json
import math
import os

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from app.bubble_kernel import FEATURES, predict_kernel
from app.config import ROOT
from app.storage import ToolError

RUN=ROOT/'data/h3_confirmed/continuous_height'
HEIGHTS={.2:'H1',.8:'H2',1.2:'H3',1.8:'H4'}


def predict_continuous(current_q,target_q,salinity,pl,height,target_height=None):
    target_height=height if target_height is None else target_height
    if not all(math.isfinite(float(x)) for x in (current_q,target_q,salinity,pl,height,target_height)):
        raise ToolError('Q、高度、盐度和 PL 必须是有效数值。')
    for label,h in [('当前高度',height),('目标高度',target_height)]:
        if not .2-1e-9<=h<=1.8+1e-9:
            raise ToolError(f'{label}须在 0.2–1.8 m 范围内，不进行高度外推。')
    for label,value,lower,upper in [('当前 Q',current_q,1.5,2.3),('目标 Q',target_q,1.5,2.3),('盐度',salinity,.5,2.5),('PL',pl,.05,.15)]:
        if not lower-1e-9<=value<=upper+1e-9:
            raise ToolError(f'{label} 超出单项训练范围 {lower}–{upper}。')
    try:
        condition_bytes = (RUN / 'conditions.csv').read_bytes()
        conditions = pd.read_csv(BytesIO(condition_bytes))
        kernel_model = None
        kernel_names = ['rbf_model.json']
        if os.getenv('BIFB_RBF_VARIANT') == 'weighted':
            kernel_names.insert(0, 'rbf_middle_q_weighted.json')
        condition_hash = hashlib.sha256(condition_bytes).hexdigest()
        for name in kernel_names:
            kernel_path = RUN / name
            if not kernel_path.is_file():
                continue
            candidate = json.loads(kernel_path.read_text(encoding='utf-8'))
            if candidate['conditions_sha256'] == condition_hash:
                kernel_model = candidate
                break
        model = None if kernel_model else json.loads((RUN / 'model.json').read_text(encoding='utf-8'))
        points=conditions[list(FEATURES)].to_numpy(dtype=float)
        scale=np.array([1.,1.,1.,.1]); matrix=np.vstack([np.ones(len(points)),(points/scale).T])
        def predict(q,h):
            features=np.array([q,h,salinity,pl],dtype=float)
            within=bool(linprog(np.zeros(len(points)),A_eq=matrix,b_eq=np.r_[1.,features/scale],bounds=(0,None),method='highs').success)
            if kernel_model:
                return float(predict_kernel(kernel_model, features)[0]), within
            if model['selected_model']=='Linear':
                return float(np.dot(model['coefficients'],np.r_[1.,features])),within
            values=[]; features=features.astype(np.float32)
            for tree in model['trees']:
                node=0
                while tree['left'][node]!=-1:
                    node=tree['left'][node] if float(features[tree['feature'][node]])<=tree['threshold'][node] else tree['right'][node]
                values.append(tree['value'][node])
            if not values: raise ToolError('连续高度模型内容不完整。')
            return float(np.mean(values)),within
        current,current_within=predict(current_q,height); target,target_within=predict(target_q,target_height); diff=target-current
        def same_conditions(h):
            return conditions[np.isclose(conditions.height_m,h,atol=1e-9,rtol=0)
                              & np.isclose(conditions.salinity_wt_pct,salinity,atol=1e-9,rtol=0)
                              & np.isclose(conditions.PL_fraction,pl,atol=1e-9,rtol=0)]

        def measured(q,h):
            subset=same_conditions(h)
            subset=subset[np.isclose(subset.Q_m3_h,q,atol=1e-9,rtol=0)]
            if subset.empty:return None
            count=int(subset.valid_images.sum())
            return {'Q_m3_h':float(q),'Ug_m_s':float(q*.00325),'image_count':count,
                    'mean_image_d50_px':float(np.average(subset.mean_d50_px,weights=subset.valid_images)),
                    'used_in_model_training':True,'basis':'训练数据的 YOLO 图片统计，不是独立验证。'}
        current_actual=measured(current_q,height)
        change_from_measurement = None
        if current_actual:
            baseline = current_actual['mean_image_d50_px']
            measured_baseline_delta = target - baseline
            change_from_measurement = {
                'current_d50_px': baseline,
                'change_px': measured_baseline_delta,
                'change_percent': 100 * measured_baseline_delta / baseline if baseline else None,
                'image_count': current_actual['image_count'],
            }
        actual=measured(target_q,target_height); comparison=None
        if actual:
            error=abs(target-actual['mean_image_d50_px'])
            comparison={'measured':actual,'absolute_error_px':error,'relative_error_percent':error/abs(actual['mean_image_d50_px'])*100 if actual['mean_image_d50_px'] else None,
                        'evaluation_type':'training_condition_not_independent','camera_conditions_confirmed':False}
            if current_actual:
                baseline = current_actual['mean_image_d50_px']
                observed_change = actual['mean_image_d50_px'] - baseline
                comparison.update(observed_change_px=observed_change,
                                  observed_change_percent=100 * observed_change / baseline if baseline else None,
                                  change_from_measurement_error_px=abs(measured_baseline_delta - observed_change),
                                  change_absolute_error_px=abs(diff - observed_change))
        if kernel_model:
            prediction_model = kernel_model.get('variant', 'RBF')
            model_label = ('中档 Q 加权高斯核（试用版，Q＝1.8、2.0 权重为 2）'
                           if prediction_model == 'RBF_MID_Q_2X' else '等权高斯核')
            validation = (
                f"{model_label}。整档 Q 留出验证的泡径变化量平均误差 {kernel_model['q_change_mae_px']:.2f} px，"
                f"整批来源留出为 {kernel_model['source_change_mae_px']:.2f} px。"
                "误差来自现有可配对工况，未做独立复拍验证。"
            )
        else:
            prediction_model = model['selected_model']
            metrics = model['metrics'][prediction_model]
            validation = (
                f"连续高度探索模型：留出整个高度验证 MAE {metrics['mae_px']:.2f} px，"
                f"均值基准 {model['metrics']['ConditionMean']['mae_px']:.2f} px"
                "（仅盐度 1 wt%、PL 10%；两端为外推）。"
            )
        target_q_levels = sorted(map(float, same_conditions(target_height).Q_m3_h.unique()))
        if actual:
            q_support = 'measured'
        elif not target_q_levels:
            q_support = 'no_matching_group'
        elif target_q_levels[0] < target_q < target_q_levels[-1]:
            q_support = 'bracketed'
        else:
            q_support = 'outside_group_q'
        return {'kind':'ug_bubble_prediction','model_version':'continuous_height_exploratory',
                'prediction_model':prediction_model,
                'conditions':{'height_m':float(height),'target_height_m':float(target_height),'height_id':next((v for k,v in HEIGHTS.items() if abs(height-k)<1e-9),None),'salinity_wt_pct':float(salinity),'PL_fraction':float(pl)},
                'current_height_m':float(height),'target_height_m':float(target_height),
                'height_changed':not math.isclose(height,target_height,abs_tol=1e-9),
                'current_Q_m3_h':float(current_q),'current_Ug_m_s':float(current_q*.00325),'current_predicted_d50_px':current,'current':current_actual,
                'target_Q_m3_h':float(target_q),'target_Ug_m_s':float(target_q*.00325),'predicted_d50_px':target,'change_px':diff,
                'change_percent':diff/current*100 if current else None,'unit':'px','target_data_available':bool(actual),'comparison':comparison,
                'change_from_measurement':change_from_measurement,
                'change_basis':'目标 Q、目标高度的预测减当前 Q、当前高度的预测；若两者高度不同，差值同时受高度和气速影响。',
                'current_within_joint_coverage':current_within,'target_within_joint_coverage':target_within,
                'target_q_support':{'kind':q_support,'measured_q_levels':target_q_levels},
                'validation_summary':validation,
                'limitations':['不同高度的相机视野、裁剪及物理比例尺尚未核实一致，高度与数据来源存在混杂，跨高度像素关系可能不是物理规律。',
                               '仅 H3 有不同盐度和 PL 的数据；其他高度对盐度和 PL 的影响未经验证。',
                               '单项范围内但联合覆盖外的组合属于组合外推，预测趋势尚待实验核验。',
                               'YOLO 测量不等于人工真值，目标工况若有历史数据则已参与训练；预测不以当前上传图片为输入。']}
    except ToolError:raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ToolError('连续高度模型或工况数据无法读取。') from exc
