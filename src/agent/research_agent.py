"""
Main research agent: top-level orchestrator for the autonomous pipeline.

Wires together the research, planning, simulation, analysis, and paper-
generation components via the :class:`WorkflowController`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.agent.planning_engine import PlanningEngine, ResearchPlan
from src.agent.workflow_controller import PipelineReport, WorkflowController
from src.research.knowledge_extraction import KnowledgeBase, KnowledgeExtractor
from src.research.literature_review import LiteratureReviewResult, LiteratureReviewer
from src.research.tavily_client import TavilyClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ResearchAgent:
    """
    Autonomous research agent for railway derailment engineering.

    Parameters
    ----------
    output_dir:
        Root directory for all pipeline artefacts.
    tavily_api_key:
        Tavily API key (default: ``TAVILY_API_KEY`` env var).
    mock_research:
        If ``True``, skip real Tavily calls (useful for CI without API key).
    seed:
        Random seed passed to the planning engine.
    """

    def __init__(
        self,
        output_dir: str | Path = ".",
        tavily_api_key: str | None = None,
        mock_research: bool = False,
        seed: int = 42,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
        self.mock_research = mock_research
        self.seed = seed

        # Internal state – populated during execution
        self._literature: LiteratureReviewResult | None = None
        self._knowledge: KnowledgeBase | None = None
        self._plan: ResearchPlan | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> PipelineReport:
        """Execute the full autonomous research pipeline."""
        controller = WorkflowController(
            output_dir=self.output_dir, stop_on_failure=False
        )

        stages = [
            {
                "name": "literature_review",
                "fn": self._stage_literature_review,
                "critical": False,
            },
            {
                "name": "knowledge_extraction",
                "fn": self._stage_knowledge_extraction,
                "critical": False,
            },
            {
                "name": "research_planning",
                "fn": self._stage_research_planning,
                "critical": False,
            },
            {
                "name": "simulations",
                "fn": self._stage_simulations,
                "critical": False,
            },
            {
                "name": "analysis",
                "fn": self._stage_analysis,
                "critical": False,
            },
            {
                "name": "paper_generation",
                "fn": self._stage_paper_generation,
                "critical": False,
            },
        ]

        report = controller.run_pipeline(stages)
        self._save_report(report)
        return report

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _stage_literature_review(self) -> list[str]:
        """Stage 1: Discover and aggregate research papers via Tavily."""
        if self.mock_research or not self.tavily_api_key:
            logger.warning("Using mock literature review (no Tavily API key)")
            self._literature = _build_mock_literature()
        else:
            client = TavilyClient(api_key=self.tavily_api_key)
            reviewer = LiteratureReviewer(client)
            self._literature = reviewer.run()

        out_path = self.output_dir / "data" / "literature_review.json"
        self._literature.save(out_path)
        return [str(out_path)]

    def _stage_knowledge_extraction(self) -> list[str]:
        """Stage 2: Extract structured engineering knowledge from papers."""
        if self._literature is None:
            self._literature = _build_mock_literature()

        extractor = KnowledgeExtractor(self._literature)
        self._knowledge = extractor.extract()

        out_path = self.output_dir / "data" / "knowledge_base.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(self._knowledge.to_dict(), indent=2), encoding="utf-8"
        )
        logger.info("Knowledge base saved to %s", out_path)
        return [str(out_path)]

    def _stage_research_planning(self) -> list[str]:
        """Stage 3: Select best topic and formulate research questions."""
        if self._knowledge is None:
            from src.research.knowledge_extraction import KnowledgeBase

            self._knowledge = KnowledgeBase()

        engine = PlanningEngine(self._knowledge, seed=self.seed)
        self._plan = engine.generate_plan()

        out_path = self.output_dir / "data" / "research_plan.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(self._plan.to_dict(), indent=2), encoding="utf-8"
        )
        logger.info("Research plan: %s", self._plan.title)
        return [str(out_path)]

    def _stage_simulations(self) -> list[str]:
        """Stage 4: Execute physics simulations."""
        from src.simulations.scenario_runner import ScenarioRunner

        runner = ScenarioRunner(
            output_dir=self.output_dir / "data" / "simulation_results",
            seed=self.seed,
        )
        artifacts = runner.run_all()
        return artifacts

    def _stage_analysis(self) -> list[str]:
        """Stage 5: Compute metrics and generate figures."""
        from src.analysis.metrics import MetricsCalculator
        from src.analysis.visualization import Visualizer

        results_dir = self.output_dir / "data" / "simulation_results"
        figures_dir = self.output_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        calc = MetricsCalculator(results_dir)
        metrics = calc.compute_all()
        metrics_path = self.output_dir / "data" / "metrics.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        viz = Visualizer(results_dir=results_dir, figures_dir=figures_dir)
        figure_paths = viz.generate_all()
        return [str(metrics_path)] + figure_paths

    def _stage_paper_generation(self) -> list[str]:
        """Stage 6: Generate MIT-style research paper."""
        from src.paper.mit_paper_generator import MITPaperGenerator

        data_dir = self.output_dir / "data"
        figures_dir = self.output_dir / "figures"

        generator = MITPaperGenerator(
            data_dir=data_dir,
            figures_dir=figures_dir,
            output_dir=self.output_dir,
        )
        paper_path = generator.generate()
        return [str(paper_path)]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_report(self, report: PipelineReport) -> None:
        out_path = self.output_dir / "data" / "pipeline_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )
        logger.info("Pipeline report saved to %s", out_path)


# ---------------------------------------------------------------------------
# Mock data helpers (used when TAVILY_API_KEY is absent)
# ---------------------------------------------------------------------------


def _build_mock_literature() -> LiteratureReviewResult:
    """Return a minimal mock literature review for offline/CI use."""
    from src.research.literature_review import LiteratureReviewResult, Paper

    papers = [
        Paper(
            title="Wheel-Rail Interaction and Derailment Criteria",
            url="https://example.com/paper1",
            source="Vehicle System Dynamics",
            abstract=(
                "This study investigates the dynamic interaction between wheel and rail "
                "under varying speed (60–350 km/h) and load conditions. The Nadal "
                "criterion is validated against multibody simulation results."
            ),
            relevance_score=0.92,
            keywords=["wheel-rail", "Nadal", "dynamics", "derailment"],
            year="2022",
        ),
        Paper(
            title="Track Geometry Irregularities and Safety Limits",
            url="https://example.com/paper2",
            source="Railway Engineering Science",
            abstract=(
                "A probabilistic framework is developed to assess derailment risk "
                "caused by track geometry faults. Critical amplitude thresholds are "
                "derived for freight and passenger services."
            ),
            relevance_score=0.87,
            keywords=["track geometry", "probability", "safety", "irregularities"],
            year="2021",
        ),
        Paper(
            title="High-Speed Rail Bogie Dynamics Simulation",
            url="https://example.com/paper3",
            source="Multibody System Dynamics",
            abstract=(
                "Multibody simulation of a high-speed bogie at 300–350 km/h reveals "
                "critical hunting instability above 320 km/h on low-stiffness track."
            ),
            relevance_score=0.85,
            keywords=["bogie", "dynamics", "simulation", "high-speed"],
            year="2023",
        ),
        Paper(
            title="Santiago de Compostela Train Accident: Speed Excess and Curve "
                  "Negotiation Failure",
            url="https://example.com/paper4",
            source="Accident Analysis and Prevention",
            abstract=(
                "Post-accident investigation of the 2013 Santiago de Compostela "
                "derailment. The Alvia train entered a 80 km/h curve at 179 km/h, "
                "producing wheel-rail lateral forces far exceeding the Nadal limit. "
                "Analysis confirms that speed excess is the dominant derailment driver "
                "on curved track."
            ),
            relevance_score=0.84,
            keywords=["derailment", "speed", "curve", "accident", "case study"],
            year="2014",
        ),
        Paper(
            title="Hatfield Rail Crash: Track Degradation and Gauge-Corner Cracking",
            url="https://example.com/paper5",
            source="Engineering Failure Analysis",
            abstract=(
                "The Hatfield crash (2000) resulted from gauge-corner cracking that "
                "produced rail fragmentation under a 200 km/h passenger service. "
                "Track irregularity amplitudes at the failure site exceeded 8 mm, "
                "consistent with modelled critical thresholds for derailment probability."
            ),
            relevance_score=0.82,
            keywords=["track geometry", "derailment", "irregularities", "case study"],
            year="2001",
        ),
        Paper(
            title="Lac-Mégantic Derailment: Axle Load and Curve Speed Interaction",
            url="https://example.com/paper6",
            source="Safety Science",
            abstract=(
                "Investigation of the 2013 Lac-Mégantic freight train derailment. "
                "Heavy crude-oil tank cars with axle loads near 263 kN travelled "
                "at more than 100 km/h on a 65 km/h rated curve. The combined "
                "effect of high load and excessive speed is modelled using the "
                "Nadal probabilistic risk framework."
            ),
            relevance_score=0.80,
            keywords=["axle load", "derailment", "curve", "freight", "case study"],
            year="2014",
        ),
    ]
    return LiteratureReviewResult(
        papers=papers,
        research_gaps=[
            "Limited ML/AI application to derailment probability prediction",
            "Insufficient digital twin models for real-time track monitoring",
        ],
        key_findings=[
            "Derailment quotient exceeds Nadal limit at speeds above 280 km/h on curved "
            "track with combined amplitude > 8 mm",
            "Axle load above 200 kN significantly increases flange climb risk",
            "Real-world case studies confirm simulation predictions: speed excess and "
            "track irregularity above 8 mm are dominant derailment drivers",
        ],
        recommended_topics=[
            "derailment",
            "probability",
            "track geometry",
            "simulation",
        ],
    )
