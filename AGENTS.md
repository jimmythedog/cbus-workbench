# AGENTS.md — CBUS Workbench

Project policy for any coding agent (Codex, Claude Code, …).

CBUS Workbench is a small Python/PySide6 desktop utility for configuring and
maintaining CBUS/VLCB networks. **Build the smallest understandable application
that reliably meets its requirements.** Working code that is unnecessarily
complicated is defective.

## How we work

- The code must be able to be readily understood, debugged and
  changed without an agent. Before nontrivial work, explain the design and
  affected files and wait for approval. Afterwards, summarise changes, test results
  and limitations, and explain any unfamiliar Python/Qt concepts used.
- Approval covers a bounded task, not each edit. Stop and ask when requirements are
  ambiguous, scope or complexity grows, a new abstraction or dependency seems
  necessary, protocol safety is uncertain, or stronger reasoning seems needed.
  Never treat uncertainty as permission to invent requirements.
- Use the developer-selected model and effort; don't escalate without asking.
- For nontrivial work, launch a separate agent to review your work and address any
  feedback where you agree

## Git

- Never change code on `main`. Work on `issue/<number>-<short-description>`,
  branched from an up-to-date `main`; reuse it if already on it.
- Check branch and working-tree status first. Don't switch branches or discard
  uncommitted changes without approval.
- Don't commit, push, merge, delete branches, change dependencies, or create/modify
  GitHub issues without explicit approval. Leave finished work uncommitted.

## Design

- Implement only approved requirements, with the smallest change that meets them.
  No speculative features, frameworks, plugin systems, event buses or elaborate
  recovery. Prefer explicit errors and manual retry unless protocol safety requires more.
- **Outside-in:** build the smallest useful UI with stubbed data → developer approves
  the UX → define the minimal API contract it needs → implement real behaviour behind it.
  Don't build backend for anticipated screens.
- Plain, idiomatic Python and standard Qt. Type hints and dataclasses where helpful;
  avoid decorators, metaclasses, inheritance and abstraction layers unless clearly needed.
- `MainWindow` coordinates only; feature logic lives in cohesive components.
  Functions over ~50 lines or modules over ~300 prompt a review, not automatic splitting.
- Alpha stage: get common workflows working with essential data-integrity and
  hardware-safety checks. Defer rare edge cases until seen in real use.
- The old JavaScript implementation is a behavioural reference, not an architectural template.

## Hardware independence

This is a general CBUS/VLCB tool. Implement behaviour from the published
specifications, never from what a test device (e.g. CANMIO) happens to do. Don't
hardcode module types, manufacturer IDs, firmware versions, parameter counts or
capabilities. Preserve unknown values as unknown rather than inventing defaults.
Device-specific behaviour needs a documented reason and approval.

## Logging

**A feature is incomplete until its significant execution and failure paths can be
followed in the logs.**

- Standard `logging` with the project `TRACE` level, persistent rotating files,
  `faulthandler` enabled, full tracebacks.
- At TRACE: meaningful method entry/exit, key arguments/results, significant
  branches and why, state changes and CBUS exchanges — with layout, node and
  operation identifiers. Don't trace trivial methods. Never log credentials.

## Tests

**Test observable contracts, not implementation.** Before adding a test, ask which
contract or real-world risk it protects; if unclear, don't add it.

- Happy path first, then realistic failures and hardware-safety failures.
- Extend an existing test rather than adding a near-duplicate. No coverage-only tests.
- Don't assert logs, private methods, mock call counts, internal queues or signal
  wiring, and don't change production code to make such tests possible. Test
  protocol ordering only where it's part of the contract or needed for safety.
- Small fixtures and stubs; no new test frameworks without approval.
- Delete tests written only to diagnose a problem once it's fixed (or rewrite them
  as contract tests if they guard a real regression).
- If a behaviour-preserving refactor breaks a test, suspect the test.

## Comments and docs

- Comment *why*: non-obvious logic, protocol and hardware-safety constraints, and the
  stages of complex operations. Don't narrate obvious code; if it needs long
  explanation, simplify it instead.
- `README.md` is the concise entry point. Never describe planned features as implemented.
- `docs/development.md` explains responsibilities, flows and key decisions, with
  ASCII diagrams for async request/response and failure paths. Update it only when
  a change affects architecture or makes it inaccurate; keep diagrams in sync.
  Don't catalogue files or routine changes.
- Keep CI, packaging and scripts minimal; prefer built-in GitHub features.

## Commands

Python 3.14+, PySide6, uv (Nix-provided Python on NixOS). Tests use `unittest`.

```sh
uv sync --locked   # install dependencies (non-NixOS)
make run           # run the app
make test          # full suite, offscreen
make check         # tests + ruff check + format check + git diff --check
make format        # ruff format
make mdfs          # fetch pinned MMC MDF collection (git-ignored)

# single test file / case
QT_QPA_PLATFORM=offscreen uv run python -m unittest tests.test_nv_write
QT_QPA_PLATFORM=offscreen uv run python -m unittest tests.test_nv_write.SomeTestCase.test_name
```

On NixOS use plain `python` inside `nix-shell .shell.nix` (or direnv), not `uv run`.
Run focused tests while working; `make check` before handing back.

Architecture: see `docs/development.md` → *Architecture* before changing a workflow.
