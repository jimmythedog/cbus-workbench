# Development guide

This document records established development decisions and, as the application takes shape, will explain its architecture and important execution flows. It is not an inventory of source files. For application operating instructions, see
the [user guide](user-guide.md); installation and running instructions start in the
[README](../README.md#installation-and-running).

## Running from source

These instructions are for developers. End-user releases are intended to be packaged as OS-specific installers that bundle Python and application dependencies; users should not need to install Python or uv.

### Standard development setup (Windows, macOS and conventional Linux)

Follow the [source installation instructions](../README.md#installation-and-running)
to install locked dependencies and run the application. The exact supported Python
versions are defined in `pyproject.toml`.

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

### Experimental hardware response timeout

Set `CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS` before launching to override the default
2,000 ms response timeout, for example:

```sh
CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS=4000 python main.py
```

This temporary hardware-testing setting is read once per process and shared by
NV writes, EV writes and the CBUS service's request and discovery response timers.
It must be a positive integer in milliseconds, at most 2147483647 (Qt's timer
limit). Invalid configuration stops startup with a clear error in stderr and the
application log. Startup logs the effective timeout, including the default.
Restart to change it; unset it to restore the default. It changes only response
windows, with no changes to matching, verification, concurrency, retries or pacing.

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
Data directory. Live node restore uses the verified writers as described below;
backup deletion and layout restore remain disabled.

Live layout saves capture the selected view's service states with the same
`node_backup` serializer. The manifest contains `format_version`, `complete`,
`nodeNumbers` and an optional `description` (never copied to linked node files).
Each node record carries `partOfLayoutBackup: true` (standalone
records use `false`). One filename identifies the manifest and all associated node
files in their existing backup directories. The common writer accepts that filename.
This retains the prototype's relationship between a layout backup and node snapshots
without embedding or duplicating node configuration in the manifest.

No new discovery or hardware writes are triggered. Completeness describes the
included discovered nodes, not whether undiscovered hardware exists; an empty set
is incomplete. The confirmation lists incomplete node numbers. After acknowledgement
(or directly for complete discovery), an optional description dialog allows saving
or cancelling before any files are written.

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
Node and layout Compare use the Qt-independent `compare_configurations()` for
matching node configurations. It accepts two existing backup-format dictionaries
and returns rows with explicit confirmed, absent, event-absent and unknown values,
plus equal/different/unknown outcomes and an uncertainty flag. Event identities
are `(node number, event number)`, never table slots. The live adapter supplies
completed-enumeration evidence and sparse EV mappings, preserving confirmed
absence even when the serialized snapshot is incomplete. No YAML fields change.

    backup dictionary + current snapshot + live confirmation evidence
                         -> structured comparison
                              +-> existing tree (caller-supplied headings)
                              +-> compare_live_node() legacy tuples -> Restore

The tree shows confirmed differences, including numeric EVs under one-sided
events; equal and unknown rows remain available in the result, with uncertainty
shown as a summary. Event absence renders as `—`; confirmed EV absence within an
existing event renders as `Absent`. `compare_live_node()` retains its existing
confirmed-difference tuples and inconclusive flag for restore verification,
without adding one-sided EV detail tuples. Prototype comparisons remain unchanged.

View and Compare share the associated-file loader, including identity and ownership
checks. Differences retain the existing node/section/event hierarchy. Incomplete saved or current values make
the result inconclusive while confirmed differences remain visible. A node seen on
only one side is also inconclusive: neither a manifest nor the current connection
proves absence elsewhere on the logical layout. Layout Restore and Delete remain disabled.

Incomplete records use `complete: false` and positional YAML `null` for
unconfirmed known values. Descriptions are omitted when blank. Live snapshots do
not include local annotations; discovery completeness cannot establish that all
physical nodes were found.

Filesystem failures propagate to the existing UI exception reporter.

### Restoring a live node

`NodeBackupWorkflow` loads the selected YAML through the existing validator and
requests explicit confirmation. Comparison is a separate **Compare** action. It
rechecks the connection and target after the confirmation dialog. `NodeRestore`,
owned by the connection's service, coordinates the existing `NvWrite` and `EvWrite`
operations without implementing
another protocol writer. It reserves service writes until the final result;
`NodeDetails` displays progress and uses the existing editing signal to lock node
selection. Raw sending is also guarded during restore.

    file + complete target -> confirm (extra warning if incomplete)
      -> visit saved numeric NVs in ascending order
           matching confirmed live value -> skip
           different -> NvWrite(one NV), acknowledgement + readback
                     -> reread all higher NVs -> continue from next saved NV
      -> full NV reread + event/EV refresh -> verify all known saved NVs
           mismatch / incomplete -> stop before event restoration
      -> remove extra events by identity (EVULN), freeing event-table capacity
      -> process backed-up identities (NN, EN)
           missing -> EVLRN numeric EVs
           matching -> no operation
           numeric differences -> EVLRN changed EVs
           confirmed extra EV -> EVULN -> learn exit -> event/EV rediscovery
             absence confirmed -> re-enter learn -> EVLRN all saved numeric EVs
             present / incomplete discovery -> stop without teaching
         each operation -> existing learn exit -> event/EV refresh -> verify
      -> full parameter/NV/event/EV rediscovery -> compare known backup data
           complete backup + no uncertainty/differences -> full success
           incomplete + known data verified -> success with explicit uncertainty
           otherwise -> partial result with write/removal counts
      failure -> stop writes, existing learn cleanup -> rediscover -> partial result
      disconnect -> existing writer cleanup -> unverified partial result

Restore compares each saved numeric NV with confirmed live state and writes only
when it differs. Unknown saved NVs are skipped; unknown live values or incomplete
discovery stop restoration. After each verified write, the shared discovery queue
rereads all higher NVs (including indices missing from an incomplete backup) before
the next comparison. Intermediate refreshes do not reread events. Once the scan
ends, a full NV reread and event/EV refresh verify the saved NVs and obtain current
event identities before any event replacement.

Only a verification NVANS timeout after WRACK permits one additional NVRD,
retaining writer ownership and the unverified marker. Matching readback clears
the marker and follows the same higher-NV refresh path; the coordinator retains
a recovery count for the final result. A second timeout or any other write failure
uses the existing stop-and-rediscover path. NVSET is never retried.

    NVSET -> WRACK -> NVRD -> timeout -> one NVRD
                                         matching -> higher-NV refresh -> continue
                                         failure  -> stop -> full rediscovery

Each saved index is visited once. Firmware may also change earlier NVs: the full
verification detects these differences and fails without retry or rollback. The
ascending order is a generic policy, not an assumption about firmware dependencies.
The final full configuration discovery after event restoration remains required;
EV teaching that changes an NV cannot produce a successful result.

TRACE records comparisons, refresh ranges, verified write counts and failures.
Editor Save and backup Restore both continue through event reconciliation and
final verification; neither has a separate application mode.

`node_restore_events` plans each backed-up event from the latest post-NV or
post-write discovery. It stops
comparing an event when confirmed absence requires reconstruction, discarding
partial edits in favour of replaying all its numeric EVs. Extras are collected
from post-NV discovery and removed first, so a full event table can accept missing
backed-up events. Each removal is verified before processing backed-up events.
`EvWrite` accepts a restore-owned EVULN before any replacement teaching. EVULN
has no specified acknowledgement: transmission starts no WRACK wait and is counted
separately from verified removal. The writer leaves learn mode and reuses event/EV
discovery without rereading NVs. Only complete discovery showing the identity
absent verifies removal. A retained identity, incomplete discovery, send failure
or interrupted verification stops further teaching. For reconstruction the same
writer retains its pending EVs and connection ownership across discovery, then
re-enters learn mode after absence is confirmed. Disconnect reports transmitted
and verified removals separately; a late reply cannot resume reconstruction.

EVLRN keeps its existing WRACK/error/timeout and learn-mode cleanup paths. It teaches a
missing identity using a saved nonzero EV first: some nodes acknowledge a zero
EVLRN without creating the event. WRACK followed by REQEV/EVANS verifies that
first write before the remaining saved EVs, including zeros, are taught. Existing
events retain EV-index ordering unless they must be unlearned and reconstructed.
A missing or reconstructed event with no nonzero saved EV is reported as
unreconstructable before removing it; no value is invented. No
slot is invented for new events; rediscovery obtains their current slots. The
coordinator checks each event's known values (or removal) after refresh, then
performs the final full-node comparison.

Protocol: CBUS Guide 6b §7.2.7 and VLCB Opcode §3.5.14/§3.7.8 specify EVULN and
EVLRN. EVULN removes all EVs; there is no individual EV removal command. EVLRN
requires an EV index from 1 through capacity, so an empty event cannot be taught
without inventing an EV. Such an event is reported before removing it or teaching
an invented value.

Incomplete files require explicit destructive-restore confirmation. The YAML
format cannot distinguish absent from unread EV nulls within an incomplete file;
nulls and trailing omissions therefore remain unknown and never trigger unlearn.
Complete-file nulls/omissions prove absence. Final success for an incomplete file
requires complete target discovery, matching numeric backup data and matching
restored event membership, with a separate message denying full equivalence.
The ordinary Compare UI remains inconclusive for incomplete files. Backups record
only the target node number, so module/firmware provenance remains an explicit
operator confirmation rather than an inferred compatibility guarantee.

`rediscover_node()` clears the node's configuration and reuses automatic discovery,
retaining its PNN identity/CAN ID. Completion is emitted after the request queue
has exhausted follow-on work, including failures. During a failure refresh,
matching NVRD replies can reveal an unverified NV's physical value without clearing
the failed-write marker that requires reconnecting before another application.
The coordinator advances through a single-shot Qt timer so writer completion
callbacks finish their queue cleanup before the next operation begins. TRACE
records restore stages, target, write counts, failure reasons and final differences.

Failed editor Save and backup Restore meet in `NodeDetails.finish_restore()`.
`NodeFailureReport` retains a copy of the coordinator's original backup dictionary
before editor cleanup, and uses `compare_live_configuration()` with the latest
live state. The shared `BackupCompare` tree hides equal rows; operation errors
remain separate text. After transport loss cached values are labelled unknown
with their last-confirmed value, including formerly matching rows.

The dialog only calls an optional action. Its owning report keeps Retry tied to
the same service, target identity and configuration operation. Existing writer
safety locks still require reconnecting after uncertain transactions; a report
from the old connection cannot retry on a replacement service. Otherwise:

```text
Retry -> connection/identity/ownership/safety checks
      -> full node rediscovery (no writes)
      -> repeat checks after discovery releases the wire
      -> NodeRestore.begin(original requested dictionary)
      -> existing reconciliation/writers -> same updated comparison dialog
```

Retry is disabled during this attempt and after verified success. Another
configuration application invalidates older reports. Existing service/connection
signals update availability without polling. Closing or replacing a report
disconnects its observers and cancels the deferred write handoff. Read-only
rediscovery may finish, but cannot start a Retry for a closed report; an already
active writer retains responsibility for finishing protocol cleanup. There is no
automatic retry, rollback, independent write path or layout-level retry.

### Application settings and connections

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

Each connected layout has a CBUS service between its GridConnect transport and
the UI. The service interprets supported incoming CBUS messages, whether they follow a
Workbench request, another application's activity or unsolicited network traffic.
It maintains that layout's live node state and emits Qt signals when known node,
node variable (NV) or event variable (EV) state changes. The UI observes those
signals and initiates operations through the service; it neither decodes CBUS
opcodes nor manages protocol transactions.

```text
PySide6 UI ── commands ──► per-layout CBUS service ── outgoing frames ──► transport
PySide6 UI ◄── signals ─── per-layout CBUS service ◄── incoming frames ─── transport
                            (live node state)                         (TCP or serial)
```

Undiscovered parameter, NV, event identity and EV values remain unknown. A
matching NEVAL confirms an EV value, including zero. Seeing a write request does
not confirm that the write succeeded. Live connection state stays separate for
each layout, including layouts that share a logical-layout data directory.

QNN/PNN node discovery, parameter, NV, stored-event identity and
EV value discovery, and verified NV writes are implemented. Other CBUS operations will follow
incrementally as their UI needs are defined. The service uses Qt's
existing asynchronous event loop; add a `QThread` only if processing later
proves to require it.

The service listens to one connection's frame signal, keeps PNN-confirmed node
identities in memory and emits signals only for new or changed identities. When a
layout connects, `MainWindow` creates its service using the configured PC CAN ID
(100–127) and sends one QNN. Leaving Connected detaches and clears that service;
reconnecting starts discovery with empty state. The caller must choose a CAN ID
unique on the network. Discovery is visible in the status bar, Diagnostics and logs.

The service emits `discovery_status_changed`; the window reads the selected
connection's service, independently of its logical layout. Two single-shot Qt
timers provide a QNN response boundary and defer status aggregation until reply
handlers finish queuing dependent work; neither timer polls.

    QNN -> 2-second window (restart for each newly observed node)
        -> parameter / NV / event / EV requests and reply-triggered phases
        -> window expired + no pending requests or Save/refresh
           -> all node phases COMPLETE/SKIPPED: ready
           -> missing/failed phases or no nodes: incomplete

The window is a practical quiet-period boundary, not proof of complete network
enumeration: QNN is broadcast with no global final acknowledgement. A late new
PNN reopens discovery. Queue emptiness alone cannot imply success; unknown NV
count or EV capacity leaves the corresponding phase unconfirmed. Disconnect
stops the timers, and reconnect creates a fresh service. Post-Save rediscovery
uses the same status and existing progress state.

### Node discovery lifecycle

Live editing uses the existing backup dictionary directly. `NodeDetails` captures
`original_configuration = node_backup(state)` only after complete discovery and
holds a deep copy as `desired_configuration`. The NV widgets edit its `nvs` list;
`NodeEvents` edits its event records by stable event identity. Clearing an EV
stores absence (`None`); trailing absences are trimmed as in `node_backup()`.
Both tabs' existing buttons control the same session. Live discovery updates do
not replace the editable copy, and Cancel or disconnect discards it.

```text
complete discovery -> Edit on either tab -> original + desired copy
                                           | NV tab -> desired["nvs"]
                                           | Events -> desired["events"]
                                           + Cancel on either tab -> discard
                                           + Save on either tab
                                               -> NodeRestore.begin(node, desired)
                                               -> both editors locked
                                               -> writes + rediscovery + verification
                                               -> one final result on both tabs
                                               -> display confirmed state
```

Save submits the same complete dictionary as a loaded YAML backup directly to
`NodeRestore.begin()`; the reconciliation algorithm does not distinguish its
origin. `NodeDetails` holds its saving flag until `restore.finished`, so writer
completion and intermediate discovery cannot unlock the editors. Progress and
final results are mirrored on both tabs. A validation rejection preserves edits;
application completion (including failure) replaces them with confirmed state.
The editor observes only the coordinator's completion. `NvWrite.write_finished`
and `discovery_finished`, and `EvWrite.finished`, report transaction results to
the coordinator, never to the editor. Disconnect therefore produces one final
application result even though writer cleanup may finish afterwards.

`CbusService.write_nvs()` and `write_evs()` validate coordinator-owned transaction
data and pass it to the verified writers. They perform no independent comparison:
NV reconciliation and event planning in `NodeRestore` determine the writes from
confirmed hardware state. There is no NV-only Save mode or ordinary EV Save path.

The Developer's Guide 6b teaching/readback sections define the wire sequence;
no learn mode is needed. WRACK and CMDERR carry no NV index or transaction ID.
Serialisation prevents ambiguity between Workbench's own requests; another tool
must not write the same node concurrently. Each reply uses the shared response
timeout. Writes are never retried or rolled back; only the bounded NV read
recovery described above is automatic. Failed writes retain their
uncertainty markers: failure rediscovery can reveal physical values without
allowing another Save before reconnecting.

Final NV discovery clears old event slots and EVs, then uses the existing
RQEVN, NERD/ENRSP and REVAL/NEVAL discovery. Work for other nodes is preserved.
Zero events completes without NERD or EV reads. Success requires matching desired
NVs and complete NV/event/EV discovery (or non-consumer event skips). Confirmed
zero EVs, confirmed absences and unread values retain their existing meanings.
Detailed logs record application stages, comparisons, verified writes and failures.

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
`QTimer`. An automatic NV read timeout sends one additional NVRD for the same
node/index, retaining the outstanding request and using the same timeout. Only
a matching NVANS records a value and advances the queue; unrelated or duplicate
replies are ignored. The allowance resets for each newly sent request, including
a new discovery pass. NVANS has no transaction ID, so a delayed first reply can
satisfy the recovery read. No NVSET is sent.

A second NV timeout, other request timeouts and send failures abandon remaining
requests of the same kind for that node, preserve confirmed data and let other
queued work proceed. Closing the service stops the timer and clears ownership.
NERD keeps its slot while new ENRSP indices arrive; each one restarts the timer.
Each REVAL advances on a matching NEVAL or a same-node CMDERR 5. CMDERR 5 records
absence only for confirmed legacy CBUS nodes, as described above; otherwise it
leaves the value unknown and marks the pass incomplete.

```text
per-layout FIFO -> pop/send
                    +-> send failure -> INCOMPLETE -> next queued request
                    +-> sent -> one outstanding request + single-shot QTimer
                                  +-> matching reply -> record -> advance FIFO
                                  +-> first NV timeout -> same NVRD, keep owner
                                  |     match -> record, advance FIFO
                                  |     timeout/send failure -> INCOMPLETE, advance
                                  +-> other timeout -> INCOMPLETE -> advance FIFO
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
node's Raw Node Variables table shows confirmed values, with `-` for
unread indices when parameter 6 provides the count. Edit becomes available after
complete node configuration discovery while the connection is active.
The node Events tab uses the same side-by-side widget for configured nodes and
live nodes. For live nodes, it reads `NodeState` on selection and state-update
signals. Consumed event rows and editor working copies use stable event identities;
internal table indices are resolved from current discovery only. Expanded rows
remain associated with their event even when rediscovery changes its index. The layout event
catalogue supplies known produced events and any available descriptions. The
display clears with the selected identity on disconnect; it keeps no separate
discovery model.


### Verified EV writing

The editor updates the shared desired configuration described above; it does not
call `CbusService.write_evs()` directly. The coordinator uses that transaction API
with `(event NN, event number, EV index)` keys. Live nodes use
raw EV rows; the configured-node MDF form remains prototype data, not a live MDF
mapping. No event indices are persisted.

`EvWrite` owns the connection after the current automatic request completes,
excluding other writes and automatic discovery until teaching and cleanup finish.
NNLRN and NNULN have no acknowledgement. Parameter 8 bit 5 is not a universal
CBUS requirement: Guide 6b's teaching sequence does not require it, and Guide
6c §7.2.3 / §7.2.8.4 still describes it as proposed. CBUS 5.0 Rev A1 likewise
specifies no response to NNLRN/NNULN. VLCB Event Teach §14.1 specifies the learn
flag as service data; Minimum Node §9 specifies bit 6 to advertise VLCB.

After NNLRN, the writer queries parameter 8 only if discovery has confirmed that
parameter. A set bit 5 establishes reliable reporting for this Save. A confirmed
VLCB node or a CBUS node already observed with the bit set must confirm entry;
a clear bit then stops teaching. For other CBUS nodes, a clear bit cannot
distinguish normal mode from an unimplemented flag, so the standard EVLRN /
WRACK / REQEV / EVANS sequence is used. If parameter 8 is unavailable, the
writer uses that sequence directly. A failed flags query remains a failure;
there is no timeout/error fallback. Sending NNLRN never establishes entry or
write success. EVLRN uses the event identity, not the consumer node number;
WRACK/CMDERR identify the consumer. REQEV/EVANS verify the
same event identity in learn mode, avoiding stale event-table indices. Its source
CAN ID must match current discovery. VLCB Opcode specification §3.7.9 defines
EVANS NN as the event's NN. Legacy
[CBUSlib `doReqev()`](https://github.com/MERG-DEV/CBUSlib/blob/bec37f9d634b31668d2d71b2615bf7e8b566e0ed/FliM.c#L892)
instead sends EVANS through `cbusSendOpcMyNN()`, replacing NN with the consumer's
own number. For a requested short event (NN=0), Workbench accepts either zero or
that consumer's NN, while still matching CAN ID, event number and EV index
exactly. Long events retain exact event-NN matching; arbitrary NN values are
never accepted.
VLCB adds GRSP alongside WRACK/CMDERR; those duplicate responses are not needed
for this sequence. REVAL is not required for write verification.

```text
Coordinator -> validate planned EV transaction -> wait for outstanding discovery
  -> NNLRN -> known parameter 8? RQNPN(8)
       reliable flag (VLCB or observed set) -> require learn bit set
       legacy clear flag / no parameter 8 -> no mode conclusion; standard teaching
  -> EVLRN(identity, EV, value) -> WRACK(consumer)
  -> REQEV(identity, EV) -> EVANS(identity, EV, value, matching CAN ID)
       mismatch / CMDERR / timeout / send error -> stop remaining changes
       match -> record confirmed value -> repeat for next changed EV
  -> NNULN (on success and failure)
       reliable flag -> RQNPN(8): require learn bit clear
                       failure -> report uncertainty; require reconnect
       no reliable flag -> record lack of exit confirmation in TRACE
       earlier failure -> report verified count and failure; require reconnect
       all verified -> clear old slots -> RQEVN / NERD / existing EV discovery
                         complete -> transaction finished; coordinator verifies step
                         incomplete -> transaction failure; coordinator stops writes
  -> coordinator -> final full-node discovery and verification -> application result
```

The shared queue resumes after exit handling. A failed transaction blocks further
writes on that connection because physical results may be uncertain. Successful
teaching with no flag support remains usable after refresh; reconnecting cannot
add a reporting capability that the protocol does not require. Writer completion
is a transaction result; only the coordinator's final verification establishes
application success.
Before attempting an EV write, its cached value is removed: a missing key means
unknown, so Compare and backups cannot present the pre-write value as confirmed
after a failed Save. Matching readback restores the confirmed value; untouched
EVs and earlier verified writes remain available.
NNULN is always attempted, and no clear legacy bit or missing reply is presented
as proof of exit. Requested
Disconnect waits for bounded cleanup before closing the transport. Unexpected
transport loss and application shutdown attempt NNULN but cannot confirm exit;
no successful outcome is inferred from a queued frame. A WRACK from another node
while teaching stops the Save and sends NNULN to both nodes; the operator must
check both configurations. Separate configuration applications must not teach
simultaneously. TRACE includes stage, node, event identity, values, replies and
failure/cleanup outcomes; frame traffic remains in Diagnostics.

The existing event refresh uses REVAL and may be incomplete on VLCB nodes that
reject it. This is reported as saved changes with incomplete refresh, never full
success. No compatibility fallback or second discovery system is introduced.
For the manual test sequence, see the [EV hardware check](ev-hardware-check.md).

Protocol references: [CBUS Guide 6c and CBUS 5.0 Rev A1](https://github.com/cbus-traincontrol/cbus-traincontrol.github.io),
[MERG Developer’s Guide 6b, §7.2.7 and opcode definitions](https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf),
[VLCB Event Teach and Opcode specifications](https://github.com/Versatile-LCB/VLCB-documents).
