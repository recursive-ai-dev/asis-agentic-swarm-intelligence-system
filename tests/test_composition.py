"""Coupled obligations, bounded search, executable graphs, and checked reuse."""

import json

import pytest

from asis import KnowledgeBase, create_default_swarm, solve
from asis.knowledge import make_plan, plan_key
from asis.search import (
    BoundedComposer,
    GuardedProcedure,
    OperatorGraph,
    Prediction,
    ProcedureMemory,
    SearchConfig,
    Step,
    default_registry,
    model_fingerprint,
)

TASK = "latency <= 50ms ⊗ cost <= 100"


def compensation_kb():
    return KnowledgeBase.from_dict({
        "name": "coupled",
        "metrics": {"latency": {"unit": "ms", "baseline": 100},
                    "cost": {"unit": "usd", "baseline": 100, "min": 0}},
        "actions": {"fast": {"cost": 200, "effects": {"latency": {"factor": 0.1}}},
                    "cheap": {"cost": -200, "effects": {"latency": {"factor": 3}}}},
    })


def run(kb=None, task=TASK, config=None):
    swarm = create_default_swarm(kb or compensation_kb(), search_config=config)
    tid = swarm.submit(task)
    swarm.run()
    return swarm, tid, swarm.result(tid)


def test_deferred_tradeoff_finds_pair_and_final_result_has_independent_verdict():
    swarm, tid, result = run()
    assert result.solved and result.plan == {"cheap": 1, "fast": 1}
    assert result.metrics == {"cost": 100, "latency": 30}
    trace = swarm.blackboard.read(f"composition:{tid}")
    assert trace["evaluations"] <= trace["config"]["max_evaluations"]
    assert any(r["deferred"] > 0 for r in trace["runs"])
    fast = next(n for r in trace["runs"] for n in r["nodes"] if n["plan"] == [["fast", 1]])
    assert sum(r["gap"] for r in fast["residuals"]) == 2  # worse than baseline gap 1
    key = plan_key(make_plan(result.plan))
    assert swarm.blackboard.read(f"verdict:{tid}:{key}")["satisfied"]
    assert swarm.blackboard.read(f"proposal:{tid}:{key}")["proposer"] == "repairer"
    assert result.assessment == "feasible_in_model"
    assert not result.optimality_proven and not result.search_complete


def test_more_energy_does_not_make_depth_one_cross_the_tradeoff():
    result = solve(TASK, kb=compensation_kb(), budget=10000, search_config=SearchConfig(max_depth=1))
    assert result.status == "unsolved" and result.assessment == "search_incomplete"
    assert "infeasibility has not been established" in result.report


def test_three_compensating_decisions_require_three_step_allowance():
    data = compensation_kb().to_dict()
    data["actions"] = {"fast": {"cost": 300, "effects": {"latency": {"factor": 0.1}}},
                       "saving_a": {"cost": -150, "effects": {"latency": {"factor": 2}}},
                       "saving_b": {"cost": -150, "effects": {"latency": {"factor": 2}}}}
    kb = KnowledgeBase.from_dict(data)
    assert not solve(TASK, kb=kb, search_config=SearchConfig(max_depth=2)).solved
    _, _, result = run(kb, config=SearchConfig(max_depth=3, beam_width=1))
    assert result.solved and result.plan == {"fast": 1, "saving_a": 1, "saving_b": 1}
    assert result.metrics["latency"] == 40


@pytest.mark.parametrize("task", [TASK + " ⊗ ¬action:cheap", TASK + " ⊗ ¬action:fast"])
def test_forbidden_compensation_is_never_accepted(task):
    _, _, result = run(task=task)
    assert not result.solved
    forbidden = "cheap" if "¬action:cheap" in task else "fast"
    assert forbidden not in result.plan


def test_conflicting_compensations_cannot_be_combined():
    data = compensation_kb().to_dict()
    data["actions"]["fast"]["conflicts"] = ["cheap"]
    swarm, tid, result = run(KnowledgeBase.from_dict(data))
    assert not result.solved
    assert all(len(n["plan"]) < 2 for r in swarm.blackboard.read(f"composition:{tid}")["runs"] for n in r["nodes"])


