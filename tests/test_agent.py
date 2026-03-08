"""
Unit tests for agent modules:
  - planning_engine
  - workflow_controller
  - research_agent (mock mode)
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agent.planning_engine import PlanningEngine, ResearchPlan
from src.agent.workflow_controller import (
    PipelineReport,
    StageStatus,
    WorkflowController,
)
from src.agent.research_agent import ResearchAgent, _build_mock_literature
from src.research.knowledge_extraction import KnowledgeBase, ParameterRange


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _minimal_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        insights=[],
        parameter_ranges={
            "speed_kmh": ParameterRange("Train Speed", "km/h", 60.0, 350.0, 120.0),
            "axle_load_kN": ParameterRange("Axle Load", "kN", 80.0, 250.0, 160.0),
        },
        research_gaps=[
            "Limited ML application to derailment probability prediction",
            "Insufficient digital twin models",
        ],
        candidate_topics=[
            "Derailment probability under combined speed and track irregularity",
            "Lateral stability of high-speed bogies",
        ],
    )


# ---------------------------------------------------------------------------
# PlanningEngine
# ---------------------------------------------------------------------------


class TestPlanningEngine:
    def setup_method(self):
        self.kb = _minimal_knowledge_base()
        self.engine = PlanningEngine(self.kb, seed=42)

    def test_generate_plan_returns_plan(self):
        plan = self.engine.generate_plan()
        assert isinstance(plan, ResearchPlan)

    def test_plan_has_title(self):
        plan = self.engine.generate_plan()
        assert plan.title

    def test_plan_has_objective(self):
        plan = self.engine.generate_plan()
        assert plan.objective

    def test_plan_has_questions(self):
        plan = self.engine.generate_plan()
        assert len(plan.questions) >= 1

    def test_plan_selected_topic_is_string(self):
        plan = self.engine.generate_plan()
        assert isinstance(plan.selected_topic, str)
        assert len(plan.selected_topic) > 0

    def test_questions_have_simulation_scenarios(self):
        plan = self.engine.generate_plan()
        for q in plan.questions:
            assert len(q.simulation_scenarios) >= 1

    def test_score_topics_returns_sorted_list(self):
        scored = self.engine.score_topics()
        assert isinstance(scored, list)
        scores = [s for _, s in scored]
        assert scores == sorted(scores, reverse=True)

    def test_plan_to_dict_keys(self):
        plan = self.engine.generate_plan()
        d = plan.to_dict()
        assert "title" in d
        assert "objective" in d
        assert "questions" in d
        assert "selected_topic" in d

    def test_reproducible_with_same_seed(self):
        e1 = PlanningEngine(self.kb, seed=99)
        e2 = PlanningEngine(self.kb, seed=99)
        p1 = e1.generate_plan()
        p2 = e2.generate_plan()
        assert p1.selected_topic == p2.selected_topic

    def test_empty_knowledge_base_does_not_crash(self):
        empty_kb = KnowledgeBase()
        engine = PlanningEngine(empty_kb, seed=0)
        plan = engine.generate_plan()
        assert plan.selected_topic


# ---------------------------------------------------------------------------
# WorkflowController
# ---------------------------------------------------------------------------


class TestWorkflowController:
    def test_successful_pipeline(self):
        controller = WorkflowController()
        stages = [
            {"name": "stage_a", "fn": lambda: ["artifact_a"]},
            {"name": "stage_b", "fn": lambda: ["artifact_b"]},
        ]
        report = controller.run_pipeline(stages)
        assert report.overall_status == StageStatus.SUCCESS
        assert len(report.stages) == 2

    def test_failed_stage_recorded(self):
        def failing_fn():
            raise RuntimeError("intentional failure")

        controller = WorkflowController()
        stages = [{"name": "bad_stage", "fn": failing_fn}]
        report = controller.run_pipeline(stages)
        assert report.overall_status == StageStatus.FAILED
        assert report.stages[0].status == StageStatus.FAILED
        assert "intentional failure" in report.stages[0].error

    def test_stop_on_failure_skips_remaining(self):
        def failing_fn():
            raise RuntimeError("fail")

        ran = []

        def stage_b():
            ran.append("b")

        controller = WorkflowController(stop_on_failure=True)
        stages = [
            {"name": "stage_a", "fn": failing_fn},
            {"name": "stage_b", "fn": stage_b},
        ]
        report = controller.run_pipeline(stages)
        assert "b" not in ran
        assert report.stages[1].status == StageStatus.SKIPPED

    def test_pipeline_continues_after_non_critical_failure(self):
        ran = []

        def failing_fn():
            raise RuntimeError("fail")

        def stage_b():
            ran.append("b")

        controller = WorkflowController(stop_on_failure=False)
        stages = [
            {"name": "stage_a", "fn": failing_fn},
            {"name": "stage_b", "fn": stage_b},
        ]
        report = controller.run_pipeline(stages)
        assert "b" in ran

    def test_report_to_dict(self):
        controller = WorkflowController()
        stages = [{"name": "stage_a", "fn": lambda: []}]
        report = controller.run_pipeline(stages)
        d = report.to_dict()
        assert "run_id" in d
        assert "overall_status" in d
        assert "stages" in d

    def test_total_duration_is_sum_of_stages(self):
        controller = WorkflowController()
        stages = [
            {"name": "a", "fn": lambda: None},
            {"name": "b", "fn": lambda: None},
        ]
        report = controller.run_pipeline(stages)
        expected = sum(s.duration_s for s in report.stages)
        assert report.total_duration_s == pytest.approx(expected)

    def test_artifacts_stored(self):
        controller = WorkflowController()
        stages = [{"name": "a", "fn": lambda: ["file1.json", "file2.png"]}]
        report = controller.run_pipeline(stages)
        assert report.stages[0].artifacts == ["file1.json", "file2.png"]

    def test_empty_pipeline(self):
        controller = WorkflowController()
        report = controller.run_pipeline([])
        assert report.overall_status == StageStatus.SUCCESS


# ---------------------------------------------------------------------------
# ResearchAgent (mock mode)
# ---------------------------------------------------------------------------


class TestResearchAgent:
    def test_run_completes_in_mock_mode(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        report = agent.run()
        assert report is not None

    def test_data_directory_created(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        assert (tmp_path / "data").exists()

    def test_literature_review_json_created(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        assert (tmp_path / "data" / "literature_review.json").exists()

    def test_research_plan_json_created(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        assert (tmp_path / "data" / "research_plan.json").exists()

    def test_paper_generated(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        paper = tmp_path / "RESEARCH_PAPER.md"
        assert paper.exists()
        content = paper.read_text()
        assert len(content) > 500

    def test_paper_contains_sections(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        paper = (tmp_path / "RESEARCH_PAPER.md").read_text()
        for section in ["Abstract", "Introduction", "Methodology", "Results", "Conclusion"]:
            assert section in paper

    def test_pipeline_report_saved(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        assert (tmp_path / "data" / "pipeline_report.json").exists()

    def test_figures_generated(self, tmp_path):
        agent = ResearchAgent(output_dir=tmp_path, mock_research=True)
        agent.run()
        figs = list((tmp_path / "figures").glob("*.png"))
        assert len(figs) >= 3

    def test_mock_literature_structure(self):
        lit = _build_mock_literature()
        assert len(lit.papers) >= 2
        assert len(lit.research_gaps) >= 1
        assert len(lit.key_findings) >= 1


# ---------------------------------------------------------------------------
# Mock literature
# ---------------------------------------------------------------------------


class TestMockLiterature:
    def test_mock_literature_has_papers(self):
        lit = _build_mock_literature()
        assert len(lit.papers) > 0

    def test_mock_paper_has_required_fields(self):
        lit = _build_mock_literature()
        for paper in lit.papers:
            assert paper.title
            assert paper.url
            assert paper.abstract
            assert 0.0 <= paper.relevance_score <= 1.0
