# scheduler

给无人值守的 serial run 使用的独立 Python 小包。harness 留下 JSON 执行计划和修正 prompt，启动 scheduler 后可以暂停；后续执行不依赖聊天继续回复。

流程：执行 serial i → 读取结果 → 按 harness prompt 调 API 判断 → 无需修改则直接继续，需要修改则更新尚未执行的 command/task → 执行下一项。最后一项结束后不再调 API。API 返回空 `updates` 就是“按原计划继续”。

当前实现支持 macOS/Linux、Python 3.10+，运行时仅依赖标准库。机器需要保持开机和唤醒。它不会唤醒 Codex 聊天；需要代码修改时，harness 应把可执行的修改入口安排为步骤，或让步骤本身运行能完成该工作的 CLI。

## 安装与 INI 配置

支持 macOS/Linux、Python 3.10+，运行时不需要第三方库或 GUI。

```bash
git clone https://github.com/ShimingGu/scheduler.git
cd scheduler
python3 -m pip install -e .
```

如从其他项目中的 `./scheduler` 目录使用，可在那个项目中执行 `python3 -m pip install -e ./scheduler`。安装后，`python3 -m scheduler` 和 `serial-scheduler` 都可在任意工作目录使用。

复制并编辑 [examples/scheduler.ini](examples/scheduler.ini)：

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

INI 内相对路径以 **INI 所在目录** 为基准；plan 内的相对 cwd 和 key_file 以 **plan 所在目录** 为基准。CLI 显式提供的 plan/run-dir 优先于 INI；INI 的 API 配置和 autonomy 优先于 plan。endpoint/model 如果都未配置，才从所选 key 文件读取。配置解析不执行 shell，也不展开环境变量表达式。

key 文件支持 `.env`（`OPENAI_API_KEY`、`SCHEDULER_API_KEY`、`HF_TOKEN`、`DEEPSEEK_API_KEY`）、JSON（`api_key`、可选 `base_url`/`model`）或纯 key 文本。INI 只引用文件路径，不接受 key 值；也可将 `key_file` 替换为 `key_env = MY_API_KEY`，由外部环境提供凭证。不要把实际凭证或运行产物提交到仓库。

```bash
# 后台接管，立即返回 JSON：pid / run_dir / log / plan
python3 -m scheduler start --config /absolute/path/to/scheduler.ini

# 查询状态，返回 JSON
python3 -m scheduler status --config /absolute/path/to/scheduler.ini

# 查询所配置服务的模型与声明的推理强度，返回 JSON
python3 -m scheduler models --config /absolute/path/to/scheduler.ini

# 前台执行，直到全部完成；失败返回非零退出码
python3 -m scheduler run --config /absolute/path/to/scheduler.ini
```

`start` 会保存不含 key 值的最终配置快照，并将其路径放在返回 JSON 的 `plan` 字段中。后台 worker 读取这份快照，确保 INI 中的覆盖配置不会丢失。运行时 key 文件仍需要可读；环境变量 key 则由启动进程继承。原有 `run/start plan.json --run-dir ...` 用法也继续支持。

## harness 直接调用

harness 只需写出 plan JSON 和 INI，然后执行一次 `start`，无交互输入，之后可以暂停：

```python
import json
import subprocess
import sys

launched = subprocess.run(
    [sys.executable, "-m", "scheduler", "start", "--config", "/path/to/scheduler.ini"],
    check=True, capture_output=True, text=True,
)
worker = json.loads(launched.stdout)
# worker 包含 pid、run_dir、log、plan；scheduler 独立推进后续任务。
```

`start` 成功只表示已创建后台进程，后续执行结果通过 `status`、state.json 和日志查询。每次独立运行使用不同 run_dir。启动失败返回非零退出码及 stderr JSON 错误，不会要求输入或确认。

## cluster / Slurm

在计算节点安装 package、准备好可读的 key 文件，并确保节点能访问所配置的 API。在作业分配中运行 **前台 `run`**，让集群作业生命周期覆盖全部任务：

```bash
sbatch examples/slurm.sh /absolute/path/to/scheduler.ini
```

[examples/slurm.sh](examples/slurm.sh) 是最小模板；按集群实际要求添加 partition/account 等配置。脚本使用前台 `run`，不要改成 `start` 后立刻退出批作业。非 Slurm 环境可让其作业系统直接执行同样的 `run --config ...` 命令。

## 判断能力与推理强度

| autonomy | 判断边界 |
| --- | --- |
| `faithful` | 只根据 harness 明确写出的规则做最小修正；未触发规则则继续。默认档。 |
| `mediocre` | 推断必要的常规调整、解决执行细节，避免推测性优化。 |
| `ingenious` | 主动寻找有证据支持的更优后续方案，仍遵守 harness 的目标和限制。 |

三个模式都优先保留可行的原计划。它们控制模型判断策略，不是操作系统权限隔离。

