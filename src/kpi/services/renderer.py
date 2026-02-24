"""Report renderer — Jinja2 templates for preview and Confluence."""
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from kpi.domain.models import WeeklyReport

_TPL = Path(__file__).parent.parent / "templates"


def _pydantic_tojson(value, *args, **kwargs):
    """Custom tojson filter that handles Pydantic models and lists of models."""
    if isinstance(value, list):
        return json.dumps([v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value])
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(mode="json"))
    return json.dumps(value)


class ReportRenderer:
    def __init__(self) -> None:
        self._env = Environment(loader=FileSystemLoader(str(_TPL)), autoescape=False)
        self._env.filters["tojson"] = _pydantic_tojson

    def render_preview(self, r: WeeklyReport) -> str:
        return self._env.get_template("kpi_preview.html").render(r=r)

    def render_confluence(self, r: WeeklyReport) -> str:
        return self._env.get_template("kpi_confluence.html.j2").render(r=r)

    def build_title(self, r: WeeklyReport) -> str:
        name = r.project_name or "KPI"
        return f"{name} Hebdo - S{r.week_number:02d}/{r.year} - Sprint {r.sprint_number}"
