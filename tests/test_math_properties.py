import pytest
from asis import C, Expression, ConceptAtom, ConceptCategory, Operator

def test_associativity_compose():
    A = C.entity("A")
    B = C.entity("B")
    C_ent = C.entity("C")

    expr1 = C.compose(A, C.compose(B, C_ent))
    expr2 = C.compose(C.compose(A, B), C_ent)
    expr3 = C.compose(A, B, C_ent)

    assert expr1 == expr2 == expr3

    # Deep nesting
    D = C.entity("D")
    expr4 = C.compose(C.compose(A, C.compose(B, C_ent)), D)
    expr5 = C.compose(A, B, C_ent, D)
    assert expr4 == expr5

def test_associativity_union():
    A = C.entity("A")
    B = C.entity("B")
    C_ent = C.entity("C")

    expr1 = C.union(A, C.union(B, C_ent))
    expr2 = C.union(C.union(A, B), C_ent)
    expr3 = C.union(A, B, C_ent)

    assert expr1 == expr2 == expr3

def test_idempotence():
    A = C.entity("A")
    expr = C.union(A, A)
    assert expr == A

    # Multiple duplicates
    expr2 = C.union(A, A, A, A)
    assert expr2 == A

    # Mixed with other elements
    B = C.entity("B")
    expr3 = C.union(A, B, A, B)
    # Order might matter internally, but let's assert they resolve to same unique set
    assert len(expr3.operands) == 2
    assert A in expr3.operands
    assert B in expr3.operands

def test_double_negation():
    A = C.entity("A")
    expr = C.negate(A)
    expr2 = C.negate(expr)
    assert expr2 == A

    # Triple negation
    expr3 = C.negate(expr2)
    assert expr3 == expr

def test_identity_compose():
    A = C.entity("A")
    ident = C.identity()

    # A * 1 = A
    assert C.compose(A, ident) == A
    assert C.compose(ident, A) == A

    # 1 * 1 = 1
    assert C.compose(ident, ident) == ident

    # A * B * 1 = A * B
    B = C.entity("B")
    assert C.compose(A, B, ident) == C.compose(A, B)

def test_absorption_compose():
    A = C.entity("A")
    B = C.entity("B")
    zero = C.zero()

    # A * 0 = 0
    assert C.compose(A, zero) == zero
    assert C.compose(zero, A) == zero

    # A * B * 0 = 0
    assert C.compose(A, B, zero) == zero

    # 1 * 0 = 0
    ident = C.identity()
    assert C.compose(ident, zero) == zero

def test_closed_algebra_operators():
    # Test all 10 operators can be instantiated
    A = C.entity("A")
    B = C.entity("B")

    assert C.compose(A, B).operator == Operator.COMPOSE
    assert C.union(A, B).operator == Operator.UNION
    assert C.negate(A).operator == Operator.NEGATE
    assert C.project(A, "field").operator == Operator.PROJECT
    assert C.inject(A, "target").operator == Operator.INJECT
    assert C.bind(A, "var", "val").operator == Operator.BIND
    assert C.reduce(A, "acc").operator == Operator.REDUCE
    assert C.transform(A, "domain").operator == Operator.TRANSFORM
    assert C.guard(A, B).operator == Operator.GUARD
    assert C.fixpoint(A).operator == Operator.FIXPOINT
