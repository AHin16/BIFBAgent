import json
import socket
import subprocess
import unittest
import urllib.request
from unittest.mock import patch

from app.folder_picker import select_folder, select_model
from app.storage import ToolError
from desktop import LocalBackend


class FolderPickerTest(unittest.TestCase):
    def test_model_picker_returns_unicode_weight_path_and_handles_cancel(self):
        for result in ({"path": "E:/模型/气泡.pt", "cancelled": False}, {"path": "", "cancelled": True}):
            completed = subprocess.CompletedProcess([], 0, json.dumps(result, ensure_ascii=False), "")
            with patch("app.folder_picker.subprocess.run", return_value=completed) as launch:
                self.assertEqual(select_model(), result)
                self.assertEqual(launch.call_args.args[0][-2:], ["--kind", "model"])

    def test_model_dialog_api_returns_selection(self):
        from fastapi.testclient import TestClient
        from app.main import app
        selected = {"path": "E:/模型/气泡.pt", "cancelled": False}
        with patch("app.main.select_model", return_value=selected), TestClient(app) as client:
            response = client.get("/api/dialog/model")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), selected)

    def test_unicode_path_and_cancel_are_distinct_from_failure(self):
        for result in ({"path": "E:/实验/气泡批次", "cancelled": False}, {"path": "", "cancelled": True}):
            completed = subprocess.CompletedProcess([], 0, json.dumps(result, ensure_ascii=False), "")
            with patch("app.folder_picker.subprocess.run", return_value=completed):
                self.assertEqual(select_folder(), result)

    def test_failed_helper_releases_picker_for_next_attempt(self):
        failed = subprocess.CompletedProcess([], 1, "", "failed")
        with patch("app.folder_picker.subprocess.run", return_value=failed):
            with self.assertRaises(ToolError):
                select_folder()
        cancelled = subprocess.CompletedProcess([], 0, '{"path":"","cancelled":true}', "")
        with patch("app.folder_picker.subprocess.run", return_value=cancelled):
            self.assertTrue(select_folder()["cancelled"])

    def test_malformed_response_is_a_friendly_error(self):
        completed = subprocess.CompletedProcess([], 0, '[]', '')
        with patch("app.folder_picker.subprocess.run", return_value=completed):
            with self.assertRaises(ToolError):
                select_folder()


class DesktopLifecycleTest(unittest.TestCase):
    def test_busy_port_is_not_reused_and_owned_server_stops(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            occupied_port = occupied.getsockname()[1]
            backend = LocalBackend(occupied_port)
            self.assertNotEqual(backend.port, occupied_port)
            try:
                backend.start()
                with urllib.request.urlopen(backend.url + "/api/health", timeout=5) as response:
                    self.assertEqual(json.load(response)["status"], "ok")
            finally:
                backend.stop()
            self.assertFalse(backend.thread.is_alive())
            with socket.socket() as probe:
                probe.settimeout(0.5)
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", backend.port)), 0)
            self.assertEqual(occupied.getsockname()[1], occupied_port)

    def test_svg_icons_have_a_chromium_compatible_mime_type(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            for name in ("icons.svg", "brand.svg", "reactor.svg"):
                response = client.get("/static/" + name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "image/svg+xml")


if __name__ == "__main__":
    unittest.main()
