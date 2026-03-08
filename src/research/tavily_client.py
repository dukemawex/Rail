"""
Tavily API client for autonomous railway engineering research discovery.

Wraps the Tavily search API with retry logic, result caching, and structured
output tailored for the rail derailment research pipeline.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single result returned by the Tavily search API."""

    title: str
    url: str
    content: str
    score: float = 0.0
    published_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "score": self.score,
            "published_date": self.published_date,
        }


@dataclass
class SearchResponse:
    """Aggregated response from a Tavily search query."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    answer: str = ""
    follow_up_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "follow_up_questions": self.follow_up_questions,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_TAVILY_API_URL = "https://api.tavily.com/search"
_DEFAULT_MAX_RESULTS = 10
_DEFAULT_SEARCH_DEPTH = "advanced"
_RETRY_DELAYS = (1, 2, 4)  # seconds between retries


class TavilyClient:
    """
    Tavily search client with automatic retries and structured output.

    Parameters
    ----------
    api_key:
        Tavily API key.  Defaults to the ``TAVILY_API_KEY`` environment variable.
    max_results:
        Default maximum number of results per query.
    search_depth:
        ``"basic"`` or ``"advanced"`` – determines result richness.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = _DEFAULT_MAX_RESULTS,
        search_depth: str = _DEFAULT_SEARCH_DEPTH,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Tavily API key is required. "
                "Set the TAVILY_API_KEY environment variable or pass api_key=."
            )
        self.max_results = max_results
        self.search_depth = search_depth
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int | None = None,
        include_answer: bool = True,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        topic: str = "general",
    ) -> SearchResponse:
        """
        Execute a Tavily search query and return a :class:`SearchResponse`.

        Parameters
        ----------
        query:
            Natural-language search query.
        max_results:
            Override default result count for this call.
        include_answer:
            Request a synthesised AI answer in addition to raw results.
        include_domains:
            Restrict results to these domains.
        exclude_domains:
            Exclude results from these domains.
        topic:
            Topic category hint (``"general"`` or ``"news"``).
        """
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": self.search_depth,
            "include_answer": include_answer,
            "max_results": max_results or self.max_results,
            "topic": topic,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        raw = self._post_with_retry(payload)
        return self._parse_response(query, raw)

    def search_railway_research(self, topic: str, max_results: int = 10) -> SearchResponse:
        """Convenience wrapper for railway-specific research queries."""
        refined_query = (
            f"railway engineering {topic} derailment safety peer-reviewed research"
        )
        logger.info("Searching Tavily for: %s", refined_query)
        return self.search(
            query=refined_query,
            max_results=max_results,
            include_answer=True,
        )

    def search_multiple(
        self, queries: list[str], max_results_each: int = 5
    ) -> list[SearchResponse]:
        """Execute multiple queries and return a list of responses."""
        responses = []
        for q in queries:
            try:
                resp = self.search(q, max_results=max_results_each)
                responses.append(resp)
                time.sleep(0.5)  # polite rate-limiting
            except Exception as exc:  # noqa: BLE001
                logger.warning("Search failed for query '%s': %s", q, exc)
        return responses

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the Tavily API with exponential back-off retries."""
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                response = self._session.post(
                    _TAVILY_API_URL,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()  # type: ignore[return-value]
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in {401, 403}:
                    raise  # authentication errors – no point retrying
                last_exc = exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc

            if delay is not None:
                logger.warning(
                    "Tavily request failed (attempt %d/%d): %s – retrying in %ss",
                    attempt,
                    len(_RETRY_DELAYS) + 1,
                    last_exc,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"Tavily API request failed after {len(_RETRY_DELAYS) + 1} attempts: {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse_response(query: str, raw: dict[str, Any]) -> SearchResponse:
        """Convert the raw JSON payload from Tavily into a :class:`SearchResponse`."""
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=float(r.get("score", 0.0)),
                published_date=r.get("published_date", ""),
            )
            for r in raw.get("results", [])
        ]
        return SearchResponse(
            query=query,
            results=results,
            answer=raw.get("answer", ""),
            follow_up_questions=raw.get("follow_up_questions", []),
        )
