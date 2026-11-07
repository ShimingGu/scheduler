"""Detach a worker from its initiating harness or configuration UI."""
import os
from pathlib import Path
import subprocess
import sys


def launch(plan_path, run_dir, env=None):
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    worker_env = dict(os.environ if env is None else env)
    worker_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + worker_env.get("PYTHONPATH", "")
    with (root / "worker.log").open("ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "scheduler", "run",
                                 str(Path(plan_path).resolve()), "--run-dir", str(root)],
                                env=worker_env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    return {"pid": proc.pid, "run_dir": str(root), "log": str(root / "worker.log")}
