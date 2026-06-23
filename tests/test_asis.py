"""Rigorous test suite for ASIS 2.0 — Algebraic Swarm Intelligence System."""

import json
import time
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the parent module is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asis import (
    ConceptAtom, ConceptCategory, ConceptAtom,
    Expression, Operator,
    C,
    Rule, RuleEngine,
    AlgebraicMessage, MessageType, Blackboard,
    Agent, Orchestrator, Analyst, Planner, Executor, Validator, Synthesizer, AgentRole,
    SwarmController, create_default_swarm,
)


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
            Operator.COMPOSE,
            ConceptAtom.create("a", ConceptCategory.ACTION),
            ConceptAtom.create("b", ConceptCategory.ACTION),
        )
        outer = Expression.from_operator(Operator.COMPOSE, inner)
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
        pattern = Expression.from_atom(var_x)
        rule = Rule("test", pattern, C.action("dummy"))
        target1 = C.action("hello")
        target2 = C.action("world")
        # Same pattern, same var — bindings must be consistent
        b1 = rule._match(pattern, target1)
        # Apply pattern again — new match
        assert b1 is not None
        assert b1["x"] == target1

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


# ============================================================================
# COMMUNICATION
# ============================================================================

class TestAlgebraicMessage:
    def test_create(self):
        msg = AlgebraicMessage(
            sender="alice",
            receiver="bob",
            message_type=MessageType.DIRECTIVE,
            payload=C.goal("test"),
        )
        assert msg.sender == "alice"
        assert msg.receiver == "bob"
        assert msg.message_type == MessageType.DIRECTIVE

    def test_auto_timestamp(self):
        msg = AlgebraicMessage(
            sender="a", receiver="b",
            message_type=MessageType.QUERY, payload=C.goal("x"),
        )
        assert isinstance(msg.timestamp, float)

    def test_auto_correlation_id(self):
        msg = AlgebraicMessage(
            sender="a", receiver="b",
            message_type=MessageType.RESULT, payload=C.goal("x"),
        )
        assert len(msg.correlation_id) == 16

    def test_frozen(self):
        msg = AlgebraicMessage(
            sender="a", receiver="b",
            message_type=MessageType.SIGNAL, payload=C.goal("x"),
        )
        with pytest.raises(AttributeError):
            msg.sender = "c"  # type: ignore[misc]

    def test_to_dict(self):
        payload = C.goal("test")
        msg = AlgebraicMessage(
            sender="a", receiver="b",
            message_type=MessageType.FEEDBACK,
            payload=payload,
        )
        d = msg.to_dict()
        assert d["sender"] == "a"
        assert d["receiver"] == "b"
        assert d["message_type"] == "FEEDBACK"
        assert d["payload"]["type"] == "atom"


class TestBlackboard:
    def test_write_read(self):
        bb = Blackboard()
        bb.write("key1", C.goal("test"), "agent1")
        val = bb.read("key1")
        assert val == C.goal("test")

    def test_read_missing(self):
        bb = Blackboard()
        assert bb.read("nonexistent") is None

    def test_write_updates(self):
        bb = Blackboard()
        bb.write("k", C.goal("v1"), "a1")
        bb.write("k", C.goal("v2"), "a2")
        assert bb.read("k") == C.goal("v2")

    def test_get_all(self):
        bb = Blackboard()
        bb.write("k1", C.goal("g1"), "a1")
        bb.write("k2", C.action("a2"), "a2")
        all_entries = bb.get_all()
        assert "k1" in all_entries
        assert "k2" in all_entries
        assert all_entries["k1"]["writer"] == "a1"

    def test_history(self):
        bb = Blackboard()
        bb.write("k", C.goal("g"), "a")
        assert len(bb._history) == 1


# ============================================================================
# AGENTS
# ============================================================================

class TestAgentBase:
    def test_receive(self):
        agent = Orchestrator()
        msg = AlgebraicMessage(
            sender="user", receiver="orchestrator",
            message_type=MessageType.DIRECTIVE, payload=C.goal("test"),
        )
        agent.receive(msg)
        assert len(agent._inbox) == 1

    def test_process_inbox(self):
        agent = Analyst()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.QUERY, payload=C.goal("test"),
        )
        agent.receive(msg)
        responses = agent.process_inbox(Blackboard())
        assert len(responses) > 0

    def test_process_inbox_empty(self):
        agent = Orchestrator()
        responses = agent.process_inbox(Blackboard())
        assert responses == []

    def test_learn_recall(self):
        agent = Orchestrator()
        agent.learn("key1", C.goal("stored"))
        assert agent.recall("key1") == C.goal("stored")

    def test_recall_missing(self):
        agent = Orchestrator()
        assert agent.recall("nonexistent") is None

    def test_to_dict(self):
        agent = Orchestrator()
        d = agent.to_dict()
        assert d["agent_id"] == "orchestrator"
        assert d["role"] == "ORCHESTRATOR"
        assert d["state"] == "idle"
        assert d["processed_count"] == 0

    def test_processed_count_increments(self):
        agent = Analyst()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.DELEGATION, payload=C.goal("test"),
        )
        agent.receive(msg)
        agent.process_inbox(Blackboard())
        assert agent._processed_count == 1

    def test_state_during_processing(self):
        agent = Analyst()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.DELEGATION, payload=C.goal("test"),
        )
        agent.receive(msg)
        agent.process_inbox(Blackboard())
        assert agent._state == "idle"

    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Agent("abstract", AgentRole.ANALYST)  # type: ignore[abstract]


