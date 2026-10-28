"""Malformed domain documents produce actionable schema errors, never crashes."""

import json

import pytest

from asis import KnowledgeBase, KnowledgeBaseError, main


@pytest.mark.parametrize("document", [None, [], [1], False, 4, "domain"])
def test_root_must_be_an_object(document):
    with pytest.raises(KnowledgeBaseError, match="knowledge base: expected an object"):
        KnowledgeBase.from_dict(document)


@pytest.mark.parametrize("section", ["metrics", "actions", "goals"])
@pytest.mark.parametrize("value", [[], False, "", 7])
def test_sections_reject_non_objects_even_when_empty(section, value):
    with pytest.raises(KnowledgeBaseError, match=f"{section}: expected an object"):
        KnowledgeBase.from_dict({section: value})


@pytest.mark.parametrize("section,label", [("metrics", "metric"), ("actions", "action"), ("goals", "goal")])
@pytest.mark.parametrize("value", [[], False, "", 7])
def test_declarations_must_be_objects(section, label, value):
    with pytest.raises(KnowledgeBaseError, match=f"{label} item: expected an object"):
        KnowledgeBase.from_dict({section: {"item": value}})


@pytest.mark.parametrize("effects", [[], False, "", {"latency": []}, {"latency": False}, {"latency": 2}])
def test_effects_and_effect_declarations_must_be_objects(effects):
    with pytest.raises(KnowledgeBaseError, match="expected an object"):
        KnowledgeBase.from_dict({"actions": {"x": {"effects": effects}}})


@pytest.mark.parametrize("name", ["", "   ", 1, None])
@pytest.mark.parametrize("section", ["metrics", "actions", "goals"])
def test_invalid_declaration_names_cannot_reach_sorting_or_alias_logic(section, name):
    with pytest.raises(KnowledgeBaseError, match="expected a nonempty string name"):
        KnowledgeBase.from_dict({section: {name: {}}})


@pytest.mark.parametrize("document", [
    {"name": ""},
    {"name": None},
    {"description": []},
    {"metrics": {"latency": {"unit": None}}},
    {"metrics": {"latency": {"description": False}}},
    {"actions": {"x": {"description": 3}}},
    {"goals": {"g": {"description": {}}}},
])
def test_names_units_and_descriptions_have_declared_string_types(document):
    with pytest.raises(KnowledgeBaseError, match="expected a.*string"):
        KnowledgeBase.from_dict(document)


@pytest.mark.parametrize("document", [
    {"metrics": {"latency": {"aliases": [""]}}},
    {"actions": {"x": {"provides": ["   "]}}},
    {"actions": {"x": {"requires": [False]}}},
    {"actions": {"x": {"conflicts": [None]}}},
    {"goals": {"g": {"needs": [""]}}},
    {"actions": {"x": {"effects": {"": {}}}}},
])
def test_references_and_effect_metric_names_must_be_nonempty_strings(document):
    with pytest.raises(KnowledgeBaseError, match="nonempty"):
        KnowledgeBase.from_dict(document)


def test_independent_schema_errors_are_collected_together():
    document = {
        "name": [], "description": False,
        "metrics": {"latency": {"unit": 3, "aliases": [False], "baseline": True}, "": {}},
        "actions": {"x": {"effects": {"latency": []}, "cost": "free", "max_uses": True}},
        "goals": [],
    }
    with pytest.raises(KnowledgeBaseError) as failure:
        KnowledgeBase.from_dict(document)
    assert len(failure.value.problems) == 10
    message = str(failure.value)
    for location in ("name:", "description:", "metric latency.unit", "metric latency.aliases",
                     "metric latency.baseline", "metrics key", "action x.effect latency", "action x.cost",
                     "action x.max_uses", "goals:"):
        assert location in message


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), 10 ** 1000])
def test_numbers_must_fit_finite_model_values(value):
    with pytest.raises(KnowledgeBaseError, match="expected a finite number"):
        KnowledgeBase.from_dict({"actions": {"x": {"cost": value}}})


def test_optional_null_sections_and_entries_preserve_empty_defaults():
    empty = KnowledgeBase.from_dict({"metrics": None, "actions": None, "goals": None})
    assert empty.estimate(()) == {"cost": 0}
    kb = KnowledgeBase.from_dict({
        "metrics": {"latency": None},
        "actions": {"empty": None, "noop": {"effects": {"latency": None}, "provides": None}},
        "goals": {"g": None},
    })
    assert kb.estimate((("empty", 1), ("noop", 1))) == {"cost": 0, "latency": 0}
    assert kb.actions["noop"].provides == frozenset()


@pytest.mark.parametrize("document", [[], {"metrics": []}, {"actions": {"x": False}},
                                     {"metrics": {"latency": {"unit": []}}}])
def test_cli_reports_schema_errors_without_a_traceback(tmp_path, capsys, document):
    path = tmp_path / "domain.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["kb", "--kb", str(path)]) == 1
    output = capsys.readouterr()
    assert "invalid knowledge base" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""


@pytest.mark.parametrize("declared", [("cheap",), ("fast",), ("cheap", "fast")])
def test_one_sided_conflicts_are_enforced_in_either_alphabetical_direction(declared):
    actions = {"cheap": {}, "fast": {}}
    for name in declared:
        actions[name]["conflicts"] = ["fast" if name == "cheap" else "cheap"]
    kb = KnowledgeBase.from_dict({"actions": actions})
    assert kb.plan_problems((("cheap", 1), ("fast", 1))) == ["'cheap' conflicts with 'fast'"]
    assert kb.plan_problems((("cheap", 1),)) == []
    assert kb.plan_problems((("fast", 1),)) == []
