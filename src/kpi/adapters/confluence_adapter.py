"""Confluence adapter — publish KPI pages."""
from __future__ import annotations
from typing import Any
import structlog
from atlassian import Confluence
from kpi.adapters.network import resolve_proxies, resolve_ssl
logger = structlog.get_logger()

class ConfluenceAdapter:
    def __init__(self, cfg: dict[str, Any]) -> None:
        c = cfg["confluence"]
        self._client = Confluence(url=c["url"], token=c["token"],
                                  verify_ssl=resolve_ssl(cfg), proxies=resolve_proxies())
        self._space = c["space_key"]
        self._parent = c["parent_page_title"]

    def publish(self, title: str, body: str) -> str:
        page = self._client.get_page_by_title(self._space, title)
        if page:
            self._client.update_page(page["id"], title, body, type="page", representation="storage")
            return page["id"]
        parent = self._client.get_page_by_title(self._space, self._parent)
        r = self._client.create_page(self._space, title, body,
                                     parent_id=parent["id"] if parent else None,
                                     type="page", representation="storage")
        return r.get("id", "?")