def test_extension_includes_prerequisites_and_forbidden_prerequisites_block_it():
    data = compensation_kb().to_dict()
    data["actions"]["permit"] = {}
    data["actions"]["cheap"]["requires"] = ["permit"]
    kb = KnowledgeBase.from_dict(data)
    _, _, result = run(kb, config=SearchConfig(max_depth=2))
    assert result.solved and result.plan == {"fast": 1, "cheap": 1, "permit": 1}
    _, _, blocked = run(kb, task=TASK + " ⊗ ¬action:permit")
    assert not blocked.solved and "permit" not in blocked.plan


def test_repeated_compensation_obeys_use_limit():
    data = compensation_kb().to_dict()
    data["actions"]["cheap"] = {"cost": -100, "effects": {"latency": {"factor": 1.5}}, "max_uses": 2}
    _, _, result = run(KnowledgeBase.from_dict(data))
    assert result.solved and result.plan == {"cheap": 2, "fast": 1}
    data["actions"]["cheap"]["max_uses"] = 1
    _, _, limited = run(KnowledgeBase.from_dict(data))
    assert not limited.solved
    assert limited.plan.get("cheap", 0) <= 1


def test_composition_work_allowance_is_observed_and_leaves_unresolved_frontier():
    swarm, tid, result = run(config=SearchConfig(max_evaluations=2))
    assert not result.solved
    history = swarm.blackboard.read(f"composition:{tid}")
    assert history["evaluations"] == 2
    assert not history["coverage_complete"]
    assert any(n["reason"] == "evaluation allowance" for r in history["runs"] for n in r["frontier"])
    assert not result.search_complete


def test_compensation_traces_are_deterministic():
    a, _, _ = run()
    b, _, _ = run()
    assert json.dumps(a.export_trace(), sort_keys=True) == json.dumps(b.export_trace(), sort_keys=True)


def test_checked_procedure_reuses_across_thresholds_with_fewer_composition_evaluations():
    swarm, first, _ = run()
    second = swarm.submit("latency <= 40ms ⊗ cost <= 100")
    swarm.run()
    assert swarm.result(second).solved
    one = swarm.blackboard.read(f"composition:{first}")
    two = swarm.blackboard.read(f"composition:{second}")
    assert two["evaluations"] < one["evaluations"]
    assert any(r["reused"] for r in two["runs"])
    assert "reuse guarded composition" in swarm.result(second).report
    # A stricter threshold cannot be silently weakened by the reused artifact.
    third = swarm.submit("latency <= 20ms ⊗ cost <= 100")
    swarm.run()
    assert not swarm.result(third).solved


def test_model_change_invalidates_both_solution_and_procedure_memory():
    swarm, _, _ = run()
    assert swarm.blackboard.read("procedure-library")
    data = swarm.kb.to_dict()
    data["actions"]["cheap"]["effects"]["latency"]["factor"] = 7
    swarm.kb = KnowledgeBase.from_dict(data)
    tid = swarm.submit(TASK)
    swarm.run()
    result = swarm.result(tid)
    assert not result.solved
    assert "recalled" not in result.report and "reuse guarded composition" not in result.report
    assert swarm.blackboard.read("procedure-library") == []


def test_forbidden_action_guard_prevents_procedure_replay():
    swarm, _, _ = run()
    tid = swarm.submit(TASK + " ⊗ ¬action:cheap")
    swarm.run()
    assert not swarm.result(tid).solved
    assert "cheap" not in swarm.result(tid).plan


def test_speculative_composition_does_not_populate_procedure_memory_without_checker():
    swarm = create_default_swarm(compensation_kb())
    tid = swarm.submit(TASK)
    for _ in range(30):
        swarm.step()
        if swarm.blackboard.has(f"composition:{tid}"):
            break
    assert swarm.blackboard.has(f"composition:{tid}")
    swarm.remove_agent("checker")
    swarm.run()
    assert not swarm.result(tid).solved
    assert swarm.blackboard.read("procedure-library") == []


