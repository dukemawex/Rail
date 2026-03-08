#!/usr/bin/env python3
"""
run_pipeline.py – CLI entry point for the autonomous research pipeline.

Usage
-----
    python scripts/run_pipeline.py [--output-dir OUTPUT_DIR] [--mock] [--seed SEED] [--region REGION]

Region options
--------------
    africa, europe, asia, north_america, south_america, global (default)

Environment variables
---------------------
    TAVILY_API_KEY   Tavily API key (required unless --mock is set)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure the repository root is on the Python path when running as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.agent.research_agent import ResearchAgent

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_pipeline")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous railway derailment research pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Root directory for all pipeline output (default: current directory)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock research data instead of real Tavily API calls",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible simulations (default: 42)",
    )
    parser.add_argument(
        "--region",
        default="global",
        choices=["africa", "europe", "asia", "north_america", "south_america", "global"],
        help=(
            "Geographic region of focus for case studies and literature search "
            "(default: global)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key and not args.mock:
        logger.warning(
            "TAVILY_API_KEY not set – running in mock mode. "
            "Pass --mock explicitly to suppress this warning."
        )
        args.mock = True

    logger.info(
        "Starting pipeline | output_dir=%s | mock=%s | seed=%d",
        args.output_dir,
        args.mock,
        args.seed,
    )

    agent = ResearchAgent(
        output_dir=args.output_dir,
        tavily_api_key=tavily_key,
        mock_research=args.mock,
        seed=args.seed,
        region=args.region,
    )

    report = agent.run()

    # Print summary
    print("\n" + "=" * 60)
    print(f"Pipeline run {report.run_id}: {report.overall_status.value.upper()}")
    print(f"Total duration: {report.total_duration_s:.1f}s")
    print("=" * 60)
    for stage in report.stages:
        icon = "✓" if stage.status.value == "success" else ("✗" if stage.status.value == "failed" else "–")
        print(f"  {icon} [{stage.status.value:8s}] {stage.name} ({stage.duration_s:.1f}s)")
        if stage.error:
            print(f"            ERROR: {stage.error[:120]}")
    print("=" * 60)

    return 0 if report.overall_status.value == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
