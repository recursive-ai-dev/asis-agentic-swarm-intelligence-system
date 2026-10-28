"""Model work includes every prediction, even one never proposed for validation."""

import pytest

from asis import KnowledgeBase, SearchConfig, SwarmController, create_default_swarm, solve


def test_model_evaluations_count_every_engine_call(monkeypatch):
    kb = KnowledgeBase.default()
    actual_calls = []
    original = kb.estimate

    def counted(plan):
        actual_calls.append(plan)
        return original(plan)

    monkeypatch.setattr(kb, "estimate", counted)
    result = solve("optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps", kb)
    assert result.solved
    assert result.model_evaluations == len(actual_calls)
    assert result.model_evaluations > result.plans_considered
    assert result.assessment == "feasible_in_model"
    assert not result.optimality_proven
    assert not result.search_complete
    assert result.to_dict()["model_evaluations"] == len(actual_calls)


def test_model_counts_are_isolated_between_concurrent_tasks(monkeypatch):
    kb = KnowledgeBase.default()
    calls = []
    original = kb.estimate

    def counted(plan):
        calls.append(plan)
        return original(plan)

    monkeypatch.setattr(kb, "estimate", counted)
    swarm = create_default_swarm(kb)
    ids = [swarm.submit("latency < 100ms"), swarm.submit("throughput > 1000rps")]
    swarm.run()
    results = [swarm.result(tid) for tid in ids]
    assert all(r.model_evaluations > 0 for r in results)
    assert sum(r.model_evaluations for r in results) == len(calls)
    frame = swarm.snapshot()
    assert all(frame["tasks"][r.task_id]["model_evaluations"] == r.model_evaluations for r in results)


def test_unfinished_search_makes_no_proof_claim():
    swarm = create_default_swarm(search_config=SearchConfig(max_depth=1))
    tid = swarm.submit("latency < 20ms")
    swarm.run()
    result = swarm.result(tid)
    assert result.status == "unsolved"
    assert result.assessment == "search_incomplete"
    assert not result.search_complete and not result.optimality_proven


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_bad_energy_budget_fails_before_recording_task(bad):
    with pytest.raises(ValueError, match="positive integer"):
        SwarmController(energy_budget=bad)
    swarm = create_default_swarm()
    with pytest.raises(ValueError, match="positive integer"):
        swarm.submit("latency < 100ms", budget=bad)
    assert not swarm.tasks()


def test_zero_steps_preserves_pending_task_and_zero_model_work():
    swarm = create_default_swarm()
    tid = swarm.submit("latency < 100ms")
    swarm.run(max_steps=0)
    result = swarm.result(tid)
    assert result.status == "open" and result.assessment == "pending"
    assert result.model_evaluations == 0

