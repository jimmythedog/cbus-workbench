# CBUS Workbench

A cross-platform desktop application for configuring and maintaining CBUS/VLCB networks.

## Status

Early development. TCP/IP layouts can connect to a configured hub and show their
connection status. Complete incoming GridConnect frames are logged at TRACE. For a
connected TCP or serial layout, Layout → Send GridConnect Frame… allows raw frames to
be sent. Serial layouts use their configured device path.

## Development

CBUS Workbench will be developed using Python and PySide6 (Qt).

Development follows an outside-in approach, starting with the user interface before implementing CBUS communications.

See [Requirements](REQUIREMENTS.md) for the intended capabilities and [Development Guidelines](AGENTS.md) for the project's development principles.
