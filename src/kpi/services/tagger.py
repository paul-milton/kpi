"""Semantic tagger — suggest single-word labels for stories."""
from __future__ import annotations
import re
from typing import Any
import structlog
from kpi.domain.dimensions import flatten_taggable, parse_dimensions
from kpi.domain.models import DimensionNode, JiraStory, TagSuggestion
logger = structlog.get_logger()

class SemanticTagger:
    def __init__(self, cfg: dict[str, Any]) -> None:
        tree = parse_dimensions(cfg["dimensions"])
        self._all_labels = {n.label for n in flatten_taggable(tree)}
        self._entries = [{"label": n.label,
                          "patterns": [(_compile(kw), kw) for kw in n.keywords]}
                         for n in flatten_taggable(tree)]
        self._threshold = cfg["tagger"]["confidence_threshold"]
        self._max = cfg["tagger"]["max_labels_per_story"]

    def suggest_labels(self, story: JiraStory) -> list[TagSuggestion]:
        text = _norm(f"{story.summary} {story.summary} {story.description}")
        existing = set(story.labels)
        out: list[TagSuggestion] = []
        for e in self._entries:
            if e["label"] in existing: continue
            matched = [(kw, len(p.findall(text))) for p, kw in e["patterns"]]
            matched = [(kw, h) for kw, h in matched if h > 0]
            if not matched: continue
            score = min(0.45 + (len(matched)-1)*0.10 + sum(h-1 for _,h in matched)*0.04, 1.0)
            if score >= self._threshold:
                out.append(TagSuggestion(story_key=story.key, story_summary=story.summary,
                    label=e["label"], confidence=score,
                    reason=", ".join(kw for kw, _ in matched)))
        out.sort(key=lambda s: s.confidence, reverse=True)
        return out[:self._max]

    def suggest_all(self, stories: list[JiraStory]) -> list[TagSuggestion]:
        return [s for st in stories for s in self.suggest_labels(st)]

    def find_untagged(self, stories: list[JiraStory]) -> list[JiraStory]:
        return [s for s in stories
                if not (set(s.labels) & self._all_labels) and not self.suggest_labels(s)]

def _compile(kw: str) -> re.Pattern:
    e = re.escape(kw)
    return re.compile(rf"\b{e}\b", re.I) if len(kw) <= 4 and " " not in kw else re.compile(e, re.I)

def _norm(text: str) -> str:
    if not text: return ""
    text = re.sub(r"\{[^}]+\}", " ", text)
    text = re.sub(r"\[[^]]*\|([^]]*)\]", r"\1", text)
    return text.lower().replace("\n", " ").strip()
