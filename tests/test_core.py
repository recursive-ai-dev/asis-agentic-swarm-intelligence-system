"""Tests for the algebraic core: concepts, expressions, the C factory and the rule engine."""

import pytest

from asis import C, ConceptAtom, ConceptCategory, Expression, Operator, Rule, RuleEngine



# ============================================================================
# CONCEPTATOM
# ============================================================================

class TestConceptAtom:
    def test_create(self):
        a = ConceptAtom.create("test", ConceptCategory.ENTITY, "domain", {"key": "val"})
        assert a.name == "test"
        assert a.category == ConceptCategory.ENTITY
        assert a.domain == "domain"
        assert a.metadata == {"key": "val"}

    def test_create_default_domain(self):
        a = ConceptAtom.create("test", ConceptCategory.GOAL)
        assert a.domain == "general"
        assert a.metadata == {}

    def test_create_no_metadata(self):
        a = ConceptAtom.create("x", ConceptCategory.ACTION, "sys")
        assert a.metadata_tuple == ()

    def test_serialize(self):
        a = ConceptAtom.create("foo", ConceptCategory.CONSTRAINT, "net")
        assert a.serialize() == "ATOM(foo:CONSTRAINT:net)"

    def test_to_dict(self):
        a = ConceptAtom.create("bar", ConceptCategory.STATE, "sys", {"k": "v"})
        assert a.to_dict() == {
            "name": "bar",
            "category": "STATE",
            "domain": "sys",
            "metadata": {"k": "v"},
        }

    def test_matches_pattern_exact(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY, "d")
        p = ConceptAtom.create("x", ConceptCategory.ENTITY, "d")
        assert a.matches_pattern(p)

    def test_matches_pattern_wildcard_name(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        p = ConceptAtom.create("_", ConceptCategory.ENTITY)
        assert a.matches_pattern(p)

    def test_matches_pattern_wildcard_domain(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY, "d")
        p = ConceptAtom.create("x", ConceptCategory.ENTITY, "_")
        assert a.matches_pattern(p)

    def test_matches_pattern_mismatch_category(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        p = ConceptAtom.create("x", ConceptCategory.ACTION)
        assert not a.matches_pattern(p)

    def test_matches_pattern_mismatch_name(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        p = ConceptAtom.create("y", ConceptCategory.ENTITY)
        assert not a.matches_pattern(p)

    def test_with_domain(self):
        a = ConceptAtom.create("x", ConceptCategory.GOAL, "old")
        b = a.with_domain("new")
        assert b.domain == "new"
        assert b.name == "x"
        assert a.domain == "old"  # immutability

    def test_frozen_immutable(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        with pytest.raises(AttributeError):
            a.name = "y"  # type: ignore[misc]

    def test_hashable(self):
        a1 = ConceptAtom.create("x", ConceptCategory.ENTITY)
        a2 = ConceptAtom.create("x", ConceptCategory.ENTITY)
        s = {a1, a2}
        assert len(s) == 1

    def test_repr(self):
        a = ConceptAtom.create("foo", ConceptCategory.ACTION, "sys")
        assert repr(a) == "foo:ACTION:sys"


# ============================================================================
# EXPRESSION
# ============================================================================

class TestExpression:
    def test_from_atom(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        e = Expression.from_atom(a)
        assert e.is_leaf
        assert e.atom == a

    def test_from_operator(self):
        a1 = ConceptAtom.create("a", ConceptCategory.ACTION)
        a2 = ConceptAtom.create("b", ConceptCategory.ACTION)
        e = Expression.from_operator(Operator.COMPOSE, a1, a2)
        assert not e.is_leaf
        assert e.operator == Operator.COMPOSE
        assert len(e.operands) == 2

    def test_from_operator_with_expressions(self):
        e1 = Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION))
        e2 = Expression.from_atom(ConceptAtom.create("b", ConceptCategory.ACTION))
        e = Expression.from_operator(Operator.UNION, e1, e2)
        assert e.operator == Operator.UNION

    def test_from_operator_raises_on_bad_type(self):
        with pytest.raises(TypeError):
            Expression.from_operator(Operator.COMPOSE, "not_valid")

    def test_leaf_depth(self):
        e = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        assert e.depth == 0

    def test_nested_depth(self):
        inner = Expression.from_operator(
            Operator.UNION,
            ConceptAtom.create("a", ConceptCategory.ACTION),
            ConceptAtom.create("b", ConceptCategory.ACTION),
        )
        # Operator.COMPOSE automatically unwraps if there's only one element, because of identity rules,
        # or maybe the logic strips it. Oh right, COMPOSE with a single operand is just the operand itself!
        # Let's add a second operand so it doesn't unwrap.
        outer = Expression.from_operator(Operator.COMPOSE, inner, ConceptAtom.create("c", ConceptCategory.ACTION))
        assert outer.depth == 2

    def test_depth_cached(self):
        e = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        assert e.depth == 0
        assert e._depth_cache == 0

    def test_atoms_leaf(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        e = Expression.from_atom(a)
        assert e.atoms == frozenset({a})

    def test_atoms_nested(self):
        a1 = ConceptAtom.create("a", ConceptCategory.ACTION)
        a2 = ConceptAtom.create("b", ConceptCategory.ACTION)
        e = Expression.from_operator(Operator.COMPOSE, a1, a2)
        assert e.atoms == frozenset({a1, a2})

    def test_atoms_cached(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        e = Expression.from_atom(a)
        assert e.atoms == frozenset({a})
        assert e._atoms_cache is not None

    def test_to_dict_atom(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY, "d")
        e = Expression.from_atom(a)
        d = e.to_dict()
        assert d["type"] == "atom"
        assert d["atom"]["name"] == "x"

    def test_to_dict_expression(self):
        a = ConceptAtom.create("x", ConceptCategory.ENTITY)
        e = Expression.from_operator(Operator.NEGATE, a)
        d = e.to_dict()
        assert d["type"] == "expression"
        assert d["operator"] == Operator.NEGATE.value

    def test_substitute_atom(self):
        old = ConceptAtom.create("a", ConceptCategory.ENTITY)
        new = ConceptAtom.create("b", ConceptCategory.ENTITY)
        e = Expression.from_atom(old)
        result = e.substitute(old, new)
        assert result.atom == new

    def test_substitute_expression(self):
        old = ConceptAtom.create("a", ConceptCategory.ENTITY)
        new_expr = Expression.from_operator(
            Operator.COMPOSE,
            ConceptAtom.create("b", ConceptCategory.ENTITY),
            ConceptAtom.create("c", ConceptCategory.ENTITY),
        )
        e = Expression.from_atom(old)
        result = e.substitute(old, new_expr)
        assert not result.is_leaf
        assert result.operator == Operator.COMPOSE

    def test_substitute_no_match(self):
        old = ConceptAtom.create("a", ConceptCategory.ENTITY)
        other = ConceptAtom.create("b", ConceptCategory.ENTITY)
        e = Expression.from_atom(old)
        result = e.substitute(other, ConceptAtom.create("c", ConceptCategory.ENTITY))
        assert result == e

    def test_substitute_nested(self):
        old = ConceptAtom.create("a", ConceptCategory.ENTITY)
        new = ConceptAtom.create("z", ConceptCategory.ENTITY)
        inner = Expression.from_operator(
            Operator.COMPOSE, old, ConceptAtom.create("b", ConceptCategory.ENTITY)
        )
        outer = Expression.from_operator(Operator.UNION, inner)
        result = outer.substitute(old, new)
        result_atoms = {ca.name for ca in result.atoms}
        assert "z" in result_atoms
        assert "a" not in result_atoms

    def test_serialize_atom(self):
        a = ConceptAtom.create("x", ConceptCategory.ACTION, "d")
        e = Expression.from_atom(a)
        assert e.serialize() == "ATOM(x:ACTION:d)"

    def test_serialize_expression(self):
        e = Expression.from_operator(
            Operator.COMPOSE,
            ConceptAtom.create("a", ConceptCategory.ACTION),
            ConceptAtom.create("b", ConceptCategory.ACTION),
        )
        s = e.serialize()
        assert s.startswith("(⊗")
        assert "ATOM(a:ACTION:general)" in s
        assert "ATOM(b:ACTION:general)" in s

    def test_serialize_with_bindings(self):
        e = Expression(
            operator=Operator.COMPOSE,
            operands=(Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION)),),
            bindings={"task_id": "abc123"},
        )
        s = e.serialize()
        assert "[task_id=abc123]" in s

    def test_serialize_cached(self):
        e = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        s1 = e.serialize()
        s2 = e.serialize()
        assert s1 == s2
        assert e._serialize_cache is not None

    def test_hash(self):
        e1 = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        e2 = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        assert hash(e1) == hash(e2)

    def test_eq(self):
        e1 = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        e2 = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        assert e1 == e2

    def test_eq_different(self):
        e1 = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        e2 = Expression.from_atom(ConceptAtom.create("y", ConceptCategory.ENTITY))
        assert e1 != e2

    def test_repr(self):
        e = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.GOAL))
        assert repr(e) == e.serialize()

    def test_matmul_operator(self):
        a = Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION))
        b = Expression.from_atom(ConceptAtom.create("b", ConceptCategory.ACTION))
        result = a @ b
        assert result.operator == Operator.COMPOSE
        assert len(result.operands) == 2

    def test_matmul_with_atom(self):
        e = Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION))
        a = ConceptAtom.create("b", ConceptCategory.ACTION)
        result = e @ a
        assert result.operator == Operator.COMPOSE

    def test_or_operator(self):
        a = Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION))
        b = Expression.from_atom(ConceptAtom.create("b", ConceptCategory.ACTION))
        result = a | b
        assert result.operator == Operator.UNION

    def test_or_with_atom(self):
        e = Expression.from_atom(ConceptAtom.create("a", ConceptCategory.ACTION))
        a = ConceptAtom.create("b", ConceptCategory.ACTION)
        result = e | a
        assert result.operator == Operator.UNION

    def test_invert_operator(self):
        e = Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY))
        result = ~e
        assert result.operator == Operator.NEGATE


