"""ASIS — Algebraic Swarm Intelligence System.

A deterministic team of single-purpose specialists that plans against a
knowledge base: give it a goal and constraints, get back the cheapest plan
that meets them (or a precise account of why none does).

Modules: :mod:`asis.core` (algebra, parser, rule engine), :mod:`asis.knowledge`
(domain model), :mod:`asis.organism` (signals and substrate),
:mod:`asis.specialists` (the team), :mod:`asis.server` (live dashboard).
"""

from asis.cli import main
from asis.core import (
    C,
    ConceptAtom,
    ConceptCategory,
    Expression,
    Operator,
    ParseError,
    Rule,
    RuleEngine,
    __version__,
    parse_expression,
)
from asis.knowledge import (
    Action,
    Constraint,
    ConstraintError,
    Effect,
    Goal,
    KnowledgeBase,
    KnowledgeBaseError,
    Metric,
    plan_key,
)
from asis.organism import (
    VITAL,
    Blackboard,
    Context,
    Kind,
    Receptor,
    Signal,
    Specialist,
    SwarmController,
    TaskResult,
)
from asis.specialists import (
    Checker,
    Decomposer,
    Estimator,
    Explainer,
    Immune,
    Intake,
    Judge,
    Memory,
    Optimizer,
    Planner,
    Regulator,
    Repairer,
    create_default_swarm,
    default_team,
    solve,
)

__all__ = [
    "VITAL", "Action", "Blackboard", "C", "Checker", "ConceptAtom", "ConceptCategory", "Constraint",
    "ConstraintError", "Context", "Decomposer", "Effect", "Estimator", "Explainer", "Expression", "Goal",
    "Immune", "Intake", "Judge", "Kind", "KnowledgeBase", "KnowledgeBaseError", "Memory", "Metric",
    "Operator", "Optimizer", "ParseError", "Planner", "Receptor", "Regulator", "Repairer", "Rule",
    "RuleEngine", "Signal", "Specialist", "SwarmController", "TaskResult", "__version__",
    "create_default_swarm", "default_team", "main", "parse_expression", "plan_key", "solve",
]
