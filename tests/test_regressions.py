"""Regression tests for defects fixed ahead of release, and for the CLI contract."""

import json

from asis import C, ConceptAtom, ConceptCategory, Expression, __version__, main

DEMO = "optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps"


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


def test_rule_type_hints_resolve():
    import typing

    from asis import Rule

    assert "condition" in typing.get_type_hints(Rule)


def test_expression_is_public():
    assert Expression.from_atom(ConceptAtom.create("x", ConceptCategory.ENTITY)).is_leaf


def test_cli_run_writes_trace(tmp_path, capsys):
    out = tmp_path / "trace.json"
    assert main(["--output", str(out)]) == 0
    trace = json.loads(out.read_text(encoding="utf-8"))
    assert trace["version"] == __version__
    assert trace["statistics"]["converged"] is True
    assert "Status: SOLVED" in capsys.readouterr().out


def test_cli_run_no_trace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--no-trace"]) == 0
    assert not (tmp_path / "asis_trace.json").exists()


def test_cli_solve_exit_codes(capsys):
    assert main(["solve", DEMO]) == 0
    assert main(["solve", "optimize_system ⊗ latency < 20ms"]) == 2
    assert main(["solve", "optimize_system ⊗ latency < 10ms ⊗ latency > 20ms"]) == 3
    assert main(["solve", "(broken"]) == 1
    assert "expected ')'" in capsys.readouterr().err


def test_cli_solve_json(capsys):
    assert main(["solve", DEMO, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "solved"
    assert result["metrics"]["latency"] < 100


def test_cli_solve_with_custom_kb_and_trace(tmp_path, capsys):
    kb = tmp_path / "kb.json"
    kb.write_text(json.dumps({
        "name": "tiny",
        "metrics": {"speed": {"unit": "rps", "baseline": 10}},
        "actions": {"boost": {"cost": 3, "effects": {"speed": {"add": 10}}}},
        "goals": {"go_fast": {"needs": []}},
    }), encoding="utf-8")
    trace = tmp_path / "t.json"
    assert main(["solve", "go_fast ⊗ speed > 15", "--kb", str(kb), "--trace", str(trace)]) == 0
    assert "boost" in capsys.readouterr().out
    assert json.loads(trace.read_text(encoding="utf-8"))["knowledge_base"] == "tiny"


def test_cli_bad_kb(tmp_path, capsys):
    kb = tmp_path / "kb.json"
    kb.write_text(json.dumps({"actions": {"x": {"requires": ["ghost"]}}}), encoding="utf-8")
    assert main(["solve", DEMO, "--kb", str(kb)]) == 1
    assert "ghost" in capsys.readouterr().err
    assert main(["kb", "--kb", str(tmp_path / "missing.json")]) == 1


def test_cli_kb_listing(capsys):
    assert main(["kb"]) == 0
    out = capsys.readouterr().out
    assert "optimize_system" in out and "add_cache" in out and "latency" in out
    assert main(["kb", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "web_service"
