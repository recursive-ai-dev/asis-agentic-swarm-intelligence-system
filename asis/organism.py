"""The organism: signals, receptors, specialists, and the substrate between them.

Specialists never address each other. Each declares **receptors** — the
signal kinds (optionally filtered by a predicate) it responds to — and emits
signals into the shared medium. The :class:`SwarmController` is the
substrate: it delivers every signal to each *tissue* (group of interchangeable
specialists) with a matching receptor, picks the least-loaded cell within a
tissue, charges the task's **energy** budget for the work, and senses when a
task has gone **quiescent** (nothing in flight) or run out of energy. What to
do about that is decided by specialists, not by the substrate.

Every step: deliver last step's signals → every specialist processes its
inbox → the substrate senses task state. Processing order is registration
order, so identical inputs always produce identical traces.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, ClassVar, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from asis.core import ConceptAtom, ConceptCategory, Expression, Operator, __version__, parse_expression
from asis.knowledge import KnowledgeBase, Plan, plan_key


class Kind(str, Enum):
    """Signal kinds, in the order a task usually meets them."""

    TASK = "TASK"                  # user      → intake
    OPENED = "OPENED"              # intake    → immune: structured task spec
    CLEARED = "CLEARED"            # immune    → decomposer
    REJECTED = "REJECTED"          # immune, planner → judge
    REQUIREMENTS = "REQUIREMENTS"  # decomposer → planner, memory
    PROPOSAL = "PROPOSAL"          # planner, repairer, optimizer, memory → immune
    PLAN = "PLAN"                  # immune    → estimator
    ESTIMATE = "ESTIMATE"          # estimator → checker
    VERDICT = "VERDICT"            # checker   → repairer (violated) / optimizer (satisfied)
    QUIESCENT = "QUIESCENT"        # substrate → regulator: nothing in flight for the task
    EXHAUSTED = "EXHAUSTED"        # substrate → regulator: energy budget spent
    ESCALATE = "ESCALATE"          # regulator → repairer: search harder
    SETTLE = "SETTLE"              # regulator → judge: decide now
    RESULT = "RESULT"              # judge     → explainer, memory


# Vital signals are never dropped and cost no energy: an exhausted task must
# still be able to wind down and report.
VITAL = frozenset({Kind.QUIESCENT, Kind.EXHAUSTED, Kind.SETTLE, Kind.REJECTED, Kind.RESULT})

SUBSTRATE = "substrate"


@dataclass(frozen=True, eq=False)
class Signal:
    kind: Kind
    task_id: str
    sender: str
    payload: Expression
    data: Mapping[str, Any] = field(default_factory=dict)
    seq: int = -1
    step: int = -1

    def to_dict(self, receiver: Optional[str]) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "receiver": receiver,
            "message_type": self.kind.value,
            "task_id": self.task_id,
            "payload": self.payload.to_dict(),
            "payload_text": self.payload.serialize(),
            "data": self.data,
            "correlation_id": f"{self.seq:06d}",
            "timestamp": float(self.step),
        }


@dataclass(frozen=True)
class Receptor:
    kind: Kind
    when: Optional[Callable[[Signal], bool]] = None

    def matches(self, signal: Signal) -> bool:
        return signal.kind == self.kind and (self.when is None or bool(self.when(signal)))


# ============================================================================
# BLACKBOARD
# ============================================================================

class Blackboard:
    """Shared, append-only-history memory: the organism's extracellular medium."""

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._writers: Dict[str, str] = {}
        self._history: List[Dict[str, Any]] = []

    def write(self, key: str, value: Any, writer: str) -> None:
        self._data[key] = value
        self._writers[key] = writer
        self._history.append({"version": len(self._history), "key": key,
                              "value": _serialize(value), "writer": writer})

    def read(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._data

    def items(self, prefix: str) -> List[Tuple[str, Any]]:
        return [(k, v) for k, v in self._data.items() if k.startswith(prefix)]

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"value": _serialize(v), "writer": self._writers.get(k, "unknown")}
                for k, v in self._data.items()}


def _serialize(value: Any) -> str:
    if isinstance(value, Expression):
        return value.serialize()
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


