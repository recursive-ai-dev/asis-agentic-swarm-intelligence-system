# ASIS 2.0 — Algebraic Swarm Intelligence System

> *A deterministic, rule-based multi-agent architecture implementing a Symbolic Algebra of Concepts (SAC), with real-time cyberpunk visualization.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python 3.14+](https://img.shields.io/badge/Python-3.14+-blue.svg)](https://www.python.org/)

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
A self-contained, zero-dependency HTML dashboard featuring:
- **Force-directed agent network** with 6 specialized agent types
- **Animated message packets** traveling between agents in real-time
- **Neon glow effects** and particle systems
- **Live expression tree visualization**
- **Interactive task injection** — click "Inject Task" and watch the swarm solve it
- **Convergence detection** with animated banners
- **Full keyboard shortcuts** (Space to pause, Ctrl+Enter to inject, Escape to close)

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
- Canonical ordering via sorted processing and tuple-based bindings
- Full audit trail via global log, versioned blackboard, and execution snapshots
- **Same inputs always produce the same trace** — verified by the test suite

---

## Quick Start

### Open the Live Dashboard
Simply open `asis_dashboard.html` in any modern browser:
```bash
open asis_dashboard.html     # macOS
firefox asis_dashboard.html  # Linux
chrome asis_dashboard.html   # Windows / Linux
```

The dashboard runs a **live simulation** of the swarm in real-time. Watch as:
1. Tasks are injected into the Orchestrator
2. Messages pulse through the network as glowing packets
3. Agents light up when processing
4. The system converges to a fixed point

### Run the Engine
```bash
python asis.py
```

This executes a full symbolic simulation and exports a JSON trace to `asis_trace.json`.

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
pip install pytest
```

### Run Tests
```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pip install pytest-cov
pytest tests/ --cov=asis --cov-report=term-missing

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
atom.serialize()    # "ATOM(name:CATEGORY:domain)"
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
swarm.run_until_convergence(max_steps=50)         # Dict
swarm.export_trace()                              # Dict
swarm.save_trace("trace.json")                    # None
```

---

## Files

| File | Description |
|------|-------------|
| `asis.py` | Production-grade ASIS engine with rule engine, full agent hierarchy, and trace export |
| `asis_dashboard.html` | Self-contained interactive cyberpunk visualization (zero dependencies) |
| `asis_trace.json` | Sample execution trace from a 3-task simulation |
| `LICENSE.md` | MIT License |
| `tests/test_asis.py` | Comprehensive test suite (100+ tests across all modules) |

---

## Keyboard Shortcuts (Dashboard)

| Key | Action |
|-----|--------|
| `Space` | Pause / Resume simulation |
| `Ctrl + Enter` | Open task injection modal |
| `Escape` | Close modal |
| `Click agent` | Select agent (see details) |

---

## Mathematical Properties

- **Closed Algebra**: All operators produce valid Expression trees
- **Associativity**: COMPOSE and UNION are associative (flattened automatically)
- **Identity**: `_identity` element for COMPOSE
- **Absorption**: `_zero` element absorbs in COMPOSE
- **Idempotence**: A ⊕ A = A
- **Double Negation**: ¬¬A = A
- **Determinism**: Zero randomness in core execution; same inputs → same trace

---

## License

This project is licensed under the MIT License — see [LICENSE.md](LICENSE.md).

---

*Built on the Symbolic Algebra of Concepts — where agents communicate through expression trees, not natural language.*
