"""Read user-owned credential files without executing shell code."""

import json
from pathlib import Path
import shlex


def parse_credentials(text):
    text = text.strip().lstrip("\ufeff")
    if text.startswith("{"):
        values = json.loads(text)
        if not isinstance(values, dict):
            raise ValueError("invalid credential file")
    elif "=" in text or "\n" in text:
        values = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, value = line.removeprefix("export ").partition("=")
            if sep:
                parts = shlex.split(value, comments=True)
                values[name.strip()] = " ".join(parts)
    else:
        values = {"api_key": text}
    key = next((values.get(name) for name in
                ("api_key", "SCHEDULER_API_KEY", "OPENAI_API_KEY", "HF_TOKEN", "DEEPSEEK_API_KEY")
                if values.get(name)), None)
    if not isinstance(key, str) or not key.strip():
        raise ValueError("credential file has no supported API key field")
    return {
        "key": key.strip(),
        "base_url": values.get("base_url") or values.get("OPENAI_BASE_URL") or values.get("AGENT_OPENAI_BASE_URL") or "",
        "model": values.get("model") or values.get("OPENAI_MODEL") or values.get("AGENT_OPENAI_MODEL") or "",
    }


def load_credentials(path):
    return parse_credentials(Path(path).expanduser().read_text(encoding="utf-8"))
