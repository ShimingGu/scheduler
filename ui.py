"""Loopback-only configuration UI; uploaded keys remain in process memory."""
import copy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys

from .core import ChatAPI, Scheduler, SchedulerError, read_json, write_json
from .credentials import parse_credentials
from .launcher import launch
from .catalog import model_catalog


def demo_plan():
    worker = Path(__file__).resolve().parent / "examples" / "worker.py"
    return {"cwd": str(worker.parent), "autonomy": "faithful",
            "revision_prompt": "If latest_result.output.recommended_samples is greater than the next step task.samples, set ONLY that samples value to the recommendation. Keep its other fields and command unchanged. Otherwise return empty updates.",
            "steps": [{"id": "pilot", "command": [sys.executable, str(worker)], "task": {"samples": 10, "pilot": True}},
                      {"id": "main", "command": [sys.executable, str(worker)], "task": {"samples": 20}}]}


class Application:
    def __init__(self, run_root):
        self.root = Path(run_root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.profiles = {}
        self.runs = {}

    def dispatch(self, route, body):
        if route == "/api/import":
            try:
                credentials = parse_credentials(body["text"])
            except Exception:
                raise SchedulerError("无法解析 key 文件；支持 .env、JSON 或纯 key 文本") from None
            pid = secrets.token_hex(8)
            self.profiles[pid] = credentials
            return {"id": pid, "name": Path(body.get("name", "key file")).name,
                    "base_url": credentials["base_url"], "model": credentials["model"]}
        if route == "/api/default":
            return {"plan": demo_plan()}
        if route == "/api/status":
            rid = body["run"]
            if rid not in self.runs:
                raise SchedulerError("unknown run")
            info = self.runs[rid]
            path = Path(info["run_dir"]) / "state.json"
            state = read_json(path) if path.exists() else {"phase": "starting", "completed": [], "pending": []}
            return {"phase": state["phase"], "error": state.get("error"),
                    "completed": state["completed"], "pending": [s["id"] for s in state["pending"]], **info}
        profile = self.profiles.get(body.get("profile"))
        if profile is None:
            raise SchedulerError("请先导入 API key 文件")
        config = {"base_url": body["base_url"].strip(), "model": body["model"].strip(),
                  "reasoning_effort": body.get("reasoning_effort", "default"),
                  "key_env": "SCHEDULER_UI_API_KEY", "timeout": 120, "max_tokens": 4096}
        if route == "/api/models":
            return {"models": model_catalog(config, profile["key"])}
        if route == "/api/start":
            plan = copy.deepcopy(body["plan"])
            plan["api"] = config
            plan["autonomy"] = body["autonomy"]
            if not Path(plan.get("cwd", ".")).is_absolute():
                raise SchedulerError("请在计划 cwd 中填写绝对工作目录")
            rid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
            root = self.root / rid
            Scheduler(plan, root)
            ChatAPI(config, key=profile["key"], autonomy=plan["autonomy"])
            write_json(root / "plan.json", plan)
            env = dict(os.environ, SCHEDULER_UI_API_KEY=profile["key"])
            info = launch(root / "plan.json", root, env)
            self.runs[rid] = info
            return {"run": rid, **info}
        raise SchedulerError("unknown operation")


def make_server(port, app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log uploaded credentials or request bodies.

        def reply(self, code, data, content_type="application/json"):
            payload = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def local_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.local_host() or self.path != "/":
                self.reply(404, {"error": "not found"})
                return
            html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
            self.reply(200, html.replace("__SESSION_TOKEN__", app.token), "text/html")

        def do_POST(self):
            if not self.local_host() or not secrets.compare_digest(self.headers.get("X-Scheduler-Token", ""), app.token):
                self.reply(403, {"error": "invalid local session"})
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 1000000:
                    raise SchedulerError("request size must be within 1 MB")
                body = json.loads(self.rfile.read(size))
                self.reply(200, app.dispatch(self.path, body))
            except Exception as exc:
                message = str(exc) if isinstance(exc, SchedulerError) else "操作失败，请检查配置和文件格式"
                self.reply(400, {"error": message})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port, run_root):
    server = make_server(port, Application(run_root))
    print(f"Scheduler UI: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
