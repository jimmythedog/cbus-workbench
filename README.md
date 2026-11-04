# CBUS Workbench

A cross-platform desktop application for configuring and maintaining CBUS/VLCB networks.

## Status

Early development. TCP/IP layouts can connect to a configured hub and show their
connection status. Complete incoming GridConnect frames are logged at TRACE. For a
connected TCP or serial layout, Layout → Send GridConnect Frame… allows raw frames to
be sent. Serial layouts use their configured device path. At startup, saved layouts
are loaded from the application settings file; a new installation starts empty.
Layouts with Auto-connect on startup enabled attempt to connect after the window opens.
On connection, Workbench sends QNN once and shows discovered PNN node identities
in the selected layout's Nodes navigator and Messages / Diagnostics. Selecting a
node shows its confirmed number, manufacturer, module type, flags, mode, producer
and consumer capabilities, own-event consumption, bootloading support, firmware,
CPU name, interface, events supported, event variables and node variables. A
confirmed nonzero beta build is shown beside the firmware version. Unconfirmed
fields show `-`. VLCB compatibility is shown as Yes/No from confirmed parameter 8,
or `-` when unavailable. Workbench requests one automatic parameter at a time per
connection, starting with each node's parameter count. Matching replies advance
a FIFO queue; a missing reply times out after two seconds, skips that node's
remaining automatic requests and lets other nodes continue. Reconnecting starts
fresh discovery state. Node Details shows the CAN ID confirmed by a received PNN
frame and Online for a discovered node while connected. Disconnected nodes show
Offline; connected nodes without discovery evidence show `-` for status. Online
reflects discovery in the current connection, without ongoing liveness polling.

The status bar shows the selected connection's layout name first, followed by
“Discovering…”, “Ready” or “Incomplete”, then the connection status, with separators
between fields. This includes rediscovery after Save. When disconnected, only
the layout name and connection status appear.
Ready means all initiated reads for observed nodes succeeded (or were skipped as
inapplicable), after a two-second QNN response window extended by each new node.
QNN has no global completion acknowledgement: ready does not guarantee every
possible node was found. Late new nodes reopen discovery; no nodes found or
unconfirmed discovery phases settle to incomplete.
After parameter 6 confirms an NV count, Workbench reads those NVs in the
background through the same request queue. The selected live node's Raw Node
Variables tab shows confirmed values as they arrive. Unread values show `-`;
confirmed zero shows `0`. Once all NVs have been discovered, choose Edit to
change values (0–255), then Save to write only changed NVs to the physical node.
Each write waits for acknowledgement and matching readback before its confirmed
value changes. Cancel discards edits without sending writes. Save stops at the
first rejection, timeout or readback mismatch and reports how many NVs were
verified; earlier verified writes remain applied. A failed Save may have changed
hardware: reconnect to rediscover before retrying. Disconnect discards unsaved
edits and reports any interrupted Save. Editing requires an active connection.
After all changed NVs are verified, Workbench rereads every NV, then rediscovers
stored events and their EV values to display firmware-generated changes.
“Saving changes…” remains visible until refresh finishes. If refresh is incomplete,
Workbench reports that changes were saved but some values could not be refreshed.
The selected live node's Events tab shows known produced events alongside
consumed events. Expand a consumed event to see its EV values. Discovered events
and EVs update as replies arrive. Normal view shows only confirmed EV values,
including zero. Edit exposes every position up to the confirmed parameter 5
capacity. Absent and unread values display as blank cells; blank means unchanged,
not zero. Entering zero explicitly assigns zero. The underlying distinction
between absent and unread is preserved. For confirmed legacy CBUS nodes, a same-node CMDERR 5 during
an outstanding EV read is treated as an absent EV, assuming the error belongs to
that request. Absent EVs save as `null`, but do not make a
backup incomplete. Trailing confirmed-absent EVs are omitted from saved lists;
internal gaps and unknown positions are preserved. VLCB or unidentified nodes retain unknown EVs after CMDERR 5.
Choose Edit / Save / Cancel to change live EVs (0–255). Only explicitly changed
values are sent; Cancel sends nothing. Save requires a connected, discovered
FLiM consumer with confirmed event identities, EV capacity and CAN ID.
Workbench requests learn mode, waits for each write acknowledgement and verifies
each EV by event identity before recording it. Learn-mode flags are checked for
VLCB nodes and CBUS nodes that report the flag set. Legacy CBUS nodes need not
report this flag: their writes are still verified. After the exit command is sent
and rediscovery completes, Workbench reports “Changes saved successfully.”
Exit confirmation details remain in Diagnostics and TRACE logs.
Events and EVs are rediscovered before the final Save result. The existing discovery
uses REVAL; nodes rejecting it can verify writes using REQEV but report an
incomplete refresh. Failures stop remaining writes and attempt learn-mode exit;
partial success and uncertain exit are reported inline. Check any uncertain node
state, then reconnect to rediscover before retrying. Requested disconnects allow
a bounded cleanup attempt; an unexpected connection loss may prevent exit.
See [the EV hardware check](docs/ev-hardware-check.md) for the manual test sequence.
The live node's Backups tab saves discovered configuration as YAML and lists saved
files. Incomplete discovery requires Cancel / Save Anyway; partial files contain
`complete: false` and `null` for unconfirmed known positions. Files are stored under
Data → `layouts/<logical-layout>/nodes/<node-number>/backups/<timestamp>.yaml`.
Select a saved backup in the live node’s Backups tab to View its configuration or
Compare it with the current discovered values. Comparisons identify events by
node number and event number. Unknown values make the result inconclusive; they
are not reported as definite differences. Complete backups distinguish absent EVs
from unread values.