# ============================================================================
# C FACTORY
# ============================================================================

class TestCFactory:
    def test_entity(self):
        e = C.entity("server")
        assert e.is_leaf
        assert e.atom.category == ConceptCategory.ENTITY
        assert e.atom.name == "server"

    def test_action(self):
        e = C.action("deploy")
        assert e.atom.category == ConceptCategory.ACTION

    def test_property(self):
        e = C.property("latency")
        assert e.atom.category == ConceptCategory.PROPERTY

    def test_constraint(self):
        e = C.constraint("latency < 100ms")
        assert e.atom.category == ConceptCategory.CONSTRAINT

    def test_goal(self):
        e = C.goal("optimize")
        assert e.atom.category == ConceptCategory.GOAL

    def test_state(self):
        e = C.state("ready")
        assert e.atom.category == ConceptCategory.STATE

    def test_compose(self):
        e = C.compose(C.action("a"), C.action("b"))
        assert e.operator == Operator.COMPOSE

    def test_compose_requires_two(self):
        with pytest.raises(ValueError, match="COMPOSE requires at least 2 operands"):
            C.compose(C.action("a"))

    def test_union(self):
        e = C.union(C.action("a"), C.action("b"))
        assert e.operator == Operator.UNION

    def test_union_requires_two(self):
        with pytest.raises(ValueError, match="UNION requires at least 2 operands"):
            C.union(C.action("a"))

    def test_guard(self):
        e = C.guard(C.constraint("x < 1"), C.action("do_it"))
        assert e.operator == Operator.GUARD
        assert len(e.operands) == 2

    def test_entity_with_metadata(self):
        e = C.entity("server", "cloud", {"region": "us-east"})
        assert e.atom.metadata == {"region": "us-east"}
        assert e.atom.domain == "cloud"

    def test_compose_with_mixed_types(self):
        e = C.compose(C.goal("g"), ConceptAtom.create("c", ConceptCategory.CONSTRAINT))
        assert e.operator == Operator.COMPOSE


