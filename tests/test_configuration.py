import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from scheduler.core import AUTONOMY, ChatAPI, Scheduler, SchedulerError
from scheduler.credentials import parse_credentials
from scheduler.ui import Application, demo_plan, make_server, model_catalog


class ConfigurationTests(unittest.TestCase):
    def test_supported_key_files_and_no_shell_execution(self):
        for text in ('export OPENAI_API_KEY="synthetic-value" # comment\nOPENAI_MODEL=example',
                     '{"api_key":"synthetic-value","model":"example"}', 'synthetic-value'):
            self.assertEqual(parse_credentials(text)["key"], "synthetic-value")
        value = parse_credentials('OPENAI_API_KEY="$(do-not-run)"')
        self.assertEqual(value["key"], "$(do-not-run)")

    def test_judgment_and_effort_are_independent(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"reason\\":\\"ok\\",\\"updates\\":[]}"}}]}'

        config = {"model": "test", "base_url": "https://example.invalid/v1", "reasoning_effort": "high"}
        for mode in AUTONOMY:
            with patch("urllib.request.urlopen", return_value=Response()) as transport:
                ChatAPI(config, key="synthetic-value", autonomy=mode)({})
                payload = json.loads(transport.call_args.args[0].data)
                self.assertIn(AUTONOMY[mode], payload["messages"][0]["content"])
                self.assertEqual(payload["reasoning_effort"], "high")
        config["reasoning_effort"] = "default"
        with patch("urllib.request.urlopen", return_value=Response()) as transport:
            ChatAPI(config, key="synthetic-value")({})
            self.assertNotIn("reasoning_effort", json.loads(transport.call_args.args[0].data))

    def test_key_file_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key.env"
            path.write_text("OPENAI_API_KEY=synthetic-value\n")
            client = ChatAPI({"model": "test", "base_url": "https://example.invalid", "key_file": str(path)})
            self.assertEqual(client.key, "synthetic-value")

    def test_invalid_judgment_rejected(self):
        plan = demo_plan()
        plan["autonomy"] = "anything"
        with self.assertRaises(SchedulerError):
            Scheduler(plan, "/tmp/unused")

    def test_ui_upload_and_launch_never_persist_key(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Application(folder)
            imported = app.dispatch("/api/import", {"name": "key.env", "text": "OPENAI_API_KEY=synthetic-value\nOPENAI_MODEL=test\nOPENAI_BASE_URL=https://example.invalid/v1"})
            self.assertNotIn("synthetic-value", json.dumps(imported))
            body = {"profile": imported["id"], "base_url": imported["base_url"], "model": "test",
                    "autonomy": "ingenious", "reasoning_effort": "high", "plan": demo_plan()}
            with patch("scheduler.ui.launch", return_value={"pid": 123, "run_dir": folder}) as launcher:
                result = app.dispatch("/api/start", body)
                plan_path = launcher.call_args.args[0]
                plan = json.loads(plan_path.read_text())
                self.assertNotIn("synthetic-value", plan_path.read_text())
                self.assertEqual(plan["autonomy"], "ingenious")
                self.assertEqual(plan["api"]["reasoning_effort"], "high")
                self.assertEqual(launcher.call_args.args[2]["SCHEDULER_UI_API_KEY"], "synthetic-value")
                self.assertNotIn("synthetic-value", json.dumps(result))

    def test_ui_http_requires_session_token(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Application(folder)
            server = make_server(0, app)
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/") as response:
                page = response.read().decode()
                self.assertIn(app.token, page)
                self.assertNotIn("__TRANSLATIONS__", page)
                self.assertIn("Français", page)
                for mode in AUTONOMY:
                    self.assertIn(mode, page)
            request = urllib.request.Request(base + "/api/default", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(json.load(error.exception)["error_code"], "session_invalid")
            error.exception.close()
            request.add_header("X-Scheduler-Token", app.token)
            with urllib.request.urlopen(request) as response:
                self.assertEqual(len(json.load(response)["plan"]["steps"]), 2)


if __name__ == "__main__":
    unittest.main()
