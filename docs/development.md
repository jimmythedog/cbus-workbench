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

On systems where Ruff is installed through uv as a development dependency, use `uv run ruff` instead.

Run the focused TCP connection and frame checks with:

```sh
python -m unittest discover -s tests -v
```

## Logs

The application configures standard Python logging before constructing the Qt UI. Development runs start at TRACE; PyInstaller packaged releases start at INFO. Logs go to a rotating plain-text file (5 MiB per file, three backups). The first `configure_logging()` call sets the initial level and log destination; the View → Logging Level menu can change the `workbench` logger's level for the current session.

The file is `cbus-workbench.log` in the per-user log directory:

- Windows: `%LOCALAPPDATA%\CBUS Workbench\Logs`
- macOS: `~/Library/Logs/CBUS Workbench`
- Linux: `${XDG_STATE_HOME:-~/.local/state}/cbus-workbench/logs`

Use a logger named `workbench.<area>`. For detailed records, call `trace(logger, "Opening %s", name)` from `workbench.logging_config`. Pass identifying fields as `extra={"fields": {"layout_id": 12}}`; they appear as `layout_id=12` after the message. Keep sensitive values out of log messages and fields.

Top-level UI actions that need an error dialog can call `ErrorReporter.run(description, operation)` from their Qt signal connection. It logs an exception with its traceback and shows one critical dialog instead of re-raising it. At startup, `main.py` also installs the reporter as `sys.excepthook` for unexpected PySide6 callback exceptions, restoring the previous hook when the event loop exits. This process-wide hook is a last-resort reporting mechanism; after an unexpected exception, the application is not guaranteed to be in a consistent state. The reporter sends dialog requests through a Qt signal so dialogs run on the GUI thread. Validation failures and cancelled dialogs return normally and do not use this path.

## Architecture

`workbench.app_settings` owns the single `settings.yaml` in Qt's `AppDataLocation`
for the application name `CBUS Workbench`. Its YAML mapping uses display names as
layout keys and keeps TCP and serial connection fields together so switching types
does not discard the inactive endpoint. It validates before saving and uses Qt's
`QSaveFile` to replace an existing file atomically. `MainWindow` loads these settings
at startup, translates them into its existing layout fields and selects the saved
default. A missing file starts with no layouts; invalid settings are reported through
the UI error reporter without changing the file. After the event loop starts,
`MainWindow` attempts to connect each layout marked for auto-connect using the same
path as manual Connect; one failure does not stop other attempts or change the
selected default layout.

Layout connection settings live in `MainWindow` for the current session. A TCP layout
gets a `TcpConnection` when Connect is selected. Its `QTcpSocket` runs on the Qt event
loop and reports connection, disconnection and errors through signals; `MainWindow`
updates the selected layout's status from those signals. `readyRead` collects TCP bytes
until complete colon-to-semicolon GridConnect frames are available, then signals and
logs each frame at TRACE. `send` queues one complete ASCII frame with `QTcpSocket.write`
and logs it at TRACE. Changing a layout's endpoint, deleting it or closing the window
closes its socket. A serial layout gets a `SerialConnection`, which opens its configured
device path with `QSerialPort` and reports the same connection states and errors. It
uses Qt's default port settings (9600 baud, 8 data bits, no parity, one stop bit, no
flow control). Serial `readyRead` buffers bytes until complete GridConnect frames are
available, then emits and logs each frame at TRACE. Like TCP, serial `send` validates
one complete printable ASCII frame, queues it with `QSerialPort.write` and logs it at
TRACE. Both transports use the same Send GridConnect Frame dialog. Disconnecting,
changing the device path, deleting the layout or closing the window closes the port.
