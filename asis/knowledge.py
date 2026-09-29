"""Knowledge base: the shared "genome" every specialist can read.

A knowledge base describes a domain in three parts:

* **metrics** — measurable quantities with a unit and a baseline value
  (``latency`` 180 ms, ``throughput`` 400 rps, ...). ``cost`` always exists.
* **actions** — interventions with a cost, effects on metrics, capabilities
  they provide, prerequisites (``requires``), mutual exclusions
  (``conflicts``) and a maximum number of uses.
* **goals** — named objectives that decompose into capabilities and/or
  sub-goals.

Plans are multisets of actions. A plan's predicted metrics are

    value = (baseline + Σ count·add) · Π factor^count

clamped to the metric's ``min``/``max``. The cost metric additionally
includes ``Σ count·action.cost``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

# A plan is a canonical, hashable multiset: ((action, count), ...) sorted by name.
Plan = Tuple[Tuple[str, int], ...]

EMPTY_PLAN: Plan = ()
_ROUND = 6


class KnowledgeBaseError(ValueError):
    """Raised when a knowledge base definition is invalid."""

    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__("invalid knowledge base:\n  - " + "\n  - ".join(problems))


class ConstraintError(ValueError):
    """Raised when a constraint cannot be parsed against a knowledge base."""


# ============================================================================
# UNITS
# ============================================================================

# Each family maps a unit to its size in the family's base unit.
_UNIT_FAMILIES: Dict[str, Dict[str, float]] = {
    "time": {"ns": 1e-6, "us": 1e-3, "µs": 1e-3, "ms": 1.0, "s": 1000.0, "sec": 1000.0, "min": 60000.0},
    "rate": {"rps": 1.0, "qps": 1.0, "/s": 1.0, "rpm": 1 / 60, "rph": 1 / 3600},
    "percent": {"%": 1.0, "pct": 1.0, "percent": 1.0},
    "money": {"usd": 1.0, "$": 1.0},
}


def _unit_family(unit: str) -> Optional[str]:
    for family, units in _UNIT_FAMILIES.items():
        if unit in units:
            return family
    return None


def convert(value: float, from_unit: Optional[str], to_unit: str) -> float:
    """Convert ``value`` from ``from_unit`` to ``to_unit`` (``None`` means "already in to_unit")."""
    if not from_unit or from_unit == to_unit:
        return value
    family = _unit_family(from_unit)
    if family is None or family != _unit_family(to_unit):
        raise ConstraintError(f"unit '{from_unit}' is not compatible with '{to_unit or 'unitless'}'")
    units = _UNIT_FAMILIES[family]
    return value * units[from_unit] / units[to_unit]


# ============================================================================
# DOMAIN MODEL
# ============================================================================

@dataclass(frozen=True)
class Metric:
    name: str
    unit: str = ""
    baseline: float = 0.0
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    aliases: Tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Effect:
    add: float = 0.0
    factor: float = 1.0


@dataclass(frozen=True)
class Action:
    name: str
    cost: float = 0.0
    effects: Mapping[str, Effect] = field(default_factory=dict)
    provides: FrozenSet[str] = frozenset()
    requires: Tuple[str, ...] = ()
    conflicts: FrozenSet[str] = frozenset()
    max_uses: int = 1
    description: str = ""


@dataclass(frozen=True)
class Goal:
    name: str
    needs: Tuple[str, ...] = ()
    description: str = ""


_OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "=": "==", "==": "==", "!=": "!=",
        "≤": "<=", "≥": ">=", "≠": "!="}
_NEGATED = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
_CONSTRAINT_RE = re.compile(
    r"^\s*(?P<metric>.+?)\s*(?P<op><=|>=|==|!=|≤|≥|≠|<|>|=)\s*"
    r"(?P<num>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>[^\s\d.][^\s]*)?\s*$"
)
_STRICT_EPS = 1e-6


@dataclass(frozen=True)
class Constraint:
    """A numeric bound on one metric, with its value in the metric's unit."""

    metric: str
    op: str
    value: float
    text: str

    def negated(self) -> Constraint:
        return Constraint(self.metric, _NEGATED[self.op], self.value, f"¬({self.text})")

    def violation(self, actual: float) -> float:
        """0.0 when satisfied, otherwise the relative distance to the bound."""
        v, a = self.value, actual
        scale = max(abs(v), 1e-9)
        tol = 1e-9 * max(1.0, abs(v))
        if self.op == "<":
            return 0.0 if a < v - tol else (a - v) / scale + _STRICT_EPS
        if self.op == "<=":
            return 0.0 if a <= v + tol else (a - v) / scale
        if self.op == ">":
            return 0.0 if a > v + tol else (v - a) / scale + _STRICT_EPS
        if self.op == ">=":
            return 0.0 if a >= v - tol else (v - a) / scale
        if self.op == "==":
            return 0.0 if abs(a - v) <= tol else abs(a - v) / scale
        return 0.0 if abs(a - v) > tol else _STRICT_EPS  # "!="

    def satisfied(self, actual: float) -> bool:
        return self.violation(actual) == 0.0

    def describe(self, unit: str = "") -> str:
        sep = "" if unit in ("", "%") else " "
        return f"{self.metric} {self.op} {_fmt(self.value)}{sep}{unit}"

    def to_dict(self) -> Dict[str, Any]:
        return {"metric": self.metric, "op": self.op, "value": self.value, "text": self.text}

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Constraint:
        return Constraint(d["metric"], d["op"], float(d["value"]), d["text"])


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def _norm_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", "_", name.strip().lower())