def test_registry_prediction_does_not_secretly_accept_or_discard():
    kb = compensation_kb()
    calls = []
    registry = default_registry()
    plan = (("fast", 1),)
    prediction = registry.invoke("predict", plan, kb, lambda p: calls.append(p) or kb.estimate(p))
    assert isinstance(prediction, Prediction) and calls == [plan]
    assert prediction.metrics["cost"] == 300
    assert prediction.evidence == "model_prediction"
    obligations = registry.invoke("residual", prediction, [kb.parse_constraint("cost <= 100")])
    assert obligations.total == 2
    assert not registry.invoke("check", obligations, lambda r: not r.unmet)


@pytest.mark.parametrize("steps", [
    (Step("residual", ("not_produced", "constraints"), "r"),),
    (Step("residual", ("candidate", "constraints"), "r"),),
    (Step("predict", ("candidate", "model", "predictor"), "candidate"),),
])
def test_invalid_graphs_are_rejected_before_any_predictions(steps):
    kb = compensation_kb()
    calls = []
    with pytest.raises((TypeError, ValueError)):
        OperatorGraph(steps).run(default_registry(), {"candidate": (), "model": kb, "constraints": [],
                                                     "predictor": lambda p: calls.append(p) or kb.estimate(p)})
    assert calls == []


def test_direct_composer_counts_every_prediction_even_rejected_branches():
    kb = compensation_kb()
    constraints = [kb.parse_constraint(t) for t in ("latency <= 50ms", "cost <= 100")]
    calls = []
    result = BoundedComposer(SearchConfig()).compose((), kb.estimate(()), kb, constraints, (),
        lambda p: calls.append(p) or kb.estimate(p), lambda p: not kb.plan_problems(p), lambda p: False)
    assert result.evaluations == len(calls)
    assert (("fast", 1),) in calls and (("cheap", 1),) in calls
    assert result.candidates[0].plan == (("cheap", 1), ("fast", 1))
    assert not result.to_dict()["coverage_complete"]


def test_caller_allowance_cannot_override_composer_configuration_cap():
    kb = compensation_kb()
    calls = []
    constraints = [kb.parse_constraint("latency <= 50ms"), kb.parse_constraint("cost <= 100")]
    result = BoundedComposer(SearchConfig(max_evaluations=1)).compose((), kb.estimate(()), kb, constraints, (),
        lambda p: calls.append(p) or kb.estimate(p), lambda p: True, lambda p: False, allowance=10000)
    assert result.evaluations == len(calls) == 1
    assert "allowance" in result.stop_reason


def test_procedure_memory_is_bounded_and_model_guards_include_units_and_bounds():
    kb = compensation_kb()
    memory = ProcedureMemory(capacity=1)
    memory.remember(GuardedProcedure(model_fingerprint(kb), ("fast",), (("latency",),)))
    memory.remember(GuardedProcedure(model_fingerprint(kb), ("fast", "cheap"), (("latency",), ("cost",))))
    assert len(memory.compatible(kb)) == 1
    assert memory.compatible(kb)[0].actions == ("fast", "cheap")
    data = kb.to_dict()
    data["metrics"]["latency"]["unit"] = "s"
    assert memory.compatible(KnowledgeBase.from_dict(data)) == ()


@pytest.mark.parametrize("kwargs", [{"max_depth": 0}, {"beam_width": -1}, {"max_evaluations": 0},
                                    {"max_depth": True}, {"beam_width": 1.5}])
def test_invalid_allowances_rejected(kwargs):
    with pytest.raises(ValueError, match="positive integer"):
        SearchConfig(**kwargs)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_procedure_memory_capacity_is_rejected_at_construction(capacity):
    with pytest.raises(ValueError, match="positive integer"):
        ProcedureMemory(capacity)
