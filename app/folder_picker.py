"""Run browser-mode dialogs in a fresh process's GUI main thread."""

import argparse
import json
import logging
import subprocess
import sys
import threading
from pathlib import Path


logger = logging.getLogger(__name__)
_dialog_lock = threading.Lock()


def select_folder():
    return _select_path("folder")


def select_model():
    return _select_path("model")


def _select_path(kind):
    from app.storage import ToolError
    label = "模型权重" if kind == "model" else "文件夹"
    if not _dialog_lock.acquire(blocking=False):
        raise ToolError("选择窗口已打开，请先完成选择或取消。")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--kind", kind],
            capture_output=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode:
            logger.error("Folder dialog process failed: %s", completed.stderr[-2000:])
            raise ToolError(f"无法打开{label}窗口，请检查 PySide6 或粘贴本地路径。")
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("path"), str):
            raise ValueError("invalid path picker response")
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        logger.exception("Folder picker unavailable")
        raise ToolError(f"{label}窗口未能完成选择，请重试或粘贴本地路径。") from error
    finally:
        _dialog_lock.release()


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("folder", "model"), default="folder")
    arguments = parser.parse_args()
    application = QApplication.instance() or QApplication(sys.argv[:1])
    parent = QWidget()
    parent.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
    parent.setWindowTitle("BIFB · 选择本地文件")
    parent.resize(1, 1)
    parent.show()
    if arguments.kind == "model":
        path, _ = QFileDialog.getOpenFileName(parent, "选择气泡模型权重", "", "YOLO 模型权重 (*.pt);;所有文件 (*)")
    else:
        path = QFileDialog.getExistingDirectory(parent, "选择实验图片文件夹", "", QFileDialog.ShowDirsOnly)
    parent.close()
    sys.stdout.buffer.write(json.dumps({"path": path, "cancelled": not bool(path)}, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    application.quit()


if __name__ == "__main__":
    main()
