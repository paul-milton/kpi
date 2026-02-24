"""Network utilities — SSL and proxy resolution."""
import os, urllib3
from typing import Any

def resolve_ssl(cfg: dict[str, Any]) -> bool | str:
    val = str(cfg.get("ssl_verify", os.environ.get("SSL_VERIFY", "true"))).lower().strip()
    if val == "false":
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    return True if val == "true" else val

def resolve_proxies() -> dict[str, str] | None:
    h = os.environ.get("HTTPS_PROXY"); p = os.environ.get("HTTP_PROXY")
    return {"https": h or p, "http": p or h} if h or p else None
