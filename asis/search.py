"""Typed search operations and bounded, residual-directed compositions.

This is a small executable language for prediction-based search, not a claim
that arbitrary algorithms can be synthesized. Plans remain unordered action
multisets; operation graphs describe computations, never action timing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from asis.knowledge import Constraint, KnowledgeBase, Plan, make_plan, plan_add, plan_counts, plan_key


@dataclass(frozen=True)
class SearchConfig:
    """Finite allowances for composition, separate from message energy.

    ``max_evaluations`` is the total composition prediction allowance per task;
    estimates made by the original specialists are also counted in results but
    do not consume this separate allowance. Depth counts extension decisions;
    each extension includes prerequisite closure.
    """

    max_depth: int = 3
    beam_width: int = 8
    max_evaluations: int = 256

    def __post_init__(self) -> None:
        for name in ("max_depth", "beam_width", "max_evaluations"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> Dict[str, int]:
        return {"max_depth": self.max_depth, "beam_width": self.beam_width,
                "max_evaluations": self.max_evaluations}


def model_fingerprint(kb: KnowledgeBase) -> str:
    """Guard reuse with the complete declared model, including units and bounds."""
    return hashlib.sha256(json.dumps(kb.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Prediction:
    metrics: Mapping[str, float]
    model: str
    evidence: str = "model_prediction"


@dataclass(frozen=True)
class Residual:
    constraint: Constraint
    actual: float
    gap: float

    def to_dict(self) -> Dict[str, Any]:
        return {"constraint": self.constraint.text, "metric": self.constraint.metric,
                "actual": self.actual, "op": self.constraint.op, "target": self.constraint.value,
                "gap": self.gap}


@dataclass(frozen=True)
class ResidualVector:
    entries: Tuple[Residual, ...]

    @property
    def total(self) -> float:
        return round(sum(r.gap for r in self.entries), 9)

    @property
    def unmet(self) -> Tuple[str, ...]:
        return tuple(sorted({r.constraint.metric for r in self.entries if r.gap > 0}))

    def improves(self, before: ResidualVector) -> bool:
        return any(a.gap < b.gap - 1e-12 for a, b in zip(self.entries, before.entries, strict=True))

    def to_dict(self) -> list:
        return [r.to_dict() for r in self.entries]


@dataclass(frozen=True)
class Operation:
    name: str
    purpose: str
    input_types: Tuple[type, ...]
    output_type: type
    implementation: Callable = field(repr=False, compare=False)
    preconditions: Tuple[str, ...] = ()
    postconditions: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    cost: str = "constant overhead"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "purpose": self.purpose,
                "inputs": [t.__name__ for t in self.input_types], "output": self.output_type.__name__,
                "preconditions": list(self.preconditions), "postconditions": list(self.postconditions),
                "assumptions": list(self.assumptions), "cost": self.cost}


class OperationRegistry:
    """Operations validate input/output types without hiding acceptance policy."""

    def __init__(self) -> None:
        self._operations: Dict[str, Operation] = {}

    def register(self, operation: Operation) -> None:
        if operation.name in self._operations:
            raise ValueError(f"operation '{operation.name}' already registered")
        self._operations[operation.name] = operation

    def operation(self, name: str) -> Operation:
        return self._operations[name]

    def invoke(self, name: str, *inputs: Any) -> Any:
        op = self.operation(name)
        if len(inputs) != len(op.input_types) or any(not isinstance(v, t) for v, t in zip(inputs, op.input_types, strict=True)):
            raise TypeError(f"{name} expects {', '.join(t.__name__ for t in op.input_types)}")
        result = op.implementation(*inputs)
        if not isinstance(result, op.output_type):
            raise TypeError(f"{name} returned an incompatible result")
        return result

    def to_dict(self) -> list:
        return [op.to_dict() for op in self._operations.values()]


@dataclass(frozen=True)
class Step:
    operation: str
    inputs: Tuple[str, ...]
    output: str

    def to_dict(self) -> Dict[str, Any]:
        return {"operation": self.operation, "inputs": list(self.inputs), "output": self.output}


@dataclass(frozen=True)
class OperatorGraph:
    """A finite, acyclic sequence whose input bindings are checked before execution."""

    steps: Tuple[Step, ...]

    def run(self, registry: OperationRegistry, bindings: Mapping[str, Any]) -> Dict[str, Any]:
        values = dict(bindings)
        available = {name: type(value) for name, value in values.items()}
        for step in self.steps:
            operation = registry.operation(step.operation)
            if step.output in available:
                raise ValueError(f"graph binding '{step.output}' is assigned twice")
            if len(step.inputs) != len(operation.input_types):
                raise TypeError(f"incompatible arity for {step.operation}")
            for source, expected in zip(step.inputs, operation.input_types, strict=True):
                if source not in available:
                    raise ValueError(f"graph input '{source}' has no producer")
                if not issubclass(available[source], expected):
                    raise TypeError(f"incompatible graph input '{source}' for {step.operation}")
            available[step.output] = operation.output_type
        for step in self.steps:
            values[step.output] = registry.invoke(step.operation, *(values[s] for s in step.inputs))
        return values

    def to_dict(self) -> list:
        return [step.to_dict() for step in self.steps]


def choices(plan: Plan, kb: KnowledgeBase, forbidden: Iterable[str]) -> Tuple[str, ...]:
    counts, excluded = plan_counts(plan), set(forbidden)
    return tuple(a.name for a in kb.actions.values() if a.name not in excluded
                 and counts.get(a.name, 0) < a.max_uses)


def extend(plan: Plan, action: str, kb: KnowledgeBase) -> Plan:
    """Extend one decision and explicitly close its declared prerequisites."""
    return kb.with_prerequisites(plan_add(plan, action))


def predict(plan: Plan, kb: KnowledgeBase, predictor: Callable) -> Prediction:
    return Prediction(predictor(plan), model_fingerprint(kb))


def residual(prediction: Prediction, constraints: Sequence) -> ResidualVector:
    return ResidualVector(tuple(Residual(c, prediction.metrics[c.metric], c.violation(prediction.metrics[c.metric]))
                                for c in constraints))


def check(value: Any, predicate: Callable) -> bool:
    return bool(predicate(value))


def default_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(Operation("canonicalize", "Give equivalent action counts the same plan representation.",
                                (Mapping,), tuple, make_plan, postconditions=("sorted positive counts",)))
    registry.register(Operation("choices", "Expose available extension decisions.",
                                (tuple, KnowledgeBase, Iterable), tuple, choices,
                                postconditions=("forbidden actions excluded", "use counts bounded"), cost="O(actions)"))
    registry.register(Operation("extend", "Add a decision with declared prerequisite closure.",
                                (tuple, str, KnowledgeBase), tuple, extend,
                                preconditions=("action exists",), postconditions=("prerequisites included",),
                                assumptions=("plans are action multisets",), cost="O(prerequisite graph)"))
    registry.register(Operation("predict", "Calculate model metrics without accepting or rejecting a plan.",
                                (tuple, KnowledgeBase, Callable), Prediction, predict,
                                preconditions=("structurally valid plan",),
                                postconditions=("evidence remains model_prediction",),
                                assumptions=("declared order-independent effect model",), cost="one model evaluation"))
    registry.register(Operation("residual", "Measure every declared numeric obligation.",
                                (Prediction, Sequence), ResidualVector, residual,
                                postconditions=("hard requirements are never reweighted",), cost="O(constraints)"))
    registry.register(Operation("check", "Test one explicit predicate without changing the candidate.",
                                (object, Callable), bool, check))
    return registry


PREDICTION_GRAPH = OperatorGraph((Step("predict", ("candidate", "model", "predictor"), "prediction"),
                                  Step("residual", ("prediction", "constraints"), "residuals"),
                                  Step("check", ("residuals", "acceptance"), "accepted")))


@dataclass(frozen=True)
class Candidate:
    plan: Plan
    prediction: Prediction
    residuals: ResidualVector
    actions: Tuple[str, ...] = ()
    obligations: Tuple[Tuple[str, ...], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"plan": [list(p) for p in self.plan], "metrics": dict(self.prediction.metrics),
                "residuals": self.residuals.to_dict(), "actions": list(self.actions),
                "obligations": [list(o) for o in self.obligations], "evidence": self.prediction.evidence}


@dataclass(frozen=True)
class GuardedProcedure:
    model: str
    actions: Tuple[str, ...]
    obligations: Tuple[Tuple[str, ...], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"model": self.model, "actions": list(self.actions),
                "obligations": [list(o) for o in self.obligations],
                "guards": ["model fingerprint", "action availability", "use limits", "prerequisites",
                           "current forbidden actions", "current requirements", "fresh prediction and validation"]}


class ProcedureMemory:
    """Small session-local library; invalid model guards actively expire entries."""

    def __init__(self, capacity: int = 64):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._procedures: Dict[Tuple[str, Tuple[str, ...]], GuardedProcedure] = {}

    def remember(self, procedure: GuardedProcedure) -> None:
        key = (procedure.model, procedure.actions)
        if key not in self._procedures and len(self._procedures) >= self.capacity:
            self._procedures.pop(next(iter(self._procedures)))
        self._procedures[key] = procedure

    def compatible(self, kb: KnowledgeBase) -> Tuple[GuardedProcedure, ...]:
        signature = model_fingerprint(kb)
        for key in list(self._procedures):
            if key[0] != signature:
                del self._procedures[key]
        return tuple(self._procedures.values())


@dataclass
class CompositionResult:
    candidates: list = field(default_factory=list)
    evaluations: int = 0
    deferred: int = 0
    frontier: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    reused: bool = False
    stop_reason: str = "depth allowance reached"

    def to_dict(self) -> Dict[str, Any]:
        return {"candidates": [c.to_dict() for c in self.candidates], "evaluations": self.evaluations,
                "deferred": self.deferred, "frontier": self.frontier, "nodes": self.nodes,
                "reused": self.reused, "stop_reason": self.stop_reason, "coverage_complete": False,
                "graph": PREDICTION_GRAPH.to_dict()}


class BoundedComposer:
    """Compose extension decisions using explicit residuals and finite allowances.

    Deferred candidates may worsen total violation when they improve at least
    one unmet condition. The next extension gives priority to actions affecting
    their outstanding residuals. Beam priority is never an infeasibility bound.
    """

    def __init__(self, config: SearchConfig, registry: Optional[OperationRegistry] = None):
        self.config = config
        self.registry = registry or default_registry()

    def compose(self, initial: Plan, before: Mapping[str, float], kb: KnowledgeBase,
                constraints: Sequence[Constraint], forbidden: Iterable[str], predictor: Callable,
                valid: Callable, proposed: Callable, allowance: Optional[int] = None,
                procedures: Sequence[GuardedProcedure] = ()) -> CompositionResult:
        result = CompositionResult()
        limit = self.config.max_evaluations if allowance is None else min(self.config.max_evaluations, max(0, allowance))
        signature = model_fingerprint(kb)
        origin = Candidate(initial, Prediction(before, signature), residual(Prediction(before, signature), constraints))
        excluded = tuple(forbidden)
        seen = {initial}

        def evaluate(plan: Plan, parent: Candidate, actions: Tuple[str, ...], obligations: tuple) -> Candidate:
            values = PREDICTION_GRAPH.run(self.registry, {"candidate": plan, "model": kb, "predictor": predictor,
                "constraints": constraints, "acceptance": lambda r: not r.unmet})
            result.evaluations += 1
            candidate = Candidate(plan, values["prediction"], values["residuals"], actions, obligations)
            result.nodes.append({**candidate.to_dict(), "parent": plan_key(parent.plan), "depth": len(actions),
                                 "accepted": values["accepted"]})
            return candidate

        # A remembered computation is a proposal: all guards and metrics are
        # checked again, even when the numeric thresholds look familiar.
        for procedure in procedures:
            if result.evaluations >= limit:
                break
            if procedure.model != signature or len(procedure.actions) > self.config.max_depth:
                continue
            grown = initial
            for action in procedure.actions:
                if action not in self.registry.invoke("choices", grown, kb, excluded):
                    break
                grown = self.registry.invoke("extend", grown, action, kb)
                if not valid(grown):
                    break
            else:
                if grown in seen or proposed(grown):
                    continue
                candidate = evaluate(grown, origin, procedure.actions, procedure.obligations)
                if not candidate.residuals.unmet:
                    result.candidates.append(candidate)
                    result.reused = True
                    result.stop_reason = "guarded procedure proposed for independent validation"
                    return result

        frontier = [origin]
        for _depth in range(1, self.config.max_depth + 1):
            next_frontier = []
            for index, parent in enumerate(frontier):
                available = self.registry.invoke("choices", parent.plan, kb, excluded)
                # Merely affecting a residual grants priority, never permission
                # to weaken it or claim an unvisited branch impossible.
                available = sorted(available, key=lambda a: (not self._affects(a, parent.residuals.unmet, kb), a))
                for action_index, action in enumerate(available):
                    if result.evaluations >= limit:
                        result.stop_reason = "composition evaluation allowance reached"
                        result.frontier.append({"plan": plan_key(parent.plan), "reason": "evaluation allowance",
                                                "remaining_choices": len(available) - action_index})
                        result.frontier.extend({"plan": plan_key(n.plan), "reason": "evaluation allowance"}
                                               for n in frontier[index + 1:])
                        result.frontier.extend({"plan": plan_key(n.plan), "reason": "evaluation allowance"}
                                               for n in next_frontier)
                        self._sort(result)
                        return result
                    grown = self.registry.invoke("extend", parent.plan, action, kb)
                    if grown in seen or not valid(grown):
                        continue
                    seen.add(grown)
                    candidate = evaluate(grown, parent, (*parent.actions, action),
                                         (*parent.obligations, parent.residuals.unmet))
                    helpful = candidate.residuals.improves(parent.residuals)
                    if candidate.residuals.total < origin.residuals.total - 1e-12 and not proposed(grown):
                        result.candidates.append(candidate)
                    if helpful and candidate.residuals.unmet:
                        if candidate.residuals.total >= parent.residuals.total:
                            result.deferred += 1
                        next_frontier.append(candidate)
                    elif candidate.residuals.unmet:
                        result.frontier.append({"plan": plan_key(grown), "reason": "residual priority"})
                # Finish this layer to compare equally short feasible proposals.
            if any(not c.residuals.unmet for c in result.candidates):
                result.stop_reason = "feasible composition proposed for independent validation"
                result.frontier.extend({"plan": plan_key(n.plan), "reason": "feasible proposal found"} for n in next_frontier)
                self._sort(result)
                return result
            next_frontier.sort(key=lambda c: (c.residuals.total, c.prediction.metrics["cost"], plan_key(c.plan)))
            result.frontier.extend({"plan": plan_key(n.plan), "reason": "beam allowance"}
                                   for n in next_frontier[self.config.beam_width:])
            frontier = next_frontier[:self.config.beam_width]
            if not frontier:
                result.stop_reason = "no further residual-guided extensions"
                self._sort(result)
                return result
        result.frontier.extend({"plan": plan_key(n.plan), "reason": "depth allowance"} for n in frontier)
        self._sort(result)
        return result

    @staticmethod
    def _sort(result: CompositionResult) -> None:
        result.candidates.sort(key=lambda c: (bool(c.residuals.unmet), c.residuals.total,
                                             c.prediction.metrics["cost"], plan_key(c.plan)))

    @staticmethod
    def _affects(action: str, metrics: Tuple[str, ...], kb: KnowledgeBase) -> bool:
        closure = kb.with_prerequisites(((action, 1),))
        return any((metric == "cost" and kb.actions[name].cost != 0) or metric in kb.actions[name].effects
                   for name, _ in closure for metric in metrics)
