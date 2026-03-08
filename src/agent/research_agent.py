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
from src.research.literature_review import (
    REGIONAL_SEARCH_TOPICS,
    RAILWAY_RESEARCH_TOPICS,
    LiteratureReviewResult,
    LiteratureReviewer,
)
from src.research.tavily_client import TavilyClient

logger = logging.getLogger(__name__)

#: Accepted region identifiers (lower-case).
VALID_REGIONS: frozenset[str] = frozenset(
    ["africa", "europe", "asia", "north_america", "south_america", "global"]
)

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
    region:
        Geographic region of focus.  Must be one of ``africa``, ``europe``,
        ``asia``, ``north_america``, ``south_america``, or ``global``
        (default).
    """

    def __init__(
        self,
        output_dir: str | Path = ".",
        tavily_api_key: str | None = None,
        mock_research: bool = False,
        seed: int = 42,
        region: str = "global",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
        self.mock_research = mock_research
        self.seed = seed
        self.region = region.lower() if region.lower() in VALID_REGIONS else "global"

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
            self._literature = _build_mock_literature(region=self.region)
        else:
            client = TavilyClient(api_key=self.tavily_api_key)
            reviewer = LiteratureReviewer(client)
            # Combine base topics with region-specific supplementary topics
            topics = RAILWAY_RESEARCH_TOPICS + REGIONAL_SEARCH_TOPICS.get(
                self.region, []
            )
            self._literature = reviewer.run(topics=topics)

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
            region=self.region,
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


def _build_mock_literature(region: str = "global") -> LiteratureReviewResult:
    """Return a minimal mock literature review for offline/CI use.

    Parameters
    ----------
    region:
        Geographic region of focus.  Determines which case-study papers are
        appended to the core paper set.
    """
    from src.research.literature_review import LiteratureReviewResult, Paper

    # ------------------------------------------------------------------
    # Core papers (region-independent)
    # ------------------------------------------------------------------
    core_papers = [
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
    ]

    # ------------------------------------------------------------------
    # Region-specific case-study papers
    # ------------------------------------------------------------------
    _REGIONAL_PAPERS: dict[str, list[Paper]] = {
        "europe": [
            Paper(
                title="Santiago de Compostela Train Accident: Speed Excess and Curve "
                      "Negotiation Failure",
                url="https://example.com/eu_paper1",
                source="Accident Analysis and Prevention",
                abstract=(
                    "Post-accident investigation of the 2013 Santiago de Compostela "
                    "derailment. The Alvia train entered a 80 km/h curve at 179 km/h, "
                    "producing wheel-rail lateral forces far exceeding the Nadal limit."
                ),
                relevance_score=0.84,
                keywords=["derailment", "speed", "curve", "accident", "case study"],
                year="2014",
            ),
            Paper(
                title="Hatfield Rail Crash: Track Degradation and Gauge-Corner Cracking",
                url="https://example.com/eu_paper2",
                source="Engineering Failure Analysis",
                abstract=(
                    "The Hatfield crash (2000) resulted from gauge-corner cracking that "
                    "produced rail fragmentation under a 200 km/h passenger service. "
                    "Track irregularity amplitudes at the failure site exceeded 8 mm."
                ),
                relevance_score=0.82,
                keywords=["track geometry", "derailment", "irregularities", "case study"],
                year="2001",
            ),
            Paper(
                title="Eschede ICE Disaster: Wheel Tyre Fatigue and High-Speed Risk",
                url="https://example.com/eu_paper3",
                source="International Journal of Fatigue",
                abstract=(
                    "The 1998 Eschede disaster killed 101 people when a fatigued ICE "
                    "wheel tyre fractured at 200 km/h. Analysis reveals the compound "
                    "effect of wheel defect and high speed on derailment probability."
                ),
                relevance_score=0.81,
                keywords=["wheel defect", "fatigue", "high-speed", "derailment"],
                year="1999",
            ),
        ],
        "africa": [
            Paper(
                title="Cairo Train Collision 2021: Infrastructure Maintenance Deficit "
                      "and Risk Analysis",
                url="https://example.com/af_paper1",
                source="Safety Science",
                abstract=(
                    "Two trains collided near Tahta, Egypt in 2021, killing 32 people. "
                    "Investigation identified deferred track maintenance and signalling "
                    "failures. Track geometry irregularities exceeded safe limits."
                ),
                relevance_score=0.83,
                keywords=["derailment", "track geometry", "maintenance", "case study"],
                year="2021",
            ),
            Paper(
                title="TAZARA Line Freight Derailments: Narrow-Gauge Track Degradation",
                url="https://example.com/af_paper2",
                source="Journal of Rail Transport Planning and Management",
                abstract=(
                    "Repeated freight derailments on the Tanzania–Zambia Railway Authority "
                    "narrow-gauge network are attributed to heavy axle loads on under-maintained "
                    "metre-gauge track with chronically high geometry deviation."
                ),
                relevance_score=0.80,
                keywords=["narrow gauge", "axle load", "track geometry", "Africa", "case study"],
                year="2018",
            ),
            Paper(
                title="Shosholoza Meyl Collision near Booysens: Brake Failure on "
                      "Steep Grade",
                url="https://example.com/af_paper3",
                source="Engineering Failure Analysis",
                abstract=(
                    "A 2013 passenger train collision in South Africa resulted from "
                    "brake failure on a 1-in-50 grade, producing axle loads equivalent "
                    "to impact loading far exceeding Nadal limits on curved track."
                ),
                relevance_score=0.78,
                keywords=["brake failure", "grade", "axle load", "South Africa", "case study"],
                year="2014",
            ),
        ],
        "asia": [
            Paper(
                title="Wenzhou High-Speed Rail Collision 2011: Signalling Failure "
                      "and Dynamic Impact",
                url="https://example.com/as_paper1",
                source="Accident Analysis and Prevention",
                abstract=(
                    "The 2011 Wenzhou rear-end collision between two CRH trains on "
                    "a viaduct killed 40 people. The impact speed produced derailment "
                    "forces far exceeding static Nadal limits."
                ),
                relevance_score=0.84,
                keywords=["high-speed", "collision", "derailment", "China", "case study"],
                year="2012",
            ),
            Paper(
                title="Odisha Balasore Triple-Train Collision 2023: Signalling, Speed, "
                      "and Track Loading",
                url="https://example.com/as_paper2",
                source="Railway Engineering Science",
                abstract=(
                    "On 2 June 2023, three trains collided near Balasore, Odisha, killing "
                    "291 people. Investigation revealed a signalling anomaly that directed "
                    "a passenger express onto an occupied loop track at operational speed."
                ),
                relevance_score=0.83,
                keywords=["collision", "derailment", "India", "case study"],
                year="2023",
            ),
            Paper(
                title="Shinkansen Chuetsu Earthquake Derailment 2004: Seismic "
                      "Excitation and Track Irregularity",
                url="https://example.com/as_paper3",
                source="Earthquake Engineering and Structural Dynamics",
                abstract=(
                    "The Chuetsu earthquake caused partial derailment of Toki 325 "
                    "Shinkansen at 200 km/h. No fatalities occurred due to automatic "
                    "emergency braking. Track irregularity amplitudes spiked to 15 mm."
                ),
                relevance_score=0.80,
                keywords=["seismic", "derailment", "Shinkansen", "Japan", "case study"],
                year="2005",
            ),
        ],
        "north_america": [
            Paper(
                title="Lac-Mégantic Derailment: Axle Load and Curve Speed Interaction",
                url="https://example.com/na_paper1",
                source="Safety Science",
                abstract=(
                    "Investigation of the 2013 Lac-Mégantic freight train derailment. "
                    "Heavy crude-oil tank cars with axle loads near 263 kN travelled "
                    "at more than 100 km/h on a 65 km/h rated curve."
                ),
                relevance_score=0.84,
                keywords=["axle load", "derailment", "curve", "freight", "case study"],
                year="2014",
            ),
            Paper(
                title="East Palestine Ohio 2023: Freight Derailment and Track "
                      "Geometry Defect Detection",
                url="https://example.com/na_paper2",
                source="Transportation Research Record",
                abstract=(
                    "The February 2023 Norfolk Southern derailment in East Palestine "
                    "involved a bearing overheating failure not detected in time by "
                    "trackside hot-box detectors. Track geometry deviation was within "
                    "FRA Class 4 limits at the derailment site."
                ),
                relevance_score=0.82,
                keywords=["bearing", "derailment", "freight", "North America", "case study"],
                year="2023",
            ),
            Paper(
                title="Chatsworth Collision 2008: Distracted Driving and High-Speed "
                      "Passenger Crash",
                url="https://example.com/na_paper3",
                source="Accident Analysis and Prevention",
                abstract=(
                    "A 2008 head-on collision between a Metrolink commuter train and "
                    "a freight locomotive in Chatsworth, California killed 25 people. "
                    "Impact speed produced lateral loads exceeding 3× the static Nadal "
                    "limit."
                ),
                relevance_score=0.80,
                keywords=["collision", "lateral force", "North America", "case study"],
                year="2009",
            ),
        ],
        "south_america": [
            Paper(
                title="Once Station Crash, Argentina 2012: Brake Failure and "
                      "Terminal Impact Dynamics",
                url="https://example.com/sa_paper1",
                source="Engineering Failure Analysis",
                abstract=(
                    "A 2012 commuter train overran its terminal at Once Station, Buenos "
                    "Aires, killing 51 people. Brake degradation led to impact speeds of "
                    "approximately 20 km/h, producing severe buffer-stop lateral forces."
                ),
                relevance_score=0.82,
                keywords=["brake failure", "terminal impact", "Argentina", "case study"],
                year="2013",
            ),
            Paper(
                title="Braço do Norte Freight Derailment, Brazil: Mountain Grade "
                      "and Axle Load Interaction",
                url="https://example.com/sa_paper2",
                source="Journal of Rail Transport Planning and Management",
                abstract=(
                    "Repeated freight derailments on steep-grade mountain lines in "
                    "Santa Catarina, Brazil, are linked to heavy iron-ore axle loads "
                    "and substandard track geometry on curves with radius < 400 m."
                ),
                relevance_score=0.79,
                keywords=["axle load", "grade", "curve", "South America", "case study"],
                year="2017",
            ),
            Paper(
                title="Caracas Metro Derailment, Venezuela 2013: Track Degradation "
                      "and Deferred Maintenance",
                url="https://example.com/sa_paper3",
                source="Safety Science",
                abstract=(
                    "A 2013 metro derailment in Caracas caused injuries and service "
                    "disruption. Post-incident survey identified track geometry "
                    "deviation well above permissible limits due to deferred maintenance."
                ),
                relevance_score=0.77,
                keywords=["metro", "track geometry", "maintenance", "case study"],
                year="2014",
            ),
        ],
        "global": [
            Paper(
                title="Santiago de Compostela Train Accident: Speed Excess and Curve "
                      "Negotiation Failure",
                url="https://example.com/g_paper1",
                source="Accident Analysis and Prevention",
                abstract=(
                    "Post-accident investigation of the 2013 Santiago de Compostela "
                    "derailment. The Alvia train entered a 80 km/h curve at 179 km/h, "
                    "producing wheel-rail lateral forces far exceeding the Nadal limit."
                ),
                relevance_score=0.84,
                keywords=["derailment", "speed", "curve", "accident", "case study"],
                year="2014",
            ),
            Paper(
                title="Hatfield Rail Crash: Track Degradation and Gauge-Corner Cracking",
                url="https://example.com/g_paper2",
                source="Engineering Failure Analysis",
                abstract=(
                    "The Hatfield crash (2000) resulted from gauge-corner cracking that "
                    "produced rail fragmentation under a 200 km/h passenger service. "
                    "Track irregularity amplitudes at the failure site exceeded 8 mm."
                ),
                relevance_score=0.82,
                keywords=["track geometry", "derailment", "irregularities", "case study"],
                year="2001",
            ),
            Paper(
                title="Lac-Mégantic Derailment: Axle Load and Curve Speed Interaction",
                url="https://example.com/g_paper3",
                source="Safety Science",
                abstract=(
                    "Investigation of the 2013 Lac-Mégantic freight train derailment. "
                    "Heavy crude-oil tank cars with axle loads near 263 kN travelled "
                    "at more than 100 km/h on a 65 km/h rated curve."
                ),
                relevance_score=0.80,
                keywords=["axle load", "derailment", "curve", "freight", "case study"],
                year="2014",
            ),
        ],
    }

    region_key = region.lower() if region.lower() in _REGIONAL_PAPERS else "global"
    papers = core_papers + _REGIONAL_PAPERS[region_key]

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
