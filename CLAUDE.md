# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `AGENTS.md` first and follow it.** It is the authoritative project policy
(simplicity, developer ownership, outside-in development, TRACE logging, contract
tests, git branch workflow, approval/reporting rules, hardware independence).
It is written for Codex but applies equally here. Key points that are easy to miss:

- The developer is learning Python: explain design and affected files before
  significant work, and explain unfamiliar Python/Qt concepts afterwards.
- Work on `issue/<number>-<short-description>` branches, never `main`. Do not
  commit, push, change dependencies or touch GitHub issues without explicit approval;
  leave completed work uncommitted for review.
- A feature is incomplete unless its significant paths are traceable in the logs.
- Tests protect observable contracts only — no log assertions, private-method
  coupling or mock call counts. Remove temporary diagnostic tests before finishing.
- Implement protocol behaviour from the CBUS/VLCB specifications; never hardcode
  behaviour observed on test hardware (e.g. CANMIO).
- Only update `docs/development.md` when it adds real architectural understanding
  or corrects an inaccuracy; keep its ASCII flow diagrams in sync with the code.

## Commands

Python 3.14+, PySide6, uv. The Makefile picks Nix-provided Python on NixOS
(`/etc/NIXOS` present) and uv elsewhere.

```sh
uv sync --locked              # install dependencies (non-NixOS)
make run                      # run the app (NixOS: python main.py, NOT uv run)
make test                     # full unittest suite, QT_QPA_PLATFORM=offscreen
make lint                     # ruff check .
make format                   # ruff format .
make check                    # tests + lint + format check + git diff --check
make mdfs                     # fetch pinned MMC MDF collection into resources/mdfs/ (git-ignored)
```

Tests use standard `unittest` (not pytest). Run a single file / test:

```sh
QT_QPA_PLATFORM=offscreen uv run python -m unittest tests.test_nv_write
QT_QPA_PLATFORM=offscreen uv run python -m unittest tests.test_nv_write.SomeTestCase.test_name
```

On NixOS, wrap with `nix-shell .shell.nix --run '...'` (or rely on direnv) and use
plain `python`. CI (`.github/workflows/ci.yml`) runs the unittest suite, `ruff check`
and `ruff format --check`. `.githooks/pre-commit` runs Ruff on staged files.

## Architecture

`docs/development.md` is the detailed architecture guide (execution flows,
discovery lifecycle, restore, request queue, verified writes, logging). Consult the
relevant section before changing a workflow. The big picture:

```text
PySide6 UI ── commands ──► per-layout CbusService ── GridConnect frames ──► Tcp/SerialConnection
PySide6 UI ◄── Qt signals ─ per-layout CbusService ◄── GridConnect frames ── transport
                            (live NodeState)
```

- **Transport** (`tcp_connection.py`, `serial_connection.py`, `gridconnect.py`):
  GridConnect ASCII frames over TCP or serial.
- **Opcode decoders** — one small module per CBUS message (`pnn.py`, `paran.py`,
  `nvans.py`, `neval.py`, `enrsp.py`, `numev.py`, `cmderr.py`, `wrack.py`, …):
  pure functions returning frozen dataclasses, citing the MERG Developer's Guide
  section they implement.
- **`cbus_service.py`** (`CbusService`): one per connected layout, created by
  `MainWindow` on connect and discarded on disconnect. Owns live `NodeState`, QNN/PNN
  discovery, a single shared FIFO request queue with response timeouts, presence
  polling, and the verified writers (`nv_write.py`, `ev_write.py`, `nv_save.py`,
  `node_restore.py`). The UI never decodes opcodes or manages transactions; it
  calls service methods and observes signals. Unknown values stay unknown (`None`),
  and seeing a write request never confirms it succeeded.
- **UI**: `window.py` (`MainWindow`, application-level coordination only) →
  `layout_view.py` → `node_view.py` → `node_details.py`, with feature components
  (`node_variables.py`, `node_events.py`, backup/restore/compare dialogs and
  `*_workflow.py` helpers) holding feature logic.
- **Persistence**: YAML files under Qt's standard Data/State locations
  (`paths.py`, `app_settings.py`, `layout_settings.py`, `node_metadata.py`,
  `annotations.py`, `node_backup_files.py`, `layout_backups.py`). Backups use the
  backup dictionary format (`node_snapshot.py`); `configuration_compare.py`
  compares two such dictionaries and is also used for restore verification.
- **MDFs** (`mdfs.py`, `mdf_*.py`, `event_mdf.py`): module description files from
  the bundled/pinned MMC collection or user overrides, rendered as controls over
  the same raw NV/EV values. Never downloaded at runtime.
- **Logging** (`logging_config.py`): custom `TRACE` level; use loggers named
  `workbench.<area>`, `trace(logger, ...)`, and identifying fields via
  `extra={"fields": {...}}`. UI actions report errors through `ErrorReporter.run()`.
