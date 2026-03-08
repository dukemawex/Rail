# Rail – Autonomous Railway Derailment Research Agent

An autonomous AI research pipeline that performs engineering research on
train derailments, runs physics-based simulations, and automatically
produces an MIT-style research paper — all driven by GitHub Actions.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions CI/CD                         │
│  (weekly schedule / manual trigger)                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         ResearchAgent                                │
│                                                                      │
│  Stage 1: Literature Review ──► Tavily API ──► SearchResponse        │
│                                                                      │
│  Stage 2: Knowledge Extraction ──► KnowledgeBase                    │
│             (parameter ranges, insights, gaps)                      │
│                                                                      │
│  Stage 3: Research Planning ──► ResearchPlan                        │
│             (topic selection, research questions)                   │
│                                                                      │
│  Stage 4: Simulations ──► ScenarioRunner                            │
│             ├── wheel_rail_dynamics (ODE model)                     │
│             ├── derailment_probability (Nadal + Gaussian risk)       │
│             └── scenario_runner (5 scenario JSON files)             │
│                                                                      │
│  Stage 5: Analysis ──► MetricsCalculator + Visualizer               │
│             └── 5 publication-quality PNG figures                   │
│                                                                      │
│  Stage 6: Paper Generation ──► MITPaperGenerator                   │
│             └── RESEARCH_PAPER.md                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
repo-root/
│
├── src/
│   ├── research/
│   │   ├── tavily_client.py          # Tavily API wrapper with retry logic
│   │   ├── literature_review.py      # Multi-topic search and deduplication
│   │   └── knowledge_extraction.py   # Structured knowledge from papers
│   │
│   ├── agent/
│   │   ├── research_agent.py         # Top-level pipeline orchestrator
│   │   ├── planning_engine.py        # Topic selection & research questions
│   │   └── workflow_controller.py   # Stage execution with status tracking
│   │
│   ├── simulations/
│   │   ├── wheel_rail_dynamics.py    # Hertz + Kalker physics model, ODE
│   │   ├── derailment_probability.py # Nadal criterion + Gaussian risk model
│   │   └── scenario_runner.py       # Orchestrates all simulation scenarios
│   │
│   ├── analysis/
│   │   ├── metrics.py               # Safety metric calculator
│   │   └── visualization.py         # Matplotlib figure generator
│   │
│   └── paper/
│       ├── mit_paper_generator.py   # Assembles the research paper
│       └── templates/
│           └── mit_template.md      # Markdown paper template
│
├── data/
│   └── simulation_results/          # JSON output from simulations
│
├── figures/                         # Generated PNG figures
│
├── tests/
│   ├── test_simulations.py
│   ├── test_agent.py
│   └── test_research_pipeline.py
│
├── scripts/
│   └── run_pipeline.py             # CLI entry point
│
├── .github/
│   └── workflows/
│       └── autonomous_research.yml  # GitHub Actions workflow
│
├── requirements.txt
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- A [Tavily API key](https://tavily.com) (optional – the pipeline works without one via `--mock`)

### Installation

```bash
# Clone the repository
git clone https://github.com/dukemawex/Rail.git
cd Rail

# Install dependencies
pip install -r requirements.txt

# Install the package in editable mode
pip install -e .
```

### Running Locally

**Without Tavily API key (mock mode):**

```bash
python scripts/run_pipeline.py --mock
```

**With Tavily API key (live research):**

```bash
export TAVILY_API_KEY="tvly-your-key-here"
python scripts/run_pipeline.py
```

**All options:**

```
python scripts/run_pipeline.py --help

options:
  --output-dir OUTPUT_DIR   Root directory for pipeline output (default: .)
  --mock                    Use mock research data instead of Tavily API
  --seed SEED               Random seed for reproducible simulations (default: 42)
```

### Running Tests

```bash
pytest tests/ -v
```

To run with coverage:

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## Tavily API Configuration

1. Sign up at [https://tavily.com](https://tavily.com) to obtain an API key.
2. Set the key as an environment variable:
   ```bash
   export TAVILY_API_KEY="tvly-your-key-here"
   ```
3. For GitHub Actions, add the key as a **repository secret** named `TAVILY_API_KEY`
   (Settings → Secrets and variables → Actions → New repository secret).

If `TAVILY_API_KEY` is absent the pipeline automatically falls back to mock mode,
which uses pre-built paper data and runs all simulations without any external calls.

---

## GitHub Actions Automation

The workflow (`.github/workflows/autonomous_research.yml`) runs automatically on:

| Trigger | Schedule / Condition |
|---------|----------------------|
| **Scheduled** | Every Sunday at 02:00 UTC |
| **Manual** | Via the *Actions* tab → *Run workflow* |

### What the workflow does

1. Checks out the repository
2. Sets up Python 3.11
3. Installs dependencies
4. Runs the full test suite
5. Executes the research pipeline
6. Uploads simulation results and figures as build artefacts
7. Commits and pushes updated `data/`, `figures/`, and `RESEARCH_PAPER.md` back to the repo

### Manual trigger with options

In the Actions tab click **Run workflow** and optionally set:
- `mock_research`: `true` to skip Tavily API calls
- `seed`: integer seed for reproducible outputs

---

## Simulation Models

### Wheel-Rail Contact (Hertz Theory)

The contact patch geometry and normal pressure are computed using Hertz
elastic contact theory for a steel wheel on a steel rail.  The model
accounts for combined wheel and rail curvature to produce realistic
contact patch sizes.

### Lateral Dynamics (2-DOF ODE)

A simplified single-wheelset model describes lateral displacement and
velocity under combined suspension stiffness, damping, creep force
(Kalker linear theory), and stochastic track irregularity excitation.
The ODE is integrated with SciPy `solve_ivp` (RK45).

### Derailment Probability (Nadal + Gaussian)

Derailment probability is computed analytically as:

```
P(derailment) = P(Q/P > limit)
```

where:
- **Q/P** is the lateral-to-vertical wheel force ratio
- **limit** = (tan α − μ) / (1 + μ tan α)  (Nadal criterion, EN 14363)
- Q/P is modelled as normally distributed with CV = 15 %

### Simulation Scenarios

| Scenario | Description |
|----------|-------------|
| `speed_sweep` | Derailment probability vs. speed for four irregularity levels |
| `load_sweep` | Derailment probability vs. axle load for four speeds |
| `irregularity_sweep` | Derailment probability vs. irregularity amplitude |
| `combined_risk_surface` | 2-D risk surface over speed × axle load |
| `wheelset_dynamics` | Time-domain lateral displacement at three speeds |

---

## Generated Outputs

After a pipeline run the following artefacts are produced:

| Path | Description |
|------|-------------|
| `data/literature_review.json` | Discovered papers and research gaps |
| `data/knowledge_base.json` | Structured engineering insights |
| `data/research_plan.json` | Selected topic and research questions |
| `data/simulation_results/*.json` | Raw simulation data |
| `data/metrics.json` | Computed safety metrics |
| `figures/fig_speed_sweep.png` | Derailment probability vs. speed |
| `figures/fig_load_sweep.png` | Derailment probability vs. axle load |
| `figures/fig_irregularity_sweep.png` | Derailment probability vs. irregularity |
| `figures/fig_combined_risk_surface.png` | 2-D risk surface |
| `figures/fig_wheelset_dynamics.png` | Time-domain lateral dynamics |
| `RESEARCH_PAPER.md` | Full MIT-style research paper |

---

## Extending the Pipeline

The pipeline is modular and extensible:

- **Add new simulation scenarios** by adding `_scenario_*` methods to `ScenarioRunner`.
- **Add new research topics** by appending to `RAILWAY_RESEARCH_TOPICS` in `literature_review.py`.
- **Add new figures** by adding a `_plot_*` method to `Visualizer`.
- **Customise the paper** by editing `src/paper/templates/mit_template.md`.

---

## Production Considerations

- **API keys** are handled exclusively via environment variables — never committed.
- **Reproducibility** is ensured by seeding all RNG sources.
- **Error handling** is built into every stage; a failed stage is recorded and the pipeline continues.
- **Logging** is emitted at INFO/WARNING/ERROR level throughout.
- **Dependency pinning** uses `>=` lower bounds with `<` major-version upper bounds for stability.

---

## License

MIT — see [LICENSE](LICENSE).