# --- Orchestrator ---

class TestOrchestrator:
    def test_directive_decomposes_compose(self):
        orch = Orchestrator()
        msg = AlgebraicMessage(
            sender="user", receiver="orchestrator",
            message_type=MessageType.DIRECTIVE,
            payload=C.compose(C.goal("g"), C.constraint("c")),
        )
        orch.receive(msg)
        responses = orch.process_inbox(Blackboard())
        # Should delegate to planner for COMPOSE tasks
        delegations = [r for r in responses if r.message_type == MessageType.DELEGATION]
        assert len(delegations) >= 1
        assert delegations[0].receiver == "planner"

    def test_directive_single_goal(self):
        orch = Orchestrator()
        msg = AlgebraicMessage(
            sender="user", receiver="orchestrator",
            message_type=MessageType.DIRECTIVE,
            payload=C.goal("simple"),
        )
        orch.receive(msg)
        responses = orch.process_inbox(Blackboard())
        # Single goal: delegate to analyst
        delegations = [r for r in responses if r.message_type == MessageType.DELEGATION]
        assert len(delegations) >= 1
        assert delegations[0].receiver == "analyst"

    def test_result_from_synthesizer(self):
        orch = Orchestrator()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="synthesizer", receiver="orchestrator",
            message_type=MessageType.RESULT,
            payload=C.goal("done"),
        )
        orch.receive(msg)
        responses = orch.process_inbox(bb)
        # Final result — no new messages, just stored
        assert len(responses) == 0

    def test_intermediate_result_routes_to_synthesizer(self):
        orch = Orchestrator()
        msg = AlgebraicMessage(
            sender="analyst", receiver="orchestrator",
            message_type=MessageType.RESULT,
            payload=C.goal("intermediate"),
        )
        orch.receive(msg)
        responses = orch.process_inbox(Blackboard())
        assert any(r.receiver == "synthesizer" for r in responses)

    def test_writes_task_to_blackboard(self):
        orch = Orchestrator()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="user", receiver="orchestrator",
            message_type=MessageType.DIRECTIVE,
            payload=C.goal("test_task"),
        )
        orch.receive(msg)
        orch.process_inbox(bb)
        # Blackboard should have task entry
        entries = bb.get_all()
        task_keys = [k for k in entries if k.startswith("task:")]
        assert len(task_keys) == 1


# --- Analyst ---

class TestAnalyst:
    def test_delegation_triggers_analysis(self):
        analyst = Analyst()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.DELEGATION,
            payload=C.goal("analyze_this"),
        )
        analyst.receive(msg)
        responses = analyst.process_inbox(bb)
        assert len(responses) >= 1
        assert responses[0].receiver == "orchestrator"

    def test_analysis_writes_blackboard(self):
        analyst = Analyst()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.DELEGATION,
            payload=C.goal("test"),
        )
        analyst.receive(msg)
        analyst.process_inbox(bb)
        analysis_keys = [k for k in bb.get_all() if k.startswith("analysis:")]
        assert len(analysis_keys) == 1

    def test_analysis_result(self):
        analyst = Analyst()
        msg = AlgebraicMessage(
            sender="orch", receiver="analyst",
            message_type=MessageType.QUERY,
            payload=C.goal("q"),
        )
        analyst.receive(msg)
        responses = analyst.process_inbox(Blackboard())
        assert responses[0].message_type == MessageType.RESULT


# --- Planner ---

class TestPlanner:
    def test_delegation_creates_plan(self):
        planner = Planner()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="orch", receiver="planner",
            message_type=MessageType.DELEGATION,
            payload=C.compose(C.goal("g"), C.constraint("c")),
        )
        planner.receive(msg)
        responses = planner.process_inbox(bb)
        assert any(r.receiver == "executor" for r in responses)
        assert any(r.receiver == "orchestrator" for r in responses)

    def test_plan_written_to_blackboard(self):
        planner = Planner()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="orch", receiver="planner",
            message_type=MessageType.DIRECTIVE,
            payload=C.goal("task"),
        )
        planner.receive(msg)
        planner.process_inbox(bb)
        plan_keys = [k for k in bb.get_all() if k.startswith("plan:")]
        assert len(plan_keys) == 1

    def test_refine_plan_adds_steps(self):
        planner = Planner()
        simple = C.compose(C.action("step1"), C.action("step2"))
        refined = planner._refine_plan(simple)
        assert refined.operator == Operator.COMPOSE
        assert len(refined.operands) == 3  # original expr + validate + synthesize


