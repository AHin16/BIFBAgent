"""Compare batched existing YOLO inference to prior single-image observations."""
import json
import math
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
import pandas as pd
from app.config import load_settings
from app.vision.image_io import read_image
from app.yolo_adapter import YoloAdapter

def main():
    source=ROOT/'data/optimization_pilot/multi_20261112'
    images=pd.read_csv(source/'image_summary.csv')
    images=images.groupby(['height_id','Q_m3_h'],sort=True).head(2)
    details=pd.read_csv(source/'bubble_details.csv')
    adapter=YoloAdapter(); adapter.load(load_settings().model_copy(update={'confidence':.25,'mm_per_pixel':None}))
    predictor=adapter.predictor; findings=[]; start=time.perf_counter()
    for i in range(0,len(images),4):
        group=images.iloc[i:i+4]; originals=[read_image(p) for p in group.image_path]
        results=predictor.model.predict(source=originals,task=predictor.task,conf=predictor.conf_threshold,
            iou=predictor.iou_threshold,imgsz=predictor.input_size,retina_masks=True,verbose=False,device=0)
        for (_,row),im,res in zip(group.iterrows(),originals,results):
            height,width=im.shape[:2]; boxes=res.boxes.data.detach().cpu().numpy() if res.boxes is not None else []
            masks=res.masks.data.cpu().numpy() if res.masks is not None else []
            sizes=[]
            for idx,b in enumerate(boxes):
                x1,y1,x2,y2=map(float,b[:4]); edge=x1<=0 or y1<=0 or x2>=width-1 or y2>=height-1
                if idx>=len(masks): continue
                m=masks[idx].astype(np.float32,copy=False)
                if m.shape!=(height,width): m=cv2.resize(m,(width,height),interpolation=cv2.INTER_LINEAR)
                mask=m>.5
                if not mask.any() or edge or mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any(): continue
                sizes.append(2*math.sqrt(np.count_nonzero(mask)/math.pi))
            old=details[details.image_id==row.image_id]
            oldclean=old[(old.bbox_touches_edge==False)&(old.mask_touches_edge.astype(str).str.lower()=='false')].diameter_px
            findings.append({'image_id':row.image_id,'old_count':len(old),'batch_count':len(boxes),
                'old_clean_d50':float(oldclean.median()) if len(oldclean) else None,
                'batch_clean_d50':float(np.median(sizes)) if sizes else None})
    print(json.dumps({'seconds':time.perf_counter()-start,'images':len(findings),'findings':findings},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
