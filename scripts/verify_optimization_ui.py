"""Offscreen Qt smoke check for the existing desktop UI; no model calls."""
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu --disable-gpu-compositing')
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from desktop import LocalBackend


def main():
    app=QApplication(sys.argv)
    backend=LocalBackend(0); backend.start()
    view=QWebEngineView(); view.resize(1450,1000); view.show()
    status={'done':False, 'success':False}
    def inspect(value):
        status['done']=True
        try:
            result=json.loads(value)
            assert result['visible'] and result['target_range'] == ['1.5','2.3'] and result['upload'] and result['pl'] and not result['workbench_visible'], result
            assert result['activity_text'] == '测试行动记录' and result['activity_columns'] == 3, result
            assert '1.5–2.3' in result['velocity_hint'] and result['height_range'] == ['0.2','1.8'] and result['height_value']=='0.7', result
            assert result['target_height_default_hidden'] and result['target_height_enabled'] and result['target_height_restored'], result
            assert result['conditions'] == 40 and result['history_card'] and result['without_actual']==0 and result['with_actual']==1, result
            out=ROOT/'data/validation/optimization_ui.png'; out.parent.mkdir(parents=True,exist_ok=True)
            def finish():
                if not view.grab().save(str(out)):
                    print('Failed to save preview',flush=True)
                else:
                    print(json.dumps(result,ensure_ascii=False),flush=True); print(str(out),flush=True)
                    status['success']=True
                app.quit()
            QTimer.singleShot(1200,finish)
            return
        except Exception as error: print('UI check failed:',error,flush=True)
        app.quit()
    def loaded(ok):
        if not ok: print('UI failed to load',flush=True); app.quit(); return
        QTimer.singleShot(2500,lambda: view.page().runJavaScript("""
          document.querySelector('[data-nav="optimization"]').click();
          optimizationEvent({type:'status',time:'12:00',message:'测试行动记录'});
          const velocity = document.querySelector('#optimization-form [name=current_q]');
          velocity.value = '1.5';
          const height = document.querySelector('#optimization-form [name=height_m]'); height.value='0.7';
          const toggle=document.querySelector('[name=use_target_height]');
          const fields=document.getElementById('optimization-target-height-fields');
          const targetHeight=document.querySelector('[name=target_height_m]');
          const targetDefault=fields.hidden && !targetHeight.required;
          toggle.checked=true;toggle.dispatchEvent(new Event('change'));
          const targetEnabled=!fields.hidden && targetHeight.required;
          toggle.checked=false;toggle.dispatchEvent(new Event('change'));
          const targetRestored=fields.hidden && !targetHeight.required;
          optimizationEvent({type:'tool_result',tool:'lookup_condition_measurements',result:{status:'success',image_count:1000,valid_images:998,mean_image_d50_px:120,image_d50_p10_px:100,image_d50_p90_px:140,low_quality_images:5,source:'测试来源',artifacts:[]}});
          const historyCard=document.getElementById('optimization-output').textContent.includes('当前工况气泡大小');
          const prediction={status:'success',current_predicted_d50_px:120,predicted_d50_px:125,change_px:5,change_percent:4,conditions:{height_m:.7,salinity_wt_pct:1,PL_fraction:.1},validation_summary:'测试',target_data_available:false,artifacts:[]};
          optimizationEvent({type:'tool_result',tool:'predict_ug_bubble_diameter',result:prediction});
          const withoutActual=document.querySelectorAll('#optimization-output .result-comparison').length;
          prediction.comparison={measured:{mean_image_d50_px:123,image_count:1000},absolute_error_px:2,relative_error_percent:1.6};
          optimizationEvent({type:'tool_result',tool:'predict_ug_bubble_diameter',result:prediction});
          const withActual=document.querySelectorAll('#optimization-output .result-comparison').length;
          JSON.stringify({visible:!document.getElementById('optimization-view').hidden,
             workbench_visible:!document.getElementById('workbench-view').hidden,
             target_range:[document.querySelector('[name=target_q]').min,document.querySelector('[name=target_q]').max],
             upload:!!document.getElementById('optimization-file'),
             pl:!!document.querySelector('#optimization-form [name=pl_percent]'),
             supported:document.getElementById('optimization-supported').textContent,
             activity_text:document.querySelector('#optimization-activity .activity-content')?.textContent,
             activity_columns:document.querySelector('#optimization-activity .activity-row')?.children.length,
             velocity_hint:document.getElementById('optimization-velocity-hint').textContent,
             height_range:[height.min,height.max], height_value:height.value,
             target_height_default_hidden:targetDefault,target_height_enabled:targetEnabled,target_height_restored:targetRestored,
             conditions:document.querySelectorAll('#optimization-condition option').length-1,history_card:historyCard,without_actual:withoutActual,with_actual:withActual})
        """,inspect))
    view.loadFinished.connect(loaded)
    QTimer.singleShot(30000,app.quit)
    view.load(QUrl(backend.url)); app.exec()
    view.close(); backend.stop()
    if not status['success']: raise SystemExit('UI smoke check failed or timed out')


if __name__=='__main__': main()
