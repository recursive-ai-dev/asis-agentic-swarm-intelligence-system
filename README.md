# ASIS — Algebraic Swarm Intelligence System

> *A deterministic swarm planner that uses unmet constraints to compose bounded search operations. Give it goals and constraints; get back a checked plan, its computation history, and an honest account of search limits.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/recursive-ai-dev/asis-agentic-swarm-intelligence-system/actions/workflows/ci.yml/badge.svg)](https://github.com/recursive-ai-dev/asis-agentic-swarm-intelligence-system/actions/workflows/ci.yml)

```console
$ asis solve "optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps"
Status: SOLVED
Why it stopped: constraints met and no cheaper variant found

Plan:
  - add_cache — put a read-through cache in front of the database (+40 usd)
  - async_queue — move slow work onto a background queue (+25 usd)
  - upgrade_instance — move to a larger instance class (+90 usd)

Predicted metrics:
  cost: 255 usd (was 100 usd)
  error_rate: 2.2% (was 2%)
  latency: 67.2 ms (was 180 ms)  [✓ latency < 100 ms]
  throughput: 1050 rps (was 400 rps)  [✓ throughput > 1000 rps]

How the team got there:
  1. initial plan: nothing is required up front [planner]
  2. add add_cache: latency 180 → 108, throughput 400 → 500 [repairer]
  3. add upgrade_instance: latency 108 → 86.4, throughput 500 → 750 [repairer]
  4. add async_queue: latency 86.4 → 67.2, throughput 750 → 1050 [repairer]
```

---

## The idea: a body, not a boss

A body has no central controller telling each cell what to do. It has many single-purpose cells and organs that react to the signals they have receptors for, share one genome, keep themselves in balance through feedback loops, defend against what doesn't belong, remember what worked, and keep working when a part is lost.

ASIS is built the same way:

| In a body | In ASIS |
|---|---|
| Cells respond to hormones they have receptors for | Specialists declare **receptors** for signal kinds. Nobody addresses anybody; the substrate delivers each signal to every tissue that can hear it |
| One genome in every cell | Every specialist reads the same **knowledge base**, but each only does its own job |
| Extracellular medium | A shared **blackboard** where specialists leave specs, proposals and verdicts for each other |
| Metabolism | Each task has **message energy**; internal model evaluations are counted separately |
| Homeostasis | The **regulator** raises search effort when a task stalls and calls for a decision when there is nothing left to try or energy runs out |
| Negative feedback | The repairer stands down once any plan satisfies the task; the optimizer takes over |
| Immune system | The **immune** specialist rejects malformed or contradictory tasks and quarantines invalid or already-seen plans |
| Immunological memory | **Memory** recognises a problem it has solved before, even when it is worded differently, and re-proposes the answer |
| Redundancy | Several cells can form one tissue (two estimators by default); the substrate spreads work between them |
| Graceful degradation | Remove any specialist and the organism still answers honestly, or visibly stalls if it was a vital organ ([measured below](#lesions)) |

### The team

| Specialist | Receptors | Job |
|---|---|---|
| **intake** | `TASK` | Reads a task expression into goals, required/forbidden items and constraints |
| **immune** | `OPENED`, `PROPOSAL` | Screens tasks (unknown names with "did you mean", unit mismatches, contradictions, impossible bounds) and plans (conflicts, missing prerequisites, forbidden actions, repeats) |
| **decomposer** | `CLEARED` | Expands goals into required capabilities with the rule engine over the goal hierarchy |
| **memory** | `REQUIREMENTS`, satisfied `VERDICT`, `RESULT` | Recalls model-guarded solutions and learns procedures after independent validation |
| **planner** | `REQUIREMENTS` | Drafts the cheapest plan that provides every required capability |
| **estimator** ×2 | `PLAN` | Predicts every metric for a plan |
| **checker** | `ESTIMATE` | Compares predictions against constraints; records a verdict |
| **repairer** | `VERDICT` (violated), `ESCALATE` | Tries improving single moves; when those stall, composes bounded extensions through deferred tradeoff branches and recalls guarded procedures |
| **optimizer** | `VERDICT` (satisfied) | Looks for a cheaper plan that still satisfies everything: single moves, then pairs |
| **regulator** | `QUIESCENT`, `EXHAUSTED` | Homeostasis: escalate effort or call for a decision |
| **judge** | `SETTLE`, `REJECTED` | Chooses the answer: the cheapest satisfying plan, else the closest miss |
| **explainer** | `RESULT` | Writes the report: plan, numbers, and how the team got there |

### How a task flows

```
TASK ─▶ intake ─▶ immune ─▶ decomposer ─▶ planner ──┐   memory ──┐
                                                    ▼            ▼
         ┌──────────────── PROPOSAL ─▶ immune ─▶ estimator ─▶ checker
         │                                                     │
         ├── repairer ◀─ violated ─────────────────────────────┤
         └── optimizer ◀─ satisfied ───────────────────────────┘

substrate senses QUIESCENT / EXHAUSTED ─▶ regulator ─▶ ESCALATE ─▶ repairer
                                                    └▶ SETTLE ─▶ judge ─▶ RESULT ─▶ explainer, memory
```

The substrate only does physiology: it delivers signals, charges energy, and notices when a task has nothing in flight or has run out of energy. Every decision is made by a specialist.

---

## Quick Start

### Install
ASIS has no runtime dependencies and needs Python 3.10 or newer.

On Debian or Ubuntu with Python 3.10 or newer, build and install the native package:

```bash
./build-deb.sh
sudo apt install ./dist/asis-swarm_3.1.0_all.deb
asis --version
asis dashboard
```

The build uses Python 3 and `dpkg-deb`; it needs no root access, pip, or network.
The `all` package works on CPU architectures supported by the system Python.
It installs `/usr/bin/asis`, a private application under `/usr/lib/asis-swarm`,
a desktop launcher, an icon, and `man asis`. It does not start a background
service. The desktop launcher opens the local dashboard on an available port,
with a console showing its address; press Ctrl+C in that console to stop it.
To uninstall, run `sudo apt remove asis-swarm`.

The builder refuses existing outputs; use `./build-deb.sh --force` for an
intentional rebuild. A `.deb.sha256` file accompanies the package. Set
`SOURCE_DATE_EPOCH` to fix archive timestamps across source checkouts.

For a Python environment instead:

```bash
pip install .            # from a checkout
pip install -e ".[dev]"  # editable install with test/lint tooling
```

### Solve a task
```bash
asis solve "optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps"
asis solve "high_availability ⊗ uptime >= 99.9% ⊗ cost < 400"
asis solve "(scale_out ⊕ high_availability) ⊗ throughput > 1500rps ⊗ ¬goal:caching ⊗ cost < 500"
asis solve "cut_costs ⊗ cost < 80 ⊗ latency < 200ms" --json
asis solve "launch_feature" --trace launch.json      # also save a full trace
asis solve "..." --kb my_domain.json --budget 800   # your own knowledge base
```

Exit status: `0` solved, `2` not solved (the closest plan is reported), `3` rejected before planning, `1` usage or input error.

### Compose compensating actions

The bundled `compensation` domain reproduces a coupled-constraint failure of
the earlier greedy repairer. Baseline latency and cost are 100. `fast` reduces
latency but adds 200 cost; `cheap` saves 200 cost but triples latency. Either
action alone makes total violation worse. Together they yield latency 30 and
cost 100:

```bash
asis solve "latency <= 50ms ⊗ cost <= 100" --kb compensation --json
asis solve "latency <= 50ms ⊗ cost <= 100" --kb compensation \
    --search-depth 3 --beam-width 8 --search-evaluations 256 --trace compensation-trace.json
```

The composer uses an executable, typed operation registry: generate choices,
extend with prerequisites, predict, measure each residual, and check a stated
condition. Prediction never silently discards a candidate. A branch can be
deferred when one residual improves while another worsens. Its remaining
residuals prioritize the next extension. The search graph describes computation;
domain actions remain an unordered multiset.

Composition starts at effort 2 when ordinary repair stalls. Depth bounds the
number of extension decisions (each includes prerequisite closure), beam width
bounds retained branches, and `--search-evaluations` bounds composition model
evaluations per task. This last allowance is **separate from greedy repair and
optimization**, whose evaluations are also counted in the reported total.
`--search-depth 1` provides a single-step comparison. The trace retains residual
vectors, operation metadata, explored nodes, and reasons for deferring branches.
This is a restricted composition grammar, not arbitrary program synthesis or an
exhaustive coverage certificate.

Useful extension procedures are stored in session memory with a complete model
fingerprint. Reuse checks action availability, use limits, prerequisites,
conflicts, forbidden actions, and the current task's requirements. Numeric
thresholds may differ; every reused result is predicted and validated again.
Memory is local to a running swarm, with no cross-domain role binding or disk
persistence.

### See what a knowledge base offers
```bash
asis kb           # goals, capabilities, metrics (with aliases) and actions
asis kb --json
```

### Watch the team work
```bash
asis dashboard                  # serves http://localhost:8765/ and opens a browser
asis dashboard --kb my.json     # with your own knowledge base
asis dashboard --port 0         # any free port
asis dashboard --no-demo        # start without the demo task
```

The dashboard is driven by the real engine. It shows the specialists on a ring with the substrate at the centre, every signal as it is delivered, each task's status, remaining energy and answer (click a task for its full report), and the expression tree of the payload in flight. The task dialog offers the knowledge base's goals and metrics as one-click chips.

The server binds to `127.0.0.1` by default and has no authentication; only use `--host` on a network you trust. All browser tabs share one organism. Opened directly as a file (`asis/dashboard.html`), the page replays any trace from `asis run` or `asis solve --trace` (**Load Trace**).

---

## Task Notation

| Syntax | Meaning |
|---|---|
| `optimize_system`, `goal:launch_feature` | a goal from the knowledge base, or a capability (bare text is a goal) |
| `latency < 100ms`, `uptime >= 99.9%` | a constraint (any text with `< <= > >= = != ≤ ≥ ≠`). Units convert: `p99 < 0.1s` means `latency < 100 ms` |
| `a ⊗ b` or `a * b` | all of these |
| `(a ⊕ b)` or `(a \| b)` | either goal. `⊗` binds tighter than `⊕`, so group alternatives in parentheses |
| `action:add_cdn` | this action must be in the plan |
| `¬action:x`, `¬goal:caching` | never use this action / anything providing this capability |
| `¬(latency < 150ms)` | the negated constraint (`latency >= 150 ms`) |

```python
from asis import parse_expression
parse_expression("goal:ship ⊗ (entity:api ⊕ entity:db) ⊗ latency < 50ms")
```

---

## Writing a Knowledge Base

A knowledge base is a JSON file with three sections. See [`asis/domains/web_service.json`](asis/domains/web_service.json) for a complete example.

```json
{
  "name": "kitchen",
  "metrics": {
    "prep_time": {"unit": "min", "baseline": 60, "min": 0, "aliases": ["time"]},
    "cost": {"unit": "usd", "baseline": 0}
  },
  "actions": {
    "mise_en_place": {"cost": 5, "effects": {"prep_time": {"add": -15}}},
    "sous_chef": {"cost": 40, "effects": {"prep_time": {"factor": 0.5}}, "provides": ["help"]},
    "second_oven": {"cost": 30, "requires": ["sous_chef"], "max_uses": 2,
                    "effects": {"prep_time": {"add": -5}}}
  },
  "goals": {
    "dinner_party": {"needs": ["help"]}
  }
}
```

- **Metrics** have a unit, a baseline, optional `min`/`max` bounds and aliases. A `cost` metric always exists; plans are ranked by it.
- **Actions** have a cost, `effects` on metrics (`add` and/or `factor`), the capabilities they `provide`, prerequisite actions (`requires`), mutual exclusions (`conflicts`) and `max_uses`. Negative costs are savings.
- **Goals** `need` capabilities and/or other goals.
- A plan's metrics are `(baseline + Σ add) × Π factor`, clamped to the metric's bounds.

The loader validates everything: unknown references, requires-and-conflicts pairs, non-positive factors, goal cycles and impossible bounds are reported together.

---

## Python API

```python
from asis import KnowledgeBase, SearchConfig, create_default_swarm, solve

result = solve("optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps")
result.status        # "solved" | "unsolved" | "rejected" | "stalled" | "open"
result.plan          # {"add_cache": 1, "async_queue": 1, "upgrade_instance": 1}
result.metrics       # predicted metrics for the chosen plan
result.cost, result.violations, result.reason, result.report
result.energy_used, result.budget
result.model_evaluations   # all built-in prediction calls, including rejected moves
result.plans_considered    # distinct candidates receiving a checker verdict
result.assessment          # feasible_in_model | search_incomplete | rejected | pending
result.optimality_proven   # False: the bounded heuristic search supplies no proof
result.search_complete     # False: unvisited regions may remain

result = solve("latency <= 50ms ⊗ cost <= 100",
               kb=KnowledgeBase.load("asis/domains/compensation.json"),
               search_config=SearchConfig(max_depth=3, beam_width=8, max_evaluations=256))

# One organism, many tasks, shared memory:
swarm = create_default_swarm(KnowledgeBase.load("kitchen.json"), energy_budget=400)
a = swarm.submit("dinner_party ⊗ prep_time < 20min")
swarm.run()
b = swarm.submit("dinner_party ⊗ time < 1200s")    # same problem, different words
swarm.run()                                        # or swarm.step() one step at a time
swarm.result(b).report                             # "... recalled: the same problem was solved in task …"
swarm.save_trace("trace.json")
```

### Adding a specialist
Specialists join through receptors. Nothing else needs to change:

```python
from asis import Kind, Receptor, Specialist

class Auditor(Specialist):
    tissue = "auditor"
    receptors = (Receptor(Kind.RESULT),)
    description = "Keeps a record of every answer."

    def handle(self, signal, ctx):
        print(signal.task_id, signal.data["status"])
        return []          # or signals to emit, via self.emit(kind, task_id, payload, **data)

swarm = create_default_swarm()
swarm.register_agent(Auditor())
```

`swarm.remove_agent(agent_id)` takes one out.

---

## Guarantees

- **Deterministic.** No randomness, threads or wall-clock time in the engine. Identical inputs produce byte-identical traces (tested).
- **Checked feasibility.** `solved` means a candidate satisfies the declared requirements and effect model. The optimizer returns the cheapest checked candidate it finds. Some tested examples match an exhaustive oracle; a cheaper unvisited candidate may still exist.
- **Honest limits.** `unsolved` means no satisfying plan was found within this search. It does not establish infeasibility. Results explicitly report `assessment`, `optimality_proven`, and `search_complete`.
- **Answers on termination.** With the default team and sufficient step allowance, tasks end solved, unsolved (with the closest checked plan), or rejected. Removing a vital specialist can stall a task; a step limit can leave it open.
- **Bounded composition.** Each task has message energy (400 by default) and a separate composition evaluation allowance (256), depth (3), and beam width (8). Reported model evaluations count every built-in prediction, including rejected candidates and report baselines. Message energy alone is not a fair measure of search cost.
- **Isolated.** Many tasks in one organism reach the same answers as each task alone (tested).

### Lesions
What happens when one specialist is removed (`tests/test_team.py::TestLesions`):

| Removed | Effect |
|---|---|
| an estimator, memory, explainer | Same answer (without the explainer there is no report; without memory, repeats cost more energy) |
| optimizer | Still solves, but pays more (`high_availability ⊗ uptime >= 99.9% ⊗ cost < 400`: 255 instead of 215) |
| repairer | Only tasks the first draft already satisfies are solved; the rest get an honest "unsolved" |
| intake, immune, decomposer, planner, checker | "unsolved: no plan was ever evaluated" — the organism still answers |
| regulator or judge | **Vital organs:** tasks stall. A second regulator cell prevents it |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  asis/specialists.py  The team: 12 single-purpose specialists      │
│  asis/search.py       Typed operations, bounded composer, memory  │
│  asis/organism.py     Signals, receptors, blackboard, substrate    │
│  asis/knowledge.py    Metrics, actions, goals, constraints, units  │
│  asis/core.py         Algebra, ASIS notation parser, rule engine   │
│  asis/server.py       Dashboard HTTP server (standard library)     │
│  asis/cli.py          asis run | solve | kb | dashboard            │
└──────────────────────────────────────────────────────────────────┘
```

Every signal carries an **expression**: a plan is the `⊗` of its action atoms, a verdict is `satisfied ⊗ plan`, an estimate is `plan ⊗ (⊕ metric atoms)`. Expressions are immutable, canonicalized trees (associativity is flattened, `A ⊕ A = A`, `¬¬A = A`, `_identity` and `_zero` for `⊗`), which keeps traces reproducible and lets the dashboard draw what the specialists are passing around.

---

## Testing

```bash
pip install -e ".[dev]"
pytest
pytest --cov=asis --cov-report=term-missing
ruff check .
python scripts/benchmark_search.py --output dist/search-benchmark.json
./build-deb.sh
```

| Suite | Covers |
|---|---|
| `test_core.py`, `test_math_properties.py` | Algebra, factory, rule engine (including subterm rewriting) |
| `test_knowledge.py` | Loading and validation, constraints and units, estimation, plans |
| `test_team.py` | Outcomes checked against exhaustive search, rejections, reports, substrate behaviour, memory, lesions |
| `test_dashboard.py` | Notation parser, frame API, HTTP endpoints and input validation |
| `test_regressions.py` | Past defects and the CLI contract (exit codes, JSON, custom knowledge bases) |
| `test_stress.py` | Deep and wide expressions; 60 concurrent tasks in one organism |
| `test_composition.py`, `test_work_accounting.py` | Deferred compensation, guarded reuse, graph typing, evaluation accounting and limits |
| `test_cli_composition.py`, `test_packaging.py` | Search controls, bundled domains, Debian metadata, reproducibility, extracted CLI and dashboard |

The benchmark compares depths 1, 2, and 3 on small two- and three-action
compensation problems, including infeasible cases. It enumerates every multiset
as an independent oracle and records all engine model evaluations and elapsed
time. These synthetic checks establish correctness on the included cases;
they do not establish a general efficiency advantage over fixed lookahead.

---

## Files

| File | Description |
|---|---|
| `asis/` | The package (see [Architecture](#architecture)); `asis/domains/web_service.json` is the bundled example domain |
| `asis/dashboard.html` | Dashboard client: renders engine frames live or from a trace (loads web fonts from Google Fonts) |
| `asis_trace.json` | Sample trace produced by `asis run` |
| `build.sh` | Builds a standalone binary with PyInstaller |
| `build-deb.sh`, `packaging/` | Native Debian package builder, launcher, desktop integration and manual |
| `scripts/benchmark_search.py` | Reproducible small-domain comparison against exhaustive enumeration |
| `CHANGELOG.md` | Release notes |

## Keyboard Shortcuts (Dashboard)

| Key | Action |
|---|---|
| `Space` | Pause / resume stepping |
| `→` | Advance one step |
| `Ctrl + Enter` | Open the task dialog, or submit it when open |
| `Escape` | Close a dialog |
| Click a task | Show its report |

## Limits

- The effect model is additive-then-multiplicative per metric; interactions between actions beyond `requires` and `conflicts` are not modelled.
- Search is heuristic: greedy repair, bounded residual-guided extension compositions, and local cost optimization. Branches dropped by depth, beam, or residual priority may contain solutions; no global optimality or infeasibility is certified.
- Deferred compositions currently add actions; removing or swapping actions remains part of the existing repairer and optimizer. Operation metadata and model fingerprints preserve declared assumptions, rather than supplying a proof of those assumptions.
- Expressions are processed recursively; trees nested deeper than roughly 800–900 levels raise `RecursionError`.

## License

MIT — see [LICENSE.md](LICENSE.md).
