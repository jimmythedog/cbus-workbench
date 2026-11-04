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

The project provides a `Makefile` with convenient commands for common development tasks.

| Command | Purpose |
|---|---|
| `make` | Show available commands |
| `make run` | Run the application |
| `make test` | Run the full Python test suite |
| `make lint` | Run Ruff lint checks |
| `make format` | Format Python source files |
| `make check` | Run tests, linting, formatting checks and `git diff --check` |

The Makefile automatically uses `nix-shell .shell.nix` on NixOS, ensuring tests run with Nix-provided Python and PySide6. On other platforms, tests use the uv-managed environment.

To run the full validation before committing:

```sh
make check
```

The equivalent commands can also be run individually. For example, on NixOS:

```sh
nix-shell .shell.nix --run 'python -m unittest discover -s tests'
ruff check .
ruff format --check .
git diff --check
```

On other platforms, use `uv run python -m unittest discover -s tests` for the tests.

The Makefile requires GNU Make. Windows developers can use an environment such as MSYS2 or run the underlying commands directly.

GitHub Actions continues to run its own validation commands.

## Logs

The application configures standard Python logging before constructing the Qt UI. Development runs start at TRACE; PyInstaller packaged releases start at INFO. Logs go to a rotating plain-text file (5 MiB per file, three backups). The first `configure_logging()` call sets the initial level and log destination; the View → Logging Level menu can change the `workbench` logger's level for the current session.

The file is `cbus-workbench.log` in the `logs` subdirectory of Qt's
`StateLocation`. On Linux this defaults to
`${XDG_STATE_HOME:-~/.local/state}/cbus-workbench/logs`. Help → Application
Directories shows the locations resolved on the current platform.

Use a logger named `workbench.<area>`. For detailed records, call `trace(logger, "Opening %s", name)` from `workbench.logging_config`. Pass identifying fields as `extra={"fields": {"layout_id": 12}}`; they appear as `layout_id=12` after the message. Keep sensitive values out of log messages and fields.

Top-level UI actions that need an error dialog can call `ErrorReporter.run(description, operation)` from their Qt signal connection. It logs an exception with its traceback and shows one critical dialog instead of re-raising it. At startup, `main.py` also installs the reporter as `sys.excepthook` for unexpected PySide6 callback exceptions, restoring the previous hook when the event loop exits. This process-wide hook is a last-resort reporting mechanism; after an unexpected exception, the application is not guaranteed to be in a consistent state. The reporter sends dialog requests through a Qt signal so dialogs run on the GUI thread. Validation failures and cancelled dialogs return normally and do not use this path.

## Architecture

Connection changes in `MainWindow.set_connection_state()` refresh backup actions
through `LayoutView.set_connected()`. Availability uses the connection state,
independently of discovery results. Disconnect still closes the service and clears
live identities and values. The existing node navigator then lists node numbers
with saved YAML files as “<node-number> (offline)”; these entries contain only an integer,
never a cached PNN or NodeState. Selecting one loads the ordinary backup list.
Discovery replaces that entry with a live identity after reconnection. Saved View
reads files directly; New and Compare are guarded while disconnected.

`NodeDetails` owns the node backup buttons and displays. Its plain Python
`NodeBackupWorkflow` helper handles the selected backup's dialogs, snapshots and
changes to `NodeBackups`. After a restore, one callback to `NodeDetails` refreshes
the variable and event displays; prototype layout backups still use the same `NodeBackups`
store through `LayoutView` for their demo data. Live nodes instead use
`node_backup_files` to capture confirmed `NodeState` values in the issue #44 YAML
format. `NodeDetails` retains the selected live state and logical layout;
`NodeBackupWorkflow` requests acknowledgement for incomplete discovery before
writing. Filenames provide timestamps; listing reads actual files from the Qt
Data directory. Live restore and other unfinished backup actions are disabled.

Live layout saves capture the selected view's service states with the same
`node_backup` serializer. The manifest contains only `format_version`, `complete`
and `nodeNumbers`. Each node record carries `partOfLayoutBackup: true` (standalone
records use `false`). One filename identifies the manifest and all associated node
files in their existing backup directories. The common writer accepts that filename.
This retains the prototype's relationship between a layout backup and node snapshots
without embedding or duplicating node configuration in the manifest.

No new discovery or hardware writes are triggered. Completeness describes the
included discovered nodes, not whether undiscovered hardware exists; an empty set
is incomplete. The confirmation lists incomplete node numbers.

    selected states -> node_backup for each node -> completeness check
                                                    |             |
                                                  Cancel      Save Anyway
                                                    |             |
                                                  stop      one filename
                                                                  |
                                                     write each node file
                                                        |         |
                                                      failure   all saved
                                                        |         |
                                                      report   write manifest
                                                                  |
                                                           refresh layout list

