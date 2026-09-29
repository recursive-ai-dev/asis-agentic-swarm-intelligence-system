"""Tests for the knowledge base: loading, validation, constraints, units and estimation."""

import json

import pytest

from asis import ConstraintError, KnowledgeBase, KnowledgeBaseError
from asis.knowledge import convert, make_plan, plan_key


@pytest.fixture
def kb():
    return KnowledgeBase.default()


def tiny(**overrides):
    data = {
        "name": "tiny",
        "metrics": {"speed": {"unit": "rps", "baseline": 10, "min": 0}},
        "actions": {
            "a": {"cost": 5, "effects": {"speed": {"add": 10}}, "provides": ["fast"], "max_uses": 3},
            "b": {"cost": 20, "effects": {"speed": {"factor": 2}}, "requires": ["a"]},
            "c": {"cost": 1, "conflicts": ["a"]},
        },
        "goals": {"go": {"needs": ["fast"]}, "top": {"needs": ["go"]}},
    }
    data.update(overrides)
    return data


class TestLoading:
    def test_default_domain_loads(self, kb):
        assert kb.name == "web_service"
        assert {"latency", "throughput", "availability", "cost"} <= set(kb.metrics)
        assert "optimize_system" in kb.goals

    def test_cost_metric_is_always_present(self):
        kb = KnowledgeBase.from_dict(tiny())
        assert "cost" in kb.metrics

    def test_round_trip_through_dict(self, kb):
        again = KnowledgeBase.from_dict(json.loads(json.dumps(kb.to_dict())))
        assert again.to_dict() == kb.to_dict()

    def test_load_from_file(self, tmp_path):
        path = tmp_path / "kb.json"
        path.write_text(json.dumps(tiny()), encoding="utf-8")
        assert KnowledgeBase.load(path).name == "tiny"

    def test_invalid_json_file(self, tmp_path):
        path = tmp_path / "kb.json"
        path.write_text("{nope", encoding="utf-8")
        with pytest.raises(KnowledgeBaseError, match="not valid JSON"):
            KnowledgeBase.load(path)

    @pytest.mark.parametrize("patch,message", [
        ({"actions": {"x": {"effects": {"nope": {"add": 1}}}}}, "unknown metric 'nope'"),
        ({"actions": {"x": {"requires": ["ghost"]}}}, "requires unknown action 'ghost'"),
        ({"actions": {"x": {"conflicts": ["ghost"]}}}, "conflicts with unknown action 'ghost'"),
        ({"actions": {"x": {"max_uses": 0}}}, "max_uses"),
        ({"actions": {"x": {"cost": "free"}}}, "expected a finite number"),
        ({"actions": {"x": {"effects": {"speed": {"factor": 0}}}}}, "factor on 'speed' must be positive"),
        ({"goals": {"g": {"needs": ["unobtainium"]}}}, "neither a goal nor a capability"),
        ({"goals": {"g1": {"needs": ["g2"]}, "g2": {"needs": ["g1"]}}}, "goal cycle"),
        ({"metrics": {"speed": {"min": 5, "max": 1}}}, "min is greater than max"),
    ])
    def test_validation_reports_problems(self, patch, message):
        data = tiny()
        for section, entries in patch.items():
            data[section] = {**data.get(section, {}), **entries}
        with pytest.raises(KnowledgeBaseError, match=message):
            KnowledgeBase.from_dict(data)

    def test_requires_and_conflicts_same_action_is_rejected(self):
        data = tiny(actions={"a": {"requires": ["b"], "conflicts": ["b"]}, "b": {}})
        with pytest.raises(KnowledgeBaseError, match="requires 'b' but conflicts"):
            KnowledgeBase.from_dict(data)


class TestConstraints:
    @pytest.mark.parametrize("text,metric,op,value", [
        ("latency < 100ms", "latency", "<", 100),
        ("p99<=0.1s", "latency", "<=", 100),
        ("Response Time ≤ 250 ms", "latency", "<=", 250),
        ("uptime >= 99.9%", "availability", ">=", 99.9),
        ("throughput > 60rpm", "throughput", ">", 1),
        ("cost = 300", "cost", "==", 300),
        ("errors ≠ 0", "error_rate", "!=", 0),
    ])
    def test_parse(self, kb, text, metric, op, value):
        c = kb.parse_constraint(text)
        assert (c.metric, c.op) == (metric, op)
        assert c.value == pytest.approx(value)

    @pytest.mark.parametrize("text,message", [
        ("latency is low", "cannot read"),
        ("speed < 3", "unknown metric 'speed'"),
        ("latency < 3kg", "not compatible"),
        ("latency < 3rps", "not compatible"),
    ])
    def test_parse_errors(self, kb, text, message):
        with pytest.raises(ConstraintError, match=message):
            kb.parse_constraint(text)

    def test_strict_bounds_are_strict(self, kb):
        c = kb.parse_constraint("throughput > 1000rps")
        assert not c.satisfied(1000)
        assert c.violation(1000) > 0
        assert c.satisfied(1000.5)

    def test_violation_grows_with_distance(self, kb):
        c = kb.parse_constraint("latency < 100ms")
        assert c.violation(90) == 0
        assert 0 < c.violation(110) < c.violation(150)

    def test_negation(self, kb):
        c = kb.parse_constraint("latency < 100ms").negated()
        assert c.op == ">="
        assert c.satisfied(100) and not c.satisfied(99)

    def test_unit_conversion(self):
        assert convert(1, "s", "ms") == 1000
        assert convert(120, "rpm", "rps") == pytest.approx(2)
        assert convert(5, None, "ms") == 5


class TestEstimation:
    def test_baseline(self, kb):
        m = kb.estimate(())
        assert m["latency"] == 180 and m["throughput"] == 400 and m["cost"] == 100

    def test_add_then_multiply(self):
        kb = KnowledgeBase.from_dict(tiny())
        m = kb.estimate(make_plan({"a": 2, "b": 1}))
        assert m["speed"] == (10 + 20) * 2
        assert m["cost"] == 5 * 2 + 20

    def test_clamped_to_bounds(self, kb):
        plan = kb.with_prerequisites(make_plan({"add_replica": 5, "failover_region": 1}))
        assert kb.estimate(plan)["availability"] == kb.metrics["availability"].maximum

    def test_prerequisite_closure(self, kb):
        plan = kb.with_prerequisites(make_plan({"deploy": 1}))
        assert plan_key(plan) == "ci_pipeline,deploy,write_tests"

    def test_plan_problems(self, kb):
        problems = kb.plan_problems(make_plan({"add_replica": 6, "upgrade_instance": 1, "downsize_instance": 1}))
        assert any("max 5" in p for p in problems)
        assert any("requires 'load_balancer'" in p for p in problems)
        assert any("conflicts" in p for p in problems)

    def test_providers_cheapest_first(self, kb):
        assert [a.name for a in kb.providers("load_balancing")] == ["load_balancer"]

    def test_plan_key(self):
        assert plan_key(()) == "∅"
        assert plan_key(make_plan({"b": 1, "a": 3})) == "a×3,b"
