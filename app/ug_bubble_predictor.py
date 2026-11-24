"""H1 Ug demonstration. Uses the frozen Q=2.0 held-out model and local summaries."""
import math
from pathlib import Path
import json
import pandas as pd
from app.analysis import save_plot
from app.config import ROOT
from app.storage import ToolError
from app.h3_bubble_predictor import predict_h3, ready as h3_ready

RUN=ROOT/'data/ug_h1_demo/20261113_130903'
HEIGHT_FULL_RUN=ROOT/'data/height_full'
SCALE=.00325


def available_prediction_heights():
    model_path=HEIGHT_FULL_RUN/'model.json'
    if not model_path.exists():
        return ['H1']
    try:
        bundle=json.loads(model_path.read_text(encoding='utf-8'))
        if not (HEIGHT_FULL_RUN/'image_statistics.csv').is_file():
            raise ValueError('missing statistics')
        heights = [h for h in ('H1','H2','H4') if h in bundle['heights']]
        if h3_ready(): heights.insert(2, 'H3')
        return heights
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ToolError('高度模型数据不完整，请检查本地模型文件。') from exc


class GasVelocityBubblePredictor:
    def __init__(self, directory=RUN):
        self.directory=Path(directory)

    def predict(self, current_q, target_q, salinity_wt_pct, PL_fraction, height_id='', source_root_name='', height_m=None, target_height_m=None):
        values=(current_q,target_q,salinity_wt_pct,PL_fraction)
        if not all(math.isfinite(float(x)) for x in values) or min(current_q,target_q)<0:
            raise ToolError('Q、盐度和 PL 必须是有效数值，Q 不能为负。')
        if height_m is not None:
            return self.predict_at_height(current_q,target_q,salinity_wt_pct,PL_fraction,height_m,source_root_name,target_height_m)
        if target_height_m is not None:
            raise ToolError('预测目标高度时必须提供数值型当前高度。')
        height_id=height_id.upper().strip()
        if height_id == 'H3':
            return predict_h3(current_q,target_q,salinity_wt_pct,PL_fraction,source_root_name)
        if abs(salinity_wt_pct-1)>1e-8 or abs(PL_fraction-.1)>1e-8:
            raise ToolError('此模型仅支持盐度 1 wt%、PL 0.10；其他条件尚无匹配模型。')
        supported=available_prediction_heights()
        if height_id not in supported:
            raise ToolError(f'此模型支持的拍摄高度为 {"、".join(supported)}；其他高度尚无匹配模型。')
        if (HEIGHT_FULL_RUN/'model.json').exists() and self.directory == RUN:
            return self._predict_height_full(current_q,target_q,salinity_wt_pct,PL_fraction,height_id)
        try:
            bundle=json.loads((self.directory/'blind_model.json').read_text(encoding='utf-8'))
            frame=pd.read_csv(self.directory/'image_statistics.csv')
        except (OSError,ValueError,KeyError) as exc:
            raise ToolError('预测模型或本地统计结果不可用，请先运行 H1 训练验证程序。') from exc
        model=bundle['models']['clean']
        lower, upper = model['train_ug_min'], model['train_ug_max']
        for label, q in (('当前', current_q), ('目标', target_q)):
            if not lower - 1e-12 <= q*SCALE <= upper + 1e-12:
                raise ToolError(f'{label} Q 超出此模型训练范围 1.5–2.3 m³/h；当前演示不进行外推。')
        def measured(q):
            subset=frame[(frame.scope=='clean') & ((frame.Q_m3_h-q).abs()<1e-9)].dropna(subset=['d50_px'])
            if subset.empty: return None
            return {'Q_m3_h':float(q),'Ug_m_s':float(q*SCALE),'image_count':len(subset),
                    'mean_image_d50_px':float(subset.d50_px.mean()),'image_d50_p10_px':float(subset.d50_px.quantile(.1)),
                    'image_d50_p90_px':float(subset.d50_px.quantile(.9)),
                    'used_in_model_training':any(abs(q-training_q)<1e-9 for training_q in model['train_Q']),
                    'basis':'YOLO 图像测量；非人工标注真值，训练工况的测量数据曾参与模型拟合。'}
        current=measured(current_q)
        target=measured(target_q)
        predicted=model['intercept_px']+model['slope_px_per_m_s']*target_q*SCALE
        current_prediction=model['intercept_px']+model['slope_px_per_m_s']*current_q*SCALE
        difference=predicted-current_prediction
        comparison=None
        if target:
            actual=target['mean_image_d50_px']
            comparison={'measured':target,'absolute_error_px':abs(predicted-actual),
                        'relative_error_percent':abs(predicted-actual)/abs(actual)*100 if actual else None,
                        'evaluation_type':'held_out_Q_2.0' if abs(target_q-2.0)<1e-9 else 'training_condition_not_independent',
                        'camera_conditions_confirmed':False}
        return {'kind':'ug_bubble_prediction', 'conditions':{'salinity_wt_pct':1.0,'PL_fraction':0.1,'height_id':'H1','height_m':0.2},
                'current_Q_m3_h':float(current_q),'current_Ug_m_s':float(current_q*SCALE),
                'current_predicted_d50_px':float(current_prediction),'current':current,
                'target_Q_m3_h':float(target_q),'target_Ug_m_s':float(target_q*SCALE),
                'predicted_d50_px':float(predicted),'change_px':float(difference),
                'change_percent':float(difference/current_prediction*100) if current_prediction else None,
                'change_basis':'目标预测值减当前预测值，均由同一模型计算','unit':'px',
                'applicable_Q_m3_h':[float(lower/SCALE),float(upper/SCALE)],
                'validation_summary':'探索性模型：Q=2.0留出对照相对误差约9.41%；四折留一Q工况MAE约9.72 px，高于常数均值基准约6.37 px。',
                'target_data_available':bool(target),'comparison':comparison,'model_training_Q':model['train_Q'],
                'limitations':['探索性预测，四折误差高于均值基准，尚不能用于可靠运行优化。',
                    '预测为每图d50的工况均值，未预测完整粒径分布。',
                    '跨Q相机位置、裁剪、视野和空间标定尚未核实；比较仅为同条件候选，不是已确认的严格实验验证。',
                    '此前V1使用过这些数据；首次Q=2留出模型未用其标签拟合，但不是完全前瞻盲测。',
                    '仅4个气速水平、每个一条实验序列，YOLO结果不等于人工标注真值；无需推断因果。']}

    def predict_at_height(self,current_q,target_q,salinity_wt_pct,PL_fraction,height_m,source_root_name='',target_height_m=None):
        from app.continuous_height_predictor import predict_continuous
        return predict_continuous(current_q,target_q,salinity_wt_pct,PL_fraction,height_m,target_height_m)
    def _predict_height_full(self,current_q,target_q,salinity_wt_pct,PL_fraction,height_id):
        try:
            bundle=json.loads((HEIGHT_FULL_RUN/'model.json').read_text(encoding='utf-8'))
            frame=pd.read_csv(HEIGHT_FULL_RUN/'image_statistics.csv')
            model=bundle['heights'][height_id]; metrics=bundle['metrics']
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise ToolError('高度模型或统计结果无法读取，请检查本地结果。') from exc
        for label,q in (('当前',current_q),('目标',target_q)):
            if not model['q_min']-1e-9<=q<=model['q_max']+1e-9:
                raise ToolError(f'{label} Q 超出模型训练范围 {model["q_min"]}–{model["q_max"]} m³/h；不进行外推。')
        def measured(q):
            subset=frame[(frame.height_id==height_id)&((frame.Q_m3_h-q).abs()<1e-9)].dropna(subset=['d50_px'])
            if subset.empty:return None
            return {'Q_m3_h':float(q),'Ug_m_s':float(q*SCALE),'image_count':len(subset),
                    'mean_image_d50_px':float(subset.d50_px.mean()),'image_d50_p10_px':float(subset.d50_px.quantile(.1)),
                    'image_d50_p90_px':float(subset.d50_px.quantile(.9)), 'used_in_model_training':True,
                    'basis':'训练数据的 YOLO 图像测量，不是独立测试或人工标注真值。'}
        current=measured(current_q); target=measured(target_q)
        def model_value(q): return model['intercept_px']+model['slope_px_per_m_s']*q*SCALE
        current_prediction=model_value(current_q); predicted=model_value(target_q); difference=predicted-current_prediction
        comparison=None
        if target:
            actual=target['mean_image_d50_px']
            comparison={'measured':target,'absolute_error_px':abs(predicted-actual),
                        'relative_error_percent':abs(predicted-actual)/abs(actual)*100 if actual else None,
                        'evaluation_type':'training_condition_not_independent','camera_conditions_confirmed':False}
        return {'kind':'ug_bubble_prediction','model_version':'height_full_exploratory_linear',
                'conditions':{'salinity_wt_pct':1.,'PL_fraction':.1,'height_id':height_id,
                              'height_m':{'H1':.2,'H2':.8,'H4':1.8}[height_id]},
                'current_Q_m3_h':float(current_q),'current_Ug_m_s':float(current_q*SCALE),
                'current_predicted_d50_px':float(current_prediction),'current':current,
                'target_Q_m3_h':float(target_q),'target_Ug_m_s':float(target_q*SCALE),'predicted_d50_px':float(predicted),
                'change_px':float(difference),'change_percent':float(difference/current_prediction*100) if current_prediction else None,
                'change_basis':'目标预测值减当前预测值，均由同一高度模型计算','unit':'px',
                'applicable_Q_m3_h':[model['q_min'],model['q_max']],
                'validation_summary':f"探索性全量模型：{height_id} 四折留一Q工况平均绝对误差 {metrics['per_height'][height_id]['mae_px']:.2f} px，同高度均值基准 {metrics['per_height'][height_id]['baseline_mae_px']:.2f} px；不代表独立实验验证。",
                'target_data_available':bool(target),'comparison':comparison,'model_training_Q':model['training_Q'],
                'limitations':['探索性预测；仅有4个气速水平，每工况一条序列，连续帧并非独立实验，不能作为可靠运行优化依据。',
                    '高度分别拟合，盐度和PL均为固定值，未学习它们的影响；不得推断其他盐度或PL。',
                    '跨工况相机视野、位置和物理标定尚未核实；仅输出像素，不能比较高度间的物理尺寸。',
                    '目标已识别数据参与最终模型拟合，图中历史YOLO不是独立验证；留一Q结果为探索性验证。',
                    '预测为每图非边缘气泡d50的工况均值，当前单图检测包含边缘，口径不同；模型不以当前照片为输入。']}


