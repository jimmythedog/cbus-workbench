# User guide

CBUS Workbench configures and maintains CBUS/VLCB networks. It is in early
development; layout backup restoration and backup deletion are not yet
available. See the [README](../README.md#installation-and-running) for installation
and running instructions.

## Contents

- [Layouts and connections](#layouts-and-connections)
- [Connecting and discovering nodes](#connecting-and-discovering-nodes)
- [Understanding discovery status](#understanding-discovery-status)
- [Viewing node information](#viewing-node-information)
- [Editing node variables (NVs)](#editing-node-variables-nvs)
- [Editing events and event variables (EVs)](#editing-events-and-event-variables-evs)
- [Creating backups](#creating-backups)
- [Backup descriptions and warning icons](#backup-descriptions-and-warning-icons)
- [Viewing and comparing backups](#viewing-and-comparing-backups)
- [Restoring a node backup](#restoring-a-node-backup)
- [Diagnostics and application directories](#diagnostics-and-application-directories)

## Layouts and connections

A new installation starts with no layouts. Choose **Layout → New…** to create one.
Enter a name and a logical layout, then choose the connection type:

- **TCP/IP**: enter the hub's host and port.
- **Serial**: enter the serial device path. The connection uses 9600 baud,
  8 data bits, no parity, one stop bit and no flow control.

The **CAN ID** is Workbench's transmitting identifier, from 100 to 127, defaulting
to 126. Choose an ID unique on your network. Enable **Auto-connect on startup**
to attempt this connection after the application window opens.

The logical layout identifies the stored node configuration and backup directory.
Connections can share a logical layout, but discovery is separate for each connection.
Changing a connection's logical layout switches its stored configuration and backup
directory after confirmation; existing data is not moved or deleted.

Select a layout in the **Layout** menu. **Edit…** and **Delete…** are available
only when its connection is closed. Layout changes are saved for the next session.
The first layout becomes the startup default. Choose **Layout → Set as default**
to change it. A star marks the default; the radio indicator marks the current
selection. Selecting a layout during a session does not change the default.
Renaming the default preserves that choice; deleting it chooses another layout.

## Connecting and discovering nodes

Select the layout, then choose **Layout → Connect**. Workbench automatically
looks for nodes and reads their configuration. Discovered nodes appear in the
selected layout's **Nodes** navigator; values fill in as replies arrive.
Choose **Layout → Disconnect** to close the connection.

Reconnecting starts fresh discovery. A node that does not reply may be missing
from the list. If a read fails or times out, confirmed values remain visible and
Workbench continues with other nodes. Reconnect to try discovery again.

## Understanding discovery status

The status bar shows the selected layout name, discovery status and connection
status. While disconnected, it shows only the layout name and connection status.

| Status | Meaning |
|---|---|
| Discovering… | Workbench is waiting for nodes or reading configuration, including refresh after Save. |
| Ready | All initiated reads for observed nodes succeeded or were inapplicable. |
| Incomplete | No nodes were found, or some discovery information remains unconfirmed. |

Workbench waits for a two-second response window, extended whenever a new node
appears, before settling the result. **Ready does not guarantee that every node
on the network was found**: there is no network-wide completion acknowledgement.
A late new node starts discovery again.

## Viewing node information

Select a node in **Nodes** to view its details. Confirmed information includes
node number, manufacturer, module type, CAN ID, flags, mode, firmware, CPU,
interface, supported events, NV and EV counts, and capabilities such as producer,
consumer, own-event consumption, bootloading and VLCB compatibility.
A confirmed nonzero beta build appears beside the firmware version.
Unconfirmed fields show `-`; VLCB compatibility shows Yes, No or `-`.

**Online** means the node was discovered during the current connection; Workbench
does not continually poll its liveness. Disconnected nodes show **Offline**;
connected nodes without discovery evidence show `-` for status.

## Editing node variables (NVs)

The live node's **Raw Node Variables** tab shows confirmed values as they arrive.
Unread values show `-`; confirmed zero shows `0`.

1. Wait for complete node configuration discovery on a connected FLiM node.
2. Choose **Edit** on either **Node Variables** or **Events**. Both tabs become
   editable and remain accessible in one session.
3. Enter NV values from 0 to 255. Switch tabs freely; all edits are retained.
4. Choose **Save** on either tab to apply the complete desired configuration, or
   **Cancel** to discard the entire session without writing.

Both configuration tabs become read-only during Save. Progress and the final result
appear on both tabs. Save uses the same application and verification process as
backup restoration: it compares against confirmed hardware state, accounts for
firmware changes, and verifies the complete resulting configuration. Unchanged
values remain part of the desired configuration.

If an acknowledged NV write's verification read times out, Workbench makes one
additional read without repeating the write. A matching value allows application
to continue, and the final result reports that verification required recovery.
If the additional read fails or differs, application stops and refreshes the
resulting state as described below.

Automatic NV discovery and refresh also make one additional read after a timeout,
including during Save and Restore. Workbench waits for that NV before continuing;
if the second read times out, discovery remains incomplete. These reads never
repeat a write or change the response timeout.

Applying the complete target can remove firmware-created events or reconstruct
an event to clear EVs. There is no rollback. Do not use another configuration tool
on the network during application. Failure stops further writes and refreshes the
resulting state; earlier writes may remain applied. Reconnect and compare before
retrying. A disconnect during Save reports a partial, unverified result.

Cancel is unavailable after Save begins. Disconnecting or selecting another node
before Save discards unsaved edits. Backup restoration remains available outside
editing sessions.

## Editing events and event variables (EVs)

The live node's **Events** tab shows known produced events alongside consumed
events. Expand a consumed event to see its EV values. Normal view shows only
confirmed numeric EV values, including zero.

Choosing **Edit** on either configuration tab exposes every supported EV position.
Enter values from 0 to 255. Clearing a numeric EV requests absence in the desired
configuration; entering `0` requests numeric zero. Unchanged values and event
identities are preserved alongside NV edits. **Cancel** on either tab discards
both NV and EV edits. **Save** applies them together as described above.

Unknown and confirmed-absent values can both appear blank during discovery, so
editing requires complete discovery, including confirmation of every EV position.

## Creating backups

Backups save currently discovered configuration; they do not start a fresh discovery
or change hardware. They contain confirmed data rather than local annotations.

### Node backup

Connect the layout, select a live node, open its **Backups** tab and choose **New**.
If discovery is incomplete, choose **Cancel** to wait or **Save Anyway** to keep
the available information. Enter an optional description and confirm the save.
The timestamped YAML file appears in the node's backup list.

### Layout backup

Open the layout's **Backups** tab and choose **New** while connected. This saves a
snapshot of the discovered nodes, with a layout manifest linking their node files.
Incomplete discovery requires **Cancel** or **Save Anyway**; an empty discovery is
also incomplete. Enter an optional description and confirm the save.

Completeness describes the included nodes: undiscovered hardware cannot be detected
by the backup. A failed save is reported and may leave some node files on disk.

### Backup storage

Find the **Data** directory through **Help → Application Directories…**. Files are
stored beneath it as follows:

- Node backups: `layouts/<logical-layout>/nodes/<node-number>/backups/<timestamp>.yaml`
- Layout manifests: `layouts/<logical-layout>/backups/<timestamp>.yaml`

A layout's associated node files use the same timestamp filename and appear in the
ordinary node backup lists. For file-format details, see the
[development guide](development.md#architecture).

## Backup descriptions and warning icons

Optional descriptions appear beside timestamp filenames in node and layout backup
lists. A layout description also appears for its linked node backups. Blank
descriptions are omitted from saved files.

No icon beside a filename means discovery was complete when the backup was created.
A **warning icon** means some configuration was missing or unconfirmed, such as
unread NVs or EVs, unavailable configuration counts or interrupted discovery.
Hover over the icon for an explanatory tooltip.

Incomplete backups retain successfully discovered values, but may lack information
needed to reproduce the complete configuration. Confirmed absent EVs do not by
themselves make a backup incomplete. See [Restoring a node backup](#restoring-a-node-backup)
for the risks of restoring an incomplete file.

## Viewing and comparing backups

Select a saved backup and choose **View** to inspect it. View works offline for
both node and layout backups. Saved node backups remain accessible as
**<node-number> (offline)** entries in **Nodes**, including after disconnecting or
restarting. Reconnecting replaces these saved-only entries as nodes are discovered.

Choose **Compare** while connected to compare a node backup with current discovered
values. Events are matched by node number and event number. Unknown values make
the result inconclusive rather than definite differences; complete backups
distinguish absent EVs from unread values.

For a layout backup, **View** shows each saved node's discovery status, NVs and
events. **Compare** compares its associated node files with current discovery.
Differences appear under **Node configurations**, with **Backup** and **Current**
columns. Nodes match by node number; events match by node and event number.
Unknown values and nodes present on only one side make the result inconclusive,
rather than proving a configuration difference.

**New** and **Compare** require a connected layout; a new node backup also requires
a selected live node. Node **Restore** requires a connected, discovered target.
Layout **Restore** and all backup **Delete** actions remain disabled.

## Restoring a node backup

Restoration writes to the physical node. Prefer a complete backup for the same
node number and confirm that it belongs to the connected module and firmware:
backup files do not record manufacturer or firmware identity. Wait for complete
discovery. Do not use another configuration application during restoration.

To review differences first, use **Compare** explicitly. **Restore** opens the
restoration confirmation directly.

1. Select the live node, open **Backups**, select a saved YAML backup and choose
   **Restore**. Standalone and layout-owned node backups are supported.
2. Read the confirmation and choose **Yes** to write, or **No** to cancel.
   Layout-owned backups warn that restoring one node independently may leave it
   inconsistent with other nodes. Incomplete backups warn that replacement may
   remove configuration that was not captured; continue only if you accept this.

Workbench processes numeric backup NVs in ascending NV-number order, writing only
values that differ from confirmed live values. Unknown backup NVs are skipped.
After each verified write, it rereads all higher-numbered NVs before continuing,
because firmware may reset other values. It then rereads all NVs and refreshes
events, verifying every known saved NV before writing events. Changes to earlier
NVs or incomplete reads stop restoration without automatic retries.

Events are matched by event node number and event number after rediscovery:

- First, events not listed in the backup are removed to free event-table capacity.
- Missing events are then taught with their saved numeric EV values.
- Matching events are left untouched; numeric differences update only those EVs.
- An event containing an EV confirmed absent in a complete backup is removed,
  taught again and given all its saved numeric EVs. This removes the extra EV.

Absent, unknown and omitted values are never converted to zero. In an incomplete
file, null and omitted EVs cannot prove absence and do not trigger reconstruction.
Their current values are retained unless another configuration write resets them.
Creating or reconstructing an event needs at least one saved numeric EV; a missing
empty event cannot be taught without inventing a value and is reported explicitly.
Each changed event is rediscovered and checked before proceeding.

Finally, Workbench rediscovers the entire node configuration and compares it with
the backup. **Node configuration restored and fully verified.** appears only for a
complete backup whose configuration is confirmed and matches. For an incomplete
backup, the result can confirm known values and the restored event membership,
but explicitly reports that unknown or uncaptured configuration cannot be verified
and full equivalence is not established. Unverified reads or mismatches are
reported as partial restoration. Progress and the final result appear beside the
backup buttons. NV/EV editing and raw sending are blocked on that connection.

A failure stops further writes and reports verified NV/EV writes, transmitted
event removals and removals verified by event rediscovery. Transmission alone does
not confirm removal. Earlier changes remain applied; there is no rollback. Workbench
attempts learn-mode cleanup and rediscovers the resulting configuration while the
connection remains available. After failure, check any learn-mode warning,
reconnect and **Compare** before deciding whether to retry manually.
Layout restoration remains unavailable.

## Diagnostics and application directories

**Messages / Diagnostics** shows sent and received CBUS frames, labels supported
opcodes and shows raw frames for others. Use **View** to show or hide the panel.
**View → Logging Level** changes logging detail for the current session.

For raw frame sending, connect a layout and choose
**Layout → Send GridConnect Frame…**. Enter a complete GridConnect frame. Raw
commands can change node configuration; use them only when you understand the command.

**Help → Application Directories…** shows the settings, logs and Data locations.
Settings are stored in Qt's configuration directory and logs in its state directory.
If migrating an existing `settings.yaml` from an older location, move it to the
shown configuration directory manually.
