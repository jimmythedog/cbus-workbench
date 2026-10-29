# Development guide

This document records established development decisions and, as the application takes shape, will explain its architecture and important execution flows. It is not an inventory of source files.

## Python

- Use **Python 3**.
- Use `python3` in documentation and commands when invoking the interpreter directly on systems where that command is available.
- The minimum supported Python 3 version has not yet been selected; record it in `pyproject.toml` when the project is initialised.
- On Windows, the interpreter command may differ; prefer the project environment via `uv run` for cross-platform instructions.

## Dependencies and environments

Use **uv** for Python dependency and virtual-environment management.

- `pyproject.toml` declares project metadata, supported Python versions and dependencies.
- `uv.lock` locks resolved dependency versions for reproducible installs across supported platforms.
- Commit both files to Git when they are created.
- Do not commit the local `.venv/` directory.
- Use `uv sync --locked` to install dependencies according to the committed lockfile.
- Use `uv run` to execute commands within the project environment.

## Architecture

Not yet defined. We will design and review the initial PySide6 interface using small stubbed data sources before documenting an implemented architecture. Add architectural explanations here only when they materially improve understanding.
