"""
Knowledge extraction from literature review results.

Converts raw :class:`LiteratureReviewResult` objects into structured
engineering insights, parameter ranges, and candidate research topics
ready for use by the :class:`PlanningEngine`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.research.literature_review import LiteratureReviewResult, Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class EngineeringInsight:
    """A distilled engineering insight extracted from one or more papers."""

    category: str  # e.g. "dynamics", "track_geometry", "probability"
    description: str
    supporting_papers: list[str] = field(default_factory=list)  # titles
    confidence: float = 0.5  # 0–1 based on number of supporting sources


@dataclass
class ParameterRange:
    """Physical parameter range inferred from the literature."""

    parameter: str
    unit: str
    min_val: float
    max_val: float
    typical_val: float
    source_count: int = 0


@dataclass
class KnowledgeBase:
    """Complete structured knowledge extracted from a literature review."""

    insights: list[EngineeringInsight] = field(default_factory=list)
    parameter_ranges: dict[str, ParameterRange] = field(default_factory=dict)
    research_gaps: list[str] = field(default_factory=list)
    candidate_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insights": [
                {
                    "category": i.category,
                    "description": i.description,
                    "supporting_papers": i.supporting_papers,
                    "confidence": i.confidence,
                }
                for i in self.insights
            ],
            "parameter_ranges": {
                k: {
                    "parameter": v.parameter,
                    "unit": v.unit,
                    "min": v.min_val,
                    "max": v.max_val,
                    "typical": v.typical_val,
                }
                for k, v in self.parameter_ranges.items()
            },
            "research_gaps": self.research_gaps,
            "candidate_topics": self.candidate_topics,
        }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

# Default physical parameter ranges based on published standards and
# engineering handbooks (used as fall-back when literature is sparse).
_DEFAULT_RANGES: dict[str, ParameterRange] = {
    "speed_kmh": ParameterRange("Train Speed", "km/h", 60.0, 350.0, 120.0),
    "axle_load_kN": ParameterRange("Axle Load", "kN", 80.0, 250.0, 160.0),
    "track_irregularity_mm": ParameterRange(
        "Track Irregularity Amplitude", "mm", 0.5, 20.0, 4.0
    ),
    "derailment_quotient": ParameterRange(
        "Nadal Derailment Quotient (Q/P)", "-", 0.0, 1.2, 0.8
    ),
    "wheel_flange_angle_deg": ParameterRange(
        "Wheel Flange Angle", "degrees", 60.0, 75.0, 70.0
    ),
    "friction_coefficient": ParameterRange(
        "Wheel-Rail Friction Coefficient", "-", 0.1, 0.5, 0.3
    ),
    "curve_radius_m": ParameterRange("Curve Radius", "m", 100.0, 10000.0, 500.0),
    "cant_deficiency_mm": ParameterRange("Cant Deficiency", "mm", 0.0, 150.0, 50.0),
}


class KnowledgeExtractor:
    """
    Extracts structured engineering knowledge from a
    :class:`LiteratureReviewResult`.

    Parameters
    ----------
    literature_result:
        Populated literature review output.
    """

    def __init__(self, literature_result: LiteratureReviewResult) -> None:
        self.result = literature_result

    def extract(self) -> KnowledgeBase:
        """Run the full extraction pipeline and return a :class:`KnowledgeBase`."""
        logger.info("Extracting knowledge from %d papers", len(self.result.papers))

        insights = self._extract_insights()
        parameter_ranges = self._extract_parameter_ranges()
        candidate_topics = self._generate_candidate_topics()

        return KnowledgeBase(
            insights=insights,
            parameter_ranges=parameter_ranges,
            research_gaps=self.result.research_gaps,
            candidate_topics=candidate_topics,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_insights(self) -> list[EngineeringInsight]:
        """Group papers by category and create aggregated insights."""
        category_map: dict[str, list[Paper]] = {
            "dynamics": [],
            "track_geometry": [],
            "probability": [],
            "simulation": [],
            "safety_standards": [],
        }

        keyword_to_category = {
            "dynamics": "dynamics",
            "bogie": "dynamics",
            "lateral stability": "dynamics",
            "vibration": "dynamics",
            "suspension": "dynamics",
            "track geometry": "track_geometry",
            "stiffness": "track_geometry",
            "irregularities": "track_geometry",
            "cant": "track_geometry",
            "probability": "probability",
            "Nadal": "probability",
            "derailment quotient": "probability",
            "flange": "probability",
            "simulation": "simulation",
            "multibody": "simulation",
            "model": "simulation",
            "safety": "safety_standards",
            "standard": "safety_standards",
        }

        for paper in self.result.papers:
            text = (paper.title + " " + paper.abstract).lower()
            assigned = False
            for kw, cat in keyword_to_category.items():
                if kw.lower() in text:
                    category_map[cat].append(paper)
                    assigned = True
                    break
            if not assigned:
                category_map["dynamics"].append(paper)

        insights: list[EngineeringInsight] = []
        for cat, papers in category_map.items():
            if not papers:
                continue
            description = _summarise_category(cat, papers)
            insights.append(
                EngineeringInsight(
                    category=cat,
                    description=description,
                    supporting_papers=[p.title for p in papers],
                    confidence=min(1.0, len(papers) / 5.0),
                )
            )
        return insights

    def _extract_parameter_ranges(self) -> dict[str, ParameterRange]:
        """Augment default parameter ranges with values found in abstracts."""
        ranges = dict(_DEFAULT_RANGES)
        all_text = " ".join(
            p.abstract for p in self.result.papers if p.abstract
        )

        # Try to refine speed range from numbers found near "km/h"
        speed_values = [
            float(m)
            for m in re.findall(r"(\d{2,3})\s*km/h", all_text)
            if 30 <= float(m) <= 400
        ]
        if len(speed_values) >= 2:
            ranges["speed_kmh"] = ParameterRange(
                "Train Speed",
                "km/h",
                min(speed_values),
                max(speed_values),
                sum(speed_values) / len(speed_values),
                source_count=len(speed_values),
            )

        return ranges

    def _generate_candidate_topics(self) -> list[str]:
        """Produce a ranked list of candidate research topics."""
        base_topics = self.result.recommended_topics or []
        gap_topics = [
            gap.split("Lack of")[-1].split("Limited")[-1].strip().capitalize()
            for gap in self.result.research_gaps
        ]
        fallback_topics = [
            "Derailment probability under combined speed and track irregularity",
            "Lateral stability of high-speed bogies on degraded track",
            "Machine-learning-enhanced derailment risk prediction",
            "Sensor fusion for real-time wheel-rail force monitoring",
        ]
        combined = base_topics + gap_topics + fallback_topics
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for t in combined:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[:8]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _summarise_category(category: str, papers: list[Paper]) -> str:
    """Generate a one-sentence summary for an insight category."""
    count = len(papers)
    titles_snippet = "; ".join(p.title[:60] for p in papers[:3])
    summaries = {
        "dynamics": (
            f"{count} source(s) address wheel-rail dynamics and vehicle stability "
            f"(e.g. {titles_snippet})."
        ),
        "track_geometry": (
            f"{count} source(s) examine track geometry defects and their effect "
            f"on derailment risk (e.g. {titles_snippet})."
        ),
        "probability": (
            f"{count} source(s) present probabilistic derailment models and "
            f"safety criteria (e.g. {titles_snippet})."
        ),
        "simulation": (
            f"{count} source(s) propose simulation frameworks for railway dynamics "
            f"(e.g. {titles_snippet})."
        ),
        "safety_standards": (
            f"{count} source(s) review safety standards and regulatory frameworks "
            f"(e.g. {titles_snippet})."
        ),
    }
    return summaries.get(category, f"{count} source(s) found for {category}.")
