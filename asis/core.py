"""Algebraic core: concepts, expressions, the ASIS notation parser and the rule engine.

Everything the specialists exchange is an :class:`Expression` — an immutable,
canonicalized tree over typed :class:`ConceptAtom` leaves — so that the same
inputs always produce the same trees, hashes and traces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple, Union

__version__ = "3.0.0"


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

    def rewrite(self, expr: Expression) -> Expression:
        """Rewrite every subterm, innermost first, until no rule applies anywhere.

        Unlike :meth:`normalize`, which only rewrites the root, this reaches
        atoms nested inside operators. Bounded by ``max_passes`` per node.
        """
        if not expr.is_leaf:
            operands = [self.rewrite(o) if isinstance(o, Expression) else Expression.from_atom(o)
                        for o in expr.operands]
            if expr.operator is not None:
                expr = Expression.from_operator(expr.operator, *operands, bindings=expr.bindings.copy())
        for _ in range(self.max_passes):
            for rule in self.rules:
                result = rule.apply(expr)
                if result is not None and result != expr:
                    expr = self.rewrite(result) if not result.is_leaf else result
                    break
            else:
                return expr
        return expr
