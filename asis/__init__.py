"""ASIS 2.0 — Algebraic Swarm Intelligence System.

A deterministic multi-agent engine built on a symbolic algebra of concepts.
The engine lives in :mod:`asis.core`; the live dashboard server in
:mod:`asis.server`.
"""

from asis.cli import main
from asis.core import (
    C,
    Agent,
    AgentRole,
    AlgebraicMessage,
    Analyst,
    Blackboard,
    ConceptAtom,
    ConceptCategory,
    Executor,
    Expression,
    MessageType,
    Operator,
    Orchestrator,
    ParseError,
    Planner,
    Rule,
    RuleEngine,
    SwarmController,
    Synthesizer,
    Validator,
    __version__,
    create_default_swarm,
    parse_expression,
)

__all__ = [
    "C",
    "Agent",
    "AgentRole",
    "AlgebraicMessage",
    "Analyst",
    "Blackboard",
    "ConceptAtom",
    "ConceptCategory",
    "Executor",
    "Expression",
    "MessageType",
    "Operator",
    "Orchestrator",
    "ParseError",
    "Planner",
    "Rule",
    "RuleEngine",
    "SwarmController",
    "Synthesizer",
    "Validator",
    "__version__",
    "create_default_swarm",
    "main",
    "parse_expression",
]
