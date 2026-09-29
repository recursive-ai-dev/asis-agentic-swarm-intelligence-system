# ASIS 2.0 — Algebraic Swarm Intelligence System

> *A deterministic, rule-based multi-agent architecture implementing a Symbolic Algebra of Concepts (SAC), with real-time cyberpunk visualization.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/recursive-ai-dev/asis-agentic-swarm-intelligence-system/actions/workflows/ci.yml/badge.svg)](https://github.com/recursive-ai-dev/asis-agentic-swarm-intelligence-system/actions/workflows/ci.yml)

---

## What Makes This Remarkable

### 1. Formal Algebraic Foundation
ASIS is built on a **typed lambda calculus variant** where:
- **ConceptAtoms** are typed atomic elements (Entity, Action, Goal, Constraint, etc.)
- **10 algebraic operators** form a closed algebra over expression trees (⊗, ⊕, ¬, π, ι, β, ρ, τ, γ, μ)
- **Immutable DAG-based expressions** with content-addressed identifiers
- **Forward-chaining rule engine** with unification and pattern matching
- **Deterministic discrete event simulation** — zero randomness, full traceability

### 2. Live Cyberpunk Dashboard
A dashboard driven by the real engine. `asis dashboard` serves it from a small standard-library HTTP server, and every agent, message and expression it shows comes from the Python `SwarmController`. There is no simulation code in the page.
- **Agent network** with the 6 specialized agents, their inbox depth and processed counts
- **Animated message packets** for every message the engine routes
- **Expression tree** of the payload in flight, drawn from `Expression.to_dict()`
- **Task injection** in ASIS notation, parsed by the engine (`parse_expression`), with parse errors shown inline
- **Step / pause / reset** controls and **convergence detection** straight from the controller
- **Trace replay**: opened as a plain file, the page replays any trace written by `asis run`

### 3. Production-Grade Agent Architecture
| Agent | Role | Capability |
|-------|------|------------|
| **Orchestrator** | Coordination | Task decomposition, routing, result aggregation |
| **Analyst** | Analysis | Requirement analysis, constraint identification, feasibility assessment |
| **Planner** | Planning | Multi-step plan generation with validation gates |
| **Executor** | Execution | Step-by-step execution with logging |
| **Validator** | Validation | Success/failure detection, feedback loops |
| **Synthesizer** | Synthesis | Final output assembly and delivery |

### 4. Determinism Guarantees
- Zero non-determinism (no random, async, or threading in core)
- Content-addressed identifiers via SHA256
- Logical clock: message timestamps are step numbers, never wall-clock time
- Canonical ordering via sorted processing and tuple-based bindings
- Full audit trail via global log, versioned blackboard, and execution snapshots
- **Same inputs always produce the same trace** — verified by the test suite

---

## Quick Start

### Install
ASIS has no runtime dependencies and needs Python 3.10 or newer.
```bash
pip install .            # from a checkout
pip install -e ".[dev]"  # editable install with test/lint tooling
```

### Open the Live Dashboard
```bash
asis dashboard                  # serves http://localhost:8765/ and opens a browser
asis dashboard --port 0         # pick any free port
asis dashboard --no-demo        # start with an empty swarm
asis dashboard --no-browser     # just print the URL
```

The swarm starts with a demo task and steps every 0.8 s. Watch as:
1. Tasks enter the Orchestrator from `user`
2. Messages pulse through the network as the engine routes them
3. Agents light up in the step they send messages
4. The swarm reaches a fixed point, and the banner and metrics report it

The server binds to `127.0.0.1` by default. It has no authentication, so only use `--host` to expose it on a network you trust. All browser tabs share one swarm.

**Replaying a trace.** Opened directly as a file (`asis/dashboard.html`), the page has no engine to talk to. Click **Load Trace** and choose a JSON trace from `asis run` to replay it step by step.

### Task Notation
Tasks typed into the dashboard, or passed to `parse_expression`, use ASIS notation:

| Syntax | Meaning |
|--------|---------|
| `a ⊗ b` or `a * b` | compose (binds tighter than union) |
| `a ⊕ b` or `a \| b` | union |
| `¬a` or `~a` | negate |
| `( … )` | grouping |
| `goal:name`, `entity:name`, … | atom with an explicit category (any `ConceptCategory`, case-insensitive) |
| `latency < 100ms` | bare text with a comparison (`< > = ≤ ≥ ≠`) is a **constraint** |
| `optimize_system` | any other bare text is a **goal** |

```python
from asis import parse_expression
parse_expression("goal:ship ⊗ (entity:api ⊕ entity:db) ⊗ latency < 50ms")
```

### Run the Engine
```bash
asis run                              # or just `asis`, or `python -m asis`
asis run --output run.json --max-steps 100
asis run --no-trace                   # print the summary only
```

This runs a demo task through the swarm and exports a JSON trace (default `asis_trace.json`). Exit status is `0` on convergence, `2` if the step budget ran out first, and `1` if the trace could not be written.

### Programmatic Usage
```python
from asis import *

# Create swarm
swarm = create_default_swarm()

# Inject a complex algebraic task
task = C.compose(
    C.goal("optimize_system"),
    C.constraint("latency < 100ms"),
    C.constraint("throughput > 1000rps")
)
swarm.inject_task(task)

# Run until algebraic fixed point (convergence)
result = swarm.run_until_convergence(max_steps=50)
print(f"Converged in {result['steps_executed']} steps")

# Export full trace for visualization
swarm.save_trace("my_trace.json")
```

---

## Testing

The project includes a comprehensive test suite using `pytest`.

### Setup
```bash
pip install -e ".[dev]"
```

### Run Tests
```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=asis --cov-report=term-missing

# Lint
ruff check .

# Run specific test class
pytest tests/ -v -k TestExpression
pytest tests/ -v -k TestSwarmController
```

### Test Coverage
The test suite covers:

| Module | Test Class | Tests |
|--------|-----------|-------|
| ConceptAtom | `TestConceptAtom` | Creation, serialization, matching, immutability, hashing |
| Expression | `TestExpression` | Construction, depth, atoms, substitution, serialization, operators |
| C Factory | `TestCFactory` | All factory methods, operators, validation |
| Rule Engine | `TestRule`, `TestRuleEngine` | Pattern matching, variable binding, normalization, chaining |
| Communication | `TestAlgebraicMessage`, `TestBlackboard` | Message creation, routing, blackboard I/O, history |
| Agents | Per-agent classes | Each agent's message handling, blackboard interaction |
| Swarm | `TestSwarmController` | Task injection, stepping, convergence, trace export |
| Integration | `TestIntegration` | End-to-end pipelines, determinism, multi-task scenarios |
| Algebra | `test_math_properties.py` | Associativity, identity, absorption, idempotence, double negation |
| Stress | `test_stress.py` | Deep nesting, bulk idempotence and absorption, multi-task injection |
| Regressions | `test_regressions.py` | Byte-identical traces, metadata identity, failure paths, CLI |
| Dashboard | `test_dashboard.py` | Task notation parser, frame API, HTTP server endpoints and input validation |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ASIS 2.0 ARCHITECTURE                     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5: Swarm Controller    │ Step-based execution       │
│  LAYER 4: Agent Hierarchy     │ 6 specialized roles         │
│  LAYER 3: Communication       │ AlgebraicMessage, Channels  │
│  LAYER 2: Rule Engine         │ Forward-chaining + unification│
│  LAYER 1: Algebraic Core      │ SAC with 10 operators       │
└─────────────────────────────────────────────────────────────┘
```

### Algebraic Operators
| Symbol | Name | Semantics |
|--------|------|-----------|
| ⊗ | COMPOSE | Sequential composition |
| ⊕ | UNION | Parallel combination |
| ¬ | NEGATE | Logical negation |
| π | PROJECT | Extract / select |
| ι | INJECT | Embed into space |
| β | BIND | Parameterize |
| ρ | REDUCE | Aggregate |
| τ | TRANSFORM | Cross-domain map |
| γ | GUARD | Conditional |
| μ | FIXPOINT | Iterate to convergence |

### Message Flow
```
User → Orchestrator → [Analyst | Planner → Executor → Validator → Synthesizer] → Orchestrator → ✓
```

---

## API Reference

### ConceptAtom
```python
atom = ConceptAtom.create(name, category, domain="general", metadata=None)
atom.name           # str
atom.category       # ConceptCategory
atom.domain         # str
atom.metadata       # Dict[str, str]
atom.serialize()    # "ATOM(name:CATEGORY:domain)", or "ATOM(name:CATEGORY:domain{k=v,...})" with metadata
atom.matches_pattern(pattern)  # bool
atom.with_domain(new_domain)   # ConceptAtom
```

### Expression
```python
# Construction
e = Expression.from_atom(atom)
e = Expression.from_operator(op, *operands, bindings=None)

# Properties
e.is_leaf    # bool
e.atom       # Optional[ConceptAtom]
e.depth      # int (cached)
e.atoms      # FrozenSet[ConceptAtom] (cached)
e.operator   # Optional[Operator]
e.operands   # Tuple[...]
e.bindings   # Dict[str, Any]

# Operations
e.substitute(old, new)  # Expression
e.serialize()            # str (cached)
e.to_dict()              # dict
e @ other  # COMPOSE     (matmul)
e | other  # UNION       (or)
~e         # NEGATE      (invert)
```

### C Factory
```python
C.entity(name, domain="general", metadata=None)
C.action(name, ...)
C.property(name, ...)
C.constraint(name, ...)
C.goal(name, ...)
C.state(name, ...)
C.compose(*exprs)       # ⊗
C.union(*exprs)          # ⊕
C.guard(condition, body) # γ
```

### Rule Engine
```python
rule = Rule(name, pattern, replacement, condition=None)
rule.apply(expression)   # Optional[Expression]

engine = RuleEngine()
engine.add_rule(rule)
engine.normalize(expression)  # Expression
engine.evaluate(expression)    # Expression
```

### SwarmController
```python
swarm = create_default_swarm()
swarm.inject_task(expression)                    # str (task_id)
swarm.step()                                      # int (messages processed)
swarm.converged                                   # bool (3 consecutive idle steps)
swarm.snapshot()                                  # Dict (current frame)
swarm.latest_snapshot                             # Optional[Dict] (frame from last step)
swarm.run_until_convergence(max_steps=50)         # Dict
swarm.export_trace()                              # Dict
swarm.save_trace("trace.json")                    # None
```

---

## Files

| File | Description |
|------|-------------|
| `asis/core.py` | Engine: algebra, parser, rule engine, agent hierarchy, swarm controller, trace export |
| `asis/cli.py` | `asis run` and `asis dashboard` commands |
| `asis/server.py` | Dashboard HTTP server and JSON API (standard library only) |
| `asis/dashboard.html` | Dashboard client: renders engine frames live or from a trace (loads web fonts from Google Fonts) |
| `asis_trace.json` | Sample trace produced by `asis run` |
| `pyproject.toml` | Packaging metadata and tool configuration |
| `build.sh` | Builds a standalone binary with PyInstaller |
| `CHANGELOG.md` | Release notes |
| `LICENSE.md` | MIT License |
| `tests/` | Test suite (190+ tests) |

---

## Keyboard Shortcuts (Dashboard)

| Key | Action |
|-----|--------|
| `Space` | Pause / Resume stepping |
| `→` | Advance one step |
| `Ctrl + Enter` | Open the task injection dialog, or submit it when open |
| `Escape` | Close the dialog |
| `Click agent` | Select agent (hover for details) |

---

## Mathematical Properties

- **Closed Algebra**: All operators produce valid Expression trees
- **Associativity**: COMPOSE and UNION are associative (flattened automatically)
- **Identity**: `_identity` element for COMPOSE
- **Absorption**: `_zero` element absorbs in COMPOSE
- **Idempotence**: A ⊕ A = A
- **Double Negation**: ¬¬A = A
- **Determinism**: Zero randomness in core execution; same inputs → byte-identical trace

### Limits
Expressions are processed recursively, so with Python's default recursion limit, trees nested deeper than roughly 800–900 levels raise `RecursionError`. Width is not limited in the same way.

---

## License

This project is licensed under the MIT License — see [LICENSE.md](LICENSE.md).

---

*Built on the Symbolic Algebra of Concepts — where agents communicate through expression trees, not natural language.*
