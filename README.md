# scheduler

[中文](README.zh-CN.md) · [English](README.md) · [Français](README.fr.md)

A small Python package for unattended serial runs. A harness leaves a JSON execution plan and a revision prompt, starts the scheduler, and can then pause. The scheduler continues independently of the chat session.

Execute serial i → read results → ask the API whether a change is needed → keep the plan or revise pending command/task values → start the next step. An empty `updates` list means continue unchanged. There is no API call after the final step.

Supports macOS/Linux and Python 3.10+. Runtime dependencies are limited to the standard library. Keep the machine awake. This package does not resume a Codex chat: if a step needs code edits, the harness must provide a command or CLI capable of making those edits.

## Installation and INI configuration

```bash
git clone https://github.com/ShimingGu/scheduler.git
cd scheduler
python3 -m pip install -e .
```

If the package is inside another project’s `./scheduler` directory, run `python3 -m pip install -e ./scheduler` from that project. After installation, both `python3 -m scheduler` and `serial-scheduler` work from any working directory. No GUI is required.

Copy and edit [examples/scheduler.ini](examples/scheduler.ini):

```ini
[scheduler]
plan = plan.json
run_dir = runs/night-001
autonomy = faithful

[api]
key_file = /absolute/path/to/your/api-key.env
base_url = https://api.deepseek.com/v1
model = deepseek-flash
reasoning_effort = default
timeout = 120
max_tokens = 4096
```

Relative paths in the INI are resolved against the **INI directory**; relative cwd and key_file paths in a plan are resolved against the **plan directory**. Explicit CLI plan/run-dir arguments override the INI; INI API settings and autonomy override the plan. Each endpoint/model field falls back to the selected key file only when it has not been configured explicitly. Configuration parsing never executes shell code or expands environment-variable expressions.

Key files accept `.env` (`OPENAI_API_KEY`, `SCHEDULER_API_KEY`, `HF_TOKEN`, `DEEPSEEK_API_KEY`), JSON (`api_key`, optional `base_url`/`model`), or a plain key. The INI accepts a file reference, not a key value. Alternatively, replace `key_file` with `key_env = MY_API_KEY` and supply credentials through the environment. Keep real credentials and run artifacts out of version control.

```bash
# Detach and immediately return JSON: pid / run_dir / log / plan
python3 -m scheduler start --config /absolute/path/to/scheduler.ini

# Query status as JSON
python3 -m scheduler status --config /absolute/path/to/scheduler.ini

# List models and declared effort levels as JSON
python3 -m scheduler models --config /absolute/path/to/scheduler.ini

# Run in the foreground until completion; failures return a nonzero exit code
python3 -m scheduler run --config /absolute/path/to/scheduler.ini
```

`start` saves the effective configuration without key values and returns its path in the `plan` field. The worker reads this snapshot so INI overrides survive detachment. Key files must remain readable; environment credentials are inherited at launch. The original `run/start plan.json --run-dir ...` syntax is also supported.

## Direct harness invocation

The harness writes the plan JSON and INI, then invokes `start` once without interactive input. It can pause afterward:

```python
import json
import subprocess
import sys

launched = subprocess.run(
    [sys.executable, "-m", "scheduler", "start", "--config", "/path/to/scheduler.ini"],
    check=True, capture_output=True, text=True,
)
worker = json.loads(launched.stdout)
# Contains pid, run_dir, log and plan; the scheduler continues independently.
```

Successful `start` means a background process was created, not that the plan finished. Use `status`, state.json and logs to inspect progress. Give each independent run a distinct run_dir. Startup failures return a nonzero exit code and a JSON error on stderr, with no input or confirmation prompt.

## Clusters / Slurm

Install the package on the compute node, provide a readable key file, and ensure the node can reach the configured API. Use **foreground `run`** inside the allocation so the batch job lasts for the whole workflow:

```bash
sbatch examples/slurm.sh /absolute/path/to/scheduler.ini
```

[examples/slurm.sh](examples/slurm.sh) is a minimal template; add partition/account settings required by your cluster. Do not replace its foreground `run` with `start` and immediately exit the batch job. Other job systems can invoke the same `run --config ...` command.

## Judgment and reasoning effort

| autonomy | Decision policy |
| --- | --- |
| `faithful` | Make the smallest change required by explicit harness rules; otherwise continue. Default. |
| `mediocre` | Infer necessary routine corrections and execution details; avoid speculative optimization. |
| `ingenious` | Proactively improve the remaining plan using evidence, within harness goals and constraints. |

All modes prefer retaining a workable plan. They steer the model’s judgment; they are not operating-system permission boundaries.

