"""
ASIS 2.0 — Algebraic Swarm Intelligence System
===============================================
A production-grade multi-agent architecture with symbolic algebra,
forward-chaining rule engine, and real-time visualization export.

Enhanced Features:
- Full forward-chaining rule engine with unification
- Deterministic symbolic execution with traceability
- JSON trace export for offline analysis
- Real problem-solving: planning, validation, synthesis
- Convergence detection with algebraic fixed-point computation
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple, Union

__version__ = "2.0.0"


# ============================================================================
# CORE ALGEBRAIC STRUCTURES
# ============================================================================

@unique
class ConceptCategory(Enum):
    ENTITY = "ENTITY"
    ACTION = "ACTION"
    PROPERTY = "PROPERTY"
    RELATION = "RELATION"
    CONSTRAINT = "CONSTRAINT"
    GOAL = "GOAL"
    STATE = "STATE"
    DOMAIN = "DOMAIN"
    METRIC = "METRIC"
    INVARIANT = "INVARIANT"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"

@unique
class Operator(Enum):
    COMPOSE = "⊗"
    UNION = "⊕"
    NEGATE = "¬"
    PROJECT = "π"
    INJECT = "ι"
    BIND = "β"
    REDUCE = "ρ"
    TRANSFORM = "τ"
    GUARD = "γ"
    FIXPOINT = "μ"

@unique
class MessageType(Enum):
    DIRECTIVE = "DIRECTIVE"
    QUERY = "QUERY"
    RESULT = "RESULT"
    SIGNAL = "SIGNAL"
    CONSTRAINT = "CONSTRAINT"
    FEEDBACK = "FEEDBACK"
    DELEGATION = "DELEGATION"
    SYNTHESIS = "SYNTHESIS"
    VALIDATION = "VALIDATION"
    HEARTBEAT = "HEARTBEAT"

@unique
class AgentRole(Enum):
    ORCHESTRATOR = "ORCHESTRATOR"
    ANALYST = "ANALYST"
    PLANNER = "PLANNER"
    EXECUTOR = "EXECUTOR"
    VALIDATOR = "VALIDATOR"
    SYNTHESIZER = "SYNTHESIZER"


@dataclass(frozen=True, eq=True)
class ConceptAtom:
    name: str
    category: ConceptCategory
    domain: str = "general"
    metadata_tuple: Tuple[Tuple[str, str], ...] = ()

    @staticmethod
    def create(name: str, category: ConceptCategory, domain: str = "general",
               metadata: Optional[Dict[str, str]] = None) -> ConceptAtom:
        meta_tuple = tuple(sorted(metadata.items())) if metadata else ()
        return ConceptAtom(name=name, category=category, domain=domain,
                          metadata_tuple=meta_tuple)

    @property
    def metadata(self) -> Dict[str, str]:
        return dict(self.metadata_tuple)

    def serialize(self) -> str:
        # Metadata is part of atom identity (dataclass equality), so it must be
        # part of the serialization too — Expression equality and hashing are
        # defined over serialize(), and omitting it would merge distinct atoms.
        if self.metadata_tuple:
            meta = ",".join(f"{k}={v}" for k, v in self.metadata_tuple)
            return f"ATOM({self.name}:{self.category.value}:{self.domain}{{{meta}}})"
        return f"ATOM({self.name}:{self.category.value}:{self.domain})"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category.value,
            "domain": self.domain,
            "metadata": self.metadata
        }

    def matches_pattern(self, pattern: ConceptAtom) -> bool:
        if pattern.name != "_" and pattern.name != self.name:
            return False
        if pattern.category != self.category:
            return False
        if pattern.domain != "_" and pattern.domain != self.domain:
            return False
        return True

    def with_domain(self, new_domain: str) -> ConceptAtom:
        return ConceptAtom(
            name=self.name, category=self.category,
            domain=new_domain, metadata_tuple=self.metadata_tuple
        )

    def __repr__(self) -> str:
        return f"{self.name}:{self.category.value}:{self.domain}"


class Expression:
    __slots__ = ('operator', 'operands', 'bindings', '_hash_cache',
                 '_serialize_cache', '_depth_cache', '_atoms_cache')

    _ZERO_ATOM = ConceptAtom.create("_zero", ConceptCategory.ENTITY, "system")
    _IDENTITY_ATOM = ConceptAtom.create("_identity", ConceptCategory.ENTITY, "system")

    def __init__(
        self,
        operator: Optional[Operator] = None,
        operands: Tuple[Union['Expression', ConceptAtom], ...] = (),
        bindings: Optional[Dict[str, Any]] = None,
    ):
        self.operator = operator
        self.operands = tuple(operands)
        self.bindings = dict(sorted(bindings.items())) if bindings else {}
        self._hash_cache: Optional[int] = None
        self._serialize_cache: Optional[str] = None
        self._depth_cache: Optional[int] = None
        self._atoms_cache: Optional[FrozenSet[ConceptAtom]] = None

    @staticmethod
    def from_atom(atom: ConceptAtom) -> 'Expression':
        return Expression(operator=None, operands=(atom,))

    @staticmethod
    def from_operator(op: Operator, *operands: Union['Expression', ConceptAtom],
                      bindings: Optional[Dict[str, Any]] = None) -> 'Expression':
        wrapped = []
        for o in operands:
            if isinstance(o, ConceptAtom):
                wrapped.append(Expression.from_atom(o))
            elif isinstance(o, Expression):
                wrapped.append(o)
            else:
                raise TypeError(f"Operand must be Expression or ConceptAtom, got {type(o)}")

        # Double Negation: ¬¬A = A
        if op == Operator.NEGATE and len(wrapped) == 1:
            inner = wrapped[0]
            if inner.operator == Operator.NEGATE and not inner.bindings:
                return inner.operands[0]

        # Associativity: Flatten nested identical operations
        if op in (Operator.COMPOSE, Operator.UNION):
            flattened = []
            for w in wrapped:
                if w.operator == op and not w.bindings:
                    flattened.extend(w.operands)
                else:
                    flattened.append(w)
            wrapped = flattened

        # Idempotence: A ⊕ A = A
        if op == Operator.UNION:
            seen = set()
            unique_wrapped = []
            for w in wrapped:
                if w not in seen:
                    seen.add(w)
                    unique_wrapped.append(w)
            wrapped = unique_wrapped
            if len(wrapped) == 1:
                return wrapped[0]

        # Identity and Absorption
        if op == Operator.COMPOSE:
            # Absorption: A ⊗ _zero = _zero
            for w in wrapped:
                if w.is_leaf and w.atom == Expression._ZERO_ATOM:
                    return Expression.from_atom(Expression._ZERO_ATOM)

            # Identity: A ⊗ _identity = A
            filtered_wrapped = []
            for w in wrapped:
                if not (w.is_leaf and w.atom == Expression._IDENTITY_ATOM):
                    filtered_wrapped.append(w)

            if not filtered_wrapped:
                return Expression.from_atom(Expression._IDENTITY_ATOM)

            if len(filtered_wrapped) == 1:
                return filtered_wrapped[0]

            wrapped = filtered_wrapped

        return Expression(operator=op, operands=tuple(wrapped), bindings=bindings)

    @property
    def is_leaf(self) -> bool:
        return self.operator is None and len(self.operands) == 1 and isinstance(self.operands[0], ConceptAtom)

    @property
    def atom(self) -> Optional[ConceptAtom]:
        if self.is_leaf:
            return self.operands[0]
        return None

    @property
    def depth(self) -> int:
        if self._depth_cache is not None:
            return self._depth_cache
        if self.is_leaf:
            self._depth_cache = 0
        else:
            child_depths = [o.depth if isinstance(o, Expression) else 0 for o in self.operands]
            self._depth_cache = 1 + max(child_depths) if child_depths else 1
        return self._depth_cache

    @property
    def atoms(self) -> FrozenSet[ConceptAtom]:
        if self._atoms_cache is not None:
            return self._atoms_cache
        result: Set[ConceptAtom] = set()
        self._collect_atoms(result)
        self._atoms_cache = frozenset(result)
        return self._atoms_cache

    def _collect_atoms(self, accumulator: Set[ConceptAtom]) -> None:
        if self.is_leaf:
            accumulator.add(self.operands[0])
        else:
            for o in self.operands:
                if isinstance(o, Expression):
                    o._collect_atoms(accumulator)
                elif isinstance(o, ConceptAtom):
                    accumulator.add(o)

    def to_dict(self) -> dict:
        if self.is_leaf:
            return {"type": "atom", "atom": self.operands[0].to_dict()}
        return {
            "type": "expression",
            "operator": self.operator.value if self.operator else None,
            "bindings": self.bindings,
            "operands": [o.to_dict() if isinstance(o, Expression) else o.to_dict() for o in self.operands]
        }

    def substitute(self, old: ConceptAtom, new: Union[ConceptAtom, 'Expression']) -> 'Expression':
        if self.is_leaf:
            if self.operands[0] == old:
                if isinstance(new, ConceptAtom):
                    return Expression.from_atom(new)
                return new
            return self
        new_operands = []
        for o in self.operands:
            if isinstance(o, Expression):
                new_operands.append(o.substitute(old, new))
            elif isinstance(o, ConceptAtom):
                if o == old:
                    if isinstance(new, ConceptAtom):
                        new_operands.append(Expression.from_atom(new))
                    else:
                        new_operands.append(new)
                else:
                    new_operands.append(Expression.from_atom(o))
        return Expression.from_operator(self.operator, *new_operands,
                                        bindings=self.bindings.copy())

    def serialize(self) -> str:
        if self._serialize_cache is not None:
            return self._serialize_cache
        if self.is_leaf:
            self._serialize_cache = self.operands[0].serialize()
        else:
            parts = [self.operator.value if self.operator else "?"]
            if self.bindings:
                binding_str = ",".join(f"{k}={v}" for k, v in sorted(self.bindings.items()))
                parts.append(f"[{binding_str}]")
            for o in self.operands:
                if isinstance(o, Expression):
                    parts.append(o.serialize())
                elif isinstance(o, ConceptAtom):
                    parts.append(o.serialize())
            self._serialize_cache = f"({' '.join(parts)})"
        return self._serialize_cache

    def __matmul__(self, other: Union['Expression', ConceptAtom]) -> 'Expression':
        if isinstance(other, ConceptAtom):
            other = Expression.from_atom(other)
        return Expression.from_operator(Operator.COMPOSE, self, other)

    def __or__(self, other: Union['Expression', ConceptAtom]) -> 'Expression':
        if isinstance(other, ConceptAtom):
            other = Expression.from_atom(other)
        return Expression.from_operator(Operator.UNION, self, other)

    def __invert__(self) -> 'Expression':
        return Expression.from_operator(Operator.NEGATE, self)

    def __hash__(self) -> int:
        if self._hash_cache is None:
            self._hash_cache = hash(self.serialize())
        return self._hash_cache

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Expression):
            return NotImplemented
        return self.serialize() == other.serialize()

    def __repr__(self) -> str:
        return self.serialize()


class C:
    @staticmethod
    def entity(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.ENTITY, domain, metadata))

    @staticmethod
    def action(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.ACTION, domain, metadata))

    @staticmethod
    def property(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.PROPERTY, domain, metadata))

    @staticmethod
    def constraint(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.CONSTRAINT, domain, metadata))

    @staticmethod
    def goal(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.GOAL, domain, metadata))

    @staticmethod
    def state(name: str, domain: str = "general", metadata: Optional[Dict[str, str]] = None) -> Expression:
        return Expression.from_atom(ConceptAtom.create(name, ConceptCategory.STATE, domain, metadata))

    @staticmethod
    def compose(*exprs: Union[Expression, ConceptAtom]) -> Expression:
        if len(exprs) < 2:
            raise ValueError("COMPOSE requires at least 2 operands")
        return Expression.from_operator(Operator.COMPOSE, *exprs)

    @staticmethod
    def union(*exprs: Union[Expression, ConceptAtom]) -> Expression:
        if len(exprs) < 2:
            raise ValueError("UNION requires at least 2 operands")
        return Expression.from_operator(Operator.UNION, *exprs)

    @staticmethod
    def guard(condition: Union[Expression, ConceptAtom],
              body: Union[Expression, ConceptAtom]) -> Expression:
        return Expression.from_operator(Operator.GUARD, condition, body)

    @staticmethod
    def negate(expr: Union[Expression, ConceptAtom]) -> Expression:
        return Expression.from_operator(Operator.NEGATE, expr)

    @staticmethod
    def project(expr: Union[Expression, ConceptAtom], field: str) -> Expression:
        return Expression.from_operator(Operator.PROJECT, expr, bindings={"field": field})

    @staticmethod
    def inject(expr: Union[Expression, ConceptAtom], target: str) -> Expression:
        return Expression.from_operator(Operator.INJECT, expr, bindings={"target": target})

    @staticmethod
    def bind(expr: Union[Expression, ConceptAtom], variable: str, value: Any) -> Expression:
        return Expression.from_operator(Operator.BIND, expr, bindings={variable: value})

    @staticmethod
    def reduce(expr: Union[Expression, ConceptAtom], accumulator: str) -> Expression:
        return Expression.from_operator(Operator.REDUCE, expr, bindings={"acc": accumulator})

    @staticmethod
    def transform(expr: Union[Expression, ConceptAtom], domain: str) -> Expression:
        return Expression.from_operator(Operator.TRANSFORM, expr, bindings={"domain": domain})

    @staticmethod
    def fixpoint(expr: Union[Expression, ConceptAtom]) -> Expression:
        return Expression.from_operator(Operator.FIXPOINT, expr)

    @staticmethod
    def identity() -> Expression:
        return Expression.from_atom(Expression._IDENTITY_ATOM)

    @staticmethod
    def zero() -> Expression:
        return Expression.from_atom(Expression._ZERO_ATOM)


class ParseError(ValueError):
    """Raised by parse_expression for malformed input."""


_COMPOSE_TOKENS = ("⊗", "*")
_UNION_TOKENS = ("⊕", "|")
_NEGATE_TOKENS = ("¬", "~")
_ATOM_STOP = set("⊗*⊕|")
_COMPARATORS = set("<>=≤≥≠")


def parse_expression(text: str) -> Expression:
    """Parse a task written in ASIS notation into an Expression.

    Grammar (⊗ binds tighter than ⊕; ASCII alternatives in brackets)::

        expr  := term  (⊕ [|] term)*
        term  := unary (⊗ [*] unary)*
        unary := ¬ [~] unary | "(" expr ")" | atom
        atom  := [category ":"] name

    ``category`` is any ConceptCategory name, case-insensitive
    (``goal:ship_it``, ``entity:db``). Without one, text containing a
    comparison (``latency < 100ms``) is a CONSTRAINT and anything else is a
    GOAL. Names may contain spaces and balanced parentheses.
    """
    parser = _ExpressionParser(text)
    expr = parser.parse_expr()
    parser.skip_ws()
    if not parser.at_end():
        raise ParseError(f"unexpected {parser.text[parser.pos]!r} at position {parser.pos}")
    return expr


class _ExpressionParser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def at_end(self) -> bool:
        return self.pos >= len(self.text)

    def skip_ws(self) -> None:
        while not self.at_end() and self.text[self.pos].isspace():
            self.pos += 1

    def accept(self, tokens: Tuple[str, ...]) -> bool:
        self.skip_ws()
        if not self.at_end() and self.text[self.pos] in tokens:
            self.pos += 1
            return True
        return False

    def parse_expr(self) -> Expression:
        operands = [self.parse_term()]
        while self.accept(_UNION_TOKENS):
            operands.append(self.parse_term())
        return operands[0] if len(operands) == 1 else Expression.from_operator(Operator.UNION, *operands)

    def parse_term(self) -> Expression:
        operands = [self.parse_unary()]
        while self.accept(_COMPOSE_TOKENS):
            operands.append(self.parse_unary())
        return operands[0] if len(operands) == 1 else Expression.from_operator(Operator.COMPOSE, *operands)

    def parse_unary(self) -> Expression:
        if self.accept(_NEGATE_TOKENS):
            return Expression.from_operator(Operator.NEGATE, self.parse_unary())
        if self.accept(("(",)):
            inner = self.parse_expr()
            if not self.accept((")",)):
                raise ParseError(f"expected ')' at position {self.pos}")
            return inner
        return self.parse_atom()

    def parse_atom(self) -> Expression:
        self.skip_ws()
        start, depth = self.pos, 0
        while not self.at_end():
            ch = self.text[self.pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            elif ch in _ATOM_STOP:
                break
            self.pos += 1
        raw = self.text[start:self.pos].strip()
        if not raw:
            where = f"at position {start}" if start < len(self.text) else "at end of input"
            raise ParseError(f"expected a concept {where}")

        category = None
        prefix, sep, rest = raw.partition(":")
        if sep and prefix.strip().upper() in ConceptCategory.__members__:
            category = ConceptCategory[prefix.strip().upper()]
            raw = rest.strip()
            if not raw:
                raise ParseError(f"missing name after '{prefix}:'")
        if category is None:
            category = ConceptCategory.CONSTRAINT if _COMPARATORS & set(raw) else ConceptCategory.GOAL
        return Expression.from_atom(ConceptAtom.create(raw, category))


# ============================================================================
# RULE ENGINE
# ============================================================================

@dataclass
class Rule:
    name: str
    pattern: Expression
    replacement: Expression
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None

    def apply(self, expr: Expression) -> Optional[Expression]:
        bindings = self._match(self.pattern, expr)
        if bindings is not None:
            if self.condition is None or self.condition(bindings):
                return self._substitute_bindings(self.replacement, bindings)
        return None

    def _match(self, pattern: Expression, target: Expression) -> Optional[Dict[str, Any]]:
        bindings: Dict[str, Any] = {}
        if self._match_recursive(pattern, target, bindings):
            return bindings
        return None

    def _match_recursive(self, pattern: Expression, target: Expression,
                         bindings: Dict[str, Any]) -> bool:
        if pattern.is_leaf and pattern.atom and pattern.atom.name.startswith("?"):
            var_name = pattern.atom.name[1:]
            if var_name in bindings:
                return bindings[var_name] == target
            bindings[var_name] = target
            return True
        if pattern.is_leaf and target.is_leaf:
            return pattern.atom == target.atom
        if pattern.operator != target.operator:
            return False
        if len(pattern.operands) != len(target.operands):
            return False
        for po, to in zip(pattern.operands, target.operands, strict=True):
            if isinstance(po, Expression) and isinstance(to, Expression):
                if not self._match_recursive(po, to, bindings):
                    return False
            elif isinstance(po, ConceptAtom) and isinstance(to, ConceptAtom):
                if po != to:
                    return False
            else:
                return False
        return True

    def _substitute_bindings(self, expr: Expression, bindings: Dict[str, Any]) -> Expression:
        if expr.is_leaf and expr.atom and expr.atom.name.startswith("?"):
            var_name = expr.atom.name[1:]
            if var_name in bindings:
                result = bindings[var_name]
                if isinstance(result, Expression):
                    return result
                elif isinstance(result, ConceptAtom):
                    return Expression.from_atom(result)
        if expr.is_leaf:
            return expr
        new_operands = []
        for o in expr.operands:
            if isinstance(o, Expression):
                new_operands.append(self._substitute_bindings(o, bindings))
            else:
                new_operands.append(o)
        return Expression.from_operator(expr.operator, *new_operands,
                                        bindings=expr.bindings.copy())


class RuleEngine:
    def __init__(self):
        self.rules: List[Rule] = []
        self.max_passes = 100

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def normalize(self, expr: Expression) -> Expression:
        current = expr
        for _ in range(self.max_passes):
            changed = False
            for rule in self.rules:
                result = rule.apply(current)
                if result is not None and result != current:
                    current = result
                    changed = True
                    break
            if not changed:
                break
        return current

    def evaluate(self, expr: Expression) -> Expression:
        return self.normalize(expr)


# ============================================================================
# COMMUNICATION
# ============================================================================

_msg_counter = itertools.count()

@dataclass(frozen=True)
class AlgebraicMessage:
    sender: str
    receiver: str
    message_type: MessageType
    payload: Expression
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: hashlib.sha256(f"{time.time()}_{next(_msg_counter)}".encode()).hexdigest()[:16])

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "message_type": self.message_type.value,
            "payload": self.payload.to_dict(),
            "payload_text": self.payload.serialize(),
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


class Blackboard:
    def __init__(self):
        self._data: Dict[str, Expression] = {}
        self._writers: Dict[str, str] = {}
        self._history: List[Dict[str, Any]] = []

    def write(self, key: str, value: Expression, writer: str) -> None:
        self._data[key] = value
        self._writers[key] = writer
        self._history.append({
            "version": len(self._history),
            "key": key,
            "value": value.serialize(),
            "writer": writer
        })

    def read(self, key: str) -> Optional[Expression]:
        return self._data.get(key)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"value": v.serialize(), "writer": self._writers.get(k, "unknown")}
                for k, v in self._data.items()}


# ============================================================================
# AGENTS WITH REAL CAPABILITIES
# ============================================================================

class Agent(ABC):
    def __init__(self, agent_id: str, role: AgentRole):
        self.agent_id = agent_id
        self.role = role
        self._knowledge: Dict[str, Expression] = {}
        self._inbox: List[AlgebraicMessage] = []
        self._outbox: List[AlgebraicMessage] = []
        self._processed_count = 0
        self._state = "idle"
        self._current_task: Optional[Expression] = None

    @abstractmethod
    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        pass

    def receive(self, message: AlgebraicMessage) -> None:
        self._inbox.append(message)

    def process_inbox(self, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        while self._inbox:
            message = self._inbox.pop(0)
            self._state = "processing"
            self._current_task = message.payload
            try:
                result = self.process_message(message, blackboard)
                responses.extend(result)
                self._processed_count += 1
            finally:
                self._state = "idle"
                self._current_task = None
        return responses

    def learn(self, key: str, value: Expression) -> None:
        self._knowledge[key] = value

    def recall(self, key: str) -> Optional[Expression]:
        return self._knowledge.get(key)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "state": self._state,
            "processed_count": self._processed_count,
            "inbox_size": len(self._inbox),
            "current_task": self._current_task.serialize() if self._current_task else None,
            "knowledge_keys": list(self._knowledge.keys())
        }


class Orchestrator(Agent):
    def __init__(self, agent_id: str = "orchestrator"):
        super().__init__(agent_id, AgentRole.ORCHESTRATOR)
        self._active_tasks: Dict[str, Expression] = {}
        self._task_assignments: Dict[str, List[str]] = {}

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type == MessageType.DIRECTIVE:
            task_id = hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]
            self._active_tasks[task_id] = message.payload

            # Decompose based on payload structure
            payload = message.payload
            if payload.operator == Operator.COMPOSE:
                # Multi-step task: delegate to planner first
                responses.append(AlgebraicMessage(
                    sender=self.agent_id,
                    receiver="planner",
                    message_type=MessageType.DELEGATION,
                    payload=C.goal("plan_task", metadata={"task_id": task_id}) @ message.payload
                ))
            else:
                # Single-step: delegate to analyst
                responses.append(AlgebraicMessage(
                    sender=self.agent_id,
                    receiver="analyst",
                    message_type=MessageType.DELEGATION,
                    payload=C.goal("analyze_task", metadata={"task_id": task_id}) @ message.payload
                ))

            blackboard.write(f"task:{task_id}", message.payload, self.agent_id)

        elif message.message_type == MessageType.RESULT:
            # Route results back to original requester or synthesize
            if message.sender == "synthesizer":
                # Final result - store and acknowledge
                task_id = next((atom.metadata["task_id"] for atom in message.payload.atoms if "task_id" in atom.metadata), "unknown")
                blackboard.write(f"result:{task_id}", message.payload, self.agent_id)
            else:
                # Intermediate result - send to synthesizer
                responses.append(AlgebraicMessage(
                    sender=self.agent_id,
                    receiver="synthesizer",
                    message_type=MessageType.SYNTHESIS,
                    payload=message.payload
                ))

        return responses


class Analyst(Agent):
    def __init__(self, agent_id: str = "analyst"):
        super().__init__(agent_id, AgentRole.ANALYST)
        self._rule_engine = RuleEngine()
        self._setup_rules()

    def _setup_rules(self) -> None:
        # Decomposition rules. Pattern variables are category-agnostic
        # wildcards, so the condition restricts this rule to goal atoms.
        self._rule_engine.add_rule(Rule(
            name="decompose_goal",
            pattern=Expression.from_atom(ConceptAtom.create("?g", ConceptCategory.GOAL)),
            replacement=C.compose(
                C.action("analyze_requirements"),
                C.action("identify_constraints"),
                C.action("assess_feasibility")
            ),
            condition=lambda b: b["g"].is_leaf and b["g"].atom.category == ConceptCategory.GOAL,
        ))

    def _analyze(self, payload: Expression) -> Expression:
        # Keep the delegation header (which carries the task_id) intact and
        # analyze each component of the task body independently.
        if payload.operator == Operator.COMPOSE:
            head, *body = payload.operands
            if head.is_leaf and head.atom.name == "analyze_task":
                return C.compose(head, *(self._rule_engine.evaluate(o) for o in body))
        return self._rule_engine.evaluate(payload)

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type in (MessageType.QUERY, MessageType.DELEGATION):
            # Analyze the payload
            analyzed = self._analyze(message.payload)

            # Store analysis on blackboard
            analysis_key = f"analysis:{hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]}"
            blackboard.write(analysis_key, analyzed, self.agent_id)

            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="orchestrator",
                message_type=MessageType.RESULT,
                payload=C.state("analyzed") @ analyzed
            ))
        return responses


class Planner(Agent):
    def __init__(self, agent_id: str = "planner"):
        super().__init__(agent_id, AgentRole.PLANNER)

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type in (MessageType.DIRECTIVE, MessageType.DELEGATION):
            payload = message.payload

            # Create a structured plan based on the goal
            if payload.operator == Operator.COMPOSE and len(payload.operands) > 0:
                # Already has structure - refine it
                plan = self._refine_plan(payload)
            else:
                # Create default plan
                plan = C.compose(
                    C.action("prepare", metadata={"phase": "1"}),
                    C.action("execute_core", metadata={"phase": "2"}),
                    C.action("validate", metadata={"phase": "3"}),
                    C.action("finalize", metadata={"phase": "4"})
                )

            plan_key = f"plan:{hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]}"
            blackboard.write(plan_key, plan, self.agent_id)

            # Delegate execution steps
            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="executor",
                message_type=MessageType.DIRECTIVE,
                payload=plan
            ))

            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="orchestrator",
                message_type=MessageType.RESULT,
                payload=C.state("planned") @ plan
            ))
        return responses

    def _refine_plan(self, expr: Expression) -> Expression:
        # Add validation and synthesis steps
        return C.compose(
            expr,
            C.action("validate_plan"),
            C.action("synthesize_output")
        )


class Executor(Agent):
    def __init__(self, agent_id: str = "executor"):
        super().__init__(agent_id, AgentRole.EXECUTOR)
        self._execution_log: List[Dict[str, Any]] = []

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type == MessageType.DIRECTIVE:
            payload = message.payload

            # Simulate execution of each step
            if payload.operator == Operator.COMPOSE:
                executed_steps = []
                for i, operand in enumerate(payload.operands):
                    if isinstance(operand, Expression):
                        step_result = C.state("executed", metadata={
                            "step": str(i),
                            "status": "success",
                            "agent": self.agent_id
                        }) @ operand
                        executed_steps.append(step_result)
                        self._execution_log.append({
                            "step": i,
                            "input": operand.serialize(),
                            "status": "success"
                        })

                result = C.compose(*executed_steps) if len(executed_steps) > 1 else executed_steps[0]
            else:
                result = C.state("executed") @ payload

            exec_key = f"execution:{hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]}"
            blackboard.write(exec_key, result, self.agent_id)

            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="validator",
                message_type=MessageType.VALIDATION,
                payload=result
            ))
        elif message.message_type == MessageType.FEEDBACK:
            # Validation failed. Re-executing the same deterministic plan would
            # fail identically, so escalate the failure instead of retrying.
            self._execution_log.append({
                "step": None,
                "input": message.payload.serialize(),
                "status": "failed"
            })
            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="orchestrator",
                message_type=MessageType.RESULT,
                payload=message.payload
            ))
        return responses


class Validator(Agent):
    def __init__(self, agent_id: str = "validator"):
        super().__init__(agent_id, AgentRole.VALIDATOR)
        self._validation_results: List[Dict[str, Any]] = []

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type == MessageType.VALIDATION:
            payload = message.payload

            # Perform validation checks
            is_valid = self._validate(payload)

            if is_valid:
                result = C.state("validated", metadata={"status": "passed"}) @ payload
                responses.append(AlgebraicMessage(
                    sender=self.agent_id,
                    receiver="synthesizer",
                    message_type=MessageType.SYNTHESIS,
                    payload=result
                ))
            else:
                result = C.state("validated", metadata={"status": "failed"}) @ payload
                responses.append(AlgebraicMessage(
                    sender=self.agent_id,
                    receiver="executor",
                    message_type=MessageType.FEEDBACK,
                    payload=result
                ))

            val_key = f"validation:{hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]}"
            blackboard.write(val_key, result, self.agent_id)
        return responses

    def _validate(self, expr: Expression) -> bool:
        # Check for error states, contradictions, etc.
        atoms = expr.atoms
        for atom in atoms:
            if atom.name == "error" or atom.name == "failed":
                return False
        return True


class Synthesizer(Agent):
    def __init__(self, agent_id: str = "synthesizer"):
        super().__init__(agent_id, AgentRole.SYNTHESIZER)

    def process_message(self, message: AlgebraicMessage, blackboard: Blackboard) -> List[AlgebraicMessage]:
        responses = []
        if message.message_type == MessageType.SYNTHESIS:
            payload = message.payload

            # Synthesize final output
            task_id = next((atom.metadata["task_id"] for atom in payload.atoms if "task_id" in atom.metadata), "unknown")
            synthesized = C.state("synthesized", metadata={"agent": self.agent_id, "task_id": task_id}) @ payload

            synth_key = f"synthesis:{hashlib.sha256(message.payload.serialize().encode()).hexdigest()[:8]}"
            blackboard.write(synth_key, synthesized, self.agent_id)

            responses.append(AlgebraicMessage(
                sender=self.agent_id,
                receiver="orchestrator",
                message_type=MessageType.RESULT,
                payload=synthesized
            ))
        return responses


# ============================================================================
# SWARM CONTROLLER WITH VISUALIZATION EXPORT
# ============================================================================

class SwarmController:
    # Consecutive steps without any new messages before the swarm is
    # considered to have reached a fixed point.
    CONVERGENCE_WINDOW = 3

    def __init__(self):
        self._agents: Dict[str, Agent] = {}
        self._blackboard = Blackboard()
        self._step_count = 0
        self._max_steps = 1000
        self._message_log: List[AlgebraicMessage] = []
        self._snapshots: List[Dict[str, Any]] = []
        self._converged = False
        self._idle_steps = 0
        self._pending_injections: List[AlgebraicMessage] = []
        self._message_seq = itertools.count()

    @property
    def converged(self) -> bool:
        return self._converged

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """The frame recorded by the most recent step, or None before any step."""
        return self._snapshots[-1] if self._snapshots else None

    def _stamp(self, message: AlgebraicMessage) -> AlgebraicMessage:
        # Replace wall-clock metadata with a logical clock so that identical
        # inputs always produce byte-identical traces.
        seq = next(self._message_seq)
        digest = hashlib.sha256(
            f"{seq}|{message.sender}|{message.receiver}|"
            f"{message.message_type.value}|{message.payload.serialize()}".encode()
        ).hexdigest()[:16]
        return dataclasses.replace(message, timestamp=float(self._step_count),
                                   correlation_id=digest)

    def register_agent(self, agent: Agent) -> None:
        self._agents[agent.agent_id] = agent

    def inject_task(self, expression: Expression, sender: str = "user") -> str:
        if "orchestrator" not in self._agents:
            raise RuntimeError("inject_task requires an agent registered as 'orchestrator'")
        task_id = hashlib.sha256(expression.serialize().encode()).hexdigest()[:8]
        message = self._stamp(AlgebraicMessage(
            sender=sender,
            receiver="orchestrator",
            message_type=MessageType.DIRECTIVE,
            payload=expression
        ))
        self._agents["orchestrator"].receive(message)
        # Recorded with the next step so the trace shows where work entered.
        self._pending_injections.append(message)
        self._converged = False
        self._idle_steps = 0
        return task_id

    def step(self) -> int:
        messages_processed = 0
        injected, self._pending_injections = self._pending_injections, []
        new_messages: List[AlgebraicMessage] = []

        for agent in self._agents.values():
            responses = agent.process_inbox(self._blackboard)
            for response in responses:
                new_messages.append(self._stamp(response))
                messages_processed += 1

        # Route messages
        for msg in new_messages:
            if msg.receiver in self._agents:
                self._agents[msg.receiver].receive(msg)
        self._message_log.extend(injected)
        self._message_log.extend(new_messages)

        self._step_count += 1

        if messages_processed == 0:
            self._idle_steps += 1
            if self._idle_steps >= self.CONVERGENCE_WINDOW:
                self._converged = True
        else:
            self._idle_steps = 0

        self._snapshots.append(self.snapshot(messages_processed, injected + new_messages))

        return messages_processed

    def snapshot(self, activity: int = 0,
                 messages: Optional[List[AlgebraicMessage]] = None) -> Dict[str, Any]:
        """Current swarm state in the frame format used by traces and the dashboard."""
        return {
            "step": self._step_count,
            "activity": activity,
            "converged": self._converged,
            "agents": {aid: agent.to_dict() for aid, agent in self._agents.items()},
            "blackboard": self._blackboard.get_all(),
            "messages": [msg.to_dict() for msg in messages or []],
            "message_count": len(self._message_log)
        }

    def run_until_convergence(self, max_steps: Optional[int] = None) -> Dict[str, Any]:
        if max_steps is None:
            max_steps = self._max_steps

        for _ in range(max_steps):
            self.step()
            if self._converged:
                break

        return {
            "steps_executed": self._step_count,
            "total_agents": len(self._agents),
            "converged": self._converged,
            "total_messages": len(self._message_log),
            "blackboard_entries": len(self._blackboard.get_all())
        }

    def export_trace(self) -> Dict[str, Any]:
        return {
            "system": "ASIS 2.0",
            "version": __version__,
            "statistics": {
                "total_steps": self._step_count,
                "total_agents": len(self._agents),
                "total_messages": len(self._message_log),
                "converged": self._converged
            },
            "agents": {aid: agent.to_dict() for aid, agent in self._agents.items()},
            "blackboard": self._blackboard.get_all(),
            "snapshots": self._snapshots,
            "message_log": [msg.to_dict() for msg in self._message_log]
        }

    def save_trace(self, filepath: str) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.export_trace(), f, indent=2, default=str)


def create_default_swarm() -> SwarmController:
    controller = SwarmController()
    controller.register_agent(Orchestrator())
    controller.register_agent(Analyst())
    controller.register_agent(Planner())
    controller.register_agent(Executor())
    controller.register_agent(Validator())
    controller.register_agent(Synthesizer())
    return controller
