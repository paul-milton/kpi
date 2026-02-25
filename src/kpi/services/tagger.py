"""Semantic tagger — NLP-enhanced label suggestions for Jira stories.

Uses spaCy French model (fr_core_news_sm) for lemmatization when available,
falls back to accent stripping + suffix stemming otherwise.
All string/text fields of tickets are analyzed.
"""
from __future__ import annotations
import re, unicodedata
from difflib import SequenceMatcher
from typing import Any
import structlog
from kpi.domain.dimensions import flatten_taggable, parse_dimensions
from kpi.domain.models import DimensionNode, JiraStory, TagSuggestion
logger = structlog.get_logger()

# ── spaCy French model (optional, auto-download) ──
_HAS_NLP = False
_nlp = None
try:
    import spacy
    try:
        _nlp = spacy.load("fr_core_news_sm")
        _HAS_NLP = True
    except OSError:
        # Auto-download model (respects system proxy via env vars)
        import subprocess, sys, os
        logger.info("spacy_download", model="fr_core_news_sm")
        env = os.environ.copy()  # inherits HTTP_PROXY / HTTPS_PROXY
        try:
            subprocess.check_call(
                [sys.executable, "-m", "spacy", "download", "fr_core_news_sm"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _nlp = spacy.load("fr_core_news_sm")
            _HAS_NLP = True
            logger.info("spacy_downloaded_ok")
        except Exception as dl_err:
            logger.warning("spacy_download_failed", err=str(dl_err)[:80])
except ImportError:
    pass  # spacy not installed at all

# French suffixes for fallback stemming
_FR_SUFFIXES = [
    'isations', 'isation', 'ifications', 'ification',
    'ations', 'ation', 'ements', 'ement', 'ments', 'ment',
    'eurs', 'eur', 'euses', 'euse',
    'iques', 'ique', 'ibles', 'ible',
    'ités', 'ité', 'ages', 'age',
    'ances', 'ance', 'ences', 'ence',
    'ions', 'ion', 'ives', 'ive', 'eux',
    'elles', 'elle', 'aux', 'als', 'al',
]


def _strip_accents(text: str) -> str:
    """Remove French diacritics (e.g. e, c, e)."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )


def _stem_french(word: str) -> str:
    """Basic French suffix stripping (fallback when spaCy unavailable)."""
    w = word.lower()
    for suffix in _FR_SUFFIXES:
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)]
    if len(w) > 3 and w[-1] in 'sx':
        return w[:-1]
    return w


def _lemmatize(text: str) -> str:
    """Lemmatize French text using spaCy, or fallback to accent+stem."""
    if _HAS_NLP:
        doc = _nlp(text[:5000])
        return ' '.join(token.lemma_.lower() for token in doc if not token.is_punct)
    stripped = _strip_accents(text.lower())
    return ' '.join(_stem_french(w) for w in stripped.split())


def _fuzzy_score(needle: str, haystack: str) -> float:
    """Compute fuzzy match score (0.0-1.0) between keyword and text."""
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    n_clean = _strip_accents(needle.lower())
    h_clean = _strip_accents(haystack.lower())
    if n_clean in h_clean:
        return 0.95
    n_stem = _stem_french(n_clean)
    if len(n_stem) >= 4 and n_stem in h_clean:
        return 0.85
    if ' ' in needle:
        words = n_clean.split()
        matched = sum(1 for w in words if w in h_clean or _stem_french(w) in h_clean)
        return matched / len(words) * 0.9 if words else 0.0
    return SequenceMatcher(None, n_clean, h_clean).ratio() if len(n_clean) >= 4 else 0.0


# ── Conception detection signals ──
CONCEPTION_SIGNALS = {
    "fonctionnel": {
        "direct": [
            "conception fonctionnelle", "spécification fonctionnelle",
            "expression de besoin",
        ],
        "indirect": [
            "règle de gestion", "parcours utilisateur", "workflow métier",
            "processus métier", "cas d'usage", "use case",
            "circuit de validation", "formulaire", "écran",
            "cahier des charges", "recueil de besoin", "besoin métier",
            "scénario",
        ],
    },
    "technique": {
        "direct": [
            "conception technique", "spécification technique", "architecture",
        ],
        "indirect": [
            "modèle de données", "schéma", "diagramme", "API", "endpoint",
            "contrat d'interface", "flux de données", "migration",
            "modélisation", "base de données", "infrastructure",
            "protocole", "interface technique",
        ],
    },
}


class SemanticTagger:
    def __init__(self, cfg: dict[str, Any]) -> None:
        tree = parse_dimensions(cfg["dimensions"])
        self._all_labels = {n.label for n in flatten_taggable(tree)}
        self._entries = []
        for n in flatten_taggable(tree):
            lemmatized_kws = [_lemmatize(kw) for kw in n.keywords]
            self._entries.append({
                "label": n.label,
                "patterns": [(_compile(kw), kw) for kw in n.keywords],
                "keywords": n.keywords,
                "lemmatized_keywords": lemmatized_kws,
            })
        self._threshold = cfg["tagger"]["confidence_threshold"]
        self._max = cfg["tagger"]["max_labels_per_story"]
        if _HAS_NLP:
            logger.info("tagger_nlp_mode", engine="spacy", model="fr_core_news_sm")
        else:
            logger.info("tagger_fallback_mode", engine="stem+fuzzy")

    def suggest_labels(self, story: JiraStory) -> list[TagSuggestion]:
        raw_text = f"{story.summary} {story.summary} {story.description}"
        text = _norm(raw_text)
        lemma_text = _lemmatize(raw_text)
        existing = set(story.labels)
        out: list[TagSuggestion] = []
        for e in self._entries:
            if e["label"] in existing:
                continue
            # Phase 1: exact regex matching (high confidence)
            matched = [(kw, len(p.findall(text))) for p, kw in e["patterns"]]
            matched = [(kw, h) for kw, h in matched if h > 0]
            # Phase 2: lemma-based matching (spaCy or stemmed)
            lemma_matched = []
            if not matched:
                for kw, lkw in zip(e["keywords"], e["lemmatized_keywords"]):
                    if lkw and len(lkw) >= 3 and lkw in lemma_text:
                        lemma_matched.append(kw)
            # Phase 3: fuzzy matching as last resort
            fuzzy_matched = []
            if not matched and not lemma_matched:
                for kw in e["keywords"]:
                    fs = _fuzzy_score(kw, text)
                    if fs >= 0.75:
                        fuzzy_matched.append((kw, fs))
            if not matched and not lemma_matched and not fuzzy_matched:
                continue
            # Score
            if matched:
                score = min(0.45 + (len(matched)-1)*0.10 + sum(h-1 for _, h in matched)*0.04, 1.0)
                reason = ", ".join(kw for kw, _ in matched)
            elif lemma_matched:
                score = min(0.40 + (len(lemma_matched)-1)*0.08, 0.90)
                reason = "~ " + ", ".join(lemma_matched)
            else:
                best_fuzzy = max(fs for _, fs in fuzzy_matched)
                score = min(0.35 + best_fuzzy * 0.3 + (len(fuzzy_matched)-1)*0.05, 0.80)
                reason = "~~ " + ", ".join(kw for kw, _ in fuzzy_matched)
            if score >= self._threshold:
                out.append(TagSuggestion(story_key=story.key, story_summary=story.summary,
                    label=e["label"], confidence=score, reason=reason))
        out.sort(key=lambda s: s.confidence, reverse=True)
        return out[:self._max]

    def suggest_all(self, stories: list[JiraStory]) -> list[TagSuggestion]:
        return [s for st in stories for s in self.suggest_labels(st)]

    def suggest_conception(self, story: JiraStory) -> list[TagSuggestion]:
        """Detect stories needing design work and suggest conception labels.

        Returns suggestions for: conception (parent), fonctionnel, technique, tests.
        A story tagged fonctionnel also gets tests automatically.
        """
        raw_text = f"{story.summary} {story.summary} {story.description}"
        text = _norm(raw_text)
        lemma_text = _lemmatize(raw_text)
        existing = set(story.labels)
        results: list[TagSuggestion] = []
        matched_dims: list[str] = []

        for dim, signals in CONCEPTION_SIGNALS.items():
            if dim in existing:
                continue
            matched_kws = []
            score = 0.0
            # Direct signals — high confidence
            for kw in signals["direct"]:
                fs = _fuzzy_score(kw, text)
                if fs >= 0.75:
                    matched_kws.append(kw)
                    score = max(score, 0.7 + fs * 0.2)
                else:
                    lkw = _lemmatize(kw)
                    if lkw and len(lkw) >= 3 and lkw in lemma_text:
                        matched_kws.append(kw)
                        score = max(score, 0.65)
            # Indirect signals — moderate confidence
            for kw in signals["indirect"]:
                fs = _fuzzy_score(kw, text)
                if fs >= 0.75:
                    matched_kws.append(kw)
                    score = max(score, 0.45 + fs * 0.15)
                else:
                    lkw = _lemmatize(kw)
                    if lkw and len(lkw) >= 3 and lkw in lemma_text:
                        matched_kws.append(kw)
                        score = max(score, 0.40)
            # Bonus for multiple matches
            if len(matched_kws) > 1:
                score = min(score + (len(matched_kws) - 1) * 0.05, 1.0)

            if matched_kws and score >= self._threshold:
                matched_dims.append(dim)
                results.append(TagSuggestion(
                    story_key=story.key, story_summary=story.summary,
                    label=dim, confidence=round(score, 2),
                    reason=", ".join(matched_kws),
                ))

        if not matched_dims:
            return []

        # Add parent label 'conception' if not already present
        if "conception" not in existing:
            best_score = max(r.confidence for r in results)
            results.insert(0, TagSuggestion(
                story_key=story.key, story_summary=story.summary,
                label="conception", confidence=best_score,
                reason="parent: " + ", ".join(matched_dims),
            ))

        # Auto-add 'tests' when fonctionnel is suggested
        if "fonctionnel" in matched_dims and "tests" not in existing:
            fonc_sug = next(r for r in results if r.label == "fonctionnel")
            results.append(TagSuggestion(
                story_key=story.key, story_summary=story.summary,
                label="tests", confidence=fonc_sug.confidence,
                reason="auto: fonctionnel → tests",
            ))

        return results

    def suggest_conception_all(self, stories: list[JiraStory]) -> list[TagSuggestion]:
        """Run conception detection on all stories."""
        return [s for st in stories for s in self.suggest_conception(st)]

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