# ============================================================================
# SPECIALISTS
# ============================================================================

@dataclass(frozen=True)
class Context:
    """What a specialist can see while handling a signal."""

    kb: KnowledgeBase
    board: Blackboard
    step: int


class Specialist(ABC):
    """A single-purpose agent. Subclasses set ``tissue``, ``receptors`` and ``handle``."""

    tissue: ClassVar[str] = "specialist"
    receptors: ClassVar[Tuple[Receptor, ...]] = ()
    metabolic_cost: ClassVar[int] = 1
    description: ClassVar[str] = ""

    def __init__(self, agent_id: Optional[str] = None):
        self.agent_id = agent_id or self.tissue
        self._inbox: List[Signal] = []
        self.processed = 0
        self.energy_spent = 0

    def responds_to(self, signal: Signal) -> bool:
        return any(r.matches(signal) for r in self.receptors)

    @abstractmethod
    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        """React to one signal; return the signals to emit (possibly none)."""

    def emit(self, kind: Kind, task_id: str, payload: Expression, **data: Any) -> Signal:
        return Signal(kind, task_id, self.agent_id, payload, data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.tissue.upper(),
            "tissue": self.tissue,
            "description": self.description,
            "receptors": sorted({r.kind.value for r in self.receptors}),
            "processed_count": self.processed,
            "inbox_size": len(self._inbox),
            "energy_spent": self.energy_spent,
        }


# ============================================================================
# TASKS
# ============================================================================

OPEN = "open"
STALLED = "stalled"


@dataclass
class TaskRecord:
    task_id: str
    text: str
    expression: Expression
    budget: int
    energy: int
    submitted_step: int
    status: str = OPEN
    closed_step: Optional[int] = None
    quiet_signaled: bool = False
    exhausted: bool = False

    @property
    def closed(self) -> bool:
        return self.status != OPEN


@dataclass(frozen=True)
class TaskResult:
    """The organism's answer to one task."""

    task_id: str
    task: str
    status: str                      # solved | unsolved | rejected | open | stalled
    plan: Dict[str, int]
    metrics: Dict[str, float]
    cost: Optional[float]
    violations: List[Dict[str, Any]]
    reason: str
    report: str
    energy_used: int
    budget: int

    @property
    def solved(self) -> bool:
        return self.status == "solved"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "task": self.task, "status": self.status, "plan": self.plan,
            "metrics": self.metrics, "cost": self.cost, "violations": self.violations,
            "reason": self.reason, "report": self.report,
            "energy_used": self.energy_used, "budget": self.budget,
        }


def plan_from_data(raw: Iterable[Iterable[Any]]) -> Plan:
    return tuple((str(a), int(n)) for a, n in raw)


def plan_expression(plan: Plan) -> Expression:
    """Render a plan as an algebraic expression: the ⊗ of its action atoms."""
    if not plan:
        return Expression.from_atom(Expression._IDENTITY_ATOM)
    atoms = [ConceptAtom.create(a, ConceptCategory.ACTION, "plan", {"count": str(n)} if n > 1 else None)
             for a, n in plan]
    return Expression.from_operator(Operator.COMPOSE, *atoms)


# ============================================================================
# SUBSTRATE
# ============================================================================

