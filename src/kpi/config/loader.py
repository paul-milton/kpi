"""Configuration loader — merges YAML + env."""
from pathlib import Path
from typing import Any
import yaml
from decouple import config as env_config
_DEFAULT = Path(__file__).parent.parent.parent.parent / "config.yaml"
def load_config(path: Path | None = None) -> dict[str, Any]:
    with open(path or _DEFAULT, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["jira"]["url"] = env_config("JIRA_URL")
    cfg["jira"]["token"] = env_config("JIRA_TOKEN")
    cfg["jira"]["project_key"] = env_config("JIRA_PROJECT_KEY", default=cfg["jira"].get("project_key", "KPI"))
    cfg["confluence"]["url"] = env_config("CONFLUENCE_URL")
    cfg["confluence"]["token"] = env_config("CONFLUENCE_TOKEN")
    cfg["ssl_verify"] = env_config("SSL_VERIFY", default="true")
    cfg.setdefault("project", {})
    cfg["project"]["name"] = env_config("PROJECT_NAME", default=cfg["project"].get("name", ""))
    return cfg
