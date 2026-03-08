"""
Workflow controller: orchestrates the full autonomous research pipeline.

Coordinates the research, simulation, analysis, and paper-generation
stages, handles errors gracefully, and provides structured status reporting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status types
# ---------------------------------------------------------------------------


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Outcome of a single pipeline stage."""

    name: str
    status: StageStatus = StageStatus.PENDING
    duration_s: float = 0.0
    artifacts: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_s": round(self.duration_s, 2),
            "artifacts": self.artifacts,
            "error": self.error,
        }


@dataclass
class PipelineReport:
    """Summary report for a complete pipeline execution."""

    run_id: str
    stages: list[StageResult] = field(default_factory=list)
    overall_status: StageStatus = StageStatus.PENDING
    start_time: float = field(default_factory=time.time)

    @property
    def total_duration_s(self) -> float:
        return sum(s.duration_s for s in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "overall_status": self.overall_status.value,
            "total_duration_s": round(self.total_duration_s, 2),
            "stages": [s.to_dict() for s in self.stages],
        }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class WorkflowController:
    """
    Executes pipeline stages sequentially, recording status and artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for all pipeline outputs.
    stop_on_failure:
        If ``True``, abort subsequent stages after any failure.
    """

    def __init__(
        self,
        output_dir: str | Path = ".",
        stop_on_failure: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.stop_on_failure = stop_on_failure
        self._report: PipelineReport | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_pipeline(self, stages: list[dict[str, Any]]) -> PipelineReport:
        """
        Execute a list of stages.

        Each stage dict must have:
          - ``name`` (str): human-readable stage name
          - ``fn`` (callable): zero-argument callable to execute
          - ``critical`` (bool, optional): if True and the stage fails,
            always abort regardless of ``stop_on_failure``
        """
        import uuid

        run_id = str(uuid.uuid4())[:8]
        report = PipelineReport(run_id=run_id)
        self._report = report
        failed = False

        logger.info("Pipeline run %s starting (%d stages)", run_id, len(stages))

        for stage_def in stages:
            name = stage_def["name"]
            fn = stage_def["fn"]
            critical = stage_def.get("critical", False)

            if failed and (self.stop_on_failure or critical):
                result = StageResult(name=name, status=StageStatus.SKIPPED)
                report.stages.append(result)
                logger.info("Stage '%s' skipped (prior failure)", name)
                continue

            result = self._run_stage(name, fn)
            report.stages.append(result)

            if result.status == StageStatus.FAILED:
                failed = True
                if critical or self.stop_on_failure:
                    logger.error("Critical stage '%s' failed – aborting pipeline", name)

        report.overall_status = (
            StageStatus.FAILED if failed else StageStatus.SUCCESS
        )
        logger.info(
            "Pipeline %s finished: %s (%.1fs)",
            run_id,
            report.overall_status.value,
            report.total_duration_s,
        )
        return report

    def get_last_report(self) -> PipelineReport | None:
        return self._report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_stage(name: str, fn: Any) -> StageResult:
        logger.info("Stage '%s' starting …", name)
        result = StageResult(name=name, status=StageStatus.RUNNING)
        t0 = time.time()
        try:
            artifacts = fn() or []
            result.artifacts = artifacts if isinstance(artifacts, list) else []
            result.status = StageStatus.SUCCESS
            logger.info("Stage '%s' succeeded", name)
        except Exception as exc:  # noqa: BLE001
            result.status = StageStatus.FAILED
            result.error = str(exc)
            logger.exception("Stage '%s' failed: %s", name, exc)
        finally:
            result.duration_s = time.time() - t0
        return result
