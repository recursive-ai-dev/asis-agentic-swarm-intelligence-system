"""Regression tests for defects fixed ahead of the 2.0.0 release."""

import json

import pytest

from asis import C, ConceptAtom, ConceptCategory, Expression, __version__, create_default_swarm, main


def _run(task, max_steps=50):
    swarm = create_default_swarm()
    task_id = swarm.inject_task(task)
    result = swarm.run_until_convergence(max_steps=max_steps)
    return swarm, task_id, result


def test_trace_is_byte_identical_across_runs():
    task = C.compose(C.goal("g"), C.constraint("c"))
    a = json.dumps(_run(task)[0].export_trace(), sort_keys=True)
    b = json.dumps(_run(task)[0].export_trace(), sort_keys=True)
    assert a == b


def test_correlation_ids_unique_within_run():
    swarm, _, _ = _run(C.compose(C.goal("g"), C.constraint("c")))
    ids = [m.correlation_id for m in swarm._message_log]
    assert len(ids) == len(set(ids))


def test_atoms_differing_only_in_metadata_are_distinct_expressions():
    a = C.goal("x", metadata={"task_id": "a"})
    b = C.goal("x", metadata={"task_id": "b"})
    assert a != b
    assert hash(a) != hash(b)
    # Idempotence must not merge distinct atoms
    assert C.union(a, b) != a


def test_serialize_includes_metadata_only_when_present():
    plain = ConceptAtom.create("x", ConceptCategory.GOAL)
    tagged = ConceptAtom.create("x", ConceptCategory.GOAL, metadata={"b": "2", "a": "1"})
    assert plain.serialize() == "ATOM(x:GOAL:general)"
    assert tagged.serialize() == "ATOM(x:GOAL:general{a=1,b=2})"


def test_single_step_task_result_keyed_by_task_id():
    swarm, task_id, result = _run(C.goal("solo"))
    assert result["converged"]
    bb = swarm._blackboard.get_all()
    assert f"result:{task_id}" in bb
    assert "result:unknown" not in bb


def test_analyst_preserves_task_content():
    swarm, _, _ = _run(C.union(C.goal("a"), C.entity("keep_me")))
    analyses = [v["value"] for k, v in swarm._blackboard.get_all().items() if k.startswith("analysis:")]
    assert len(analyses) == 1
    assert "keep_me" in analyses[0]
    assert "analyze_task" in analyses[0]


def test_analyst_rule_only_decomposes_goals():
    swarm, _, _ = _run(C.entity("not_a_goal"))
    analysis = next(v["value"] for k, v in swarm._blackboard.get_all().items() if k.startswith("analysis:"))
    assert "not_a_goal" in analysis
    assert "analyze_requirements" not in analysis


def test_failed_validation_still_produces_result():
    swarm, task_id, result = _run(C.compose(C.goal("g"), C.state("failed")))
    assert result["converged"]
    bb = swarm._blackboard.get_all()
    assert f"result:{task_id}" in bb
    assert "status=failed" in bb[f"result:{task_id}"]["value"]
    executor = swarm._agents["executor"]
    assert any(entry["status"] == "failed" for entry in executor._execution_log)


def test_run_until_convergence_respects_zero_budget():
    swarm = create_default_swarm()
    swarm.inject_task(C.goal("g"))
    result = swarm.run_until_convergence(max_steps=0)
    assert result["steps_executed"] == 0


def test_inject_task_without_orchestrator_raises_clearly():
    from asis import SwarmController

    with pytest.raises(RuntimeError, match="orchestrator"):
        SwarmController().inject_task(C.goal("g"))


def test_rule_type_hints_resolve():
    import typing

    from asis import Rule

    assert "condition" in typing.get_type_hints(Rule)


def test_cli_writes_trace(tmp_path, capsys):
    out = tmp_path / "trace.json"
    assert main(["--output", str(out)]) == 0
    trace = json.loads(out.read_text(encoding="utf-8"))
    assert trace["version"] == __version__
    assert trace["statistics"]["converged"] is True
    assert "Converged: True" in capsys.readouterr().out


def test_cli_no_trace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--no-trace"]) == 0
    assert not (tmp_path / "asis_trace.json").exists()


def test_cli_reports_non_convergence(tmp_path):
    assert main(["--no-trace", "--max-steps", "1"]) == 2


def test_expression_is_public():
    assert Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY)).is_leaf
