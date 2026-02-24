"""Dimension tree parser. Max depth: 3 levels."""
from __future__ import annotations
from typing import Any
from kpi.domain.models import DimensionNode

MAX_DEPTH = 3

def parse_dimensions(config_list: list[dict[str, Any]]) -> list[DimensionNode]:
    """Parse config 'dimensions' list into DimensionNode tree."""
    return [_parse_node(d, 0) for d in config_list]

def flatten_taggable(roots: list[DimensionNode]) -> list[DimensionNode]:
    """Collect all nodes that have keywords."""
    out: list[DimensionNode] = []
    def _walk(nodes):
        for n in nodes:
            if n.is_taggable: out.append(n)
            _walk(n.children)
    _walk(roots)
    return out

def flatten_all(roots: list[DimensionNode]) -> list[DimensionNode]:
    """Collect all nodes depth-first."""
    out: list[DimensionNode] = []
    def _walk(nodes):
        for n in nodes:
            out.append(n)
            _walk(n.children)
    _walk(roots)
    return out

def _parse_node(cfg: dict[str, Any], depth: int) -> DimensionNode:
    node = DimensionNode(label=cfg["label"], display=cfg.get("display", cfg["label"]),
                         keywords=cfg.get("keywords", []), depth=depth)
    if depth < MAX_DEPTH - 1:
        for c in cfg.get("children", []):
            node.children.append(_parse_node(c, depth + 1))
    return node