`reasoning_effort` 独立控制模型推理强度。`default` 不发送该参数，兼容性最好；其他值须所选模型支持，不会在服务拒绝后悄悄忽略。`models` 命令显示服务声明的档位，缺少元数据时仅返回 default。模型列表不保证当前 key 有调用权限或足够余额。参见 [DeepSeek 模型元数据](https://api-docs.deepseek.com/api/list-models/)、[推理强度参数](https://api-docs.deepseek.com/api/create-chat-completion/)、[Hugging Face 参数说明](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion)。

## 可选本地 GUI

```bash
python3 -m scheduler ui --port 8765
```

打开 `http://127.0.0.1:8765/`，导入 key 文件、选择模型/强度/判断档位、导入计划，再启动后台任务。GUI 只绑定本机回环地址，有会话 token 校验。上传的 key 仅存于 UI 内存，启动时通过环境变量传给 worker，不写入计划；重启 UI 需重新导入。关闭页面或 UI 服务不会停止已启动的 worker。GUI 的计划 cwd 必须是绝对路径。`--run-root` 可指定运行记录目录。

## harness 必须留下什么

参见 [examples/plan.json](examples/plan.json)。

- `cwd`：各命令的工作目录，CLI 按 plan 文件所在目录解析相对路径。
- `api`：`base_url`（如 `https://api.deepseek.com/v1` 或 `https://router.huggingface.co/v1`）、`model`、`key_env`（默认 `SCHEDULER_API_KEY`），可选 `key_file`、`reasoning_effort`、`timeout` 秒、`max_tokens`。只读取用户明确指定的 key 文件，不自动扫描本仓库的私有 `.env`。
- `steps`：有序任务列表，每项有唯一 `id`、`command` 参数数组和可选 `task` JSON 对象。参数数组直接执行，不经过 shell。
- `revision_prompt`：**由 harness 写明**如何根据结果判断是否需要修改、允许修改哪些字段、触发条件和保留约束。优先保持原计划；不要只写“请改进后续任务”。API 每次接收这个 prompt、最新结果和当前全部待执行任务。
- `step_timeout`：每个命令的最大执行秒数，默认 86400。

例如：“只有 pilot 的 recommended_samples 大于下一项 samples 时，提高下一项 samples；保留其他配置和命令。否则返回空 updates。”

步骤通过 `SCHEDULER_TASK_FILE` 环境变量读取自己的最终 task，通过 `SCHEDULER_RESULT_FILE` 指向的路径写结果 JSON。见 [examples/worker.py](examples/worker.py)。scheduler 在命令退出后读取结果，因此普通写入即可。结果限 100 KB，适合摘要；完整实验产物保存在任务工作目录中，在摘要中写明其路径。没有结果 JSON 时，会把 stdout/stderr 各最后 12 KB 交给 API，完整日志仍保留。

模型返回格式：

```json
{"reason": "无需调整，继续原计划", "updates": []}
```

或：

```json
{"reason": "pilot 要求增加样本数", "updates": [{"id": "main", "task": {"samples": 40}}]}
```

`task` 和 `command` 都是完整替换，不做局部 merge；未提及的步骤/字段保持原值。可以修改多个后续步骤，不能增加、删除、重排步骤或修改已完成项。模型只返回 JSON；scheduler 不会直接执行模型返回的自然语言或自行读取任意产物文件。命令具有当前用户权限，harness 应在 prompt 中明确允许的调整范围。任务输出会发送给所配置的 API，请保持摘要和日志不含凭证。

## 接手已经在后台运行的 serial i

如果 harness 已经启动了当前任务，把后续未执行任务放进 `steps`，再添加：

```json
"handoff": {
  "id": "serial-i",
  "completion_file": "/absolute/path/unique-run/completion.json",
  "timeout": 86400,
  "poll_interval": 1
}
```

当前任务或它的 wrapper 必须在**成功完成后**原子写入该文件：

```json
{"status": "completed", "result": {"metric": 0.82, "summary": "当前任务结果摘要"}}
```

可使用 `scheduler.core.write_json` 原子发布。该路径应为本次运行独有，启动前不存在。scheduler 等待它出现，读结果后先修正 `steps`，再启动下一项。失败时写 `status: "failed"`，scheduler 会停止。不要让原后台脚本同时启动这些后续任务；后续任务的执行权交给 scheduler。单凭一个任意 PID 无法可靠判断成功或收集结果，所以接手模式使用明确的完成文件。

## 状态与恢复

run-dir 保存 `state.json`、每一步的 task/result/log 和每次 API 的 decision。一个目录只允许一个 scheduler 执行。计划运行期间不要编辑原始 plan；后续修改由 scheduler 保存在 state 中。

API 失败或返回非法修改时，停在 `revising`，下一项不会启动；修复配置或网络后，使用相同 plan/run-dir 再次 `run` 即可重试判断，已完成命令不会重跑。等待完成文件超时也可以重新 `run`。

命令失败/超时，或 scheduler 在执行命令时异常终止，会停止并要求人工检查。不会猜测命令是否已经产生副作用并自动重跑；确认后用剩余步骤建立新计划和新的 run-dir。`status` 显示最后保存的状态，并非实时进程心跳；如果进程被外部杀死，可能仍显示 `running`，应结合 PID 和日志排查。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

自动化测试使用临时任务、模拟 API 和合成 key，不读取用户凭证。本包不包含仓库里的 DeepSeek/GLM 配置。

已完成一次真实 API smoke test：pilot 建议 40，模型将 main 的 samples 从 20 调整为 40，main 实际使用 40 并完成。在线凭证与运行记录不随仓库发布。
