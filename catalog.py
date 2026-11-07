"""Provider model discovery shared by CLI and optional local UI."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .core import SchedulerError


def model_catalog(config, key):
    base = config["base_url"].rstrip("/")
    url = urlparse(base)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}):
        raise SchedulerError("API endpoint must use HTTPS (or loopback HTTP)")
    request = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.load(response)["data"]
        result = []
        for row in rows:
            levels = row.get("effort", {}).get("supported_levels", [])
            result.append({"id": row["id"], "efforts": ["default", "none", *levels] if levels else ["default"],
                           "verified_efforts": bool(levels)})
        return result
    except urllib.error.HTTPError as exc:
        raise SchedulerError(f"Model listing HTTP {exc.code}") from None
    except Exception:
        raise SchedulerError("Could not read model catalog; you can enter a model manually") from None
