"""The specialist team.

Each specialist does one job, the way cells in a body do. None of them knows
who else exists; they only know which signals they have receptors for, what
the shared knowledge base (the "genome") says, and what others have left on
the blackboard. A plan emerges from the loop between them:

    TASK ─▶ intake ─▶ immune ─▶ decomposer ─▶ planner ──┐   memory ──┐
                                                        ▼            ▼
             ┌──────────────── PROPOSAL ─▶ immune ─▶ estimator ─▶ checker
             │                                                     │
             ├── repairer ◀─ violated ─────────────────────────────┤
             └── optimizer ◀─ satisfied ───────────────────────────┘

    substrate senses QUIESCENT/EXHAUSTED ─▶ regulator ─▶ ESCALATE (repairer)
                                                      └▶ SETTLE ─▶ judge ─▶ RESULT ─▶ explainer, memory

Blackboard keys (all per task): ``spec:``, ``requirements:``,
``proposal:<task>:<plan>``, ``verdict:<task>:<plan>``, ``effort:``,
``settled:``, ``result:``, ``report:``.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from asis.core import C, ConceptAtom, ConceptCategory, Expression, Operator, Rule, RuleEngine
from asis.knowledge import (
    Constraint,
    ConstraintError,
    KnowledgeBase,
    Plan,
    make_plan,
    plan_add,
    plan_counts,
    plan_key,
)
from asis.organism import (
    Context,
    Kind,
    Receptor,
    Signal,
    Specialist,
    SwarmController,
    TaskResult,
    plan_expression,
    plan_from_data,
)

MAX_EFFORT = 2
BEAM = {1: 1, 2: 3}


# ============================================================================
# SHARED READING OF THE BLACKBOARD
# ============================================================================

def _constraints(board, task_id: str) -> List[Constraint]:
    spec = board.read(f"spec:{task_id}") or {}
    return [Constraint.from_dict(c) for c in spec.get("constraints", [])]


def _requirements(board, task_id: str) -> Dict[str, Any]:
    return board.read(f"requirements:{task_id}") or {"groups": [], "actions": [], "forbid_actions": []}


def total_violation(metrics: Mapping[str, float], constraints: Sequence[Constraint]) -> float:
    return round(sum(c.violation(metrics[c.metric]) for c in constraints), 9)


def meets_requirements(plan: Plan, reqs: Mapping[str, Any], kb: KnowledgeBase) -> bool:
    counts = plan_counts(plan)
    if any(counts.get(a, 0) == 0 for a in reqs["actions"]):
        return False
    provided = kb.provided(plan)
    return all(any(set(alt) <= provided for alt in group) for group in reqs["groups"])


def plan_is_valid(plan: Plan, reqs: Mapping[str, Any], kb: KnowledgeBase) -> bool:
    if kb.plan_problems(plan):
        return False
    forbidden = set(reqs["forbid_actions"])
    return not any(a in forbidden for a, _ in plan) and meets_requirements(plan, reqs, kb)


def _plan_remove(plan: Plan, action: str) -> Plan:
    counts = plan_counts(plan)
    counts[action] -= 1
    return make_plan(counts)


def _changes(before: Mapping[str, float], after: Mapping[str, float], metrics: Iterable[str]) -> str:
    parts = [f"{m} {before[m]:.6g} → {after[m]:.6g}" for m in metrics if before[m] != after[m]]
    return ", ".join(parts)


def _proposal(agent: Specialist, task_id: str, plan: Plan, parent: Optional[str], move: str) -> Signal:
    return agent.emit(Kind.PROPOSAL, task_id, plan_expression(plan),
                      plan=[list(p) for p in plan], parent=parent, move=move)


def _addable(plan: Plan, kb: KnowledgeBase, forbidden: Iterable[str]) -> List[str]:
    counts, forbidden = plan_counts(plan), set(forbidden)
    return [a.name for a in kb.actions.values()
            if a.name not in forbidden and counts.get(a.name, 0) < a.max_uses]


def _with_action(plan: Plan, action: str, kb: KnowledgeBase) -> Tuple[Plan, List[str]]:
    """Add one unit of ``action`` plus any missing prerequisites."""
    grown = kb.with_prerequisites(plan_add(plan, action))
    before = plan_counts(plan)
    extras = [a for a, _ in grown if a != action and before.get(a, 0) == 0]
    return grown, extras


def _swaps(plan: Plan, kb: KnowledgeBase, forbidden: Iterable[str]) -> List[Tuple[Plan, str]]:
    """Replace one unit of an action with another. Swaps whose prerequisites
    would bring the removed action straight back are not real swaps and are skipped."""
    counts, moves = plan_counts(plan), []
    for action, _ in plan:
        shrunk = _plan_remove(plan, action)
        for other in _addable(shrunk, kb, forbidden):
            if other == action:
                continue
            swapped, extras = _with_action(shrunk, other, kb)
            if plan_counts(swapped).get(action, 0) >= counts[action]:
                continue
            moves.append((swapped, f"swap {action} for {other}" +
                          (f" (with prerequisite {', '.join(extras)})" if extras else "")))
    return moves


def _add_move(action: str, extras: List[str]) -> str:
    return f"add {action}" + (f" (with prerequisite {', '.join(extras)})" if extras else "")


# ============================================================================
# SPECIALISTS
# ============================================================================

class Intake(Specialist):
    tissue = "intake"
    receptors = (Receptor(Kind.TASK),)
    description = "Reads a task expression into goals, required/forbidden items and constraints."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        expr = signal.payload
        components = expr.operands if expr.operator == Operator.COMPOSE else (expr,)
        spec: Dict[str, List[Any]] = {"goals": [], "actions": [], "forbid_goals": [], "forbid_actions": [],
                                      "constraints": [], "ignored": [], "unsupported": []}
        for part in components:
            self._classify(part, spec)
        return [self.emit(Kind.OPENED, signal.task_id, expr, **spec)]

    @staticmethod
    def _classify(part: Expression, spec: Dict[str, List[Any]]) -> None:
        if part.is_leaf:
            atom = part.atom
            bucket = {ConceptCategory.GOAL: "goals", ConceptCategory.ACTION: "actions",
                      ConceptCategory.CONSTRAINT: "constraints"}.get(atom.category)
            if bucket == "goals":
                spec["goals"].append([atom.name])
            elif bucket == "actions":
                spec["actions"].append(atom.name)
            elif bucket == "constraints":
                spec["constraints"].append({"text": atom.name, "negated": False})
            else:
                spec["ignored"].append(atom.serialize())
            return
        inner = part.operands[0] if part.operator == Operator.NEGATE and len(part.operands) == 1 else None
        if inner is not None and inner.is_leaf:
            category, name = inner.atom.category, inner.atom.name
            if category == ConceptCategory.GOAL:
                spec["forbid_goals"].append(name)
                return
            if category == ConceptCategory.ACTION:
                spec["forbid_actions"].append(name)
                return
            if category == ConceptCategory.CONSTRAINT:
                spec["constraints"].append({"text": name, "negated": True})
                return
        if part.operator == Operator.UNION and all(
                o.is_leaf and o.atom.category == ConceptCategory.GOAL for o in part.operands):
            spec["goals"].append(sorted(o.atom.name for o in part.operands))
            return
        spec["unsupported"].append(part.serialize())


class Immune(Specialist):
    tissue = "immune"
    receptors = (Receptor(Kind.OPENED), Receptor(Kind.PROPOSAL))
    description = ("Rejects malformed or contradictory tasks, and quarantines invalid or "
                   "already-seen plans before anyone spends effort on them.")

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        if signal.kind == Kind.OPENED:
            return self._screen_task(signal, ctx)
        return self._screen_plan(signal, ctx)

    def _screen_task(self, signal: Signal, ctx: Context) -> List[Signal]:
        kb, d, problems = ctx.kb, signal.data, []
        for text in d["unsupported"]:
            hint = (" — ⊗ binds tighter than ⊕, so group alternatives first: (a ⊕ b) ⊗ constraint"
                    if text.startswith("(⊕") else "")
            problems.append(f"cannot interpret {text}: tasks combine goals, actions and constraints with ⊗, "
                            f"may negate them with ¬, and may offer alternative goals with ⊕{hint}")
        known_goals = sorted(set(kb.goals) | kb.capabilities)
        for group in d["goals"]:
            for name in group:
                if name not in kb.goals and name not in kb.capabilities:
                    problems.append(f"unknown goal '{name}'{_suggest(name, known_goals)}")
        for name in d["forbid_goals"]:
            if name not in kb.goals and name not in kb.capabilities:
                problems.append(f"unknown goal '{name}'{_suggest(name, known_goals)}")
        for name in [*d["actions"], *d["forbid_actions"]]:
            if name not in kb.actions:
                problems.append(f"unknown action '{name}'{_suggest(name, list(kb.actions))}")
        constraints = []
        for c in d["constraints"]:
            try:
                parsed = kb.parse_constraint(c["text"])
            except ConstraintError as e:
                problems.append(str(e))
                continue
            constraints.append(parsed.negated() if c["negated"] else parsed)
        problems.extend(_contradictions(constraints, kb))
        for name in sorted(set(d["actions"]) & set(d["forbid_actions"])):
            problems.append(f"action '{name}' is both required and forbidden")
        for group in d["goals"]:
            if len(group) == 1 and group[0] in d["forbid_goals"]:
                problems.append(f"goal '{group[0]}' is both required and forbidden")
        if not d["goals"] and not d["actions"] and not d["constraints"] and not d["unsupported"]:
            problems.append("the task has nothing to solve: add a goal (e.g. optimize_system) or a constraint")

        spec = {"goals": d["goals"], "actions": d["actions"], "forbid_goals": d["forbid_goals"],
                "forbid_actions": d["forbid_actions"], "constraints": [c.to_dict() for c in constraints],
                "ignored": d["ignored"]}
        if problems:
            spec["problems"] = problems
            ctx.board.write(f"spec:{signal.task_id}", spec, self.agent_id)
            return [self.emit(Kind.REJECTED, signal.task_id, C.compose(C.state("rejected"), signal.payload),
                              reason="; ".join(problems), problems=problems)]
        ctx.board.write(f"spec:{signal.task_id}", spec, self.agent_id)
        return [self.emit(Kind.CLEARED, signal.task_id, signal.payload, **spec)]

    def _screen_plan(self, signal: Signal, ctx: Context) -> List[Signal]:
        tid, plan = signal.task_id, plan_from_data(signal.data["plan"])
        key = plan_key(plan)
        record_key = f"proposal:{tid}:{key}"
        if ctx.board.has(record_key):
            return []  # self: already seen, nothing new to learn from it
        reqs = _requirements(ctx.board, tid)
        problems = ctx.kb.plan_problems(plan)
        problems += [f"'{a}' is forbidden" for a, _ in plan if a in set(reqs["forbid_actions"])]
        if not problems and not meets_requirements(plan, reqs, ctx.kb):
            problems.append("does not meet the task's requirements")
        record = {"plan": [list(p) for p in plan], "parent": signal.data.get("parent"),
                  "move": signal.data.get("move", ""), "proposer": signal.sender, "step": ctx.step}
        if problems:
            record["quarantined"] = problems
            ctx.board.write(record_key, record, self.agent_id)
            return []
        ctx.board.write(record_key, record, self.agent_id)
        return [self.emit(Kind.PLAN, tid, signal.payload, plan=signal.data["plan"])]


def _suggest(name: str, options: List[str]) -> str:
    match = difflib.get_close_matches(name, options, n=1)
    return f" (did you mean '{match[0]}'?)" if match else ""


def _contradictions(constraints: List[Constraint], kb: KnowledgeBase) -> List[str]:
    problems = []
    by_metric: Dict[str, List[Constraint]] = {}
    for c in constraints:
        by_metric.setdefault(c.metric, []).append(c)
    for metric, cs in by_metric.items():
        m = kb.metrics[metric]
        lo, lo_strict, hi, hi_strict = -math.inf, False, math.inf, False
        if m.minimum is not None:
            lo = m.minimum
        if m.maximum is not None:
            hi = m.maximum
        equals, not_equals = set(), set()
        for c in cs:
            if c.op in (">", ">=") and (c.value > lo or (c.value == lo and c.op == ">")):
                lo, lo_strict = c.value, c.op == ">"
            elif c.op in ("<", "<=") and (c.value < hi or (c.value == hi and c.op == "<")):
                hi, hi_strict = c.value, c.op == "<"
            elif c.op == "==":
                equals.add(c.value)
            elif c.op == "!=":
                not_equals.add(c.value)
        empty = lo > hi or (lo == hi and (lo_strict or hi_strict))
        empty = empty or len(equals) > 1 or bool(equals & not_equals)
        for v in equals:
            empty = empty or v < lo or v > hi or (v == lo and lo_strict) or (v == hi and hi_strict)
        if empty:
            texts = " and ".join(f"'{c.text}'" for c in cs)
            bounds = []
            if m.minimum is not None:
                bounds.append(f"at least {m.minimum:g}{m.unit}")
            if m.maximum is not None:
                bounds.append(f"at most {m.maximum:g}{m.unit}")
            limit = f" ({metric} is always {' and '.join(bounds)})" if bounds else ""
            verb = "cannot hold" if len(cs) == 1 else "cannot all hold"
            problems.append(f"{texts} {verb}{limit}")
    return problems


class Decomposer(Specialist):
    tissue = "decomposer"
    receptors = (Receptor(Kind.CLEARED),)
    description = "Expands goals into the capabilities they need, using the rule engine over the goal hierarchy."

    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(agent_id)
        self._engines: Dict[int, RuleEngine] = {}

    def _engine(self, kb: KnowledgeBase) -> RuleEngine:
        engine = self._engines.get(id(kb))
        if engine is None:
            engine = RuleEngine()
            for goal in kb.goals.values():
                needs = [_need_atom(n, kb) for n in goal.needs]
                replacement = (C.identity() if not needs else needs[0] if len(needs) == 1
                               else Expression.from_operator(Operator.COMPOSE, *needs))
                engine.add_rule(Rule(f"decompose:{goal.name}", C.goal(goal.name), replacement))
            self._engines[id(kb)] = engine
        return engine

    def capabilities(self, goal: str, kb: KnowledgeBase) -> List[str]:
        expanded = self._engine(kb).rewrite(_need_atom(goal, kb))
        return sorted(a.name for a in expanded.atoms if a.category == ConceptCategory.PROPERTY)

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        kb, d = ctx.kb, signal.data
        groups = [[self.capabilities(name, kb) for name in group] for group in d["goals"]]
        forbid_caps = {cap for name in d["forbid_goals"] for cap in self.capabilities(name, kb)}
        forbid_actions = sorted(set(d["forbid_actions"]) |
                                {a.name for a in kb.actions.values() if a.provides & forbid_caps})
        reqs = {"groups": groups, "actions": sorted(set(d["actions"])), "forbid_actions": forbid_actions,
                "forbid_capabilities": sorted(forbid_caps)}
        ctx.board.write(f"requirements:{signal.task_id}", reqs, self.agent_id)
        caps = sorted({c for group in groups for alt in group for c in alt})
        payload = (Expression.from_operator(Operator.COMPOSE, *[_capability(c) for c in caps])
                   if caps else C.identity())
        return [self.emit(Kind.REQUIREMENTS, signal.task_id, payload, **reqs)]


def _with_unit(value: float, unit: str, signed: bool = False) -> str:
    number = f"{value:+.6g}" if signed else f"{value:.6g}"
    return f"{number}{unit}" if unit in ("", "%") else f"{number} {unit}"


def _capability(name: str) -> Expression:
    return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.PROPERTY, "capability"))


def _need_atom(name: str, kb: KnowledgeBase) -> Expression:
    return C.goal(name) if name in kb.goals else _capability(name)


class Planner(Specialist):
    tissue = "planner"
    receptors = (Receptor(Kind.REQUIREMENTS),)
    description = "Drafts the cheapest plan that provides every required capability."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        kb, reqs, tid = ctx.kb, signal.data, signal.task_id
        forbidden = set(reqs["forbid_actions"])
        counts = {a: 1 for a in reqs["actions"]}
        notes, problems = [], []
        for group in reqs["groups"]:
            plan = kb.with_prerequisites(make_plan(counts))
            if any(set(alt) <= kb.provided(plan) for alt in group):
                continue
            best: Optional[Tuple[float, int, Dict[str, int], List[str]]] = None
            missing_caps: List[str] = []
            for index, alt in enumerate(group):
                trial, cost, picked = dict(counts), 0.0, []
                for cap in alt:
                    if cap in kb.provided(kb.with_prerequisites(make_plan(trial))):
                        continue
                    choice = next((a for a in kb.providers(cap) if a.name not in forbidden
                                   and not kb.plan_problems(kb.with_prerequisites(make_plan({**trial, a.name: 1})))),
                                  None)
                    if choice is None:
                        missing_caps.append(cap)
                        break
                    trial[choice.name] = 1
                    cost += choice.cost
                    picked.append(f"{cap} via {choice.name}")
                else:
                    if best is None or (cost, index) < (best[0], best[1]):
                        best = (cost, index, trial, picked)
            if best is None:
                problems.extend(_unprovidable(sorted(set(missing_caps)), group, reqs, kb))
                continue
            counts = best[2]
            notes.extend(best[3])
        plan = kb.with_prerequisites(make_plan(counts))
        problems += kb.plan_problems(plan)
        if problems:
            return [self.emit(Kind.REJECTED, tid, C.compose(C.state("unplannable"), plan_expression(plan)),
                              reason="; ".join(problems), problems=problems)]
        move = "initial plan: " + ("; ".join(notes) if notes else "nothing is required up front")
        if reqs["actions"]:
            move += f" (required: {', '.join(reqs['actions'])})"
        return [_proposal(self, tid, plan, None, move)]


def _unprovidable(caps: List[str], group: List[List[str]], reqs: Mapping[str, Any],
                  kb: KnowledgeBase) -> List[str]:
    forbidden = set(reqs["forbid_actions"])
    problems = []
    for cap in caps:
        providers = kb.providers(cap)
        if not providers:
            problems.append(f"nothing in the knowledge base provides '{cap}'")
            continue
        reasons = [f"{a.name} is forbidden" if a.name in forbidden else f"{a.name} conflicts with the plan"
                   for a in providers]
        problems.append(f"'{cap}' cannot be provided: {', '.join(reasons)}")
    return problems


class Memory(Specialist):
    tissue = "memory"
    receptors = (Receptor(Kind.REQUIREMENTS),
                 Receptor(Kind.RESULT, when=lambda s: s.data.get("status") == "solved"))
    description = "Remembers solved tasks and re-proposes the known answer when the same problem returns."

    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(agent_id)
        self._solutions: Dict[str, Tuple[Plan, str]] = {}

    @staticmethod
    def fingerprint(board, task_id: str) -> str:
        spec = board.read(f"spec:{task_id}") or {}
        reqs = _requirements(board, task_id)
        meaning = sorted((c["metric"], c["op"], c["value"]) for c in spec.get("constraints", []))
        body = json.dumps({"c": meaning, "r": reqs}, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        key = self.fingerprint(ctx.board, signal.task_id)
        if signal.kind == Kind.RESULT:
            self._solutions.setdefault(key, (plan_from_data(signal.data["plan"]), signal.task_id))
            return []
        known = self._solutions.get(key)
        if known is None:
            return []
        plan, source = known
        return [_proposal(self, signal.task_id, plan, None, f"recalled: the same problem was solved in task {source}")]


class Estimator(Specialist):
    tissue = "estimator"
    receptors = (Receptor(Kind.PLAN),)
    description = "Predicts every metric for a plan from the knowledge base's effect model."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        plan = plan_from_data(signal.data["plan"])
        metrics = ctx.kb.estimate(plan)
        atoms = [ConceptAtom.create(m, ConceptCategory.METRIC, "estimate", {"value": f"{v:.6g}"})
                 for m, v in metrics.items()]
        payload = C.compose(plan_expression(plan), Expression.from_operator(Operator.UNION, *atoms))
        return [self.emit(Kind.ESTIMATE, signal.task_id, payload, plan=signal.data["plan"], metrics=metrics)]


class Checker(Specialist):
    tissue = "checker"
    receptors = (Receptor(Kind.ESTIMATE),)
    description = "Compares predicted metrics against every constraint and records a verdict."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        tid, kb = signal.task_id, ctx.kb
        plan = plan_from_data(signal.data["plan"])
        metrics = signal.data["metrics"]
        violations = []
        for c in _constraints(ctx.board, tid):
            gap = c.violation(metrics[c.metric])
            if gap:
                unit = kb.metrics[c.metric].unit
                violations.append({"constraint": c.text, "metric": c.metric, "actual": metrics[c.metric],
                                   "target": c.describe(unit), "gap": round(gap, 9)})
        verdict = {"plan": [list(p) for p in plan], "metrics": metrics, "satisfied": not violations,
                   "violations": violations, "total_violation": round(sum(v["gap"] for v in violations), 9),
                   "cost": metrics["cost"]}
        ctx.board.write(f"verdict:{tid}:{plan_key(plan)}", verdict, self.agent_id)
        state = C.state("satisfied" if not violations else "violated")
        return [self.emit(Kind.VERDICT, tid, C.compose(state, plan_expression(plan)), **verdict)]


class Repairer(Specialist):
    tissue = "repairer"
    receptors = (Receptor(Kind.VERDICT, when=lambda s: not s.data["satisfied"]), Receptor(Kind.ESCALATE))
    metabolic_cost = 2
    description = ("Proposes changes that shrink constraint violations. Effort 1 tries single additions; "
                   "effort 2 also tries removals and swaps and keeps more candidates.")

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        tid = signal.task_id
        if signal.kind == Kind.VERDICT:
            # Negative feedback: once any plan satisfies the task, stop correcting
            # other branches; the optimizer takes it from there.
            if any(v["satisfied"] for _, v in ctx.board.items(f"verdict:{tid}:")):
                return []
            level = ctx.board.read(f"effort:{tid}", 1)
            return self._repair(plan_from_data(signal.data["plan"]), tid, ctx, level)
        level = int(signal.data["level"])
        verdicts = sorted((v for _, v in ctx.board.items(f"verdict:{tid}:") if not v["satisfied"]),
                          key=lambda v: (v["total_violation"], v["cost"], plan_key(plan_from_data(v["plan"]))))
        out, seen = [], set()
        for v in verdicts[:BEAM[level]]:
            for proposal in self._repair(plan_from_data(v["plan"]), tid, ctx, level):
                key = plan_key(plan_from_data(proposal.data["plan"]))
                if key not in seen:
                    seen.add(key)
                    out.append(proposal)
        return out

    def _repair(self, plan: Plan, tid: str, ctx: Context, level: int) -> List[Signal]:
        kb, board = ctx.kb, ctx.board
        reqs, constraints = _requirements(board, tid), _constraints(board, tid)
        before = kb.estimate(plan)
        base_v, base_cost = total_violation(before, constraints), before["cost"]
        watched = sorted({c.metric for c in constraints})

        moves: List[Tuple[Plan, str]] = []
        for action in _addable(plan, kb, reqs["forbid_actions"]):
            grown, extras = _with_action(plan, action, kb)
            moves.append((grown, _add_move(action, extras)))
        if level >= 2:
            for action, _ in plan:
                moves.append((_plan_remove(plan, action), f"remove {action}"))
            moves.extend(_swaps(plan, kb, reqs["forbid_actions"]))

        scored = []
        for candidate, move in moves:
            key = plan_key(candidate)
            if board.has(f"proposal:{tid}:{key}") or not plan_is_valid(candidate, reqs, kb):
                continue
            after = kb.estimate(candidate)
            v = total_violation(after, constraints)
            if v < base_v - 1e-12 or (level >= 2 and v <= base_v and after["cost"] < base_cost):
                scored.append((v, after["cost"], key, candidate, f"{move}: {_changes(before, after, watched)}"))
        scored.sort(key=lambda s: s[:3])
        unique, out = set(), []
        for _, _, key, candidate, move in scored:
            if key in unique:
                continue
            unique.add(key)
            out.append(_proposal(self, tid, candidate, plan_key(plan), move))
            if len(out) == BEAM[level]:
                break
        return out


class Optimizer(Specialist):
    tissue = "optimizer"
    receptors = (Receptor(Kind.VERDICT, when=lambda s: s.data["satisfied"]),)
    description = ("Looks for a cheaper plan that still satisfies every constraint: single drops, swaps and "
                   "additions first, then pairs of moves when no single move helps.")

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        kb, board, tid = ctx.kb, ctx.board, signal.task_id
        plan = plan_from_data(signal.data["plan"])
        reqs, constraints = _requirements(board, tid), _constraints(board, tid)
        cost, forbidden = signal.data["cost"], reqs["forbid_actions"]

        def cheaper(moves: Iterable[Tuple[Plan, str]]):
            best, seen = None, set()
            for candidate, move in moves:
                key = plan_key(candidate)
                if key in seen or board.has(f"proposal:{tid}:{key}") or not plan_is_valid(candidate, reqs, kb):
                    continue
                seen.add(key)
                after = kb.estimate(candidate)
                if after["cost"] >= cost or total_violation(after, constraints) > 0:
                    continue
                if best is None or (after["cost"], key) < best[0]:
                    best = ((after["cost"], key), candidate,
                            f"{move}: saves {cost - after['cost']:.6g}, constraints still hold")
            return best

        singles = [*_drops(plan), *_swaps(plan, kb, forbidden), *_adds(plan, kb, forbidden)]
        best = cheaper(singles)
        if best is None:
            best = cheaper((second, f"{first_move}, then {second_move}")
                           for first, first_move in [*_drops(plan), *_adds(plan, kb, forbidden)]
                           for second, second_move in [*_drops(first), *_adds(first, kb, forbidden)])
        if best is None:
            return []
        return [_proposal(self, tid, best[1], plan_key(plan), best[2])]


def _drops(plan: Plan) -> List[Tuple[Plan, str]]:
    return [(_plan_remove(plan, action), f"drop {action}") for action, _ in plan]


def _adds(plan: Plan, kb: KnowledgeBase, forbidden: Iterable[str]) -> List[Tuple[Plan, str]]:
    moves = []
    for action in _addable(plan, kb, forbidden):
        grown, extras = _with_action(plan, action, kb)
        moves.append((grown, _add_move(action, extras)))
    return moves


class Regulator(Specialist):
    tissue = "regulator"
    receptors = (Receptor(Kind.QUIESCENT), Receptor(Kind.EXHAUSTED))
    description = ("Homeostasis: when a task goes quiet it either raises search effort or asks for a "
                   "decision; when energy runs out it asks for a decision.")

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        tid, board = signal.task_id, ctx.board
        if board.has(f"settled:{tid}") or board.has(f"result:{tid}"):
            return []
        if signal.kind == Kind.EXHAUSTED:
            return [self._settle(tid, ctx, f"energy budget of {signal.data['budget']} spent")]
        verdicts = [v for _, v in board.items(f"verdict:{tid}:")]
        if any(v["satisfied"] for v in verdicts):
            return [self._settle(tid, ctx, "constraints met and no cheaper variant found")]
        level = board.read(f"effort:{tid}", 1)
        if verdicts and level < MAX_EFFORT:
            board.write(f"effort:{tid}", level + 1, self.agent_id)
            return [self.emit(Kind.ESCALATE, tid, C.state("escalate", metadata={"level": str(level + 1)}),
                              level=level + 1)]
        reason = (f"no plan meets every constraint after searching at effort level {level}" if verdicts
                  else "no plan was ever evaluated")
        return [self._settle(tid, ctx, reason)]

    def _settle(self, tid: str, ctx: Context, reason: str) -> Signal:
        ctx.board.write(f"settled:{tid}", reason, self.agent_id)
        return self.emit(Kind.SETTLE, tid, C.state("settle"), reason=reason)


class Judge(Specialist):
    tissue = "judge"
    receptors = (Receptor(Kind.SETTLE), Receptor(Kind.REJECTED))
    description = "Chooses the answer: the cheapest satisfying plan, else the closest miss."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        tid, board = signal.task_id, ctx.board
        if board.has(f"result:{tid}"):
            return []
        if signal.kind == Kind.REJECTED:
            result = {"status": "rejected", "plan": [], "metrics": {}, "cost": None, "violations": [],
                      "reason": signal.data["reason"], "problems": signal.data["problems"]}
        else:
            verdicts = [v for _, v in board.items(f"verdict:{tid}:")]
            solved = [v for v in verdicts if v["satisfied"]]

            def key(v: Mapping[str, Any]) -> str:
                return plan_key(plan_from_data(v["plan"]))

            if solved:
                best = min(solved, key=lambda v: (v["cost"], sum(n for _, n in v["plan"]), key(v)))
                status = "solved"
            elif verdicts:
                best = min(verdicts, key=lambda v: (v["total_violation"], v["cost"], key(v)))
                status = "unsolved"
            else:
                best, status = None, "unsolved"
            result = {"status": status, "reason": signal.data["reason"],
                      "plan": best["plan"] if best else [], "metrics": best["metrics"] if best else {},
                      "cost": best["cost"] if best else None, "violations": best["violations"] if best else [],
                      "plans_considered": len(verdicts)}
        board.write(f"result:{tid}", result, self.agent_id)
        plan = plan_from_data(result["plan"])
        return [self.emit(Kind.RESULT, tid, C.compose(C.state(result["status"]), plan_expression(plan)), **result)]


class Explainer(Specialist):
    tissue = "explainer"
    receptors = (Receptor(Kind.RESULT),)
    description = "Writes a human-readable report: the answer, the numbers, and how the team got there."

    def handle(self, signal: Signal, ctx: Context) -> Iterable[Signal]:
        ctx.board.write(f"report:{signal.task_id}", self.report(signal.task_id, signal.data, ctx), self.agent_id)
        return []

    @staticmethod
    def report(tid: str, result: Mapping[str, Any], ctx: Context) -> str:
        kb, board = ctx.kb, ctx.board
        task = board.read(f"task:{tid}") or {}
        lines = [f"Task {tid}: {task.get('text', '?')}",
                 f"Status: {result['status'].upper()}"]
        if result["status"] == "rejected":
            lines.append("Rejected before planning:")
            lines += [f"  - {p}" for p in result.get("problems", [])]
            return "\n".join(lines)

        plan = plan_from_data(result["plan"])
        lines.append(f"Why it stopped: {result['reason']}")
        lines.append("")
        lines.append("Plan:" if plan else "Plan: no changes needed")
        for name, n in plan:
            a = kb.actions[name]
            count = f" ×{n}" if n > 1 else ""
            cost_unit = kb.metrics["cost"].unit
            what = f" — {a.description}" if a.description else ""
            lines.append(f"  - {name}{count}{what} ({_with_unit(a.cost * n, cost_unit, signed=True)})")

        metrics = result["metrics"]
        if metrics:
            baseline = kb.estimate(())
            constraints = _constraints(board, tid)
            lines.append("")
            lines.append("Predicted metrics:")
            for name in kb.metrics:
                unit = kb.metrics[name].unit
                marks = [f"{'✓' if c.satisfied(metrics[name]) else '✗'} {c.describe(unit)}"
                         for c in constraints if c.metric == name]
                if not marks and metrics[name] == baseline[name]:
                    continue
                change = f" (was {_with_unit(baseline[name], unit)})" if metrics[name] != baseline[name] else ""
                lines.append(f"  {name}: {_with_unit(metrics[name], unit)}{change}"
                             + (f"  [{'; '.join(marks)}]" if marks else ""))
        if result["violations"]:
            lines.append("")
            lines.append("Still violated:")
            for v in result["violations"]:
                unit = kb.metrics[v["metric"]].unit
                lines.append(f"  - {v['constraint']}: predicted {_with_unit(v['actual'], unit)}, needs {v['target']}")

        lineage = []
        key: Optional[str] = plan_key(plan)
        while key is not None:
            record = board.read(f"proposal:{tid}:{key}")
            if record is None:
                break
            lineage.append(f"{record['move']} [{record['proposer']}]")
            key = record["parent"]
        if lineage:
            lines.append("")
            lines.append("How the team got there:")
            lines += [f"  {i}. {step}" for i, step in enumerate(reversed(lineage), 1)]
        lines.append("")
        lines.append(f"Plans evaluated: {result.get('plans_considered', 0)}")
        return "\n".join(lines)


# ============================================================================
# ASSEMBLY
# ============================================================================

def default_team(estimators: int = 2) -> List[Specialist]:
    """One of each specialist, with redundant estimators (they share a tissue)."""
    team: List[Specialist] = [Intake(), Immune(), Decomposer(), Memory(), Planner()]
    team += [Estimator(f"estimator-{i}") for i in range(1, estimators + 1)]
    team += [Checker(), Repairer(), Optimizer(), Regulator(), Judge(), Explainer()]
    return team


def create_default_swarm(kb: Optional[KnowledgeBase] = None,
                         energy_budget: int = SwarmController.DEFAULT_BUDGET) -> SwarmController:
    swarm = SwarmController(kb, energy_budget)
    for agent in default_team():
        swarm.register_agent(agent)
    return swarm


def solve(task: Any, kb: Optional[KnowledgeBase] = None, budget: Optional[int] = None,
          max_steps: int = 1000) -> TaskResult:
    """Solve one task with a fresh default team and return the result."""
    swarm = create_default_swarm(kb)
    task_id = swarm.submit(task, budget=budget)
    swarm.run(max_steps=max_steps)
    return swarm.result(task_id)