class SwarmController:
    """Carries signals between specialists and keeps the organism's vital signs."""

    DEFAULT_BUDGET = 400

    def __init__(self, kb: Optional[KnowledgeBase] = None, energy_budget: int = DEFAULT_BUDGET):
        self.kb = kb or KnowledgeBase.default()
        self.energy_budget = energy_budget
        self._agents: Dict[str, Specialist] = {}
        self._board = Blackboard()
        self._outbox: List[Signal] = []
        self._tasks: Dict[str, TaskRecord] = {}
        self._step = 0
        self._seq = itertools.count()
        self._log: List[Dict[str, Any]] = []
        self._snapshots: List[Dict[str, Any]] = []

    # --- composition --------------------------------------------------------

    def register_agent(self, agent: Specialist) -> None:
        if agent.agent_id in self._agents:
            raise ValueError(f"an agent with id '{agent.agent_id}' is already registered")
        self._agents[agent.agent_id] = agent

    def remove_agent(self, agent_id: str) -> Specialist:
        """Lesion: take a specialist out of the organism. Its inbox is lost."""
        return self._agents.pop(agent_id)

    @property
    def agents(self) -> Tuple[Specialist, ...]:
        return tuple(self._agents.values())

    @property
    def blackboard(self) -> Blackboard:
        return self._board

    # --- tasks --------------------------------------------------------------

    def submit(self, task: Union[str, Expression], budget: Optional[int] = None) -> str:
        """Submit a task (ASIS notation or an Expression). Returns its task id."""
        expression = parse_expression(task) if isinstance(task, str) else task
        text = task if isinstance(task, str) else expression.serialize()
        base = hashlib.sha256(expression.serialize().encode()).hexdigest()[:8]
        task_id, n = base, 1
        while task_id in self._tasks:
            n += 1
            task_id = f"{base}-{n}"
        budget = self.energy_budget if budget is None else budget
        self._tasks[task_id] = TaskRecord(task_id, text.strip(), expression, budget, budget, self._step)
        self._board.write(f"task:{task_id}", {"text": text.strip(), "expression": expression.serialize()}, "user")
        self._outbox.append(self._stamp(Signal(Kind.TASK, task_id, "user", expression, {"text": text.strip()})))
        return task_id

    def tasks(self) -> Dict[str, str]:
        return {tid: self._status(rec) for tid, rec in self._tasks.items()}

    def _status(self, rec: TaskRecord) -> str:
        # Nothing in flight means nothing can ever happen to this task again.
        if rec.status == OPEN and self.idle:
            return STALLED
        return rec.status

    def result(self, task_id: str) -> TaskResult:
        rec = self._tasks[task_id]
        r = self._board.read(f"result:{task_id}") or {}
        return TaskResult(
            task_id=task_id, task=rec.text, status=self._status(rec),
            plan=dict(plan_from_data(r.get("plan", []))), metrics=dict(r.get("metrics", {})),
            cost=r.get("cost"), violations=list(r.get("violations", [])),
            reason=r.get("reason", "" if rec.status != OPEN else "task has not finished"),
            report=self._board.read(f"report:{task_id}", ""),
            energy_used=rec.budget - rec.energy, budget=rec.budget,
        )

    # --- stepping -------------------------------------------------------------

    @property
    def step_count(self) -> int:
        return self._step

    @property
    def idle(self) -> bool:
        return not self._outbox and not any(a._inbox for a in self._agents.values())

    @property
    def converged(self) -> bool:
        """True when nothing is in flight and every task has an answer."""
        return self.idle and all(rec.closed for rec in self._tasks.values())

    @property
    def latest_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._snapshots[-1] if self._snapshots else None

    def _stamp(self, signal: Signal) -> Signal:
        return replace(signal, seq=next(self._seq), step=self._step)

    def step(self) -> int:
        """Deliver pending signals, let every specialist work, sense task state.

        Returns the number of deliveries made.
        """
        self._step += 1
        outgoing, self._outbox = self._outbox, []
        deliveries = self._deliver(outgoing)

        ctx = Context(self.kb, self._board, self._step)
        emitted: List[Signal] = []
        for agent in list(self._agents.values()):
            while agent._inbox:
                signal = agent._inbox.pop(0)
                for out in agent.handle(signal, ctx):
                    emitted.append(self._stamp(out))
                agent.processed += 1

        for signal in emitted:
            rec = self._tasks.get(signal.task_id)
            if rec is None:
                continue
            rec.quiet_signaled = False
            if signal.kind == Kind.RESULT and rec.status == OPEN:
                rec.status = str(signal.data.get("status", "unsolved"))
                rec.closed_step = self._step
        self._outbox.extend(emitted)
        self._sense()

        self._snapshots.append(self.snapshot(deliveries))
        return len(deliveries)

    def _deliver(self, signals: List[Signal]) -> List[Dict[str, Any]]:
        deliveries: List[Dict[str, Any]] = []
        for signal in signals:
            rec = self._tasks.get(signal.task_id)
            if rec is not None and rec.closed and signal.kind != Kind.RESULT:
                continue  # straggler for a finished task
            tissues: Dict[str, List[Specialist]] = {}
            for agent in self._agents.values():
                if agent.responds_to(signal):
                    tissues.setdefault(agent.tissue, []).append(agent)
            if not tissues:
                entry = signal.to_dict(None)
                deliveries.append(entry)
                self._log.append(entry)
                continue
            for cells in tissues.values():
                # Least busy cell right now, then the one that has done least overall;
                # min() keeps registration order for any remaining tie.
                cell = min(cells, key=lambda a: (len(a._inbox), a.processed))
                if rec is not None and signal.kind not in VITAL:
                    if rec.exhausted:
                        continue
                    if rec.energy < cell.metabolic_cost:
                        rec.exhausted = True
                        self._outbox.append(self._stamp(Signal(
                            Kind.EXHAUSTED, rec.task_id, SUBSTRATE, _state("exhausted"),
                            {"budget": rec.budget})))
                        continue
                    rec.energy -= cell.metabolic_cost
                    cell.energy_spent += cell.metabolic_cost
                cell._inbox.append(signal)
                entry = signal.to_dict(cell.agent_id)
                deliveries.append(entry)
                self._log.append(entry)
        return deliveries

    def _sense(self) -> None:
        in_flight = {s.task_id for s in self._outbox}
        for rec in self._tasks.values():
            if rec.closed or rec.exhausted or rec.quiet_signaled or rec.task_id in in_flight:
                continue
            rec.quiet_signaled = True
            self._outbox.append(self._stamp(Signal(
                Kind.QUIESCENT, rec.task_id, SUBSTRATE, _state("quiescent"), {"energy": rec.energy})))

    def run(self, max_steps: int = 1000) -> Dict[str, Any]:
        """Step until nothing is in flight (or ``max_steps``). Returns a summary."""
        for _ in range(max_steps):
            if self.idle:
                break
            self.step()
        return {
            "steps_executed": self._step,
            "converged": self.converged,
            "idle": self.idle,
            "total_agents": len(self._agents),
            "total_messages": len(self._log),
            "tasks": self.tasks(),
        }

    # Backwards-friendly alias.
    run_until_convergence = run

    # --- observation ----------------------------------------------------------

    def snapshot(self, messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Current state in the frame format used by traces and the dashboard."""
        messages = messages or []
        return {
            "step": self._step,
            "activity": len(messages),
            "converged": self.converged,
            "idle": self.idle,
            "agents": {aid: agent.to_dict() for aid, agent in self._agents.items()},
            "blackboard": self._board.get_all(),
            "messages": messages,
            "message_count": len(self._log),
            "tasks": {tid: self._task_summary(rec) for tid, rec in self._tasks.items()},
        }

    def _task_summary(self, rec: TaskRecord) -> Dict[str, Any]:
        r = self._board.read(f"result:{rec.task_id}")
        return {
            "text": rec.text,
            "status": self._status(rec),
            "energy": rec.energy,
            "budget": rec.budget,
            "effort": self._board.read(f"effort:{rec.task_id}", 1),
            "plans_considered": len(self._board.items(f"proposal:{rec.task_id}:")),
            "result": None if r is None else {
                "plan": plan_key(plan_from_data(r.get("plan", []))), "cost": r.get("cost"),
                "reason": r.get("reason", ""),
            },
            "report": self._board.read(f"report:{rec.task_id}"),
        }

    def export_trace(self) -> Dict[str, Any]:
        return {
            "system": "ASIS",
            "version": __version__,
            "knowledge_base": self.kb.name,
            "statistics": {
                "total_steps": self._step,
                "total_agents": len(self._agents),
                "total_messages": len(self._log),
                "converged": self.converged,
            },
            "agents": {aid: agent.to_dict() for aid, agent in self._agents.items()},
            "tasks": {tid: self.result(tid).to_dict() for tid in self._tasks},
            "blackboard": self._board.get_all(),
            "snapshots": self._snapshots,
            "message_log": self._log,
        }

    def save_trace(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.export_trace(), f, indent=2, ensure_ascii=False, default=str)


def _state(name: str, **metadata: str) -> Expression:
    return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.STATE, "organism", metadata or None))
