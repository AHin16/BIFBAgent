"""Native Qt shell with an owned local server and main-thread dialogs."""

import argparse
import hashlib
import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


class LocalBackend:
    """Reserve a socket before startup; never reuse another app's server."""

    def __init__(self, port=8000):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(("127.0.0.1", port))
        except OSError:
            self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config("app.main:app", log_level="warning", timeout_graceful_shutdown=3))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True, name="bifb-local-server")

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 30
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("本地服务未能启动，请查看 data/app.log。")
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        self.socket.close()


def main():
    parser = argparse.ArgumentParser(description="BIFB 智能科研助手独立窗口")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    from PySide6.QtCore import QFile, QIODevice, QObject, QStandardPaths, QTimer, QUrl, Slot
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

    application = QApplication(sys.argv)
    application.setApplicationName("BIFB 智能科研助手")
    application.setOrganizationName("BIFB")
    instance_name = "bifb-desktop-" + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:16]
    existing = QLocalSocket()
    existing.connectToServer(instance_name)
    if existing.waitForConnected(400):
        existing.write(b"activate")
        existing.waitForBytesWritten(500)
        existing.disconnectFromServer()
        return 0
    instance_server = QLocalServer()
    if not instance_server.listen(instance_name):
        QMessageBox.warning(None, "BIFB", "程序正在启动，请稍候。")
        return 0

    backend = LocalBackend(arguments.port)
    try:
        backend.start()
    except Exception as error:
        QMessageBox.critical(None, "BIFB 启动失败", str(error))
        instance_server.close()
        return 1

    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, is_main_frame):
            if url.scheme() == "about" or (url.scheme() == "http" and url.host() == "127.0.0.1" and url.port() == backend.port):
                return True
            if kind == QWebEnginePage.NavigationTypeLinkClicked and url.scheme() in {"http", "https"}:
                QDesktopServices.openUrl(url)
            return False

        def javaScriptConsoleMessage(self, level, message, line, source):
            logger.debug("UI %s:%s %s", source, line, message)

    class DesktopBridge(QObject):
        @Slot(result=str)
        def chooseFolder(self):
            path = QFileDialog.getExistingDirectory(window, "选择实验图片文件夹", "", QFileDialog.ShowDirsOnly)
            return json.dumps({"path": path, "cancelled": not bool(path)}, ensure_ascii=False)

        @Slot(result=str)
        def chooseModel(self):
            path, _ = QFileDialog.getOpenFileName(window, "选择气泡模型权重", "", "YOLO 模型权重 (*.pt);;所有文件 (*)")
            return json.dumps({"path": path, "cancelled": not bool(path)}, ensure_ascii=False)

    class ResearchWindow(QMainWindow):
        def closeEvent(self, event):
            from app.main import runs
            active = [run for run in runs.values() if not run.done]
            if active:
                for run in active:
                    run.stop_event.set()
                self.statusBar().showMessage("正在停止分析并保存已完成结果，请稍候…")
                event.ignore()
                QTimer.singleShot(200, self.close)
            else:
                super().closeEvent(event)

    window = ResearchWindow()
    window.setWindowTitle("BIFB · 多相流智能分析与优化 Agent")
    window.setWindowIcon(QIcon(str(ROOT / "app/static/brand.svg")))
    window.resize(1480, 960)
    window.setMinimumSize(1000, 700)
    view = QWebEngineView(window)
    profile = QWebEngineProfile(view)
    page = LocalPage(profile, view)
    view.setPage(page)
    channel = QWebChannel(page)
    bridge = DesktopBridge(window)
    channel.registerObject("desktop", bridge)
    page.setWebChannel(channel)
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.ReadOnly):
        backend.stop()
        raise RuntimeError("Qt WebChannel 资源不可用。")
    bridge_source = bytes(resource.readAll()).decode("utf-8")
    resource.close()
    script = QWebEngineScript()
    script.setName("bifb-desktop-bridge")
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(QWebEngineScript.MainWorld)
    script.setSourceCode(bridge_source + "\nwindow.bifbDesktopReady = new Promise(resolve => { new QWebChannel(qt.webChannelTransport, channel => resolve(channel.objects.desktop)); });")
    page.scripts().insert(script)

    def save_download(download):
        folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        path, _ = QFileDialog.getSaveFileName(window, "保存分析结果", str(Path(folder) / download.downloadFileName()))
        if not path:
            download.cancel()
            return
        download.setDownloadDirectory(str(Path(path).parent))
        download.setDownloadFileName(Path(path).name)
        download.accept()

    profile.downloadRequested.connect(save_download)
    window.setCentralWidget(view)

    def activate_existing():
        connection = instance_server.nextPendingConnection()
        if connection:
            connection.disconnectFromServer()
            connection.deleteLater()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    instance_server.newConnection.connect(activate_existing)
    view.setUrl(QUrl(backend.url))
    window.show()
    try:
        return application.exec()
    finally:
        instance_server.close()
        backend.stop()
        view.setPage(None)


if __name__ == "__main__":
    sys.exit(main())
