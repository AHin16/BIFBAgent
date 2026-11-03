"""Run browser-mode dialogs in a fresh process's GUI main thread."""

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path


logger = logging.getLogger(__name__)
_dialog_lock = threading.Lock()


def select_folder():
    from app.storage import ToolError
    if not _dialog_lock.acquire(blocking=False):
        raise ToolError("文件夹选择窗口已打开，请先完成选择或取消。")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            capture_output=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode:
            logger.error("Folder dialog process failed: %s", completed.stderr[-2000:])
            raise ToolError("无法打开文件夹窗口，请检查 PySide6 或粘贴本地路径。")
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("path"), str):
            raise ValueError("invalid folder picker response")
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        logger.exception("Folder picker unavailable")
        raise ToolError("文件夹窗口未能完成选择，请重试或粘贴本地路径。") from error
    finally:
        _dialog_lock.release()


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

    application = QApplication.instance() or QApplication(sys.argv)
    parent = QWidget()
    parent.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
    parent.setWindowTitle("BIFB · 选择实验文件夹")
    parent.resize(1, 1)
    parent.show()
    path = QFileDialog.getExistingDirectory(parent, "选择实验图片文件夹", "", QFileDialog.ShowDirsOnly)
    parent.close()
    sys.stdout.buffer.write(json.dumps({"path": path, "cancelled": not bool(path)}, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    application.quit()


if __name__ == "__main__":
    main()
