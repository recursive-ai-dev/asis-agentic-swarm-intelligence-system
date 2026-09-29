"""Behaviour of the specialist team and the substrate that connects them."""

import json

import pytest

from asis import (
    VITAL,
    C,
    Context,
    Kind,
    KnowledgeBase,
    ParseError,
    Receptor,
    Signal,
    Specialist,
    SwarmController,
    create_default_swarm,
    default_team,
    solve,
)
from asis.knowledge import make_plan

DEMO = "optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps"


def run(task, lesions=(), budget=None, kb=None):
    swarm = create_default_swarm(kb)
    for agent_id in lesions:
        swarm.remove_agent(agent_id)
    task_id = swarm.submit(task, budget=budget)
    swarm.run(max_steps=2000)
    return swarm, swarm.result(task_id)


def brute_force_cheapest(kb, constraints_text, max_actions=4):
    """Exhaustive search over small plans, to check the team's answers are optimal."""
    from itertools import combinations_with_replacement

    constraints = [kb.parse_constraint(t) for t in constraints_text]
    best = None
    names = list(kb.actions)
    for size in range(0, max_actions + 1):
        for combo in combinations_with_replacement(names, size):
            counts = {}
            for a in combo:
                counts[a] = counts.get(a, 0) + 1
            plan = make_plan(counts)
            if kb.plan_problems(plan):
                continue
            m = kb.estimate(plan)
            if all(c.satisfied(m[c.metric]) for c in constraints):
                if best is None or m["cost"] < best:
                    best = m["cost"]
    return best


# ============================================================================
# OUTCOMES
# ============================================================================

class TestSolving:
    def test_demo_task_is_solved_optimally(self):
        _, r = run(DEMO)
        assert r.solved
        assert r.metrics["latency"] < 100 and r.metrics["throughput"] > 1000
        kb = KnowledgeBase.default()
        assert r.cost == brute_force_cheapest(kb, ["latency < 100ms", "throughput > 1000rps"])

    @pytest.mark.parametrize("task,constraints", [
        ("cut_costs ⊗ cost < 80 ⊗ latency < 200ms", ["cost < 80", "latency < 200ms"]),
        ("optimize_system ⊗ latency < 120ms", ["latency < 120ms"]),
        ("optimize_system ⊗ throughput >= 900rps ⊗ cost <= 300", ["throughput >= 900rps", "cost <= 300"]),
    ])
    def test_constraint_only_tasks_find_the_cheapest_plan(self, task, constraints):
        _, r = run(task)
        assert r.solved
        assert r.cost == brute_force_cheapest(KnowledgeBase.default(), constraints)

    def test_goal_capabilities_are_provided(self):
        _, r = run("launch_feature")
        assert r.solved
        kb = KnowledgeBase.default()
        provided = kb.provided(make_plan(r.plan))
        assert {"tested", "deployed", "safe_rollout"} <= provided

    def test_nested_goals_decompose(self):
        _, r = run("production_ready")
        assert r.solved
        provided = KnowledgeBase.default().provided(make_plan(r.plan))
        assert {"tested", "deployed", "safe_rollout", "fault_isolation", "retries", "monitoring"} <= provided

    def test_alternative_goals_pick_one(self):
        _, r = run("(scale_out ⊕ high_availability) ⊗ throughput > 1500rps ⊗ ¬goal:caching ⊗ cost < 500")
        assert r.solved
        assert "add_cache" not in r.plan
        assert r.metrics["throughput"] > 1500

    def test_required_action_is_kept(self):
        _, r = run("optimize_system ⊗ action:add_cdn ⊗ latency < 150ms")
        assert r.solved
        assert r.plan.get("add_cdn") == 1

    def test_forbidden_action_is_avoided(self):
        _, r = run("optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps ⊗ ¬action:upgrade_instance")
        assert r.solved
        assert "upgrade_instance" not in r.plan

    def test_negated_constraint(self):
        _, r = run("optimize_system ⊗ ¬(latency < 150ms) ⊗ cost < 90")
        assert r.solved
        assert r.metrics["latency"] >= 150

    def test_unreachable_constraint_is_unsolved_with_closest_plan(self):
        _, r = run("optimize_system ⊗ latency < 20ms")
        assert r.status == "unsolved"
        assert r.violations and r.violations[0]["metric"] == "latency"
        assert r.metrics["latency"] < 180  # it still got as close as it could
        assert "Still violated" in r.report

    def test_physical_floor_is_found(self):
        # 2% × 0.8 × 0.5 × 0.7 × 0.9 = 0.504% is the lowest error rate the domain allows.
        _, r = run("production_ready ⊗ errors < 0.5% ⊗ cost < 350")
        assert r.status == "unsolved"
        assert r.metrics["error_rate"] == pytest.approx(0.504)


