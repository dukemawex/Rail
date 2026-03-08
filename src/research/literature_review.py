"""
Automated literature review pipeline for railway derailment research.

Uses the :class:`TavilyClient` to discover papers, extract structured
metadata, deduplicate sources, and identify research gaps.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.research.tavily_client import SearchResponse, SearchResult, TavilyClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Predefined search topics for railway derailment research
# ---------------------------------------------------------------------------

RAILWAY_RESEARCH_TOPICS = [
    "wheel rail contact mechanics derailment",
    "track geometry irregularities safety assessment",
    "derailment probability modeling statistical analysis",
    "high-speed rail dynamics simulation",
    "railway bogie dynamics lateral stability",
    "flange climb derailment mechanism",
    "Nadal criterion derailment quotient",
    "track stiffness variation derailment risk",
    "railway vehicle dynamics multibody simulation",
    "train speed safety limits curve negotiation",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Paper:
    """Structured representation of a research paper or report."""

    title: str
    url: str
    abstract: str
    source: str = ""
    year: str = ""
    relevance_score: float = 0.0
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "abstract": self.abstract,
            "source": self.source,
            "year": self.year,
            "relevance_score": self.relevance_score,
            "keywords": self.keywords,
        }


@dataclass
class LiteratureReviewResult:
    """Aggregated output of the literature review pipeline."""

    papers: list[Paper] = field(default_factory=list)
    research_gaps: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    recommended_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_papers": len(self.papers),
            "papers": [p.to_dict() for p in self.papers],
            "research_gaps": self.research_gaps,
            "key_findings": self.key_findings,
            "recommended_topics": self.recommended_topics,
        }

    def save(self, path: str | Path) -> None:
        """Persist the review to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        logger.info("Literature review saved to %s", path)


# ---------------------------------------------------------------------------
# Review pipeline
# ---------------------------------------------------------------------------


class LiteratureReviewer:
    """
    Orchestrates multi-topic Tavily searches and synthesises the results
    into a :class:`LiteratureReviewResult`.

    Parameters
    ----------
    tavily_client:
        Authenticated :class:`TavilyClient` instance.
    max_papers:
        Maximum number of unique papers to retain.
    min_relevance:
        Papers with relevance score below this value are discarded.
    """

    def __init__(
        self,
        tavily_client: TavilyClient,
        max_papers: int = 50,
        min_relevance: float = 0.3,
    ) -> None:
        self.client = tavily_client
        self.max_papers = max_papers
        self.min_relevance = min_relevance

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self, topics: list[str] | None = None, max_results_per_topic: int = 5
    ) -> LiteratureReviewResult:
        """
        Execute the full literature review.

        Parameters
        ----------
        topics:
            List of search topics.  Defaults to :data:`RAILWAY_RESEARCH_TOPICS`.
        max_results_per_topic:
            Maximum Tavily results per topic query.
        """
        topics = topics or RAILWAY_RESEARCH_TOPICS
        logger.info("Starting literature review for %d topics", len(topics))

        all_results: list[SearchResult] = []
        answers: list[str] = []

        for topic in topics:
            try:
                resp: SearchResponse = self.client.search_railway_research(
                    topic, max_results=max_results_per_topic
                )
                all_results.extend(resp.results)
                if resp.answer:
                    answers.append(resp.answer)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Search failed for topic '%s': %s", topic, exc)

        papers = self._build_papers(all_results)
        papers = self._deduplicate(papers)
        papers = self._filter_and_rank(papers)
        papers = papers[: self.max_papers]

        return LiteratureReviewResult(
            papers=papers,
            research_gaps=self._identify_gaps(papers, answers),
            key_findings=self._extract_key_findings(answers),
            recommended_topics=self._recommend_topics(papers),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_papers(results: list[SearchResult]) -> list[Paper]:
        papers = []
        for r in results:
            year = _extract_year(r.content + " " + r.published_date)
            keywords = _extract_keywords(r.title + " " + r.content)
            papers.append(
                Paper(
                    title=r.title,
                    url=r.url,
                    abstract=r.content[:600],
                    source=_extract_source(r.url),
                    year=year,
                    relevance_score=r.score,
                    keywords=keywords,
                )
            )
        return papers

    def _deduplicate(self, papers: list[Paper]) -> list[Paper]:
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        unique = []
        for p in papers:
            key = p.url or p.title.lower().strip()
            title_key = re.sub(r"\s+", " ", p.title.lower().strip())
            if key not in seen_urls and title_key not in seen_titles:
                seen_urls.add(key)
                seen_titles.add(title_key)
                unique.append(p)
        return unique

    def _filter_and_rank(self, papers: list[Paper]) -> list[Paper]:
        filtered = [p for p in papers if p.relevance_score >= self.min_relevance]
        return sorted(filtered, key=lambda p: p.relevance_score, reverse=True)

    @staticmethod
    def _identify_gaps(papers: list[Paper], answers: list[str]) -> list[str]:
        """Heuristic gap identification based on keyword absence."""
        all_text = " ".join(p.title + " " + p.abstract for p in papers).lower()
        all_text += " " + " ".join(answers).lower()

        candidate_gaps = [
            (
                "machine learning",
                "Limited ML/AI application to derailment probability prediction",
            ),
            (
                "digital twin",
                "Insufficient digital twin models for real-time track monitoring",
            ),
            (
                "climate",
                "Lack of climate-change impact studies on track geometry",
            ),
            (
                "sensor fusion",
                "Limited sensor-fusion approaches for early derailment warning",
            ),
            (
                "mixed traffic",
                "Sparse research on derailment risk in mixed-speed traffic corridors",
            ),
            (
                "autonomous",
                "Emerging need for autonomous inspection system validation frameworks",
            ),
        ]
        return [msg for keyword, msg in candidate_gaps if keyword not in all_text]

    @staticmethod
    def _extract_key_findings(answers: list[str]) -> list[str]:
        """Return a deduplicated list of key sentences from AI-generated answers."""
        findings: list[str] = []
        seen: set[str] = set()
        for answer in answers:
            for sentence in re.split(r"[.!?]", answer):
                sentence = sentence.strip()
                if len(sentence) > 40 and sentence not in seen:
                    findings.append(sentence)
                    seen.add(sentence)
                    if len(findings) >= 10:
                        return findings
        return findings

    @staticmethod
    def _recommend_topics(papers: list[Paper]) -> list[str]:
        """Derive recommended follow-up topics from the most-cited keywords."""
        from collections import Counter

        kw_counts: Counter[str] = Counter()
        for p in papers:
            kw_counts.update(p.keywords)
        return [kw for kw, _ in kw_counts.most_common(5)]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _extract_year(text: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    return match.group() if match else ""


def _extract_source(url: str) -> str:
    """Return a clean domain name from a URL."""
    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else url


def _extract_keywords(text: str) -> list[str]:
    """Simple keyword extractor based on railway domain terms."""
    domain_terms = [
        "derailment",
        "wheel-rail",
        "track geometry",
        "dynamics",
        "bogie",
        "lateral stability",
        "simulation",
        "Nadal",
        "flange",
        "creep",
        "suspension",
        "vibration",
        "stiffness",
        "safety",
        "probability",
        "speed",
        "load",
    ]
    text_lower = text.lower()
    return [term for term in domain_terms if term.lower() in text_lower]
