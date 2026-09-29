from asis import C, create_default_swarm

def test_stress_deep_nesting():
    """Test flattening performance with deeply nested structures (e.g., 2000 nested composes)."""
    # Create a 2000-deep nested COMPOSE tree.
    # Because of associativity, this should flatten into a single COMPOSE with 2001 operands instantly.

    expr = C.entity("A_0")
    for i in range(1, 2001):
        expr = C.compose(expr, C.entity(f"A_{i}"))

    assert expr.operator == C.compose(C.entity("X"), C.entity("Y")).operator
    assert len(expr.operands) == 2001
    assert expr.depth == 1  # Flattened so depth is 1

    # Test identical depth for UNION
    expr_u = C.entity("U")
    for i in range(2000):
        # We use a unique entity otherwise idempotence will reduce it all to 1
        expr_u = C.union(expr_u, C.entity(f"B_{i}"))

    assert len(expr_u.operands) == 2001
    assert expr_u.depth == 1


def test_stress_idempotence():
    """Test that massive redundant UNION operations collapse correctly."""
    A = C.entity("Target")

    # Create a union of 1000 'A's and 1000 'B's
    B = C.entity("Other")

    expr = A
    for _ in range(1000):
        expr = C.union(expr, A)
        expr = C.union(expr, B)

    assert len(expr.operands) == 2
    assert A in expr.operands
    assert B in expr.operands


def test_stress_swarm_many_tasks():
    """One organism working 60 different tasks at once, sharing specialists and memory."""
    swarm = create_default_swarm()
    templates = [
        "optimize_system ⊗ latency < {l}ms ⊗ throughput > {t}rps",
        "high_availability ⊗ uptime >= 99.{n}% ⊗ cost < 600",
        "cut_costs ⊗ cost < {c} ⊗ latency < 250ms",
    ]
    task_ids = []
    for i in range(60):
        text = templates[i % 3].format(l=60 + i, t=500 + 10 * i, n=5 + i % 4, c=70 + i % 20)
        task_ids.append(swarm.submit(text))
    summary = swarm.run(max_steps=5000)
    assert summary["converged"]
    statuses = [swarm.result(t).status for t in task_ids]
    assert all(s in ("solved", "unsolved") for s in statuses)
    assert statuses.count("solved") > 40
    for tid in task_ids:
        r = swarm.result(tid)
        if r.solved:
            assert not r.violations
            assert r.report


def test_stress_massive_absorption():
    """Test that a giant tree instantly collapses if multiplied by zero."""
    # Build a giant tree
    tree = C.entity("Start")
    for i in range(500):
        tree = C.compose(tree, C.entity(f"Node_{i}"))

    # Multiply by zero
    zeroed = C.compose(tree, C.zero())

    assert zeroed == C.zero()
    assert len(zeroed.operands) == 1 # Just the atom itself
    assert zeroed.is_leaf
