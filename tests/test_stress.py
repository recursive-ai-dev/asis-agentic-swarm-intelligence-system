import pytest
from asis import C, Expression, create_default_swarm

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


def test_stress_swarm_multi_task_injection():
    """Test swarm controller handling 100 simultaneous tasks."""
    swarm = create_default_swarm()

    task_ids = []
    # Inject 100 tasks of varying complexity
    for i in range(100):
        if i % 2 == 0:
            task = C.compose(
                C.goal(f"goal_{i}"),
                C.constraint(f"constraint_a_{i}"),
                C.constraint(f"constraint_b_{i}")
            )
        else:
            task = C.goal(f"simple_goal_{i}")

        task_id = swarm.inject_task(task)
        task_ids.append(task_id)

    result = swarm.run_until_convergence(max_steps=5000)

    # Verify convergence was reached and all tasks processed
    assert result['converged'] is True
    # At minimum, 100 tasks * 3 steps per task = 300 messages, likely much more.
    assert result['total_messages'] > 300

    bb = swarm._blackboard.get_all()
    # Check that synthesis was written for at least some multi-step tasks
    synthesis_keys = [k for k in bb.keys() if k.startswith("synthesis:")]
    assert len(synthesis_keys) > 0


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
