import copy
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
from unittest.mock import patch

from scheduler.core import ChatAPI, Scheduler, SchedulerError, apply_updates, read_json, write_json


WORKER = """import os,json,pathlib
t=json.loads(pathlib.Path(os.environ['SCHEDULER_TASK_FILE']).read_text())
pathlib.Path(os.environ['SCHEDULER_RESULT_FILE']).write_text(json.dumps({'used':t['n']}))
"""


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {"cwd": str(self.root), "revision_prompt": "Increase n when required.",
                     "api": {"base_url": "https://example.invalid/v1", "model": "test"},
                     "steps": [{"id": name, "command": [sys.executable, "-c", WORKER],
                                "task": {"n": n}} for name, n in [("a", 1), ("b", 2), ("c", 3)]]}

    def runner(self, decide, plan=None):
        return Scheduler(plan or self.plan, self.root / "run", decide)

    def test_revision_is_consumed_and_noop_continues(self):
        seen = []

        def decide(context):
            seen.append(copy.deepcopy(context))
            if context["latest_result"]["id"] == "a":
                return {"reason": "pilot requires more", "updates": [{"id": "b", "task": {"n": 8}}]}
            return {"reason": "continue unchanged", "updates": []}

        state = self.runner(decide).run()
        self.assertEqual(state["phase"], "done")
        self.assertEqual([r["output"]["used"] for r in state["completed"]], [1, 8, 3])
        self.assertEqual(len(seen), 2)  # No call after the final step.
        self.assertEqual(seen[0]["instruction"], self.plan["revision_prompt"])
        self.assertEqual(self.runner(lambda _: self.fail("completed run called API")).run(), state)

    def test_bad_api_response_pauses_before_next_command_and_resumes(self):
        with self.assertRaises(SchedulerError):
            self.runner(lambda _: {"reason": "bad", "updates": [{"id": "a", "task": {}}]}).run()
        state = read_json(self.root / "run/state.json")
        self.assertEqual(state["phase"], "revising")
        self.assertEqual([x["id"] for x in state["completed"]], ["a"])
        self.assertFalse((self.root / "run/step-0001").exists())
        final = self.runner(lambda _: {"reason": "continue", "updates": []}).run()
        self.assertEqual([x["output"]["used"] for x in final["completed"]], [1, 2, 3])

    def test_failed_step_stops_without_api_or_next_step(self):
        plan = copy.deepcopy(self.plan)
        plan["steps"][0]["command"] = [sys.executable, "-c", "raise SystemExit(7)"]
        with self.assertRaises(SchedulerError):
            self.runner(lambda _: self.fail("failed step called API"), plan).run()
        self.assertEqual(read_json(self.root / "run/state.json")["phase"], "failed")
        with self.assertRaises(SchedulerError):
            self.runner(lambda _: {}, plan).run()

    def test_handoff_result_revises_first_pending_step(self):
        plan = copy.deepcopy(self.plan)
        plan["steps"] = plan["steps"][:1]
        plan["handoff"] = {"id": "already-started", "completion_file": "complete.json", "timeout": 1}
        write_json(self.root / "complete.json", {"status": "completed", "result": {"recommended": 9}})

        def decide(context):
            self.assertEqual(context["latest_result"]["output"]["recommended"], 9)
            return {"reason": "use pilot result", "updates": [{"id": "a", "task": {"n": 9}}]}

        state = self.runner(decide, plan).run()
        self.assertEqual(state["completed"][1]["output"]["used"], 9)

    def test_interrupted_execution_never_replays(self):
        root = self.root / "run"
        write_json(root / "state.json", {"plan": self.plan, "phase": "running", "pending": self.plan["steps"], "completed": []})
        with self.assertRaises(SchedulerError):
            self.runner(lambda _: {}).run()
        self.assertFalse((root / "step-0000").exists())

    def test_api_protocol_and_no_key_disclosure(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps({"choices": [{"message": {"content": '{"reason":"ok","updates":[]}'}}]}).encode()

        with patch.dict(os.environ, {"SCHEDULER_API_KEY": "synthetic-test-value"}):
            client = ChatAPI(self.plan["api"])
        with patch("urllib.request.urlopen", return_value=Response()) as transport:
            self.assertEqual(client({"pending": []})["updates"], [])
            request = transport.call_args.args[0]
            self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
            self.assertEqual(json.loads(request.data)["model"], "test")
        with patch("urllib.request.urlopen", side_effect=ValueError("synthetic-test-value")):
            with self.assertRaises(SchedulerError) as error:
                client({})
            self.assertNotIn("synthetic-test-value", str(error.exception))

    def test_updates_reject_command_and_unknown_ids(self):
        for update in ({"id": "x", "task": {}}, {"id": "b", "command": "shell string"}):
            with self.assertRaises(SchedulerError):
                apply_updates(self.plan["steps"], {"reason": "test", "updates": [update]})

    def test_cli_runs_without_live_chat(self):
        # A one-step run needs configured API credentials, but no boundary API call.
        plan = copy.deepcopy(self.plan)
        plan["steps"] = plan["steps"][:1]
        write_json(self.root / "plan.json", plan)
        env = dict(os.environ, SCHEDULER_API_KEY="synthetic-test-value", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-m", "scheduler", "run", str(self.root / "plan.json"),
                                 "--run-dir", str(self.root / "run")], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["phase"], "done")

    def test_detached_worker_revises_then_finishes_after_launcher_exits(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(payload)
                content = json.dumps({"reason": "adjust next task", "updates": [{"id": "b", "task": {"n": 12}}]})
                data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        plan = copy.deepcopy(self.plan)
        plan["steps"] = plan["steps"][:2]
        plan["api"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
        write_json(self.root / "plan.json", plan)
        env = dict(os.environ, SCHEDULER_API_KEY="synthetic-test-value", PYTHONDONTWRITEBYTECODE="1")
        launcher = subprocess.run([sys.executable, "-m", "scheduler", "start", str(self.root / "plan.json"),
                                   "--run-dir", str(self.root / "run")], env=env, capture_output=True, text=True)
        self.assertEqual(launcher.returncode, 0, launcher.stderr)
        pid = json.loads(launcher.stdout)["pid"]
        deadline = time.monotonic() + 10
        state = {}
        try:
            while time.monotonic() < deadline:
                if (self.root / "run/state.json").exists():
                    state = read_json(self.root / "run/state.json")
                    if state["phase"] in {"done", "failed"} or "error" in state:
                        break
                time.sleep(0.05)
            self.assertEqual(state.get("phase"), "done", state)
            self.assertEqual([r["output"]["used"] for r in state["completed"]], [1, 12])
            self.assertEqual(len(calls), 1)
        finally:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    unittest.main()
