# CBUS Workbench

CBUS Workbench is a cross-platform desktop application for configuring and maintaining MERG CBUS/VLCB networks.

Built with Python and Qt, it provides a native graphical interface for discovering modules, configuring node variables and events, managing layouts, and backing up and restoring configurations.

## Features

- Discover and inspect modules on a CBUS network.
- Configure node variables (NVs) and consumed events using module descriptors (MDFs).
- Commission modules and assign node numbers.
- Back up, compare and restore node and layout configurations.
- Name nodes and events.
- Monitor CBUS traffic and send diagnostic messages.

## Installation

**See the [installation guide](docs/installation.md)** to download, install, update
or uninstall CBUS Workbench on Windows, macOS or Linux.

## Documentation

- [Installation guide](docs/installation.md): installing, updating and uninstalling
  release builds.
- [User guide](docs/user-guide.md): for everyday operation and the Development Guide
  for contributing, building and testing.
- [Development guide](docs/development.md): for environment setup, checks, architecture,
  protocol implementation and diagnostics.

## Running from source

To run from source, install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/),
clone this repository and change into its directory. Then run:

```sh
uv sync --locked
uv run python main.py
```

`uv` manages the project's virtual environment; manual activation is unnecessary.
Help → About displays the application version. Help → User Guide opens the
bundled HTML copy of the user guide in your web browser; for source runs, build
it first with `make user-guide`.
Portable builds include the pinned MDF collection for offline use. For source runs,
use `make mdfs` to fetch it. See [MDF sourcing and release refresh instructions](docs/development.md#mdf-collection-for-development-and-portable-builds).
On NixOS, follow the [NixOS development setup](docs/development.md#nixos-development)
instead, using Nix-provided Python and PySide6.