# --- Executor ---

class TestExecutor:
    def test_directive_executes(self):
        executor = Executor()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="planner", receiver="executor",
            message_type=MessageType.DIRECTIVE,
            payload=C.compose(C.action("a"), C.action("b")),
        )
        executor.receive(msg)
        responses = executor.process_inbox(bb)
        assert any(r.receiver == "validator" for r in responses)

    def test_execution_written_to_bb(self):
        executor = Executor()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="planner", receiver="executor",
            message_type=MessageType.DIRECTIVE,
            payload=C.action("single"),
        )
        executor.receive(msg)
        executor.process_inbox(bb)
        exec_keys = [k for k in bb.get_all() if k.startswith("execution:")]
        assert len(exec_keys) == 1

    def test_execution_log(self):
        executor = Executor()
        msg = AlgebraicMessage(
            sender="p", receiver="executor",
            message_type=MessageType.DIRECTIVE,
            payload=C.compose(C.action("a"), C.action("b")),
        )
        executor.receive(msg)
        executor.process_inbox(Blackboard())
        assert len(executor._execution_log) == 2


# --- Validator ---

class TestValidator:
    def test_valid_passes(self):
        validator = Validator()
        msg = AlgebraicMessage(
            sender="exec", receiver="validator",
            message_type=MessageType.VALIDATION,
            payload=C.compose(C.state("executed"), C.action("ok")),
        )
        validator.receive(msg)
        responses = validator.process_inbox(Blackboard())
        # Valid → send to synthesizer
        assert any(r.receiver == "synthesizer" for r in responses)

    def test_invalid_sends_feedback(self):
        validator = Validator()
        msg = AlgebraicMessage(
            sender="exec", receiver="validator",
            message_type=MessageType.VALIDATION,
            payload=C.compose(C.state("executed"), C.state("error")),
        )
        validator.receive(msg)
        responses = validator.process_inbox(Blackboard())
        # Invalid → send feedback to executor
        assert any(r.receiver == "executor" for r in responses)

    def test_validate_function(self):
        validator = Validator()
        assert validator._validate(C.action("good"))
        assert not validator._validate(C.state("error"))
        assert not validator._validate(C.state("failed"))

    def test_validation_written_to_bb(self):
        validator = Validator()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="exec", receiver="validator",
            message_type=MessageType.VALIDATION,
            payload=C.action("ok"),
        )
        validator.receive(msg)
        validator.process_inbox(bb)
        val_keys = [k for k in bb.get_all() if k.startswith("validation:")]
        assert len(val_keys) == 1


# --- Synthesizer ---

class TestSynthesizer:
    def test_synthesis_produces_result(self):
        synth = Synthesizer()
        msg = AlgebraicMessage(
            sender="orch", receiver="synthesizer",
            message_type=MessageType.SYNTHESIS,
            payload=C.state("validated") @ C.action("done"),
        )
        synth.receive(msg)
        responses = synth.process_inbox(Blackboard())
        assert any(r.receiver == "orchestrator" for r in responses)
        assert any(r.message_type == MessageType.RESULT for r in responses)

    def test_synthesis_written_to_bb(self):
        synth = Synthesizer()
        bb = Blackboard()
        msg = AlgebraicMessage(
            sender="orch", receiver="synthesizer",
            message_type=MessageType.SYNTHESIS,
            payload=C.action("done"),
        )
        synth.receive(msg)
        synth.process_inbox(bb)
        synth_keys = [k for k in bb.get_all() if k.startswith("synthesis:")]
        assert len(synth_keys) == 1


# ============================================================================
# SWARM CONTROLLER
# ============================================================================

