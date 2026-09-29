"""Tests for the expression parser and the live dashboard server."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from asis import C, ConceptCategory, Operator, ParseError, create_default_swarm, parse_expression
from asis.server import MAX_BODY_BYTES, create_server

# ============================================================================
# PARSER
# ============================================================================


class TestParseExpression:
    def test_bare_word_is_goal(self):
        assert parse_expression("optimize_system") == C.goal("optimize_system")

    def test_comparison_is_constraint(self):
        e = parse_expression("latency < 100ms")
        assert e.atom.category == ConceptCategory.CONSTRAINT
        assert e.atom.name == "latency < 100ms"

    def test_explicit_category_case_insensitive(self):
        assert parse_expression("Entity: db") == C.entity("db")

    def test_unknown_prefix_is_part_of_name(self):
        assert parse_expression("ratio 1:2").atom.name == "ratio 1:2"

    def test_compose_unicode_and_ascii(self):
        expected = C.compose(C.goal("a"), C.goal("b"))
        assert parse_expression("a ⊗ b") == expected
        assert parse_expression("a * b") == expected

    def test_compose_binds_tighter_than_union(self):
        e = parse_expression("a ⊕ b ⊗ c")
        assert e.operator == Operator.UNION
        assert e.operands[1].operator == Operator.COMPOSE

    def test_grouping(self):
        e = parse_expression("goal:a * (entity:b | entity:c)")
        assert e == C.compose(C.goal("a"), C.union(C.entity("b"), C.entity("c")))

    def test_negation_and_double_negation(self):
        assert parse_expression("¬a") == C.negate(C.goal("a"))
        assert parse_expression("~~a") == C.goal("a")

    def test_parentheses_inside_names(self):
        assert parse_expression("latency(p99) < 5ms").atom.name == "latency(p99) < 5ms"

    def test_flattening_matches_factory(self):
        assert parse_expression("a ⊗ b ⊗ c") == C.compose(C.goal("a"), C.goal("b"), C.goal("c"))

    @pytest.mark.parametrize("text", ["", "   ", "a ⊗", "(a", "a)", "goal:", "⊕ a", "a ⊗ ⊗ b"])
    def test_malformed_input_raises(self, text):
        with pytest.raises(ParseError):
            parse_expression(text)

    def test_parsed_task_runs_to_completion(self):
        swarm = create_default_swarm()
        task_id = swarm.inject_task(parse_expression("optimize ⊗ latency < 100ms"))
        assert swarm.run_until_convergence(max_steps=50)["converged"]
        assert f"result:{task_id}" in swarm._blackboard.get_all()


# ============================================================================
# SWARM CONTROLLER FRAME API
# ============================================================================


class TestSnapshots:
    def test_injected_task_is_logged_in_next_frame(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("g"))
        swarm.step()
        first = swarm.latest_snapshot["messages"][0]
        assert (first["sender"], first["receiver"], first["message_type"]) == ("user", "orchestrator", "DIRECTIVE")
        assert swarm._message_log[0].sender == "user"

    def test_frames_carry_payload_text_and_convergence(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("g"))
        swarm.run_until_convergence(max_steps=50)
        frames = swarm.export_trace()["snapshots"]
        assert frames[-1]["converged"] is True
        assert not any(f["converged"] for f in frames[:-1])
        msg = frames[0]["messages"][0]
        assert msg["payload_text"] == C.goal("g").serialize()

    def test_step_by_step_converges_like_run(self):
        a = create_default_swarm()
        a.inject_task(C.goal("g"))
        a.run_until_convergence(max_steps=50)
        b = create_default_swarm()
        b.inject_task(C.goal("g"))
        while not b.converged:
            b.step()
        assert a.step_count == b.step_count

    def test_injection_clears_convergence(self):
        swarm = create_default_swarm()
        swarm.inject_task(C.goal("g"))
        swarm.run_until_convergence(max_steps=50)
        assert swarm.converged
        swarm.inject_task(C.goal("h"))
        assert not swarm.converged


# ============================================================================
# HTTP SERVER
# ============================================================================


@pytest.fixture
def server():
    srv = create_server(port=0, demo=True)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    host, port = srv.server_address[:2]
    yield f"http://{host}:{port}"
    srv.shutdown()
    srv.server_close()


def _request(url, method="GET", body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.headers.get("Content-Type"), res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def _json(url, method="GET", body=None, raw=None):
    status, _, payload = _request(url, method, body, raw)
    return status, json.loads(payload)


class TestServer:
    def test_serves_dashboard(self, server):
        status, ctype, body = _request(server + "/")
        assert status == 200
        assert ctype.startswith("text/html")
        assert b"ASIS" in body

    def test_dashboard_has_no_embedded_engine(self, server):
        _, _, body = _request(server + "/")
        assert b"class ConceptAtom" not in body
        assert b"/api/step" in body

    def test_state_is_initial_frame(self, server):
        status, frame = _json(server + "/api/state")
        assert status == 200
        assert frame["step"] == 0
        assert set(frame["agents"]) == {"orchestrator", "analyst", "planner", "executor", "validator", "synthesizer"}

    def test_step_advances_real_engine(self, server):
        status, frame = _json(server + "/api/step", "POST", {})
        assert status == 200
        assert frame["step"] == 1
        pairs = [(m["sender"], m["receiver"]) for m in frame["messages"]]
        assert pairs == [("user", "orchestrator"), ("orchestrator", "planner")]

    def test_inject_and_run_to_result(self, server):
        _json(server + "/api/reset", "POST", {})
        status, frame = _json(server + "/api/inject", "POST", {"task": "goal:ship ⊗ entity:api"})
        assert status == 200
        task_id = frame["task_id"]
        assert frame["expression"] == C.compose(C.goal("ship"), C.entity("api")).serialize()
        for _ in range(30):
            _, frame = _json(server + "/api/step", "POST", {})
            if frame["converged"]:
                break
        assert frame["converged"]
        assert f"result:{task_id}" in frame["blackboard"]

    def test_reset_starts_over(self, server):
        _json(server + "/api/step", "POST", {})
        _, frame = _json(server + "/api/reset", "POST", {})
        assert frame["step"] == 0
        assert frame["blackboard"] == {}

    @pytest.mark.parametrize("body,raw", [
        ({"task": "(a"}, None),
        ({"task": ""}, None),
        ({"task": 5}, None),
        ({}, None),
        (None, b"not json"),
        (None, b"[1, 2]"),
        ({"task": "a" * 5000}, None),
    ])
    def test_inject_rejects_bad_input(self, server, body, raw):
        status, payload = _json(server + "/api/inject", "POST", body, raw)
        assert status == 400
        assert payload["error"]

    def test_rejects_oversized_body(self, server):
        status, payload = _json(server + "/api/step", "POST", raw=b" " * (MAX_BODY_BYTES + 1))
        assert status == 400

    def test_unknown_paths_404(self, server):
        assert _request(server + "/../../etc/passwd")[0] == 404
        assert _request(server + "/api/nope", "POST", {})[0] == 404
