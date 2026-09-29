"""Command-line interface: ``asis run`` and ``asis dashboard``."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from asis.core import C, __version__, create_default_swarm

_COMMANDS = ("run", "dashboard")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asis",
        description="ASIS — Algebraic Swarm Intelligence System.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{run,dashboard}")

    run = sub.add_parser("run", help="run the demo task and export a trace (default)")
    run.add_argument("-o", "--output", default="asis_trace.json",
                     help="trace output path (default: %(default)s)")
    run.add_argument("--max-steps", type=int, default=50,
                     help="step budget before giving up on convergence (default: %(default)s)")
    run.add_argument("--no-trace", action="store_true", help="do not write a trace file")

    dash = sub.add_parser("dashboard", help="serve the live dashboard backed by the engine")
    dash.add_argument("--host", default="127.0.0.1", help="interface to bind (default: %(default)s)")
    dash.add_argument("--port", type=int, default=8765, help="port to listen on; 0 picks a free one (default: %(default)s)")
    dash.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    dash.add_argument("--no-demo", action="store_true", help="start with an empty swarm instead of the demo task")
    return parser


def _run(args: argparse.Namespace) -> int:
    swarm = create_default_swarm()

    task = C.compose(
        C.goal("optimize_system"),
        C.constraint("latency < 100ms"),
        C.constraint("throughput > 1000rps")
    )

    task_id = swarm.inject_task(task)
    result = swarm.run_until_convergence(max_steps=args.max_steps)

    print(f"Task {task_id} {'completed' if result['converged'] else 'did not converge'}")
    print(f"Steps: {result['steps_executed']}")
    print(f"Messages: {result['total_messages']}")
    print(f"Converged: {result['converged']}")

    if not args.no_trace:
        try:
            swarm.save_trace(args.output)
        except OSError as e:
            print(f"error: could not save trace: {e}", file=sys.stderr)
            return 1
        print(f"Trace saved to {args.output}")
    return 0 if result["converged"] else 2


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Bare `asis [run options]` keeps working as shorthand for `asis run`.
    if not argv or (argv[0] not in _COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")
    args = _build_parser().parse_args(argv)

    if args.command == "dashboard":
        from asis.server import serve
        return serve(host=args.host, port=args.port, open_browser=not args.no_browser,
                     demo=not args.no_demo)
    return _run(args)