The manifest is written last so a failed node save cannot publish a successful
layout backup. Errors propagate; earlier node files remain, with no rollback.
Layout View resolves each manifest node number using the shared filename and checks
node identity and ownership. Node View shows the ownership flag; ordinary node View
and Compare use the same loader for standalone and associated files.
`LayoutBackupCompare` retains its prototype path and uses `compare_live_node()`
for matching discovered nodes in saved YAML layouts. View and Compare share the
associated-file loader, including identity and ownership checks. Differences retain
the existing node/section/event hierarchy. Incomplete saved or current values make
the result inconclusive while confirmed differences remain visible. A node seen on
only one side is also inconclusive: neither a manifest nor the current connection
proves absence elsewhere on the logical layout. Restore and Delete remain disabled.

Filesystem failures propagate to the existing UI exception reporter.

`workbench.paths` resolves Qt's application directories for `cbus-workbench`;
the display name remains `CBUS Workbench`. `workbench.app_settings` owns the
single `settings.yaml` in `AppConfigLocation`. Its YAML mapping uses display names as
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

### Agreed CBUS service design

Each connected layout will have a CBUS service between its GridConnect transport and
the UI. The service will interpret every incoming CBUS message, whether it follows a
Workbench request, another application's activity or unsolicited network traffic.
It will maintain that layout's live node state and emit Qt signals when known node,
node variable (NV) or event variable (EV) state changes. The UI will observe those
signals and initiate operations through the service; it will neither decode CBUS
opcodes nor manage protocol transactions.

```text
PySide6 UI ── commands ──► per-layout CBUS service ── outgoing frames ──► transport
PySide6 UI ◄── signals ─── per-layout CBUS service ◄── incoming frames ─── transport
                            (live node state)                         (TCP or serial)
```

Undiscovered parameter, NV, event identity and EV values remain unknown. A
matching NEVAL confirms an EV value, including zero. Seeing a write request does
not confirm that the write succeeded. Live connection state stays separate for
each layout, including layouts that share a logical-layout data directory.

QNN/PNN node discovery and read-only parameter, NV, stored-event identity and
EV value discovery are implemented. Other CBUS operations will follow
incrementally as their UI needs are defined. The service uses Qt's
existing asynchronous event loop; add a `QThread` only if processing later
proves to require it.

The service listens to one connection's frame signal, keeps PNN-confirmed node
identities in memory and emits signals only for new or changed identities. When a
layout connects, `MainWindow` creates its service using the configured PC CAN ID
(100–127) and sends one QNN. Leaving Connected detaches and clears that service;
reconnecting starts discovery with empty state. The caller must choose a CAN ID
unique on the network. Discovery is visible in the Diagnostics pane and logs.

### Node discovery lifecycle

Each new numbered PNN starts a parameter pass. A confirmed parameter 6 can
queue NV reads before that pass ends; the shared queue serialises the requests.
The parameter pass ending, including after failure, starts event discovery unless
the PNN confirms Consumer = No. In that case event progress is SKIPPED and the
stored-event count stays unknown.

```text
Connected -> CbusService(layout) -> QNN -> PNN (new numbered node)
                                        |
                  +---------------------+---------------------+
                  |                                           |
                  v                                           v
     RQNPN(0) -> PARAN(0) -> selected RQNPN/PARAN   any confirmed PARAN(6)
                  |                                   0 -> NV COMPLETE
          parameter pass ends                         >0 -> NVRD(i) -> NVANS(i)
                  |
                  +-> Consumer = No -> event SKIPPED
                  |
                  +-> Otherwise -> RQEVN -> NUMEV
                                             |
                                             +-> 0 -> COMPLETE
                                             +-> >0 -> NERD -> ENRSP
                                                              -> REVAL/NEVAL if EV count > 0
```

### Event identity enumeration

Only NUMEV matching the outstanding RQEVN confirms the stored count. NERD has
no separate completion response; ENRSP indices need not be sequential. The
service retains confirmed identities from an unfinished pass. Internal indices
can change when a node's event table is edited, so they are not saved as
configured node data.

```text
RQEVN -> NUMEV(count)
           +-> 0 -> COMPLETE
           +-> positive -> NERD (one outstanding request)
                            |
                            +-> ENRSP(new index, identity) -> store; restart timer
                            |      +-> distinct indices < count -> await more
                            |      +-> distinct indices = count -> COMPLETE;
                            |                                   consider EV reads
                            +-> ENRSP(same index + identity) -> ignore
                            +-> ENRSP(same index, different identity)
                            |      -> INCOMPLETE; keep first identity
                            +-> timeout -> INCOMPLETE; keep partial identities
```

### EV value discovery

