"""Report renderer — Jinja2 templates for preview and Confluence."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from kpi.domain.models import WeeklyReport

_TPL = Path(__file__).parent.parent / "templates"

class ReportRenderer:
    def __init__(self) -> None:
        self._env = Environment(loader=FileSystemLoader(str(_TPL)), autoescape=False)

    def render_preview(self, r: WeeklyReport) -> str:
        return self._env.get_template("kpi_preview.html").render(r=r)

    def render_confluence(self, r: WeeklyReport) -> str:
        return self._env.get_template("kpi_confluence.html.j2").render(r=r)

    def build_title(self, r: WeeklyReport) -> str:
        return f"KPI Hebdo - S{r.week_number:02d}/{r.year} - Sprint {r.sprint_number}"
