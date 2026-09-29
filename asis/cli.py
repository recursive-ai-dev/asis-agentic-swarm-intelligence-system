"""Command-line interface: ``asis run | solve | kb | dashboard``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from asis.core import ParseError, __version__
from asis.knowledge import KnowledgeBase, KnowledgeBaseError

_COMMANDS = ("run", "solve", "kb", "dashboard")
DEMO_TASK = "optimize_system ⊗ latency < 100ms ⊗ throughput > 1000rps"

EXIT_SOLVED, EXIT_ERROR, EXIT_UNSOLVED, EXIT_REJECTED = 0, 1, 2, 3


def _add_kb(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kb", metavar="PATH",
                        help="knowledge base JSON file (default: the bundled web_service domain)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asis",
        description="ASIS — a deterministic team of specialists that plans against a knowledge base.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{run,solve,kb,dashboard}")

    run = sub.add_parser("run", help="solve the demo task and export a trace (default)")
    run.add_argument("-o", "--output", default="asis_trace.json", help="trace output path (default: %(default)s)")
    run.add_argument("--max-steps", type=int, default=1000, help="step limit (default: %(default)s)")
    run.add_argument("--no-trace", action="store_true", help="do not write a trace file")
    _add_kb(run)

    solve = sub.add_parser("solve", help="solve a task written in ASIS notation")
    solve.add_argument("task", help=f"e.g. \"{DEMO_TASK}\"")
    solve.add_argument("--budget", type=int, help="energy budget for the task (default: 400)")
    solve.add_argument("--max-steps", type=int, default=1000, help="step limit (default: %(default)s)")
    solve.add_argument("--json", action="store_true", help="print the result as JSON")
    solve.add_argument("--trace", metavar="PATH", help="also write a full trace")
    _add_kb(solve)

    kb = sub.add_parser("kb", help="show the goals, actions and metrics a knowledge base offers")
    kb.add_argument("--json", action="store_true", help="print the knowledge base as JSON")
    _add_kb(kb)

    dash = sub.add_parser("dashboard", help="serve the live dashboard backed by the engine")
    dash.add_argument("--host", default="127.0.0.1", help="interface to bind (default: %(default)s)")
    dash.add_argument("--port", type=int, default=8765, help="port; 0 picks a free one (default: %(default)s)")
    dash.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    dash.add_argument("--no-demo", action="store_true", help="start without the demo task")
    _add_kb(dash)
    return parser


def _load_kb(path: Optional[str]) -> KnowledgeBase:
    return KnowledgeBase.load(path) if path else KnowledgeBase.default()


def _exit_code(status: str) -> int:
    return {"solved": EXIT_SOLVED, "rejected": EXIT_REJECTED}.get(status, EXIT_UNSOLVED)


def _solve(task: str, kb: KnowledgeBase, budget: Optional[int], max_steps: int, as_json: bool,
           trace: Optional[str]) -> int:
    from asis.specialists import create_default_swarm

    swarm = create_default_swarm(kb)
    task_id = swarm.submit(task, budget=budget)
    swarm.run(max_steps=max_steps)
    result = swarm.result(task_id)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(result.report or f"Task {task_id}: {result.status} — {result.reason}")
        print(f"\nEnergy used: {result.energy_used}/{result.budget} over {swarm.step_count} steps")
    if trace:
        try:
            swarm.save_trace(trace)
        except OSError as e:
            print(f"error: could not save trace: {e}", file=sys.stderr)
            return EXIT_ERROR
        if not as_json:
            print(f"Trace saved to {trace}")
    return _exit_code(result.status)


def _show_kb(kb: KnowledgeBase, as_json: bool) -> int:
    if as_json:
        print(json.dumps(kb.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"{kb.name} — {kb.description}")
    print("\nGoals:")
    for g in kb.goals.values():
        needs = ", ".join(g.needs) or "only the stated constraints"
        print(f"  {g.name}: needs {needs}")
    print("\nCapabilities (usable as goals): " + ", ".join(sorted(kb.capabilities)))
    print("\nMetrics (usable in constraints):")
    for m in kb.metrics.values():
        aliases = f"  aka {', '.join(m.aliases)}" if m.aliases else ""
        print(f"  {m.name}: baseline {m.baseline:g}{m.unit}{aliases}")
    print("\nActions:")
    for a in kb.actions.values():
        extra = []
        if a.requires:
            extra.append("requires " + ", ".join(a.requires))
        if a.conflicts:
            extra.append("conflicts with " + ", ".join(sorted(a.conflicts)))
        if a.max_uses > 1:
            extra.append(f"up to ×{a.max_uses}")
        print(f"  {a.name} ({a.cost:+g}): {a.description}" + (f" [{'; '.join(extra)}]" if extra else ""))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Bare `asis [run options]` keeps working as shorthand for `asis run`.
    if not argv or (argv[0] not in _COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")
    args = _build_parser().parse_args(argv)

    try:
        kb = _load_kb(args.kb)
    except (OSError, KnowledgeBaseError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    if args.command == "dashboard":
        from asis.server import serve
        return serve(host=args.host, port=args.port, open_browser=not args.no_browser,
                     demo=not args.no_demo, kb=kb)
    if args.command == "kb":
        return _show_kb(kb, args.json)
    try:
        if args.command == "solve":
            return _solve(args.task, kb, args.budget, args.max_steps, args.json, args.trace)
        return _solve(DEMO_TASK, kb, None, args.max_steps, False, None if args.no_trace else args.output)
    except ParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
