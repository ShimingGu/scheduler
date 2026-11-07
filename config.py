"""Non-interactive INI configuration for harnesses and cluster jobs."""
import configparser
from pathlib import Path

from .core import SchedulerError
from .credentials import load_credentials


def absolute_path(value, base):
    return (base / Path(value).expanduser()).resolve()


def load_ini(path):
    path = Path(path).expanduser().resolve()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except Exception:
        raise SchedulerError("cannot read INI configuration") from None
    allowed = {
        "scheduler": {"plan", "run_dir", "autonomy"},
        "api": {"key_file", "key_env", "base_url", "model", "reasoning_effort", "timeout", "max_tokens"},
    }
    if parser.defaults() or set(parser.sections()) - allowed.keys():
        raise SchedulerError("INI supports only [scheduler] and [api], without DEFAULT values")
    for section in parser.sections():
        if set(parser[section]) - allowed[section]:
            raise SchedulerError("unsupported INI field; use api.key_file or key_env for credentials")
    scheduler = dict(parser["scheduler"]) if parser.has_section("scheduler") else {}
    api = dict(parser["api"]) if parser.has_section("api") else {}
    for name in ("plan", "run_dir"):
        if scheduler.get(name):
            scheduler[name] = absolute_path(scheduler[name], path.parent)
    if api.get("key_file"):
        api["key_file"] = str(absolute_path(api["key_file"], path.parent))
    if api.get("key_file") and api.get("key_env"):
        raise SchedulerError("choose either key_file or key_env in INI")
    for name in ("timeout", "max_tokens"):
        if name in api:
            try:
                api[name] = int(api[name])
                if api[name] <= 0:
                    raise ValueError()
            except ValueError:
                raise SchedulerError("INI timeout/max_tokens must be positive integers") from None
    return scheduler, api


def merge_api(original, overrides):
    result = dict(original)
    # Selecting an environment key explicitly overrides a plan's key file, and vice versa.
    if overrides.get("key_env"):
        result.pop("key_file", None)
    if overrides.get("key_file"):
        result.pop("key_env", None)
    result.update(overrides)
    if result.get("key_file"):
        try:
            credentials = load_credentials(result["key_file"])
        except Exception:
            raise SchedulerError("cannot read API key file") from None
        for name in ("base_url", "model"):
            if not result.get(name):
                result[name] = credentials[name]
    return result
