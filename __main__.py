import argparse
import hashlib
import json
from pathlib import Path
import sys

from .core import ChatAPI, Scheduler, SchedulerError, read_json, write_json
from .config import absolute_path, load_ini, merge_api
from .launcher import launch


def main():
    parser = argparse.ArgumentParser(description="Unattended adaptive serial runner")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "start"):
        p = sub.add_parser(action)
        p.add_argument("plan", type=Path, nargs="?")
        p.add_argument("--config", type=Path, help="INI file (all paths relative to this file)")
        p.add_argument("--run-dir", type=Path)
    status = sub.add_parser("status")
    status.add_argument("--config", type=Path)
    status.add_argument("--run-dir", type=Path)
    models = sub.add_parser("models", help="List models and declared effort levels as JSON")
    models.add_argument("--config", type=Path, required=True)
    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--run-root", type=Path, default=Path("scheduler/runs"))
    args = parser.parse_args()
    try:
        if args.action == "ui":
            from .ui import serve
            serve(args.port, args.run_root)
            return 0
        settings, api_overrides = load_ini(args.config) if args.config else ({}, {})
        if args.action == "models":
            from .catalog import model_catalog
            api = merge_api({}, api_overrides)
            client = ChatAPI({**api, "model": api.get("model") or "catalog"})
            print(json.dumps({"models": model_catalog(api, client.key)}, ensure_ascii=False))
            return 0
        run_dir = args.run_dir or settings.get("run_dir")
        if not run_dir:
            parser.error("provide --run-dir or [scheduler] run_dir in --config")
        if args.action == "status":
            state = read_json(Path(run_dir) / "state.json")
            print(json.dumps({"phase": state["phase"], "current": state.get("current"),
                              "completed": [s["id"] for s in state["completed"]],
                              "pending": [s["id"] for s in state["pending"]],
                              "error": state.get("error")}, ensure_ascii=False, indent=2))
            return 0
        plan_path = args.plan or settings.get("plan")
        if not plan_path:
            parser.error("provide a plan path or [scheduler] plan in --config")
        plan_path = Path(plan_path).expanduser().resolve()
        plan = read_json(plan_path)
        # cwd is relative to the plan file, never the background launch directory.
        plan["cwd"] = str((plan_path.parent / plan.get("cwd", ".")).resolve())
        if plan.get("api", {}).get("key_file"):
            plan["api"]["key_file"] = str(absolute_path(plan["api"]["key_file"], plan_path.parent))
        plan["api"] = merge_api(plan.get("api", {}), api_overrides)
        if settings.get("autonomy"):
            plan["autonomy"] = settings["autonomy"]
        runner = Scheduler(plan, run_dir)
        if args.action == "run":
            state = runner.run()
            print(json.dumps({"phase": state["phase"], "completed": len(state["completed"])}))
        else:
            ChatAPI(plan["api"], autonomy=plan.get("autonomy", "faithful"))
            # Freeze the effective config so the worker does not lose INI overrides
            # or depend on the harness keeping its source files unchanged.
            digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:16]
            snapshot = Path(run_dir).resolve() / f"plan-{digest}.json"
            write_json(snapshot, plan)
            print(json.dumps({**launch(snapshot, run_dir), "plan": str(snapshot)}))
        return 0
    except (SchedulerError, OSError, ValueError, KeyError, TypeError) as exc:
        # Do not echo arbitrary file or provider content to the terminal.
        print(json.dumps({"error": str(exc) if isinstance(exc, SchedulerError) else type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
