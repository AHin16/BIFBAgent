"""Historical same-condition statistics from the existing per-image YOLO data."""
import math
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from app.analysis import save_plot
from app.config import ROOT
from app.storage import ToolError

BASE=ROOT/'data/h3_confirmed/continuous_height/conditions.csv'
H3=ROOT/'data/h3_confirmed/model/image_statistics.csv'
MARKED=ROOT/'data/height_full/image_statistics.csv'


def available_conditions():
    try:
        frame=pd.read_csv(BASE)
        return [{'current_q':float(r.Q_m3_h),'height_m':float(r.height_m),
                 'salinity_wt_pct':float(r.salinity_wt_pct),'PL_fraction':float(r.PL_fraction),
                 'source':str(r.source),'images':int(r.images),'valid_images':int(r.valid_images)}
                for r in frame.itertuples()]
    except (OSError,ValueError,KeyError) as exc:
        raise ToolError('历史工况索引不可用。') from exc


def register_condition_vision(registry):
    @registry.register('查询历史盐水实验工况的现有逐图片YOLO统计，不重新识别：输入当前 Q、高度、盐度及 PL。严格匹配同一工况，返回每图非边缘气泡中位径的平均值、图片间分布、数量与来源。历史结果不是实时数据，也不是独立重复实验。')
    def lookup_condition_measurements(context,current_q:float,height_m:float,salinity_wt_pct:float,PL_fraction:float,prediction_mm_per_pixel:float|None=None,calibration_confirmed:bool=False):
        if not all(math.isfinite(float(v)) for v in (current_q,height_m,salinity_wt_pct,PL_fraction)):
            raise ToolError('工况参数必须是有效数值。')
        if (prediction_mm_per_pixel is not None)!=calibration_confirmed or (prediction_mm_per_pixel is not None and (not math.isfinite(prediction_mm_per_pixel) or prediction_mm_per_pixel<=0)):
            raise ToolError('毫米换算需要已确认的有效比例尺。')
        try:
            marked=pd.read_csv(MARKED);marked['source']='盐水气泡不同高度照片'
            h3=pd.read_csv(H3);data=pd.concat([marked,h3],ignore_index=True)
            match=data[np.isclose(data.Q_m3_h,current_q,atol=1e-9,rtol=0)&np.isclose(data.height_m,height_m,atol=1e-9,rtol=0)&np.isclose(data.salinity_wt_pct,salinity_wt_pct,atol=1e-9,rtol=0)&np.isclose(data.PL_fraction,PL_fraction,atol=1e-9,rtol=0)].copy()
        except (OSError,ValueError,KeyError) as exc:raise ToolError('历史逐图片统计不可用。') from exc
        if match.empty:raise ToolError('没有严格匹配的历史工况；不能把模型预测或其他工况称为当前实测。')
        if match.source.nunique()!=1:raise ToolError('该工况对应多个来源，需要先区分采集来源。')
        usable=match.d50_px.dropna()
        if usable.empty:raise ToolError('该工况没有可用的非边缘气泡中位径。')
        report=context.output('historical_condition_images.csv')
        columns=['image_id','image_path','sequence_id','Q_m3_h','height_m','salinity_wt_pct','PL_fraction','valid_bubbles','low_quality','d50_px']
        match[columns].to_csv(report,index=False,encoding='utf-8-sig')
        def draw(ax):
            ax.hist(usable,bins=20,color='#729f94',edgecolor='white');ax.set_xlabel('每张图片的中位径 d50 (px)');ax.set_ylabel('图片数量')
        artifacts=[context.artifact(report,'历史同工况逐图片统计 · CSV'),save_plot(context,'历史同工况 · 图片中位径分布',draw)]
        preview_errors=[]
        for index,label in [(0,'前段'),(len(match)//2,'中段'),(len(match)-1,'后段')]:
            try:
                with Image.open(Path(str(match.iloc[index].image_path))) as image:
                    image.thumbnail((800,800));path=context.output(f'condition_{label}.png');image.save(path)
                artifacts.append(context.artifact(path,f'同工况照片 · {label}','image'))
            except (OSError,ValueError) as exc:preview_errors.append(str(exc))
        mean=float(usable.mean())
        result={'kind':'historical_condition','source':str(match.source.iloc[0]),'current_q':current_q,'height_m':height_m,
                'salinity_wt_pct':salinity_wt_pct,'PL_fraction':PL_fraction,'image_count':len(match),'valid_images':len(usable),
                'low_quality_images':int(match.low_quality.fillna(False).astype(bool).sum()),
                'mean_image_d50_px':mean,'median_image_d50_px':float(usable.median()),
                'image_d50_p10_px':float(usable.quantile(.1)),'image_d50_p90_px':float(usable.quantile(.9)),
                'source_sequences':int(match.sequence_id.nunique()),'unit':'px','artifacts':artifacts,
                'preview_unavailable':bool(preview_errors),
                'limitations':['历史同工况的既有YOLO统计，不是实时测量；连续帧不等于独立重复实验。',
                    '每张图先排除边缘及边缘状态未知的气泡，再求每图d50及工况平均；有效气泡少于5个的图片已标记。',
                    '这些历史结果参与过模型训练；不构成独立验证。']}
        if prediction_mm_per_pixel is not None:
            result.update(mean_image_d50_mm=mean*prediction_mm_per_pixel,
                image_d50_p10_mm=result['image_d50_p10_px']*prediction_mm_per_pixel,
                image_d50_p90_mm=result['image_d50_p90_px']*prediction_mm_per_pixel,
                prediction_mm_per_pixel=prediction_mm_per_pixel)
        return result
