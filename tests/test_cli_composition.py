"""CLI contracts for bounded composition, work reporting and installed domains."""

import json

import pytest

from asis import main

COMPENSATION_TASK = "latency <= 50ms ⊗ cost <= 100"


def test_bundled_compensation_domain_finds_joint_plan_and_reports_search(capsys):
    assert main(["solve", COMPENSATION_TASK, "--kb", "compensation", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["plan"] == {"cheap": 1, "fast": 1}
    assert result["metrics"] == {"cost": 100, "latency": 30}
    assert result["assessment"] == "feasible_in_model"
    assert result["optimality_proven"] is False
    assert result["model_evaluations"] >= result["plans_considered"] > 0


def test_cli_depth_limit_controls_compensation_search(capsys):
    assert main(["solve", COMPENSATION_TASK, "--kb", "compensation", "--search-depth", "1", "--json"]) == 2
    incomplete = json.loads(capsys.readouterr().out)
    assert incomplete["assessment"] == "search_incomplete"
    assert incomplete["optimality_proven"] is False
    assert main(["solve", COMPENSATION_TASK, "--kb", "compensation", "--search-depth", "2", "--json"]) == 0
    feasible = json.loads(capsys.readouterr().out)
    assert feasible["plan"] == {"cheap": 1, "fast": 1}


def test_cli_tiny_composer_allowance_preserves_honest_outcome(capsys):
    code = main(["solve", COMPENSATION_TASK, "--kb", "compensation", "--search-evaluations", "1", "--json"])
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["assessment"] == "search_incomplete"
    assert result["optimality_proven"] is False
    assert result["model_evaluations"] > 0


def test_cli_step_limit_does_not_claim_a_checked_result(capsys):
    assert main(["solve", COMPENSATION_TASK, "--kb", "compensation", "--max-steps", "1", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["assessment"] == "pending"
    assert result["optimality_proven"] is False
    assert result["plans_considered"] == 0


@pytest.mark.parametrize("flag", ["--budget", "--max-steps", "--search-depth", "--beam-width", "--search-evaluations"])
@pytest.mark.parametrize("value", ["0", "-1", "nope"])
def test_cli_rejects_invalid_work_limits(flag, value, capsys):
    with pytest.raises(SystemExit) as error:
        main(["solve", COMPENSATION_TASK, flag, value])
    assert error.value.code == 2
    assert "positive integer" in capsys.readouterr().err


def test_run_accepts_composer_controls_without_writing_trace(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--no-trace", "--search-depth", "2", "--beam-width", "2", "--search-evaluations", "10"]) == 0
    output = capsys.readouterr().out
    assert "Model evaluations:" in output
    assert not list(tmp_path.iterdir())


def test_existing_file_named_like_bundled_domain_takes_priority(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "compensation").write_text(json.dumps({"name": "local_override", "metrics": {}, "actions": {}}))
    assert main(["kb", "--kb", "compensation", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "local_override"


@pytest.mark.parametrize("raw", [b"{not json", b"\xff\xfe\x00"])
def test_cli_reports_invalid_kb_encoding_or_json_without_traceback(tmp_path, capsys, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    assert main(["kb", "--kb", str(path)]) == 1
    output = capsys.readouterr()
    assert output.err.startswith("error:")
    assert "Traceback" not in output.err
    assert not output.out


def test_cli_does_not_hide_unexpected_loader_defects(monkeypatch):
    from asis import cli

    def broken_loader(path):
        raise RuntimeError("unexpected loader defect")

    monkeypatch.setattr(cli, "_load_kb", broken_loader)
    with pytest.raises(RuntimeError, match="unexpected loader defect"):
        main(["kb"])