def register_ug_prediction_tool(registry):
    @registry.register('探索性气泡尺寸预测：输入当前和目标Q、盐度、PL及当前高度 height_m；仅当用户明确指定目标高度时传 target_height_m，否则默认与当前高度相同。Q 1.5–2.3 m³/h，高度 0.2–1.8 m；各参数须在单项范围内。若高度与Q同时改变，差值不能归因于Q。联合覆盖外须提示组合外推且未验证。')
    def predict_ug_bubble_diameter(context, current_q: float, target_q: float, salinity_wt_pct: float, PL_fraction: float, height_id: str = '', source_root_name: str = '', height_m: float | None = None, target_height_m: float | None = None, prediction_mm_per_pixel: float | None = None, calibration_confirmed: bool = False):
        result=GasVelocityBubblePredictor().predict(current_q,target_q,salinity_wt_pct,PL_fraction,height_id,source_root_name,height_m,target_height_m)
        if (prediction_mm_per_pixel is not None) != calibration_confirmed:
            raise ToolError('需要填写比例尺并确认适用于当前照片和模型训练照片，才能换算毫米。')
        if prediction_mm_per_pixel is not None:
            if not math.isfinite(prediction_mm_per_pixel) or prediction_mm_per_pixel<=0:
                raise ToolError('空间比例尺必须大于零。')
            result.update(prediction_mm_per_pixel=prediction_mm_per_pixel,
                current_predicted_d50_mm=result['current_predicted_d50_px']*prediction_mm_per_pixel,
                predicted_d50_mm=result['predicted_d50_px']*prediction_mm_per_pixel,
                change_mm=result['change_px']*prediction_mm_per_pixel,
                calibration_basis='用户确认统一空间比例尺；仅为像素预测的毫米换算。')
            measured_baseline = result.get('change_from_measurement')
            if measured_baseline:
                measured_baseline.update(
                    current_d50_mm=measured_baseline['current_d50_px'] * prediction_mm_per_pixel,
                    change_mm=measured_baseline['change_px'] * prediction_mm_per_pixel)
            if result.get('model_version') == 'continuous_height_exploratory' and result.get('limitations'):
                result['limitations'][0]='统一比例尺由用户确认；不同高度的视野、裁剪及数据来源仍可能混杂，跨高度关系需要实验验证。'
        def draw(ax):
            current = f"当前 Q={current_q:g}"
            target = f"目标 Q={target_q:g}"
            if result.get('height_changed'):
                current += f"，H={result['current_height_m']:g} m"
                target += f"，H={result['target_height_m']:g} m"
            current_measured = (result.get('current') or {}).get('mean_image_d50_px')
            target_measured = (result.get('comparison') or {}).get('measured')
            rows = [(f"{current} · 模型", result['current_predicted_d50_px'], '#9c621c', 'o')]
            if current_measured is not None:
                rows.append((f"{current} · 照片", current_measured, '#28756a', 'D'))
            rows.append((f"{target} · 模型", result['predicted_d50_px'], '#9c621c', 'o'))
            if target_measured:
                rows.append((f"{target} · 照片", target_measured['mean_image_d50_px'], '#28756a', 'D'))

            values = [row[1] for row in rows]
            span = max(max(values) - min(values), 10)
            center = (max(values) + min(values)) / 2
            ax.set_xlim(center - .65 * span, center + .95 * span)
            for index, (_, value, color, marker) in enumerate(rows):
                ax.scatter(value, index, color=color, marker=marker, s=74, zorder=3)
                ax.annotate(f"{value:.2f}", (value, index), xytext=(10, 0),
                            textcoords="offset points", va="center", color=color,
                            fontsize=13, fontweight="bold")
            ax.set_yticks(range(len(rows)), [row[0] for row in rows])
            ax.set_ylim(len(rows) - .35, -.65)
            ax.set_xlabel('每张图片中位径的平均值（px，局部刻度）')
            ax.grid(axis='x', alpha=.22)
        result['artifacts']=[save_plot(context,'气速变化 · 图片中位径对比',draw)]
        if result['target_data_available']:
            full=result.get('model_version')=='height_full_exploratory_linear'
            h3=result.get('model_version') in ('h3_exploratory_linear','h3_random_forest_exploratory')
            continuous=result.get('model_version')=='continuous_height_exploratory'
            if h3:
                from app.h3_bubble_predictor import H3_RUN
            if continuous:
                from app.h3_bubble_predictor import H3_RUN
                frame=pd.concat([pd.read_csv(HEIGHT_FULL_RUN/'image_statistics.csv'),pd.read_csv(H3_RUN/'image_statistics.csv')],ignore_index=True)
                target_h=target_height_m if target_height_m is not None else height_m
                values=frame[((frame.height_m-target_h).abs()<1e-9)&((frame.Q_m3_h-target_q).abs()<1e-9)&((frame.salinity_wt_pct-salinity_wt_pct).abs()<1e-9)&((frame.PL_fraction-PL_fraction).abs()<1e-9)]
            else:
                frame=pd.read_csv((H3_RUN if h3 else HEIGHT_FULL_RUN if full else RUN)/'image_statistics.csv')
                values=frame[(frame.height_id==height_id.upper()) & ((frame.Q_m3_h-target_q).abs()<1e-9)]
            if h3:
                values=values[(values.source==source_root_name) & ((values.salinity_wt_pct-salinity_wt_pct).abs()<1e-9) & ((values.PL_fraction-PL_fraction).abs()<1e-9)]
            elif not full and not continuous: values=values[values.scope=='clean']
            values=values.d50_px.dropna()
            def draw_distribution(ax):
                ax.hist(values,bins=10,color='#729f94',edgecolor='white',label='实验图片测量中位径')
                ax.axvline(result['predicted_d50_px'],color='#bc3444',linestyle='--',label='目标工况预测值')
                ax.set_xlabel('每张图片的中位径 (px)'); ax.set_ylabel('图片数量'); ax.legend()
            result['artifacts'].append(save_plot(context,'目标工况 · 图片中位径分布',draw_distribution))
        return result
