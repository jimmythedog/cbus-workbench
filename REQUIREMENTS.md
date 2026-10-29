# CBUS Workbench — Requirements

## Purpose

CBUS Workbench is a desktop utility for configuring and maintaining CBUS/VLCB networks. It is intended for occasional, interactive use: open it, perform a task, and close it.

**Simplicity, reliability, traceability and maintainability are fundamental requirements.**

## Core capabilities

1. **Connections:** Connect over serial or TCP, support multiple saved layouts, and display connection status.
2. **Discovery:** Discover nodes and read their configuration, including node variables (NVs), events and event variables (EVs). Inspection must work without module descriptors.
3. **Backup and restore:** Back up a layout's discovered hardware configuration and restore to compatible hardware, with explicit confirmation before writes.
4. **Configuration:** Read and edit NVs, EVs and events. Use existing Module Descriptor Files (MDFs) for meaningful controls where available; offer raw editing otherwise.
5. **Commissioning:** Discover nodes requesting commissioning, configure identities as required by the protocol, and make hardware changes explicit.

## Platform and interface

- Run on Linux, Windows and macOS using Python and a PySide6/Qt desktop interface.
- Prefer familiar desktop widgets and straightforward navigation.
- Separate GUI, CBUS communication and persistence with a few clear boundaries.
- Isolate MDF interpretation from the UI-facing configuration model so a future simplified descriptor format can be introduced without redesigning the UI.

## Diagnostics and code readability

- Maintain persistent, configurable logs, including a detailed TRACE level, so the path to an error or crash can be reconstructed where practical.
- Trace meaningful operation entry/exit, arguments/results, decisions, state changes, CBUS traffic and failures with relevant identifiers.
- Record full exception tracebacks and enable available fatal-error diagnostics.
- Explain non-obvious logic, protocol constraints and hardware-safety decisions with clear, accurate comments.
- Keep code understandable and modifiable by a developer learning Python.

## Development principles

- Develop **outside-in**: review a small UI using stubbed data before implementing hardware operations.
- Implement capabilities incrementally, driven by approved needs.
- Prefer clear errors and manual retry over elaborate recovery, except where hardware safety requires otherwise.
- Test observable contracts: happy path first, then important realistic failures and hardware-safety boundaries.
- Avoid exhaustive tests and speculative infrastructure.

## Non-goals

CBUS Workbench is not a continuously running monitoring service, a general-purpose CBUS framework, a plugin platform, or a feature-for-feature rewrite of the old JavaScript implementation. It must not silently change hardware configuration.

Unspecified features require discussion and approval.

## Initial milestone

Create a small runnable PySide6 desktop UI showing representative layouts, nodes and configuration through a minimal stubbed API. Review usability and structure **before** introducing real CBUS communication.