Parameter 5 is the supported EV count per event, not necessarily the number
explicitly defined. Only a completed event enumeration can start REVAL reads,
using the internal indices confirmed by ENRSP. EV indices run from 1 through
parameter 5; missing parameter 5 stays unknown and can start reads if a
PARAN(5) later arrives. Only a matching NEVAL records a value; a missing key
means unconfirmed, zero is a confirmed value, and a present `None` means confirmed
absent. Parameter 8 bit 6 identifies VLCB compatibility and is requested during
automatic parameter discovery. For a confirmed legacy CBUS node (bit clear),
same-node CMDERR 5 while REVAL is outstanding records `None` for that EV and
advances normally. This deliberately assumes the error belongs to our outstanding
REVAL: CMDERR itself contains no event or EV index. VLCB or unknown parameter 8
retains the conservative behaviour: leave the EV unknown and mark discovery
INCOMPLETE. Timeouts and send failures also leave progress INCOMPLETE and retain
confirmed values. Backup completeness checks EV key presence, so absent EVs are
complete while unknown EVs are not; both serialize as positional YAML `null`. Only trailing confirmed-absent EVs
are omitted from the saved list; unknown positions and internal gaps remain. A backup caller can check the existing
parameter, NV, event and EV progress (COMPLETE or SKIPPED where applicable) and
the sparse mappings to identify unconfirmed data. Discovery is read-only and
live values are separate from configured node data.

```text
event enumeration COMPLETE
  +-> no stored events or parameter 5 = 0 -> EV COMPLETE; no REVAL
  +-> parameter 5 unknown -> EV NOT_STARTED; await PARAN(5)
  +-> parameter 5 > 0 -> REVAL for each confirmed event and EV index
                         matching NEVAL -> record confirmed value, advance
                         same-node CMDERR 5 -> legacy: record absent, advance
                                           -> VLCB/unknown: INCOMPLETE, advance
                         all values/absences confirmed -> EV COMPLETE
                         timeout/send failure -> EV INCOMPLETE; keep values
event enumeration INCOMPLETE -> no automatic REVAL
```

### Shared automatic request queue

Each `CbusService` has one FIFO, one outstanding request and one single-shot
`QTimer`. Timeouts and send failures abandon remaining requests of the same kind
for that node, preserve confirmed data and let other queued work proceed.
NERD keeps its slot while new ENRSP indices arrive; each one restarts the timer.
Each REVAL advances on a matching NEVAL or a same-node CMDERR 5. CMDERR 5 records
absence only for confirmed legacy CBUS nodes, as described above; otherwise it
leaves the value unknown and marks the pass incomplete.

```text
per-layout FIFO -> pop/send
                    +-> send failure -> INCOMPLETE -> next queued request
                    +-> sent -> one outstanding request + single-shot QTimer
                                  +-> matching reply -> record -> advance FIFO
                                  +-> timeout -> INCOMPLETE -> advance FIFO
                                  +-> NERD: new ENRSP -> record, restart timer;
                                  |          keep NERD outstanding
                                  +-> NERD: enough indices -> COMPLETE -> advance
                                  +-> NERD: conflict -> stop timer;
                                            INCOMPLETE -> advance
                                  +-> REVAL: matching NEVAL -> record, advance
                                  +-> REVAL: same-node CMDERR 5
                                             legacy -> record absent, advance
                                             VLCB/unknown -> INCOMPLETE, advance
```

Diagnostics observes each connection's queued and received frame signals, so it
also shows traffic from other applications. Frame summaries are decoded outside
the UI. Every received PNN frame appears in Diagnostics, while the service's
change signals still filter duplicate identities in the navigator. The navigator
shows PNN identities for each layout. Node Details reads that layout's service
state to show confirmed PARAN parameters for the selected node; unknown values
remain `-`. Each live node state also holds sparse confirmed NV values and
independent parameter, NV, event identity and EV discovery progress. A
stored-event count of `None` is unknown; zero is a confirmed empty table.
Event identities are sparse
confirmed `(event node number, event number)` pairs keyed by internal index,
including when enumeration is incomplete. Live EV values are keyed first by
that internal index and then by EV index. Supported slots start at assumed zero,
with separate EV discovery progress.
A node-state signal lets
the UI refresh from the service when state changes; switching nodes reads values
already confirmed by the service. Identity updates keep the current selection,
and ending a connection clears that layout's live entries. The selected live
node's Raw Node Variables table shows confirmed values read-only, with `-` for
unread indices when parameter 6 provides the count.
The node Events tab uses the same side-by-side widget for configured nodes and
live nodes. For live nodes, it reads `NodeState` on selection and state-update
signals. Consumed event rows use discovered identities and keep the internal
event index so each expanded EV list reads the matching values. The layout event
catalogue supplies known produced events and any available descriptions. The
display clears with the selected identity on disconnect; it keeps no separate
discovery model.
