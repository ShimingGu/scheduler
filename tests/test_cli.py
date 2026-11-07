import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from scheduler.config import load_ini, merge_api
from scheduler.core import AUTONOMY, SchedulerError, read_json, write_json


class IniTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ini = self.root / "scheduler.ini"
        self.key = self.root / "key.env"
        self.key.write_text("OPENAI_API_KEY=synthetic-test-value\nOPENAI_BASE_URL=https://example.invalid/v1\nOPENAI_MODEL=file-model\n")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "scheduler", *args],
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                              text=True, capture_output=True)

    def test_relative_paths_literal_values_and_metadata_fallback(self):
        self.ini.write_text("[scheduler]\nplan=plan.json\nrun_dir=runs/test\nautonomy=mediocre\n[api]\nkey_file=key.env\nreasoning_effort=high\ntimeout=30\nmax_tokens=1000\n")
        settings, api = load_ini(self.ini)
        self.assertEqual(settings["plan"], self.root / "plan.json")
        self.assertEqual(settings["run_dir"], self.root / "runs/test")
        self.assertEqual(api["timeout"], 30)
        self.assertEqual(merge_api({}, api)["model"], "file-model")
        self.assertEqual(merge_api({"model": "plan-model"}, api)["model"], "plan-model")
        self.assertNotIn("key_file", merge_api(api, {"key_env": "OTHER_KEY"}))

    def test_bad_ini_returns_nonzero_without_echoing_values(self):
        self.ini.write_text("[api]\napi_key=do-not-print-this\n")
        result = self.cli("models", "--config", str(self.ini))
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stderr))
        self.assertNotIn("do-not-print-this", result.stderr + result.stdout)

    def test_ini_background_handoff_preserves_overrides_and_lists_models(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = {"data": [{"id": "ini-model", "effort": {"supported_levels": ["low", "high"]}}]}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                content = json.dumps({"reason": "adjust", "updates": [{"id": "b", "task": {"n": 9}}]})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        script = "import os,json,pathlib;t=json.loads(pathlib.Path(os.environ['SCHEDULER_TASK_FILE']).read_text());pathlib.Path(os.environ['SCHEDULER_RESULT_FILE']).write_text(json.dumps(t))"
        plan = {"cwd": ".", "revision_prompt": "Adjust the next task as needed.",
                "api": {"model": "old-model", "base_url": "https://unused.invalid"},
                "steps": [{"id": sid, "command": [sys.executable, "-c", script], "task": {"n": n}}
                          for sid, n in [("a", 1), ("b", 2)]]}
        write_json(self.root / "plan.json", plan)
        self.ini.write_text(f"[scheduler]\nplan=plan.json\nrun_dir=run\nautonomy=ingenious\n[api]\nkey_file=key.env\nbase_url=http://127.0.0.1:{server.server_port}/v1\nmodel=ini-model\nreasoning_effort=high\n")
        listed = self.cli("models", "--config", str(self.ini))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["models"][0]["id"], "ini-model")
        result = self.cli("start", "--config", str(self.ini))
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertNotIn("synthetic-test-value", Path(info["plan"]).read_text())
        state = {}
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                path = self.root / "run/state.json"
                if path.exists():
                    state = read_json(path)
                    if state["phase"] in {"done", "failed"} or "error" in state:
                        break
                time.sleep(0.05)
            self.assertEqual(state.get("phase"), "done", state)
            self.assertEqual(state["completed"][-1]["output"], {"n": 9})
            self.assertEqual(requests[0]["model"], "ini-model")
            self.assertEqual(requests[0]["reasoning_effort"], "high")
            self.assertIn(AUTONOMY["ingenious"], requests[0]["messages"][0]["content"])
            status = self.cli("status", "--config", str(self.ini))
            self.assertEqual(json.loads(status.stdout)["phase"], "done")
            # Resume through the captured effective plan, without the source INI.
            resumed = self.cli("run", info["plan"], "--run-dir", info["run_dir"])
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(len(requests), 1)
            self.assertEqual(read_json(self.root / "plan.json"), plan)
        finally:
            try:
                os.kill(info["pid"], 15)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    unittest.main()
