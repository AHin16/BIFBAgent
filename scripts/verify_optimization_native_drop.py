"""Offscreen native drag integration smoke test with a temporary local image."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu --disable-gpu-compositing')
from PySide6.QtCore import QCoreApplication,QMimeData,QPoint,QPointF,QTimer,QUrl,Qt
from PySide6.QtGui import QDragEnterEvent,QDropEvent,QImage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
import desktop


def main():
    state={'success':False}
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)/'Q=1.8,1WT%,10%PL,H2_files';folder.mkdir()
        image=folder/'frame.png';QImage(20,20,QImage.Format_RGB32).save(str(image))
        original=QApplication.exec
        def execute(self):
            def start():
                windows=QApplication.topLevelWidgets()
                window=next((w for w in windows if w.findChild(QWebEngineView)),None)
                if not window: print('window not found',flush=True);self.quit();return
                view=window.findChild(QWebEngineView)
                def drag():
                    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(image))])
                    enter=QDragEnterEvent(QPoint(80,80),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    drop=QDropEvent(QPointF(80,80),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    QCoreApplication.sendEvent(view,enter);QCoreApplication.sendEvent(view,drop)
                    def inspect():
                        view.page().runJavaScript("""JSON.stringify({q:document.querySelector('[name=current_q]').value,h:document.querySelector('[name=height_m]').value,s:document.querySelector('[name=salinity_wt_pct]').value,pl:document.querySelector('[name=pl_percent]').value,message:document.getElementById('optimization-metadata-status').textContent})""",finish)
                    QTimer.singleShot(2500,inspect)
                view.page().runJavaScript("document.querySelector('[data-nav=optimization]').click()")
                QTimer.singleShot(1500,drag)
            def finish(value):
                try:
                    data=json.loads(value);print(json.dumps(data,ensure_ascii=False),flush=True)
                    assert [data['q'],data['h'],data['s'],data['pl']]==['1.8','0.8','1','10'],data
                    state['success']=True
                except Exception as exc:print('native drop failed:',exc,flush=True)
                self.quit()
            QTimer.singleShot(5000,start);QTimer.singleShot(30000,self.quit)
            return original()
        QApplication.exec=execute
        try:desktop.main()
        finally:QApplication.exec=original
    if not state['success']:raise SystemExit('native drop check failed or timed out')


if __name__=='__main__':main()