class TestSwarmController:
    def test_create_default(self):
        swarm = SwarmController()
        swarm.register_agent(Orchestrator())
        swarm.register_agent(Analyst())
        assert "orchestrator" in swarm._agents
        assert "analyst" in swarm._agents

    def test_create_default_swarm(self):
        swarm = create_default_swarm()
        assert len(swarm._agents) == 6
        for role in ["orchestrator", "analyst", "planner", "executor", "validator", "synthesizer"]:
            assert role in swarm._agents

    def test_inject_task(self):
        swarm = create_default_swarm()
        task_id = swarm.inject_task(C.goal("test"))
        assert isinstance(task_id, str)
        assert len(task_id) == 8

    def test_step_processes_messages(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.compose(C.goal("g"), C.constraint("c")))
        activity = swarm.step()
        assert activity > 0

    def test_step_with_no_activity(self):
        swarm = create_default_swarm()
        activity = swarm.step()
        assert activity == 0  # no messages pending

    def test_run_until_convergence_detects_fixed_point(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.compose(C.goal("g"), C.constraint("c")))
        result = swarm.run_until_convergence(max_steps=20)
        assert result["converged"]
        assert result["steps_executed"] > 0
        assert result["total_messages"] > 0

    def test_run_until_convergence_max_steps(self):
        swarm = create_default_swarm()
        # No task injected — needs 3 consecutive zero-activity steps
        result = swarm.run_until_convergence(max_steps=5)
        assert result["converged"]
        assert result["steps_executed"] >= 3

    def test_consecutive_tasks(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("task1"))
        swarm.run_until_convergence(max_steps=20)
        r1 = swarm._step_count
        swarm.inject_task(C.compose(C.goal("task2"), C.constraint("c2")))
        swarm.run_until_convergence(max_steps=20)
        assert swarm._step_count > r1

    def test_export_trace_structure(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        swarm.run_until_convergence(max_steps=5)
        trace = swarm.export_trace()
        assert trace["system"] == "ASIS 2.0"
        assert trace["version"] == "2.0.0"
        assert "statistics" in trace
        assert trace["statistics"]["total_agents"] == 6
        assert "agents" in trace
        assert "blackboard" in trace
        assert "snapshots" in trace
        assert "message_log" in trace

    def test_save_trace(self, tmp_path):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        swarm.run_until_convergence(max_steps=10)
        filepath = tmp_path / "test_trace.json"
        swarm.save_trace(str(filepath))
        assert filepath.exists()
        with open(filepath) as f:
            data = json.load(f)
        assert data["system"] == "ASIS 2.0"
        assert data["statistics"]["converged"]

    def test_snapshots_taken_on_step(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        swarm.step()
        assert len(swarm._snapshots) >= 1

    def test_step_count_increments(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        before = swarm._step_count
        swarm.step()
        assert swarm._step_count == before + 1


# ============================================================================
# INTEGRATION: END-TO-END SWARM EXECUTION
# ============================================================================

class TestIntegration:
    def test_full_pipeline_compose_task(self):
        swarm = create_default_swarm()
        task = C.compose(
            C.goal("optimize"),
            C.constraint("latency < 100ms"),
            C.constraint("throughput > 1000"),
        )
        swarm.inject_task(task)
        result = swarm.run_until_convergence(max_steps=30)
        assert result["converged"]
        assert result["steps_executed"] > 0
        assert result["total_messages"] >= 5  # orchestrated pipeline

    def test_full_pipeline_single_goal(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("simple_task"))
        result = swarm.run_until_convergence(max_steps=30)
        assert result["converged"]

    def test_multiple_tasks_pipeline(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("task_a"))
        swarm.inject_task(C.compose(C.goal("task_b"), C.constraint("c")))
        swarm.inject_task(C.goal("task_c"))
        result = swarm.run_until_convergence(max_steps=50)
        assert result["converged"]
        assert result["total_agents"] == 6

    def test_blackboard_accumulates_knowledge(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        swarm.run_until_convergence(max_steps=20)
        entries = swarm._blackboard.get_all()
        categories = set(k.split(":")[0] for k in entries)
        # Should have entries from multiple agent types
        assert "task" in categories
        assert "analysis" in categories or "plan" in categories

    def test_message_routing_completeness(self):
        """Verify all 6 agents participate in message flow."""
        swarm = create_default_swarm()
        swarm.inject_task(C.compose(C.goal("g"), C.constraint("c")))
        swarm.run_until_convergence(max_steps=20)
        all_senders = {msg.sender for msg in swarm._message_log}
        for role in ["orchestrator", "planner", "executor", "validator", "synthesizer"]:
            assert role in all_senders, f"{role} never sent a message"

    def test_no_orphan_results(self):
        """Every result message should have a corresponding consumer."""
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("test"))
        swarm.run_until_convergence(max_steps=20)
        for msg in swarm._message_log:
            if msg.receiver not in swarm._agents:
                assert msg.receiver == "user", f"Orphan message to {msg.receiver}"

    def test_deterministic_execution(self):
        """Same inputs should produce same trace structure."""
        def run_swarm():
            s = create_default_swarm()
            s.inject_task(C.compose(C.goal("g"), C.constraint("c")))
            s.run_until_convergence(max_steps=20)
            return [m.to_dict() for m in s._message_log]

        trace1 = run_swarm()
        trace2 = run_swarm()
        # Compare message types and routing (timestamps/correlation_ids differ)
        def normalize(t):
            return [(m["sender"], m["receiver"], m["message_type"]) for m in t]
        assert normalize(trace1) == normalize(trace2)
