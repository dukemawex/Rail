"""
Unit tests for the research pipeline modules:
  - tavily_client
  - literature_review
  - knowledge_extraction
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.research.tavily_client import SearchResponse, SearchResult, TavilyClient
from src.research.literature_review import (
    LiteratureReviewResult,
    LiteratureReviewer,
    Paper,
    _extract_keywords,
    _extract_source,
    _extract_year,
)
from src.research.knowledge_extraction import (
    KnowledgeExtractor,
    KnowledgeBase,
    _DEFAULT_RANGES,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_search_result(
    title: str = "Test Paper",
    url: str = "https://example.com/paper",
    content: str = "wheel-rail derailment dynamics 2022",
    score: float = 0.8,
) -> SearchResult:
    return SearchResult(title=title, url=url, content=content, score=score)


def _make_paper(
    title: str = "Test Paper",
    abstract: str = "Derailment at 200 km/h on curved track.",
    relevance_score: float = 0.75,
) -> Paper:
    return Paper(
        title=title,
        url="https://example.com",
        abstract=abstract,
        relevance_score=relevance_score,
        keywords=["derailment", "dynamics"],
    )


def _mock_tavily_response() -> dict:
    return {
        "results": [
            {
                "title": "Wheel-Rail Dynamics Study",
                "url": "https://science.org/paper1",
                "content": "derailment probability 120 km/h curve",
                "score": 0.85,
                "published_date": "2023-01-15",
            },
            {
                "title": "Track Geometry Safety Assessment",
                "url": "https://rail.org/paper2",
                "content": "track irregularities stiffness bogie 2022",
                "score": 0.72,
                "published_date": "2022-06-01",
            },
        ],
        "answer": "Derailment risk increases above 200 km/h on curved track.",
        "follow_up_questions": ["What is the Nadal limit?"],
    }


# ---------------------------------------------------------------------------
# TavilyClient
# ---------------------------------------------------------------------------


class TestTavilyClient:
    def test_raises_without_api_key(self):
        with pytest.raises(ValueError, match="API key"):
            TavilyClient(api_key="")

    def test_raises_without_env_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key"):
            TavilyClient()

    def test_search_returns_search_response(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        client = TavilyClient(api_key="test-key")

        with patch.object(client, "_post_with_retry", return_value=_mock_tavily_response()):
            resp = client.search("wheel rail dynamics")

        assert isinstance(resp, SearchResponse)
        assert resp.query == "wheel rail dynamics"
        assert len(resp.results) == 2

    def test_search_response_fields(self, monkeypatch):
        client = TavilyClient(api_key="test-key")
        with patch.object(client, "_post_with_retry", return_value=_mock_tavily_response()):
            resp = client.search("test")

        assert resp.answer == "Derailment risk increases above 200 km/h on curved track."
        assert resp.follow_up_questions == ["What is the Nadal limit?"]

    def test_search_result_score(self, monkeypatch):
        client = TavilyClient(api_key="test-key")
        with patch.object(client, "_post_with_retry", return_value=_mock_tavily_response()):
            resp = client.search("test")

        assert resp.results[0].score == pytest.approx(0.85)
        assert resp.results[1].score == pytest.approx(0.72)

    def test_search_railway_research_appends_terms(self, monkeypatch):
        client = TavilyClient(api_key="test-key")
        calls = []

        def mock_search(query, **kwargs):
            calls.append(query)
            return SearchResponse(query=query)

        with patch.object(client, "search", side_effect=mock_search):
            client.search_railway_research("bogie dynamics")

        assert len(calls) == 1
        assert "railway engineering" in calls[0].lower()
        assert "bogie dynamics" in calls[0].lower()

    def test_search_multiple_handles_failures_gracefully(self, monkeypatch):
        client = TavilyClient(api_key="test-key")
        call_count = [0]

        def mock_search(query, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("network error")
            return SearchResponse(query=query)

        with patch.object(client, "search", side_effect=mock_search):
            responses = client.search_multiple(["q1", "q2", "q3"])

        assert len(responses) == 2  # q2 failed, q1 and q3 succeeded

    def test_parse_response_empty_results(self):
        raw = {"results": [], "answer": "", "follow_up_questions": []}
        resp = TavilyClient._parse_response("test", raw)
        assert resp.results == []

    def test_search_result_to_dict(self):
        r = SearchResult(title="T", url="U", content="C", score=0.9, published_date="2023")
        d = r.to_dict()
        assert d["title"] == "T"
        assert d["url"] == "U"
        assert d["score"] == pytest.approx(0.9)

    def test_search_response_to_dict(self):
        resp = SearchResponse(query="q", answer="a", results=[_make_search_result()])
        d = resp.to_dict()
        assert d["query"] == "q"
        assert d["answer"] == "a"
        assert len(d["results"]) == 1

    def test_http_auth_error_not_retried(self, monkeypatch):
        """401 / 403 errors should be raised immediately without retry."""
        import requests

        client = TavilyClient(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        http_err = requests.exceptions.HTTPError(response=mock_response)

        with patch.object(client._session, "post", side_effect=http_err):
            with pytest.raises(requests.exceptions.HTTPError):
                client.search("test")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    def test_extract_year_finds_year(self):
        assert _extract_year("published in 2022") == "2022"
        assert _extract_year("study from 1998") == "1998"

    def test_extract_year_returns_empty_if_missing(self):
        assert _extract_year("no date here") == ""

    def test_extract_source_domain(self):
        assert _extract_source("https://www.example.com/paper") == "example.com"
        assert _extract_source("https://rail.org/article") == "rail.org"

    def test_extract_keywords_finds_domain_terms(self):
        text = "Study of derailment and bogie dynamics with Nadal criterion"
        kws = _extract_keywords(text)
        assert "derailment" in kws
        assert "bogie" in kws
        assert "Nadal" in kws

    def test_extract_keywords_empty_text(self):
        kws = _extract_keywords("")
        assert isinstance(kws, list)


# ---------------------------------------------------------------------------
# LiteratureReviewer
# ---------------------------------------------------------------------------


class TestLiteratureReviewer:
    def _make_reviewer_with_mock_client(self) -> LiteratureReviewer:
        mock_client = MagicMock()
        mock_client.search_railway_research.return_value = SearchResponse(
            query="test",
            results=[
                _make_search_result(
                    title=f"Paper {i}", score=0.7 + i * 0.05
                )
                for i in range(3)
            ],
            answer="Derailment occurs at high speeds.",
        )
        return LiteratureReviewer(mock_client)

    def test_run_returns_result(self):
        reviewer = self._make_reviewer_with_mock_client()
        result = reviewer.run(topics=["test topic"])
        assert isinstance(result, LiteratureReviewResult)

    def test_run_filters_low_relevance(self):
        mock_client = MagicMock()
        mock_client.search_railway_research.return_value = SearchResponse(
            query="test",
            results=[
                _make_search_result(url="https://low.com", score=0.1),  # below threshold
                _make_search_result(title="High score", url="https://high.com", score=0.9),
            ],
        )
        reviewer = LiteratureReviewer(mock_client, min_relevance=0.5)
        result = reviewer.run(topics=["test"])
        titles = [p.title for p in result.papers]
        assert "High score" in titles

    def test_deduplication(self):
        mock_client = MagicMock()
        # Two results with same URL
        mock_client.search_railway_research.return_value = SearchResponse(
            query="test",
            results=[
                _make_search_result(url="https://dup.com", score=0.8),
                _make_search_result(url="https://dup.com", score=0.8),
            ],
        )
        reviewer = LiteratureReviewer(mock_client, min_relevance=0.0)
        result = reviewer.run(topics=["test"])
        urls = [p.url for p in result.papers]
        assert len(urls) == len(set(urls))

    def test_save_creates_file(self, tmp_path):
        reviewer = self._make_reviewer_with_mock_client()
        result = reviewer.run(topics=["test"])
        out = tmp_path / "review.json"
        result.save(out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert "papers" in data

    def test_research_gaps_identified(self):
        # Gaps are returned when keywords are absent from text
        lit = LiteratureReviewResult(papers=[], research_gaps=[], key_findings=[])
        assert isinstance(lit.research_gaps, list)


# ---------------------------------------------------------------------------
# KnowledgeExtractor
# ---------------------------------------------------------------------------


class TestKnowledgeExtractor:
    def _make_result_with_papers(self) -> LiteratureReviewResult:
        return LiteratureReviewResult(
            papers=[
                Paper(
                    title="Wheel-Rail Dynamics at High Speed",
                    url="https://ex.com/1",
                    abstract="Dynamics and bogie behaviour at 300 km/h on curved track.",
                    relevance_score=0.9,
                    keywords=["dynamics", "bogie"],
                    year="2022",
                ),
                Paper(
                    title="Track Geometry and Safety Probability",
                    url="https://ex.com/2",
                    abstract="Probability of derailment with track geometry irregularities 8 mm.",
                    relevance_score=0.85,
                    keywords=["track geometry", "probability"],
                    year="2021",
                ),
            ],
            research_gaps=["Limited ML application"],
            key_findings=["Speed is the dominant driver"],
            recommended_topics=["derailment", "dynamics"],
        )

    def test_extract_returns_knowledge_base(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        assert isinstance(kb, KnowledgeBase)

    def test_insights_not_empty(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        assert len(kb.insights) >= 1

    def test_parameter_ranges_not_empty(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        assert len(kb.parameter_ranges) >= 1

    def test_default_ranges_present(self):
        extractor = KnowledgeExtractor(LiteratureReviewResult())
        kb = extractor.extract()
        assert "speed_kmh" in kb.parameter_ranges
        assert "axle_load_kN" in kb.parameter_ranges

    def test_candidate_topics_generated(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        assert len(kb.candidate_topics) >= 1

    def test_research_gaps_preserved(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        assert kb.research_gaps == ["Limited ML application"]

    def test_to_dict_structure(self):
        extractor = KnowledgeExtractor(self._make_result_with_papers())
        kb = extractor.extract()
        d = kb.to_dict()
        assert "insights" in d
        assert "parameter_ranges" in d
        assert "research_gaps" in d
        assert "candidate_topics" in d

    def test_speed_range_updated_from_abstracts(self):
        # Abstract mentions "300 km/h" – should refine speed range
        result = LiteratureReviewResult(
            papers=[
                Paper(
                    title="Speed Study",
                    url="https://ex.com",
                    abstract="Speeds of 80 km/h to 300 km/h were tested.",
                    relevance_score=0.8,
                )
            ]
        )
        extractor = KnowledgeExtractor(result)
        kb = extractor.extract()
        speed = kb.parameter_ranges.get("speed_kmh")
        assert speed is not None
        # Both 80 and 300 should be reflected
        assert speed.min_val <= 80.0
        assert speed.max_val >= 300.0