# ============================================================================
# RULE ENGINE
# ============================================================================

class TestRule:
    def test_rule_apply_match(self):
        var_a = ConceptAtom.create("?x", ConceptCategory.ACTION)
        pattern = Expression.from_atom(var_a)
        replacement = C.action("resolved")
        rule = Rule("test", pattern, replacement)
        target = C.action("anything")
        result = rule.apply(target)
        assert result == replacement

    def test_rule_apply_no_match(self):
        pattern = Expression.from_atom(ConceptAtom.create("_", ConceptCategory.ACTION))
        replacement = C.action("resolved")
        rule = Rule("test", pattern, replacement)
        target = C.entity("not_action")
        result = rule.apply(target)
        assert result is None

    def test_variable_wildcard_matches_any_category(self):
        var_pattern = Expression.from_atom(ConceptAtom.create("?x", ConceptCategory.ACTION))
        rule = Rule("wildcard", var_pattern, C.action("matched"))
        target = C.entity("anything")
        result = rule.apply(target)
        assert result == C.action("matched")

    def test_rule_with_condition(self):
        var_a = ConceptAtom.create("?x", ConceptCategory.ACTION)
        pattern = Expression.from_atom(var_a)
        replacement = C.action("resolved")
        rule = Rule("test", pattern, replacement, condition=lambda b: False)
        target = C.action("anything")
        result = rule.apply(target)
        assert result is None

    def test_rule_condition_passes(self):
        var_a = ConceptAtom.create("?x", ConceptCategory.ACTION)
        pattern = Expression.from_atom(var_a)
        replacement = C.action("resolved")
        rule = Rule("test", pattern, replacement, condition=lambda b: True)
        target = C.action("anything")
        result = rule.apply(target)
        assert result == replacement

    def test_match_variable_binding(self):
        var_x = ConceptAtom.create("?x", ConceptCategory.ACTION)
        pattern = Expression.from_atom(var_x)
        rule = Rule("test", pattern, C.action("dummy"))
        target = C.action("hello")
        bindings = rule._match(pattern, target)
        assert bindings is not None
        assert bindings["x"] == target

    def test_match_consistent_binding(self):
        var_x = ConceptAtom.create("?x", ConceptCategory.ACTION)
        pattern = Expression.from_operator(Operator.GUARD, var_x, var_x)
        rule = Rule("test", pattern, C.action("dummy"))
        # A variable occurring twice must bind to the same subexpression
        same = C.guard(C.action("hello"), C.action("hello"))
        b1 = rule._match(pattern, same)
        assert b1 is not None
        assert b1["x"] == C.action("hello")
        different = C.guard(C.action("hello"), C.action("world"))
        assert rule._match(pattern, different) is None

    def test_match_structurally_different(self):
        pattern = Expression.from_operator(
            Operator.COMPOSE,
            ConceptAtom.create("?a", ConceptCategory.ACTION),
            ConceptAtom.create("?b", ConceptCategory.ACTION),
        )
        rule = Rule("test", pattern, C.action("dummy"))
        target = Expression.from_operator(
            Operator.UNION,
            C.action("x"),
            C.action("y"),
        )
        result = rule.apply(target)
        assert result is None


