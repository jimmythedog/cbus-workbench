# CBUS Workbench

A cross-platform desktop application for configuring and maintaining CBUS/VLCB networks,
built with Python and PySide6 (Qt).

## Status and features

Early development. Currently implemented:

- Saved layouts with TCP/IP or serial GridConnect connections and optional auto-connect.
- Node discovery, connection/discovery status and confirmed node information.
  Discovered nodes and their last-known parameters/CAN ID are remembered without backups.
  During hardware discovery (including Save and restore readbacks), node selection
  is disabled and the displayed details remain unchanged; MDF processing is deferred
  until discovery ends. When
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
- Send ON/OFF from an event's context menu, or use Layout → Send Event…
  for repeated long/short event testing on the selected layout. Short events
  display a disabled node number of 0 and send ASON/ASOF with NN zero,
  using the selected layout's configured CAN ID and connection.
  Long events default to the first discovered node; event numbers are 0–65535.
  Sending requires a connection and does not confirm that a node acted on the
  event. Outgoing frames appear in Diagnostics.
- Transmitted and received events appear in the layout event list as `NN:EN`, with short
  events using `0:EN`. Short events are not attributed to a node's Produced
  Events list. Observations do not become configured events.

Layout Restore confirms and restores selected online nodes sequentially, then shows
remaining differences, unknown values and offline nodes. Retry reads hardware afresh
and applies outstanding differences when safe. Node and Layout Restore offer separate
configuration and annotation choices, both checked by default. Annotation-only restore
works offline without hardware checks; Layout Restore applies node annotations only
to selected nodes and layout event names even with no nodes selected. Backup deletion is not available yet.
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
