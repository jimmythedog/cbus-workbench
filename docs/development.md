# Development guide

This document records established development decisions and, as the application takes shape, will explain its architecture and important execution flows. It is not an inventory of source files.

## Running from source

These instructions are for developers. End-user releases are intended to be packaged as OS-specific installers that bundle Python and application dependencies; users should not need to install Python or uv.

### Standard development setup (Windows, macOS and conventional Linux)

1. Install **Python 3** and [uv](https://docs.astral.sh/uv/).
2. Clone the repository and change into its directory.
3. Install the project's locked dependencies:

   ```sh
   uv sync --locked
   ```

4. Start CBUS Workbench:

   ```sh
   uv run python main.py
   ```

`uv` creates and manages the project's `.venv/` environment. You do not need to activate it manually. The exact supported Python versions are defined in `pyproject.toml`.

To add a Python runtime dependency, use `uv add <package>`; to add a development dependency, use `uv add --dev <package>`. Commit changes to both `pyproject.toml` and `uv.lock`, but never commit `.venv/`.

### NixOS development

NixOS may not load the native libraries included in PySide6's PyPI wheels without extra compatibility setup. For local NixOS development, we use Nix-provided Python and PySide6 instead.

Install and enable `direnv` with `nix-direnv`, then from the repository directory run:

```sh
direnv allow
python main.py
```

The repository's `.envrc` loads `.shell.nix`, which provides Python, PySide6, uv and Ruff. **Use `python main.py` rather than `uv run python main.py` on NixOS**: the latter selects uv's virtual environment and may load the incompatible PyPI Qt wheels.

The NixOS setup is a development-environment exception, not a separate application implementation. The application code remains cross-platform. Dependencies installed only into uv's `.venv/` will not automatically be available to Nix-provided Python; when adding dependencies, verify the NixOS setup as well.

## Quality checks

Ruff handles Python linting and formatting:

```sh
ruff check .
ruff format --check .
```

On systems where Ruff is installed through uv as a development dependency, use `uv run ruff` instead. Add test instructions when the first tests are introduced.

## Architecture

Not yet defined. We will design and review the initial PySide6 interface using small stubbed data sources before documenting an implemented architecture. Add architectural explanations here only when they materially improve understanding.
