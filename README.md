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
fields show `-`. Workbench requests one automatic parameter at a time per
connection, starting with each node's parameter count. Matching replies advance
a FIFO queue; a missing reply times out after two seconds, skips that node's
remaining automatic requests and lets other nodes continue. Reconnecting starts
fresh discovery state.
After parameter 6 confirms an NV count, Workbench reads those NVs in the
background through the same request queue. The selected live node's Raw Node
Variables tab shows confirmed values as they arrive. Unread values show `-`;
confirmed zero shows `0`. Live values are read-only.
The selected live node's Events tab shows known produced events alongside
consumed events. Expand a consumed event to see its EV values. Discovered events
and EVs update as replies arrive; an unknown EV shows `-`. Displayed zero EVs
may be assumed defaults where no reply was received. Hide zero EVs filters the
display without changing stored values. Live events are read-only.
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
