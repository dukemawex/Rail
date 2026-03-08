"""
Research planning engine.

Given a :class:`KnowledgeBase`, the planning engine selects the best
research topic, formulates specific research questions, and allocates
simulation scenarios to each question.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

from src.research.knowledge_extraction import KnowledgeBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ResearchQuestion:
    """A well-defined research question with associated simulation plan."""

    id: str
    question: str
    hypothesis: str
    simulation_scenarios: list[str] = field(default_factory=list)
    priority: float = 0.5  # 0–1


@dataclass
class ResearchPlan:
    """Complete research plan for one pipeline run."""

    title: str
    objective: str
    questions: list[ResearchQuestion] = field(default_factory=list)
    selected_topic: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "objective": self.objective,
            "selected_topic": self.selected_topic,
            "rationale": self.rationale,
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "hypothesis": q.hypothesis,
                    "simulation_scenarios": q.simulation_scenarios,
                    "priority": q.priority,
                }
                for q in self.questions
            ],
        }


# ---------------------------------------------------------------------------
# Planning engine
# ---------------------------------------------------------------------------


class PlanningEngine:
    """
    Selects the most impactful research topic and formulates a structured
    :class:`ResearchPlan`.

    Parameters
    ----------
    knowledge_base:
        Populated :class:`KnowledgeBase` from the extraction phase.
    seed:
        Random seed for reproducible topic selection when scores are tied.
    """

    def __init__(self, knowledge_base: KnowledgeBase, seed: int = 42) -> None:
        self.kb = knowledge_base
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_plan(self) -> ResearchPlan:
        """Build and return a complete :class:`ResearchPlan`."""
        topic = self._select_topic()
        questions = self._formulate_questions(topic)
        return ResearchPlan(
            title=f"Autonomous Research: {topic}",
            objective=(
                f"Investigate '{topic}' through physics-based simulation and "
                "probabilistic modelling to improve railway safety standards."
            ),
            questions=questions,
            selected_topic=topic,
            rationale=self._build_rationale(topic),
        )

    def score_topics(self) -> list[tuple[str, float]]:
        """Return topics with heuristic priority scores (topic, score)."""
        topics = self.kb.candidate_topics or _DEFAULT_TOPICS
        scored = []
        for i, topic in enumerate(topics):
            score = _score_topic(topic, self.kb) - i * 0.05
            scored.append((topic, round(max(0.0, score), 3)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_topic(self) -> str:
        scored = self.score_topics()
        if not scored:
            return _DEFAULT_TOPICS[0]
        # Take the top-scored topic (tie-break with seed for reproducibility)
        best_score = scored[0][1]
        top_topics = [t for t, s in scored if s >= best_score - 0.01]
        return self.rng.choice(top_topics)

    def _build_rationale(self, topic: str) -> str:
        gap_count = len(self.kb.research_gaps)
        paper_count = len(self.kb.insights)
        return (
            f"Topic '{topic}' was selected because it directly addresses "
            f"{gap_count} identified research gap(s) and is supported by "
            f"{paper_count} insight cluster(s) in the literature review."
        )

    def _formulate_questions(self, topic: str) -> list[ResearchQuestion]:
        """Create a set of simulation-driven research questions for the topic."""
        params = self.kb.parameter_ranges

        speed_max = params.get("speed_kmh")
        speed_label = f"{speed_max.max_val:.0f} km/h" if speed_max else "350 km/h"

        load_max = params.get("axle_load_kN")
        load_label = f"{load_max.max_val:.0f} kN" if load_max else "250 kN"

        irr_max = params.get("track_irregularity_mm")
        irr_label = f"{irr_max.max_val:.0f} mm" if irr_max else "20 mm"

        return [
            ResearchQuestion(
                id="RQ1",
                question=(
                    f"How does train speed (up to {speed_label}) affect "
                    "derailment probability on curved track with moderate geometry defects?"
                ),
                hypothesis=(
                    "Derailment probability increases non-linearly with speed, "
                    "with a critical threshold above which the risk becomes unacceptable."
                ),
                simulation_scenarios=[
                    "speed_sweep_curved_track",
                    "speed_safety_margin",
                ],
                priority=0.9,
            ),
            ResearchQuestion(
                id="RQ2",
                question=(
                    f"What axle load (up to {load_label}) causes critical "
                    "Nadal quotient exceedance under combined geometry faults?"
                ),
                hypothesis=(
                    "There exists an axle-load threshold beyond which the combined "
                    "effect of load and geometry faults produces deterministic derailment."
                ),
                simulation_scenarios=[
                    "load_sweep_geometry_fault",
                    "combined_load_irregularity",
                ],
                priority=0.8,
            ),
            ResearchQuestion(
                id="RQ3",
                question=(
                    f"How do track irregularity amplitudes up to {irr_label} "
                    "compound with vehicle speed to affect lateral wheel force?"
                ),
                hypothesis=(
                    "Track irregularity amplitude and spatial frequency interact "
                    "resonantly with bogie natural frequency, producing peak lateral forces."
                ),
                simulation_scenarios=[
                    "irregularity_amplitude_sweep",
                    "frequency_resonance_analysis",
                ],
                priority=0.85,
            ),
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_TOPICS = [
    "Derailment probability under combined speed and track irregularity",
    "Lateral stability of high-speed bogies on degraded track",
    "Machine-learning-enhanced derailment risk prediction",
    "Effect of axle load on flange climb in sharp curves",
]


def _score_topic(topic: str, kb: KnowledgeBase) -> float:
    """Compute a heuristic relevance score for a research topic."""
    score = 0.5
    topic_lower = topic.lower()

    # Boost if topic addresses a known gap
    for gap in kb.research_gaps:
        gap_words = set(re.split(r"\W+", gap.lower()))
        topic_words = set(re.split(r"\W+", topic_lower))
        if len(gap_words & topic_words) >= 2:
            score += 0.2
            break

    # Boost if topic keywords appear in insights
    for insight in kb.insights:
        if any(kw in topic_lower for kw in insight.description.lower().split()):
            score += 0.05

    return min(1.0, score)