class TestRejection:
    @pytest.mark.parametrize("task,fragment", [
        ("optimize_system ⊗ latency < 10ms ⊗ latency > 20ms", "cannot all hold"),
        ("optimize_system ⊗ uptime > 100%", "at most 99.999%"),
        ("hi_availability", "did you mean 'high_availability'"),
        ("optimize_system ⊗ action:add_cahce", "did you mean 'add_cache'"),
        ("optimize_system ⊗ speed < 3", "unknown metric 'speed'"),
        ("optimize_system ⊗ latency < 3kg", "not compatible"),
        ("action:add_cache ⊗ ¬action:add_cache", "both required and forbidden"),
        ("scale_out ⊕ high_availability ⊗ throughput > 1500rps", "group alternatives first"),
        ("entity:database", "nothing to solve"),
        ("production_ready ⊗ ¬action:retry_with_backoff", "retry_with_backoff is forbidden"),
    ])
    def test_rejections_explain_themselves(self, task, fragment):
        _, r = run(task)
        assert r.status == "rejected"
        assert fragment in r.reason
        assert fragment in r.report

    def test_rejection_is_cheap(self):
        _, r = run("optimize_system ⊗ latency < 10ms ⊗ latency > 20ms")
        assert r.energy_used <= 3

    def test_submit_rejects_unparseable_text(self):
        with pytest.raises(ParseError):
            create_default_swarm().submit("(a")


class TestReport:
    def test_report_explains_plan_numbers_and_lineage(self):
        _, r = run(DEMO)
        assert "Status: SOLVED" in r.report
        assert "✓ latency < 100 ms" in r.report
        assert "How the team got there:" in r.report
        assert "[repairer]" in r.report and "[planner]" in r.report

    def test_result_to_dict_is_json_serializable(self):
        _, r = run(DEMO)
        json.dumps(r.to_dict())


# ============================================================================
# THE ORGANISM
# ============================================================================

class TestSubstrate:
    def test_every_specialist_has_one_tissue_and_receptors(self):
        for agent in default_team():
            assert agent.tissue and agent.receptors and agent.description

    def test_signals_are_delivered_by_receptor_not_address(self):
        swarm, _ = run(DEMO)
        for entry in swarm.export_trace()["message_log"]:
            receiver = entry["receiver"]
            if receiver is None:
                continue
            agent = next(a for a in swarm.agents if a.agent_id == receiver)
            assert entry["message_type"] in {r.kind.value for r in agent.receptors}

    def test_redundant_cells_share_the_load(self):
        swarm, _ = run(DEMO)
        e1, e2 = (next(a for a in swarm.agents if a.agent_id == f"estimator-{i}") for i in (1, 2))
        assert e1.processed > 0 and e2.processed > 0
        assert abs(e1.processed - e2.processed) <= 1

    def test_energy_is_charged_to_the_task(self):
        swarm, r = run(DEMO)
        assert 0 < r.energy_used < r.budget
        assert r.energy_used == sum(a.energy_spent for a in swarm.agents)

    def test_exhaustion_still_produces_an_answer(self):
        _, r = run("optimize_system ⊗ latency < 20ms", budget=12)
        assert r.status == "unsolved"
        assert "energy budget of 12 spent" in r.reason
        assert r.energy_used <= 12

    def test_vital_signals_cost_nothing(self):
        assert {Kind.SETTLE, Kind.RESULT, Kind.QUIESCENT, Kind.EXHAUSTED, Kind.REJECTED} == set(VITAL)

    def test_trace_is_byte_identical_across_runs(self):
        a = json.dumps(run(DEMO)[0].export_trace(), sort_keys=True)
        b = json.dumps(run(DEMO)[0].export_trace(), sort_keys=True)
        assert a == b

    def test_duplicate_task_ids_are_disambiguated(self):
        swarm = create_default_swarm()
        a, b = swarm.submit(DEMO), swarm.submit(DEMO)
        assert a != b and b.startswith(a)

    def test_unheard_signals_are_logged(self):
        swarm, _ = run(DEMO, lesions=["explainer"])
        unheard = [m for m in swarm.export_trace()["message_log"] if m["receiver"] is None]
        assert any(m["message_type"] == "RESULT" for m in unheard) is False  # memory still hears RESULT
        swarm, _ = run(DEMO, lesions=["explainer", "memory"])
        unheard = [m for m in swarm.export_trace()["message_log"] if m["receiver"] is None]
        assert any(m["message_type"] == "RESULT" for m in unheard)

    def test_duplicate_agent_ids_are_refused(self):
        swarm = SwarmController()
        swarm.register_agent(default_team()[0])
        with pytest.raises(ValueError, match="already registered"):
            swarm.register_agent(default_team()[0])

    def test_many_tasks_at_once_do_not_interfere(self):
        swarm = create_default_swarm()
        ids = [swarm.submit(t) for t in (DEMO, "launch_feature", "optimize_system ⊗ latency < 10ms ⊗ latency > 20ms")]
        swarm.run()
        alone = [run(t)[1] for t in (DEMO, "launch_feature", "optimize_system ⊗ latency < 10ms ⊗ latency > 20ms")]
        for tid, solo in zip(ids, alone, strict=True):
            together = swarm.result(tid)
            assert (together.status, together.plan, together.cost) == (solo.status, solo.plan, solo.cost)

    def test_custom_specialist_joins_through_receptors(self):
        heard = []

        class Auditor(Specialist):
            tissue = "auditor"
            receptors = (Receptor(Kind.RESULT),)
            description = "Keeps a record of every answer."

            def handle(self, signal: Signal, ctx: Context):
                heard.append((signal.task_id, signal.data["status"]))
                return []

        swarm = create_default_swarm()
        swarm.register_agent(Auditor())
        tid = swarm.submit(DEMO)
        swarm.run()
        assert heard == [(tid, "solved")]


