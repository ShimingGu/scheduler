"""A task reads its revised config and writes a concise result for the scheduler."""
import json
import os
from pathlib import Path

task = json.loads(Path(os.environ["SCHEDULER_TASK_FILE"]).read_text())
result = {"samples_used": task["samples"]}
if task.get("pilot"):
    result["recommended_samples"] = 40
Path(os.environ["SCHEDULER_RESULT_FILE"]).write_text(json.dumps(result))
print(json.dumps(result))