`reasoning_effort` separately controls model reasoning. `default` omits the parameter for compatibility. Other values require model support and are never silently dropped after a provider rejection. `models` reports declared effort levels, or only default when metadata is absent. A listed model does not guarantee access or sufficient balance for the selected key. See [DeepSeek model metadata](https://api-docs.deepseek.com/api/list-models/), [effort parameters](https://api-docs.deepseek.com/api/create-chat-completion/) and [Hugging Face parameters](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion).

## Optional local GUI

```bash
python3 -m scheduler ui --port 8765
```

Open `http://127.0.0.1:8765/`. Use the top-right selector for **中文 / English / Français**. The interface remembers your choice and translates labels, notices, errors and status text. Switching languages preserves credentials, model selections and edited plans; original prompts, task data and protocol identifiers are kept intact.

Import key files, choose a model/effort/judgment mode, import a plan, and start the background run. The GUI binds only to loopback and validates a session token. Uploaded keys stay in UI memory and reach workers through environment variables, not plan files. Reimport keys after restarting the UI. Closing the page or UI service does not stop launched workers. GUI plans require an absolute cwd. Use `--run-root` to choose the run-record directory.

## What the harness must provide

See [examples/plan.json](examples/plan.json).

- `cwd`: the command working directory; CLI resolves relative paths against the plan directory.
- `api`: `base_url` (for example `https://api.deepseek.com/v1` or `https://router.huggingface.co/v1`), `model`, `key_env` (default `SCHEDULER_API_KEY`), and optional `key_file`, `reasoning_effort`, `timeout` in seconds and `max_tokens`. Only explicitly selected key files are read; no private files are auto-discovered.
- `steps`: an ordered list with unique `id` values, a `command` argv array and an optional `task` JSON object. Commands execute directly, without a shell.
- `revision_prompt`: **written by the harness**, specifying triggers, permitted changes and constraints. Prefer keeping the original plan; avoid vague instructions such as “improve the next tasks.” Each API request includes this prompt, the latest result and all pending steps.
- `step_timeout`: maximum command duration in seconds; default 86400.

Example rule: “Only increase the next step’s samples if the pilot recommended_samples exceeds it. Preserve other settings and commands. Otherwise return empty updates.”

A step reads its final task from `SCHEDULER_TASK_FILE` and writes JSON to `SCHEDULER_RESULT_FILE`; see [examples/worker.py](examples/worker.py). The scheduler reads after command exit, so an ordinary write is sufficient. Results are limited to 100 KB: keep summaries concise and reference full artifacts by path. Without a result JSON, the API receives the last 12 KB of stdout and stderr each; full logs stay on disk.

The model returns:

```json
{"reason": "No adjustment needed", "updates": []}
```

Or:

```json
{"reason": "Pilot requires more samples", "updates": [{"id": "main", "task": {"samples": 40}}]}
```

`task` and `command` are complete replacements, not partial merges. Unmentioned fields and steps remain unchanged. Multiple pending steps may change; adding, deleting, reordering or editing completed steps is forbidden. The model returns JSON, not directly executed prose. It cannot independently read arbitrary artifact files. Commands run with the current user’s permissions; define allowed scope in the prompt. Task output is sent to the configured API, so keep credentials out of summaries and logs.

## Taking over an already running serial i

Place only the unstarted steps in `steps`, then add:

```json
"handoff": {
  "id": "serial-i",
  "completion_file": "/absolute/path/unique-run/completion.json",
  "timeout": 86400,
  "poll_interval": 1
}
```

The current task or its wrapper must **atomically publish this file after success**:

```json
{"status": "completed", "result": {"metric": 0.82, "summary": "Current task result summary"}}
```

Use `scheduler.core.write_json` for atomic publication. The path must be unique to this run and initially absent. The scheduler waits for it, reads the result, reviews pending steps, then starts the next step. Publish `status: "failed"` on failure to stop the scheduler. The original background script must not also start pending steps: execution ownership transfers to the scheduler. A PID alone cannot reliably establish success or collect results, so handoff uses an explicit completion file.

## State and recovery

The run directory stores `state.json`, per-step tasks/results/logs and API decisions. Only one scheduler can own it. Do not edit the original plan during a run; revisions are stored in state.

API failures or invalid updates pause at `revising` before the next command. Fix the credentials/network, then invoke `run` again with the same effective plan/run directory to retry the decision without rerunning completed commands. A handoff timeout can also be retried.

Command failures/timeouts, or termination of the scheduler during command execution, require manual inspection. The scheduler never guesses whether side effects occurred and automatically replays a command. After inspection, create a new plan and run directory for remaining work. `status` shows the last checkpoint, not a live heartbeat; an externally killed process may still appear as `running`. Check its PID and logs.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Automated tests use temporary jobs, mock APIs and synthetic keys, without user credentials. A real API smoke test also verified that a pilot recommendation of 40 revised main.samples from 20 to 40 and the next step actually used 40. Online credentials and run records are excluded from the repository.
