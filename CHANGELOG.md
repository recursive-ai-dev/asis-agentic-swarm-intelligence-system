# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.0.0] — Unreleased

First packaged release.

### Added
- **The dashboard runs on the real engine.** `asis dashboard` serves it from
  a standard-library HTTP server with a small JSON API (`/api/state`,
  `/api/step`, `/api/inject`, `/api/reset`) backed by a live
  `SwarmController`. The JavaScript copy of the engine is gone. It had
  drifted from the Python engine: no algebraic canonicalization, a different
  Analyst, and different task IDs. Opened as a plain file, the dashboard
  replays traces from `asis run` instead.
- The dashboard's expression tree panel draws the actual tree of the payload
  in flight. It used to count parentheses and draw a fixed set of dots.
- Step button (and `→` key) for single-stepping the swarm. Parse errors are
  shown in the task dialog.
- `parse_expression()` / `ParseError`: a parser for ASIS task notation
  (`⊗ * ⊕ | ¬ ~ ( )`, `category:name` atoms). It replaces the dashboard's
  keyword guessing, which made a task a goal only if its text contained
  "goal", "optimize" or "solve".
- `SwarmController.converged`, `.step_count`, `.snapshot()` and
  `.latest_snapshot`. Convergence is now tracked per step, so the swarm can be
  stepped manually as well as with `run_until_convergence`.
- `pyproject.toml` packaging: installable as `asis-swarm`, with an `asis`
  command offering `asis run` (`--output`, `--max-steps`, `--no-trace`) and
  `asis dashboard` (`--host`, `--port`, `--no-browser`, `--no-demo`).
  A bare `asis` is shorthand for `asis run`.
- `asis.__version__`; the exported trace's `version` field now reads from it.
- GitHub Actions CI: ruff lint, tests on Python 3.10–3.14, and package build.
- Regression test suite (`tests/test_regressions.py`).

### Changed
- `asis.py` is now the `asis` package (`asis/core.py`, `cli.py`, `server.py`,
  `dashboard.html`). `from asis import …` is unchanged. Run the demo with
  `asis run` or `python -m asis` instead of `python asis.py`.
- Trace format: injected tasks now appear in the message log (as
  `user → orchestrator` in the following step's frame), so `total_messages`
  is one higher per injected task. Each message carries `payload_text`, and each
  snapshot carries `converged`.
- `build.sh` builds the package entry point and bundles the dashboard into
  the binary.
- **Traces are now fully deterministic.** Message timestamps are a logical
  clock (the step number) and correlation IDs are derived from a per-swarm
  sequence number plus message content. Wall-clock timestamps were removed
  from snapshots and the trace header, and blackboard history entries carry a
  `version` number instead of a timestamp. Two runs with the same inputs now
  produce byte-identical traces, as the README has always claimed.
- `ConceptAtom.serialize()` includes metadata when present, e.g.
  `ATOM(x:GOAL:general{task_id=ab12})`. Atoms without metadata serialize as
  before. Blackboard keys derived from serialized payloads change as a result.
- The CLI exits with status `2` if the swarm does not converge within the step
  budget and `1` if the trace cannot be written.

### Fixed
- Expressions differing only in atom metadata compared equal and hashed the
  same, so `⊕` idempotence merged distinct atoms (for example, two tasks'
  tagged goals).
- The Analyst's goal-decomposition rule matched any expression, not just goal
  atoms, and replaced the whole payload. That dropped the task content and its
  `task_id`, so every single-step task was stored as `result:unknown`.
- Tasks that failed validation never produced a result: the Executor ignored
  the Validator's `FEEDBACK` message. Failures are now escalated to the
  Orchestrator and recorded as `result:<task_id>` with `status=failed`.
- `run_until_convergence(max_steps=0)` ran 1000 steps instead of zero.
- `inject_task` raises a clear `RuntimeError` when no orchestrator is
  registered, where it used to raise a bare `KeyError`.
- `Callable` was used in `Rule`'s annotations without being imported, so
  `typing.get_type_hints(Rule)` raised `NameError`.
- `test_match_consistent_binding` did not test consistency. It now checks that
  a repeated pattern variable must bind the same subexpression.
- Dashboard: the convergence banner stayed partly visible at the top of the
  screen when it should have been hidden; the agent graph overlapped the
  control buttons on laptop-sized screens; user-entered task text was inserted
  into the message log as raw HTML; and Firefox showed an unstyled scrollbar.

### Earlier fixes (pre-release)
- `Expression.substitute` and `Rule._substitute_bindings` bypassed
  canonicalization (flattening, identity, absorption).
- `Agent.process_inbox` left an agent stuck in `"processing"` if a handler
  raised.
- Orchestrator and Synthesizer read `task_id` from the wrong place.
- Correlation IDs could collide under fast execution.