# ============================================================================
# PLANS
# ============================================================================

def make_plan(counts: Mapping[str, int]) -> Plan:
    return tuple(sorted((a, int(n)) for a, n in counts.items() if n > 0))


def plan_counts(plan: Plan) -> Dict[str, int]:
    return dict(plan)


def plan_key(plan: Plan) -> str:
    if not plan:
        return "∅"
    return ",".join(a if n == 1 else f"{a}×{n}" for a, n in plan)


def plan_add(plan: Plan, action: str, n: int = 1) -> Plan:
    counts = plan_counts(plan)
    counts[action] = counts.get(action, 0) + n
    return make_plan(counts)


# ============================================================================
# KNOWLEDGE BASE
# ============================================================================

class KnowledgeBase:
    def __init__(self, name: str, metrics: Iterable[Metric], actions: Iterable[Action],
                 goals: Iterable[Goal] = (), description: str = ""):
        self.name = name
        self.description = description
        self.metrics: Dict[str, Metric] = {m.name: m for m in sorted(metrics, key=lambda m: m.name)}
        if "cost" not in self.metrics:
            self.metrics = dict(sorted({**self.metrics, "cost": Metric("cost", "usd", 0.0)}.items()))
        self.actions: Dict[str, Action] = {a.name: a for a in sorted(actions, key=lambda a: a.name)}
        self.goals: Dict[str, Goal] = {g.name: g for g in sorted(goals, key=lambda g: g.name)}
        self.capabilities: FrozenSet[str] = frozenset(c for a in self.actions.values() for c in a.provides)
        self._aliases: Dict[str, str] = {}
        for m in self.metrics.values():
            for alias in (m.name, *m.aliases):
                self._aliases[_norm_name(alias)] = m.name
        problems = self._validate()
        if problems:
            raise KnowledgeBaseError(problems)

    # --- construction -------------------------------------------------------

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> KnowledgeBase:
        problems: List[str] = []

        def num(where: str, value: Any, default: float = 0.0) -> float:
            if value is None:
                return default
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                problems.append(f"{where}: expected a finite number, got {value!r}")
                return default
            return float(value)

        def names(where: str, value: Any) -> Tuple[str, ...]:
            if value is None:
                return ()
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                problems.append(f"{where}: expected a list of names")
                return ()
            return tuple(value)

        metrics = []
        for name, m in (data.get("metrics") or {}).items():
            m = m or {}
            metrics.append(Metric(
                name=name, unit=m.get("unit", ""), baseline=num(f"metric {name}.baseline", m.get("baseline")),
                minimum=None if m.get("min") is None else num(f"metric {name}.min", m.get("min")),
                maximum=None if m.get("max") is None else num(f"metric {name}.max", m.get("max")),
                aliases=names(f"metric {name}.aliases", m.get("aliases")),
                description=m.get("description", ""),
            ))
        actions = []
        for name, a in (data.get("actions") or {}).items():
            a = a or {}
            effects = {}
            for metric, e in (a.get("effects") or {}).items():
                e = e or {}
                effects[metric] = Effect(add=num(f"action {name}.effects.{metric}.add", e.get("add")),
                                         factor=num(f"action {name}.effects.{metric}.factor", e.get("factor"), 1.0))
            max_uses = a.get("max_uses", 1)
            if isinstance(max_uses, bool) or not isinstance(max_uses, int) or max_uses < 1:
                problems.append(f"action {name}.max_uses: expected a positive integer, got {max_uses!r}")
                max_uses = 1
            actions.append(Action(
                name=name, cost=num(f"action {name}.cost", a.get("cost")), effects=effects,
                provides=frozenset(names(f"action {name}.provides", a.get("provides"))),
                requires=names(f"action {name}.requires", a.get("requires")),
                conflicts=frozenset(names(f"action {name}.conflicts", a.get("conflicts"))),
                max_uses=max_uses, description=a.get("description", ""),
            ))
        goals = [Goal(name=name, needs=names(f"goal {name}.needs", (g or {}).get("needs")),
                      description=(g or {}).get("description", ""))
                 for name, g in (data.get("goals") or {}).items()]
        if problems:
            raise KnowledgeBaseError(problems)
        return KnowledgeBase(data.get("name", "unnamed"), metrics, actions, goals, data.get("description", ""))

    @staticmethod
    def load(path: str | Path) -> KnowledgeBase:
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise KnowledgeBaseError([f"{path}: not valid JSON ({e})"]) from e
        return KnowledgeBase.from_dict(data)

    @staticmethod
    def default() -> KnowledgeBase:
        """The bundled ``web_service`` example domain."""
        text = resources.files("asis").joinpath("domains/web_service.json").read_text(encoding="utf-8")
        return KnowledgeBase.from_dict(json.loads(text))

    def _validate(self) -> List[str]:
        problems = []
        for m in self.metrics.values():
            if m.minimum is not None and m.maximum is not None and m.minimum > m.maximum:
                problems.append(f"metric {m.name}: min is greater than max")
        for a in self.actions.values():
            for metric, e in a.effects.items():
                if metric not in self.metrics:
                    problems.append(f"action {a.name}: effect on unknown metric '{metric}'")
                if e.factor <= 0:
                    problems.append(f"action {a.name}: factor on '{metric}' must be positive")
            for r in a.requires:
                if r not in self.actions:
                    problems.append(f"action {a.name}: requires unknown action '{r}'")
                elif r in a.conflicts or a.name in self.actions[r].conflicts:
                    problems.append(f"action {a.name}: requires '{r}' but conflicts with it")
            for c in a.conflicts:
                if c not in self.actions:
                    problems.append(f"action {a.name}: conflicts with unknown action '{c}'")
        for g in self.goals.values():
            for need in g.needs:
                if need not in self.goals and need not in self.capabilities:
                    problems.append(f"goal {g.name}: needs '{need}', which is neither a goal nor a capability")
            if g.name in self.capabilities:
                problems.append(f"goal {g.name}: name clashes with a capability")
        problems.extend(self._goal_cycles())
        return problems

    def _goal_cycles(self) -> List[str]:
        problems, state = [], {}

        def visit(name: str, path: List[str]) -> None:
            if state.get(name) == "done":
                return
            if state.get(name) == "active":
                problems.append("goal cycle: " + " → ".join(path[path.index(name):] + [name]))
                return
            state[name] = "active"
            for need in self.goals[name].needs:
                if need in self.goals:
                    visit(need, path + [name])
            state[name] = "done"

        for name in self.goals:
            visit(name, [])
        return problems

    # --- queries -----------------------------------------------------------

    def resolve_metric(self, name: str) -> Optional[Metric]:
        canonical = self._aliases.get(_norm_name(name))
        return self.metrics.get(canonical) if canonical else None

    def parse_constraint(self, text: str) -> Constraint:
        match = _CONSTRAINT_RE.match(text)
        if not match:
            raise ConstraintError(f"cannot read '{text}' as a constraint (expected e.g. 'latency < 100ms')")
        metric = self.resolve_metric(match["metric"])
        if metric is None:
            known = ", ".join(self.metrics)
            raise ConstraintError(f"unknown metric '{match['metric'].strip()}' in '{text}' (known: {known})")
        value = convert(float(match["num"]), match["unit"], metric.unit)
        return Constraint(metric.name, _OPS[match["op"]], round(value, _ROUND), text.strip())

    def providers(self, capability: str) -> List[Action]:
        return sorted((a for a in self.actions.values() if capability in a.provides), key=lambda a: (a.cost, a.name))

    def estimate(self, plan: Plan) -> Dict[str, float]:
        counts = plan_counts(plan)
        result = {}
        for m in self.metrics.values():
            add, factor = 0.0, 1.0
            for action_name, n in counts.items():
                action = self.actions[action_name]
                e = action.effects.get(m.name)
                if e:
                    add += e.add * n
                    factor *= e.factor ** n
                if m.name == "cost":
                    add += action.cost * n
            value = (m.baseline + add) * factor
            if m.minimum is not None:
                value = max(m.minimum, value)
            if m.maximum is not None:
                value = min(m.maximum, value)
            result[m.name] = round(value, _ROUND)
        return result

    def with_prerequisites(self, plan: Plan) -> Plan:
        counts = plan_counts(plan)
        pending = list(counts)
        while pending:
            for r in self.actions[pending.pop()].requires:
                if counts.get(r, 0) == 0:
                    counts[r] = 1
                    pending.append(r)
        return make_plan(counts)

    def plan_problems(self, plan: Plan) -> List[str]:
        """Structural problems: unknown actions, over-use, missing prerequisites, conflicts."""
        problems = []
        counts = plan_counts(plan)
        for name, n in plan:
            action = self.actions.get(name)
            if action is None:
                problems.append(f"unknown action '{name}'")
                continue
            if n > action.max_uses:
                problems.append(f"'{name}' used {n} times (max {action.max_uses})")
            for r in action.requires:
                if counts.get(r, 0) == 0:
                    problems.append(f"'{name}' requires '{r}'")
            for c in sorted(action.conflicts):
                if counts.get(c, 0) and name < c:
                    problems.append(f"'{name}' conflicts with '{c}'")
        return problems

    def provided(self, plan: Plan) -> FrozenSet[str]:
        return frozenset(c for name, _ in plan for c in self.actions[name].provides)

    def to_dict(self) -> Dict[str, Any]:
        def effect(e: Effect) -> Dict[str, float]:
            d = {}
            if e.add:
                d["add"] = e.add
            if e.factor != 1.0:
                d["factor"] = e.factor
            return d

        return {
            "name": self.name,
            "description": self.description,
            "metrics": {m.name: {k: v for k, v in {
                "unit": m.unit, "baseline": m.baseline, "min": m.minimum, "max": m.maximum,
                "aliases": list(m.aliases) or None, "description": m.description or None,
            }.items() if v is not None} for m in self.metrics.values()},
            "actions": {a.name: {k: v for k, v in {
                "cost": a.cost, "effects": {k: effect(e) for k, e in sorted(a.effects.items())} or None,
                "provides": sorted(a.provides) or None, "requires": list(a.requires) or None,
                "conflicts": sorted(a.conflicts) or None, "max_uses": a.max_uses if a.max_uses != 1 else None,
                "description": a.description or None,
            }.items() if v is not None} for a in self.actions.values()},
            "goals": {g.name: {k: v for k, v in {
                "needs": list(g.needs), "description": g.description or None,
            }.items() if v is not None} for g in self.goals.values()},
        }
