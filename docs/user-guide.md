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
- [Observed events](#observed-events)
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

The summary to the right of **Nodes | Events | Backups** shows the selected
layout name and configured host/port or serial device, plus CAN ID. Hover over
it to read the full summary when space is limited.

Select a layout in the **Layout** menu. **Edit…** opens Layout Settings.
**Node polling (seconds)** sets this connection's reachability interval from 0 to
300 seconds (default 10); zero disables periodic polling. Changes apply when
you save, without reconnecting, and are saved for the next session. While a
connection is active, only the polling interval is editable. **Delete…** and
changes to connection settings require the connection to be closed.
The first layout becomes the startup default. Choose **Layout → Set as default**
to change it. A star marks the default; the radio indicator marks the current
selection. Selecting a layout during a session does not change the default.
Renaming the default preserves that choice; deleting it chooses another layout.

## Connecting and discovering nodes

Select the layout, then choose **Layout → Connect**. Workbench automatically
looks for nodes and reads their configuration. Discovered nodes appear in the
selected layout's **Nodes** navigator; values fill in as replies arrive.
Choose **Layout → Disconnect** to close the connection.

Known nodes remain in the navigator and start Offline. Normal discovery marks
responding nodes Online. While connected, Workbench checks known nodes roughly
at the configured interval (default 10 seconds), deferring checks during
discovery, editing and restore.
One failed check marks Offline; a successful check marks Online again.
Disconnect marks every node Offline. Status is runtime-only and is not saved.

If a configuration read fails or times out, confirmed values remain visible and
Workbench continues with other nodes. Reconnect to try discovery again.
Online status does not replace Restore's fresh pre-write safety checks.

## Observed events

The layout **Events** tab lists distinct ON/OFF event identities received while
connected. Events are shown as `nodeNumber:eventNumber`; short events use node
number zero. New identities are saved immediately and appear again after restarting
Workbench. Repeated sightings do not add rows or rewrite the saved catalogue.
Double-click an event's **Description** cell in this view or in **Node → Produced
Events** to open the same small **Save**/**Cancel** editor. Both views edit one
layout-level event name; saving from either immediately updates the other.
Editing works while disconnected. Names are saved separately from the observed
identities, so removing an observation does not delete its name.

A node's **Produced Events** tab filters the same list by node number, including
when viewing a saved offline node. Connections using the same logical layout share
observations; different logical layouts keep separate lists. Disconnecting and
reconnecting preserves the catalogue.

## Editing node annotations

Double-click the read-only **Name** label on **Node Details** to open a small
node-name editor. Choose **Save** to update the label and navigator immediately,
or **Cancel** to discard the draft. This also works for offline nodes. Node Details
has no separate annotation action buttons or MDF token list.

To edit a token name, double-click its existing MDF label in **Node Variables**
or an expanded **Consumed Events** form. Group headings and NV page titles also
support double-click; right-click a displayed selection name to edit its tokens.
A small dialog shows the complete label as fixed context and one text field per
user-editable token in that label. Only those token values can change. Choose
**Save** to persist them and refresh every occurrence, or **Cancel** to discard
the draft. Surrounding label text and automatic structural placeholders are not
editable. A blank value removes the override and uses the MDF default shown in
the field. Only overrides are stored; changing an MDF can change its defaults.

Saved-only nodes use their last confirmed parameters to locate the MDF and show
read-only NV forms for offline label editing. Without a matching MDF, overrides
remain saved but have no labels from which to edit them. Offline EV labels require
an existing presentation; reconnect to inspect EV forms that are not available.
Token editing is unavailable during NV/EV configuration editing or hardware writes.

On **Consumed Events**, double-click an event's **Description** cell to open a
small editor with **Save** and **Cancel**. Saving immediately updates that cell;
blank text clears the annotation. This works offline and never writes to hardware.
The annotation belongs to this consuming node: two nodes can name the same event differently.
They are separate from the layout's produced/observed event name. Offline entries
come from saved names and the latest node backup when available.

All annotation editing works offline, sends no CBUS traffic, and survives
restart, rediscovery and reconnect. NV/EV **Edit** and **Save** still require a
connected node and apply hardware configuration separately.

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

Select a node in **Nodes** to view its details. Scroll within **Node Details**
when the rows do not fit the available height. Confirmed information includes
node number, manufacturer, module type, module identifier, CAN ID, mode, firmware, CPU,
interface, supported events, NV and EV counts, and capabilities such as producer,
consumer, own-event consumption, bootloading and VLCB compatibility.
Known manufacturer and module names appear as text (for example, MERG and CANMIO);
unrecognised values retain their numeric IDs. Node Details and its summary use
manufacturer parameter 1 and module type parameter 3 from current discovery, or
persisted parameters for a saved node. Discovery reads all parameters supported
by the node's reported count and saves confirmed values, including those not
shown in Node Details. Unknown live parameters show `-` without
falling back to saved values. Known manufacturer/module-type pairs use Workbench's static module-name table,
even when a matching MDF supplies a different name. Otherwise, a compatible MDF's
`moduleName` is used, followed by the numeric module type when no name is known.
MERG type 8 uses its newer name CANSOL; MERG type 36 remains CANCDU despite its
MDF naming it CANACC4. Saved-only nodes retain their offline labels
and saved details; they do not resolve MDF names.
Mode and operational capabilities still use live PNN flags and remain unknown for
saved nodes.
The module identifier combines the confirmed manufacturer and module type bytes
as uppercase hexadecimal (for example, `A520`). CAN ID appears immediately below
Interface, and in the compact summary, only when the node reports a CAN interface.
This is independent of whether the layout connects through TCP/IP or serial.
A confirmed nonzero beta build appears beside the firmware version.
Unconfirmed fields show `-`; VLCB compatibility shows Yes, No or `-`.

**Module descriptor** shows the compatible MDF selected from confirmed live node
identity, firmware and any processor restriction, for example
`CANMIO-A520-3d.json (System)` or `CANMIO-A520-3d.json (User)`. Hover over it to see
the full file path. Compatible user MDFs take precedence over system MDFs.
`None` means no compatible MDF can be established; `Error` means lookup failed
or a matching file is invalid. Error details are recorded in the application log;
an invalid user override does not silently fall back to a system file.
The selected MDF also supplies NV forms when its presentation constructs
are supported. Supported EV controls appear beside the raw values in consumed events.

**Online** means the node responded during discovery or its latest presence check.
Known nodes start **Offline** and return to Offline after one failed check or
when the layout disconnects. Disabling periodic polling keeps the last status
until fresh evidence arrives or the layout disconnects.

## Editing node variables (NVs)

The live node's **Raw Node Variables** tab shows confirmed values as they arrive.
Unread values show `-`; confirmed zero shows `0`.

Raw Values shows only the NV number and value; use MDF token labels for local naming.

For live nodes with a compatible MDF using the supported presentation subset,
Node Variables offers compact settings pages with Raw Values first in the
left-hand navigation. Flat MDF settings appear on a Settings page. Native bordered groups
keep their titles and compact controls together; nested groups do not
add navigation. Large settings pages scroll within the settings area without
enlarging the application window. Settings controls support editing Select, Number, Slider, BitSingle and BitArray
values during Edit. Both views show the same working copy, and Cancel returns to confirmed
values. Unsupported controls are omitted from settings pages; pages with no
supported controls are omitted too. Raw Values always remains available,
including NVs whose settings controls are unsupported. If no supported pages
remain, or the MDF is missing or invalid, the raw table is shown.
Unknown values remain blank or indeterminate; an unknown visibility condition
leaves its rows visible and read-only with a `Visibility unknown` tooltip.
Settings can depend on a whole NV or a single bit; for example, CANCMD 4d
shows SoD Delay when NV2 bit 6 is set and Honk Interval when bit 7 is set.
These conditions follow edits and return to confirmed values on Cancel.

During Edit, supported MDF controls and Raw Values edit the same desired raw NV/EV
configuration. Changes immediately refresh other controls representing the same
value, including visibility and NV-dependent event labels. Bit and masked edits
preserve all other bits. Unknown values remain unknown and their MDF controls
stay read-only; Dual controls also remain read-only. Outside Edit, all MDF controls
show confirmed hardware values and are read-only. Save applies the raw desired
configuration through the existing verified Save operation; Cancel discards it.
Event MDF controls are constructed when an event is first expanded.

MDF numbers and sliders display scaled
values and units in compact numeric controls. Values outside the MDF limits
remain visible, with the range discrepancy explained in a tooltip. Masked selections
use only their specified bits; unknown or unmatched values leave the choice unselected.
Bit arrays show labelled checkboxes in MDF order; unread NVs show
indeterminate marks. Overloaded bit labels follow their controlling NV; known
unmatched labels are hidden, while unread controlling NVs show “label unknown”.
Annotations are skipped; template labels are displayed literally without substitution.

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
or change hardware. New node backups also include the node's annotations in a
separate section. Layout backups include layout event names and the annotations
of their included nodes. Annotations do not affect discovery completeness.

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
- Layout event names: `layouts/<logical-layout>/annotations.yaml`
- Node names, MDF overrides and consumed-event names: `layouts/<logical-layout>/nodes/<node-number>/annotations.yaml`

A layout's associated node files use the same timestamp filename and appear in the
ordinary node backup lists. For file-format details, see the
[development guide](development.md#architecture).

## Backup descriptions and warning icons

Node and layout backup lists show **Date & Time** in the current system locale
and local timezone, without milliseconds, with newest backups first. Filenames
record local wall time without a timezone offset, so the repeated hour when DST
ends cannot be distinguished. Original filenames remain in use for backup actions.
Optional descriptions appear beside the date and time. The node backup table also
shows a read-only **Source** column: **Layout** for backups belonging to a layout backup, otherwise **Node**. A layout description
also appears for its linked node backups. Blank
descriptions are omitted when creating backups. Double-click a description to edit
it, then choose **Save** to update the existing YAML file immediately, or **Cancel**
to discard the edit. Editing a linked node backup updates its owning layout
description. Configuration and annotations are unchanged; no CBUS traffic is sent.

No icon beside a date and time means discovery was complete when the backup was created.
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
restarting. Discovered nodes are also remembered without a backup. Their last
confirmed parameters and CAN ID are saved per logical layout and loaded while
disconnected; incomplete discovery preserves earlier values. These are last-known
values, not proof that a node is currently reachable. Nodes absent from later
discovery remain listed. Reconnecting replaces saved-only entries as nodes are discovered.
MDF selections are not saved. The **Module descriptor** label reports live lookup;
saved-only nodes can use their remembered parameters to locate MDF token defaults.
Remembered details do not make a node eligible for hardware configuration.

Right-click an offline node and choose **Forget Node** to remove it from the
navigator. Confirmation permanently deletes its local directory, annotations and
node backups. Historical layout backups remain available. Forget sends no CBUS
commands; normal discovery can add the node again later. A storage failure is
reported and leaves the node listed.

Choose **Compare** while connected to compare a node backup with current discovered
values. Events are matched by node number and event number. Unknown values make
the result inconclusive rather than definite differences; complete backups
distinguish absent EVs from unread values. Expand an event present on only one
side to inspect its confirmed EV values, including zero. The missing-event side
shows `—`; `Absent` means a confirmed absent EV within an existing event.

For a layout backup, **View** shows each saved node's discovery status, NVs and
events. **Compare** compares its associated node files with current discovery.
Differences appear under **Node configurations**, with **Backup** and **Current**
columns. Nodes match by node number; events match by node and event number.
Unknown values and nodes present on only one side make the result inconclusive,
rather than proving a configuration difference.

**New** and **Compare** require a connected layout; a new node backup also requires
a selected live node. Hardware restoration requires a connected, discovered target.
Node and layout backups containing annotations can restore those annotations while offline.
All backup **Delete** actions remain disabled.

## Restoring a node backup

Choose **Restore configuration**, **Restore annotations**, or both. Both checkboxes
start checked; **Restore** is disabled when neither is selected. Configuration
restoration writes to the physical node, requires a connected, completely discovered
target, and should use a backup for the same node and firmware. Do not use another
configuration application during hardware restoration.

To review configuration differences first, use **Compare** explicitly.

1. Select a live or remembered offline node, open **Backups**, select a saved YAML
   backup and choose **Restore**. Standalone and layout-owned backups are supported.
2. Choose what to restore. For annotations only, uncheck **Restore configuration**;
   this also works offline and sends no CBUS discovery requests, writes or verification.
3. Choose **Restore** to confirm, or **No** to cancel. When configuration is selected,
   layout-owned backups warn about restoring a single node independently. Incomplete
   backups warn that replacement may remove uncaptured configuration.

**Restore annotations** applies the node name, consumed-event names and MDF token
overrides saved in the backup. Uncheck it to keep current annotations. Older backups
without annotations leave current names untouched. Local annotation writes are
independent of hardware results, comparison and Retry. A local write failure is
reported separately and retains the previous annotations.

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

An individual rejected write or confirmed readback mismatch is recorded, while
independent changes continue after the required refresh and safe learn-mode cleanup.
A failed event creation or removal prevents dependent teaching, but does not by
itself prevent restoring other events. Verified NV/EV writes, transmitted event
removals and verified removals are reported separately; transmission alone does not
confirm removal. Earlier changes remain applied; there is no rollback.

Further changes stop if the node cannot be reached, discovery cannot confirm the
configuration needed to continue, or protocol safety remains uncertain. This includes
missing write acknowledgements, exhausted verification reads, unconfirmed learn-mode
exit after a failure, and another node acknowledging broadcast teaching. An open
connection alone does not prove the node is reachable. Some legacy nodes cannot
confirm learn-mode exit after failure and therefore require reconnection.

Workbench reads the resulting configuration and shows **Requested vs Actual** with
remaining differences and unknown values. **Retry**, when available, reads hardware
afresh and applies only outstanding differences. Follow any safety blocker or
learn-mode warning before reconnecting and comparing again.

For a saved layout backup, **Restore** opens the node and operation selection.
**Restore configuration** and **Restore annotations** both start checked. Uncheck
either to restore only the other; **Restore** is disabled when neither is selected.

With **Restore configuration** checked, the existing read-only eligibility scan runs
automatically on opening the dialog and when configuration is checked again.
Responding eligible nodes become **Online** and selectable. Offline nodes and
supported compatibility mismatches cannot receive configuration. A single mismatch
appears beside the node; multiple issues appear in its tooltip.

Nodes with backed-up annotations remain selectable when **Restore annotations** is
checked, including offline or incompatible nodes. With both options checked,
configuration is restored only to selected nodes that passed eligibility; annotations
are restored to selected nodes with backed-up annotations. Unselected nodes remain
untouched, and ineligible nodes never enter hardware comparison or Retry.

Unchecking **Restore configuration** stops remaining eligibility checks and skips
hardware discovery, writes and verification. Only nodes with backed-up annotations
can then be selected, including while offline. **Select All / Select None** affects
selectable rows. Layout-level event names can be restored with no nodes selected.
Annotation-only restoration finishes without a hardware comparison or Retry report.

Choose **Restore** for explicit confirmation. Incomplete hardware backups require
acknowledgement that uncaptured configuration may be removed. Confirm that backups
belong to the connected modules: they do not identify manufacturer or firmware.
Closing the selection stops unsent eligibility checks; disconnecting prevents further
configuration restoration while keeping local annotations available.
The following hardware workflow applies only when configuration is selected.

Nodes are restored sequentially. Each target is checked again and read afresh before
restoration. Independent node failures do not stop other selected nodes, but existing
protocol-safety blockers prevent further writes. Do not use another configuration
tool during the operation. There is no rollback.

At completion, Workbench reads available hardware again and shows **Desired vs Actual**
with remaining differences, **No differences found** for confirmed matches,
**Unknown** for unconfirmed values and **Offline** for unreachable nodes. Blocked and
unattempted selected nodes remain in the comparison. Concise warnings identify
unresolved protocol safety or learn mode; detailed failure explanations are in
Diagnostics.

When differences or unknown values remain, **Retry** repeats the same restoration
workflow against the original desired configuration. It first reads the hardware
afresh; the existing node restore applies only outstanding changes, then the layout
is read again for an updated comparison. Retry occurs only when clicked. It is hidden
for a conclusive match and disabled while disconnected, busy, or blocked by unresolved
protocol safety or reported learn mode. An offline node does not disable Retry while
the connection is active; presence and identity are revalidated before writes. Follow any safety
warning before reconnecting and comparing again; a report from a disconnected service
cannot retry through a replacement connection. Ordinary backup Compare has no Retry.

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
