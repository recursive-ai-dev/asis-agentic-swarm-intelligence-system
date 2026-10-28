#!/usr/bin/env python3
"""Compare bounded compositions with depth-one search and a small exact oracle.

This is an accounting/reproduction tool, not evidence of a general speedup.
The oracle enumerates every action multiset and is intentionally restricted to
small synthetic cases. All engine model calls count, including rejected moves.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asis import KnowledgeBase, SearchConfig, solve  # noqa: E402
from asis.knowledge import make_plan  # noqa: E402


def case(depth: int, distractors: int) -> KnowledgeBase:
    actions = {"fast": {"cost": 300, "effects": {"latency": {"factor": 0.1}}}}
    for i in range(depth - 1):
        actions[f"saving_{i}"] = {
            "cost": -300 / (depth - 1),
            "effects": {"latency": {"factor": 4 ** (1 / (depth - 1))}},
        }
    for i in range(distractors):
        actions[f"distractor_{i}"] = {"cost": 10 + i, "effects": {"latency": {"factor": 1.1}}}
    return KnowledgeBase.from_dict({
        "name": f"compensation_depth_{depth}",
        "metrics": {"latency": {"unit": "ms", "baseline": 100},
                    "cost": {"unit": "usd", "baseline": 100, "min": 0}},
        "actions": actions,
    })


def oracle(kb: KnowledgeBase, limit: float) -> dict:
    constraints = [kb.parse_constraint(f"latency <= {limit}ms"), kb.parse_constraint("cost <= 100")]
    best, evaluations, regions = None, 0, 0
    names = list(kb.actions)
    for counts in itertools.product(*(range(kb.actions[a].max_uses + 1) for a in names)):
        regions += 1
        plan = make_plan(dict(zip(names, counts, strict=True)))
        if kb.plan_problems(plan):
            continue
        metrics = kb.estimate(plan)
        evaluations += 1
        if all(c.satisfied(metrics[c.metric]) for c in constraints):
            key = (metrics["cost"], sum(counts), plan)
            if best is None or key < best:
                best = key
    return {"feasible": best is not None, "best_cost": best[0] if best else None,
            "model_evaluations": evaluations, "regions": regions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distractors", type=int, default=2, help="0–10 irrelevant actions (default: 2)")
    parser.add_argument("--output", type=Path, help="save JSON measurements")
    args = parser.parse_args()
    if not 0 <= args.distractors <= 10:
        parser.error("--distractors must be between 0 and 10 (the oracle is exhaustive)")
    rows = []
    for depth in (2, 3):
        kb = case(depth, args.distractors)
        for limit in (50, 20):
            truth = oracle(kb, limit)
            task = f"latency <= {limit}ms ⊗ cost <= 100"
            for allowance in (1, 2, 3):
                started = time.perf_counter()
                result = solve(task, kb, search_config=SearchConfig(max_depth=allowance))
                elapsed = time.perf_counter() - started
                # False unsolved results are legitimate incomplete searches;
                # false solved results fail this benchmark immediately.
                if result.solved and not truth["feasible"]:
                    raise AssertionError("solver produced a false feasible result")
                if truth["feasible"] and allowance >= depth and not result.solved:
                    raise AssertionError("bounded composition missed this known in-allowance regression")
                if result.solved:
                    predicted = kb.estimate(make_plan(result.plan))
                    assert predicted["latency"] <= limit and predicted["cost"] <= 100
                rows.append({"required_depth": depth, "search_depth": allowance,
                             "latency_limit": limit, "distractors": args.distractors,
                             "status": result.status, "assessment": result.assessment,
                             "model_evaluations": result.model_evaluations,
                             "plans_checked": result.plans_considered,
                             "elapsed_seconds": elapsed, "oracle": truth})
    payload = json.dumps({"note": "Synthetic correctness comparison; no general efficiency claim.", "runs": rows}, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