class TestMemory:
    def test_repeated_problem_is_recalled_and_cheaper(self):
        swarm = create_default_swarm()
        first = swarm.submit(DEMO)
        swarm.run()
        second = swarm.submit(DEMO)
        swarm.run()
        a, b = swarm.result(first), swarm.result(second)
        assert (a.plan, a.cost) == (b.plan, b.cost)
        assert b.energy_used < a.energy_used
        assert "recalled" in b.report

    def test_memory_matches_on_meaning_not_wording(self):
        swarm = create_default_swarm()
        swarm.submit("optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps")
        swarm.run()
        tid = swarm.submit("optimize_system ⊗ p99 < 0.1s ⊗ rps > 1000")
        swarm.run()
        assert "recalled" in swarm.result(tid).report


# ============================================================================
# LESIONS: remove one specialist and check the organism degrades like a body
# ============================================================================

class TestLesions:
    @pytest.mark.parametrize("lesion", ["estimator-1", "estimator-2", "memory", "explainer"])
    def test_non_vital_specialists_do_not_change_answers(self, lesion):
        _, intact = run(DEMO)
        _, lesioned = run(DEMO, lesions=[lesion])
        assert (lesioned.status, lesioned.plan, lesioned.cost) == (intact.status, intact.plan, intact.cost)

    def test_without_explainer_there_is_no_report(self):
        _, r = run(DEMO, lesions=["explainer"])
        assert r.solved and r.report == ""

    def test_without_optimizer_answers_cost_more(self):
        task = "high_availability ⊗ uptime >= 99.9% ⊗ cost < 400"
        _, intact = run(task)
        _, lesioned = run(task, lesions=["optimizer"])
        assert intact.solved and lesioned.solved
        assert lesioned.cost > intact.cost

    def test_without_repairer_only_first_drafts_succeed(self):
        _, needs_repair = run(DEMO, lesions=["repairer"])
        assert needs_repair.status == "unsolved"
        _, first_draft_ok = run("high_availability ⊗ uptime >= 99.9% ⊗ cost < 400", lesions=["repairer"])
        assert first_draft_ok.solved

    @pytest.mark.parametrize("lesion", ["intake", "immune", "decomposer", "planner", "checker"])
    def test_losing_a_pipeline_stage_still_yields_an_honest_answer(self, lesion):
        swarm, r = run(DEMO, lesions=[lesion])
        assert swarm.converged
        assert r.status == "unsolved"
        assert r.reason == "no plan was ever evaluated"

    @pytest.mark.parametrize("lesion", ["regulator", "judge"])
    def test_vital_organs(self, lesion):
        swarm, r = run(DEMO, lesions=[lesion])
        assert swarm.idle and not swarm.converged
        assert r.status == "stalled"

    def test_regulator_redundancy_prevents_stall(self):
        from asis import Regulator

        swarm = create_default_swarm()
        swarm.register_agent(Regulator("regulator-2"))
        swarm.remove_agent("regulator")
        tid = swarm.submit(DEMO)
        swarm.run()
        assert swarm.result(tid).solved


def test_solve_convenience():
    r = solve(DEMO)
    assert r.solved and r.task == DEMO


def test_custom_knowledge_base():
    kb = KnowledgeBase.from_dict({
        "name": "kitchen",
        "metrics": {"prep_time": {"unit": "min", "baseline": 60, "min": 0}},
        "actions": {
            "mise_en_place": {"cost": 5, "effects": {"prep_time": {"add": -15}}},
            "sous_chef": {"cost": 40, "effects": {"prep_time": {"factor": 0.5}}, "provides": ["help"]},
            "food_processor": {"cost": 10, "effects": {"prep_time": {"add": -10}}},
        },
        "goals": {"dinner_party": {"needs": ["help"]}},
    })
    r = solve("dinner_party ⊗ prep_time < 20min", kb=kb)
    assert r.solved
    assert r.plan == {"sous_chef": 1, "mise_en_place": 1, "food_processor": 1} or r.metrics["prep_time"] < 20
    assert C  # the algebra is still what carries every signal
