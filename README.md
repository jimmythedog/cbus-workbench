# CBUS Workbench

A cross-platform desktop application for configuring and maintaining CBUS/VLCB networks,
built with Python and PySide6 (Qt).

## Status and features

Early development. Currently implemented:

- Saved layouts with TCP/IP or serial GridConnect connections and optional auto-connect.
- Node discovery, connection/discovery status and confirmed node information.
  Discovered nodes and their last-known parameters/CAN ID are remembered without backups.
  During full discovery, node selection is disabled and details remain empty; MDF
  lookup and module names are deferred until discovery ends. When
  discovery ends, the previous node is restored if found; otherwise the first
  discovered node is selected, including when discovery is incomplete.
- Reading node variables (NVs), stored events and event variables (EVs), with one
  shared editing session and verified application of the complete configuration.
- Separate full-width Produced Events and Consumed Events tabs.
  Live EV rows show supported MDF controls alongside their raw values.
  Supported MDF controls and raw values edit the same desired configuration;
  outside Edit, they display confirmed hardware values and remain read-only.
- Node and layout backups, optional descriptions, incomplete-backup warnings,
  offline viewing, comparison and node restoration with final verification.
  Node backup New, Compare and Restore actions remain disabled throughout restoration.
- Failed node Save/Restore reports requested versus actual differences and unknown
  values, with optional Retry after fresh discovery when the connection is safe.
  Uncertain writes or learn-mode state require reconnecting before another attempt.
- Messages / Diagnostics, raw GridConnect frame sending and persistent logs.

Layout Restore confirms and restores selected online nodes sequentially, then shows
remaining differences, unknown values and offline nodes. Retry reads hardware afresh
and applies outstanding differences when safe. Backup deletion is not available yet.
See [Requirements](REQUIREMENTS.md) for intended capabilities, including planned work.

## Installation and running

To run from source, install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/),
clone this repository and change into its directory. Then run:

```sh
uv sync --locked
uv run python main.py
```

`uv` manages the project's virtual environment; manual activation is unnecessary.
On NixOS, follow the [NixOS development setup](docs/development.md#nixos-development)
instead, using Nix-provided Python and PySide6.

## Documentation

- [User guide](docs/user-guide.md): layouts, connections, node configuration and backups.
- [Development guide](docs/development.md): environment setup, checks, architecture,
  protocol implementation and diagnostics.
- [Development guidelines](AGENTS.md): project principles and contribution workflow.