class TestRuleEngine:
    def test_add_rule(self):
        engine = RuleEngine()
        rule = Rule("r1", C.action("a"), C.action("b"))
        engine.add_rule(rule)
        assert len(engine.rules) == 1

    def test_normalize_identity(self):
        engine = RuleEngine()
        expr = C.action("stay")
        result = engine.normalize(expr)
        assert result == expr

    def test_normalize_triggers_rule(self):
        engine = RuleEngine()
        var_a = ConceptAtom.create("?x", ConceptCategory.ACTION)
        engine.add_rule(Rule("resolve", Expression.from_atom(var_a), C.action("resolved")))
        result = engine.normalize(C.action("anything"))
        assert result == C.action("resolved")

    def test_normalize_chaining(self):
        engine = RuleEngine()
        var_x = ConceptAtom.create("?x", ConceptCategory.ACTION)
        engine.add_rule(
            Rule("step1", Expression.from_atom(var_x), C.action("mid"))
        )
        result = engine.normalize(C.action("start"))
        assert result == C.action("mid")

    def test_evaluate_delegates(self):
        engine = RuleEngine()
        result = engine.evaluate(C.goal("test"))
        assert result == C.goal("test")

    def test_max_passes_bound(self):
        engine = RuleEngine()
        engine.max_passes = 1
        var_x = ConceptAtom.create("?x", ConceptCategory.ACTION)
        # A rule that keeps expanding
        engine.add_rule(
            Rule("loop", Expression.from_atom(var_x),
                 C.compose(C.action("a"), C.action("b")))
        )
        result = engine.normalize(C.action("in"))
        # At least one pass happened
        assert result != C.action("in")


class TestRewrite:
    def test_rewrites_nested_subterms(self):
        engine = RuleEngine()
        engine.add_rule(Rule("a->b", C.goal("a"), C.goal("b")))
        expr = C.compose(C.entity("x"), C.guard(C.goal("a"), C.entity("y")))
        assert engine.normalize(expr) == expr  # root-only rewriting cannot reach it
        assert engine.rewrite(expr) == C.compose(C.entity("x"), C.guard(C.goal("b"), C.entity("y")))

    def test_rewrites_to_fixpoint_through_chains(self):
        engine = RuleEngine()
        engine.add_rule(Rule("top", C.goal("top"), C.compose(C.goal("mid"), C.property("p1"))))
        engine.add_rule(Rule("mid", C.goal("mid"), C.compose(C.property("p2"), C.property("p3"))))
        result = engine.rewrite(C.goal("top"))
        assert {a.name for a in result.atoms} == {"p1", "p2", "p3"}

    def test_rewrite_to_identity_disappears_in_compose(self):
        engine = RuleEngine()
        engine.add_rule(Rule("gone", C.goal("g"), C.identity()))
        assert engine.rewrite(C.compose(C.goal("g"), C.property("p"))) == C.property("p")