Saved node backups remain accessible through entries labelled “<node-number> (offline)” in
the Nodes list, including after disconnecting or restarting. View works offline for
both node and layout backups. New and Compare require a connected layout; New
node backup also requires a selected live node. Restore and Delete are disabled.
Reconnecting replaces saved-only entries as nodes are discovered again.

The layout’s Backups tab lists saved manifests under
Data → `layouts/<logical-layout>/backups/<timestamp>.yaml`. Each manifest lists
its discovered node numbers and overall completeness. Associated node backups use
the same filename under `layouts/<logical-layout>/nodes/<node-number>/backups/`
and appear in the ordinary node Backups list, with View and Compare available.
Node YAML includes `partOfLayoutBackup: true` for these associated backups and
`false` for standalone node backups.
Select a saved layout manifest and choose Compare to compare its associated node
files with current discovery. Differences appear under Node configurations with
Backup and Current columns. Nodes match by node number and events by node/event
number. Unknown values and nodes seen on only one side make the comparison
inconclusive; they are not reported as definite differences.
View shows each saved node’s discovery status, NVs and events. Incomplete discovery
requires Cancel / Save Anyway; an empty discovery is also marked incomplete.
These snapshots contain confirmed discovery data only, without annotations.
Completeness describes the included nodes; undiscovered hardware cannot be detected
by the backup. Node files are written first and the manifest last. A failed save is
reported and may leave node files on disk. Layout restore and deletion are unavailable.

Find the Data directory in Help → Application Directories. Live backup restore is
not implemented.
Messages / Diagnostics also shows sent and received CBUS frames, including parameter
requests and replies. It labels supported opcodes and shows raw frames for others.
Layout → New, Edit and Delete save changes to that file. The first layout is the
default on startup; renaming it preserves that choice, and deleting it chooses
another layout. Selecting a layout during a session does not change the default.
Layout → Set as default saves the selected layout as the startup choice. A star
marks the default in the Layout menu; the radio indicator marks the selection.
Edit and Delete are available only when that layout's connection is closed.
Each layout's connection settings include a transmitting CAN ID from 100 to 127,
defaulting to 126 for new and existing layouts.
Changing a layout's logical layout switches its stored node configuration and
backup directory after confirmation; existing data is not moved or deleted.

## Development

CBUS Workbench will be developed using Python and PySide6 (Qt).

Development follows an outside-in approach, starting with the user interface before implementing CBUS communications.

See [Requirements](REQUIREMENTS.md) for the intended capabilities and [Development Guidelines](AGENTS.md) for the project's development principles.

Application directories are available under **Help → Application Directories…**.
Settings are stored in Qt's configuration directory; logs are in its state
directory. Move an existing `settings.yaml` to the configuration directory manually.
