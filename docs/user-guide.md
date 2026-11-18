# User guide

CBUS Workbench configures and maintains CBUS/VLCB networks. It is in early
development; layout backup restoration and backup deletion are not yet
available. See the [installation guide](installation.md) to install, update or
uninstall it. **Help → User Guide** opens this guide in your web browser without
needing a network connection.

## Contents

- [Layouts and connections](#layouts-and-connections)
- [Importing MMC layouts](#importing-mmc-layouts)
- [Connecting and discovering nodes](#connecting-and-discovering-nodes)
- [Assigning a node number](#assigning-a-node-number)
- [Understanding discovery status](#understanding-discovery-status)
- [Viewing node information](#viewing-node-information)
- [Observed events](#observed-events)
- [Editing node variables (NVs)](#editing-node-variables-nvs)
- [Editing events and event variables (EVs)](#editing-events-and-event-variables-evs)
- [Teaching and deleting consumed events](#teaching-and-deleting-consumed-events)
- [Creating backups](#creating-backups)
- [Backup descriptions and warning icons](#backup-descriptions-and-warning-icons)
- [Viewing and comparing backups](#viewing-and-comparing-backups)
- [Restoring a node backup](#restoring-a-node-backup)
- [Diagnostics and application directories](#diagnostics-and-application-directories)

## Layouts and connections

A new installation starts with no layouts. Choose **Layouts → New…** to create one.
Enter a name and a logical layout, then choose the connection type:

- **TCP/IP**: enter the hub's host and port.
- **Serial**: the connection uses 9600 baud, 8 data bits, no parity, one stop
  bit and no flow control. Choose how the device is found:
  - **Auto-select serial device** (the default for new layouts) connects to an
    adapter matching the one this layout last used successfully, even if its
    device name (for example `COM3` or `/dev/ttyACM0`) has changed. An adapter is
    remembered only after a connection's discovery shows **Ready**. Matching uses
    the adapter's USB vendor and product IDs, plus its serial number when it has
    one. Adapters without a serial number, such as the CANUSB4, are recognised
    by model only: a different adapter of the same model is also accepted. If no
    adapter has been remembered yet, it is not plugged in, or several matching
    adapters are connected, Workbench lists every serial port and asks you to
    choose. **Confirmed adapter** shows the remembered adapter. Devices without
    USB IDs can never be remembered, so turn Auto-select off for them.
  - With Auto-select off, choose a port from **Detected** (use **Refresh** after
    plugging in an adapter) or type any device path. Every serial port is
    listed, including unrecognised adapters. On Linux, a stable
    `/dev/serial/by-id/` path is used for adapters that report a serial
    number.

  Listing ports never opens them or sends CBUS traffic. Layouts saved before
  Auto-select existed keep using their configured device path.

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
The first layout becomes the startup default. Choose **Layouts → Set as default**
to change it. A star marks the default; the radio indicator marks the current
selection. Selecting a layout during a session does not change the default.
Renaming the default preserves that choice; deleting it chooses another layout.

## Importing MMC layouts

Choose **Layouts → Import MMC layouts…**, then **Browse directory…** to select
MMC's `layouts/` directory or a single layout directory. **Browse file…** accepts
one `layoutData.json`. The chooser starts in MMC's effective layouts directory:
`~/MMC-SERVER/layouts` on Linux/macOS or `C:\ProgramData\MMC-SERVER\layouts` on
Windows, respecting `CUSTOM` user-data settings in the default base's
`appSettings.json`. If unavailable, it starts in your home directory. MMC files
are only read.

Check the layouts to import and edit each **CW layout name** as needed. A name
matching an existing CW layout (ignoring case) imports into that layout using its
existing settings as the initial proposal. Clicking **Import** always opens
Layout Settings for each selected MMC layout. Existing names start with their CW
settings and logical layout ID; new names start with the MMC details. Review or
amend the settings. The confirmed **Logical layout** ID determines where the
annotations are imported, including when you select an existing logical layout.
New layouts keep auto-connect disabled. Cancelling any settings review returns
to the preview without creating layouts or importing annotations from the batch.
Choose distinct destinations within one import. Review the added, replaced and
preserved annotation counts. Select a row to see its destination, node count,
connection settings and skipped categories in the word-wrapped details area below
the table; scroll that area if needed.

**Overwrite existing annotations** is unchecked initially. Existing names and
token overrides are preserved unless you check it; unrelated annotations always
remain. Blank MMC names never erase saved values. Import includes node names,
channel/token overrides and layout event names. Each imported event name also adds
its identity to the observed-event catalogue, so it appears immediately in **Events**
and in the matching node's **Produced Events**. Existing identities are retained;
repeat imports do not add duplicates. The overwrite option controls descriptions,
not event membership. Node entries are saved offline until normal discovery finds
them. Token names remain stored even when an MDF is not yet available to display them.

Existing destinations start with their current CW connection settings rather than
MMC's settings. Settings you confirm are saved through the normal layout persistence.
Hardware metadata and backups are not changed by import.
Missing or unsupported MMC connection settings do not block import; configure the
connection through **Layouts → Edit…** before connecting. Import itself neither
connects nor sends CBUS traffic. After success, the last imported destination becomes
the selected layout, displaying its nodes and events. If import is cancelled or fails,
the previous selection is preserved.

Subtitles, groups, colours, module identity hints, MMC UI/runtime settings and
indexed-event relationships are skipped and reported. Backups, NVs, EVs and hardware
configuration are not imported. Invalid input is reported before saving; ordinary
save failures undo completed annotation changes and leave new layouts unpublished.

## Connecting and discovering nodes

Select the layout, then choose **Layouts → Connect**. Workbench automatically
looks for nodes and reads their identities and parameters. Discovered nodes appear
in the selected layout's **Nodes** navigator.

A node's NVs and events are read the first time you need them: opening **Node
Variables** reads its NVs; opening **Consumed Events** or the node's **Backups**
reads its NVs and events. Each is read once per connection. If a read fails,
use **Refresh Node** to try again. Layout backup **New** and **Compare**, and
**Teach to Node…**, first read any online node not yet loaded (the window shows a
wait cursor meanwhile), then carry on.
While Workbench is reading, the layout shows a wait cursor and node selection,
**Events** and **Backups** are unavailable.
Choose **Layouts → Disconnect** to close the connection.

Known nodes remain in the navigator and start Offline. Normal discovery marks
responding nodes Online. While connected, Workbench checks known nodes roughly
at the configured interval (default 10 seconds), deferring checks during
discovery, editing and restore.
One failed check marks Offline; a successful check marks Online again.
Disconnect marks every node Offline. Status is runtime-only and is not saved.

If a configuration read fails or times out, confirmed values remain visible and
Workbench continues with other nodes. Use **Refresh Node** or
**Layouts → Refresh** to reread configuration when the connection is idle.
Online status does not replace Restore's fresh pre-write safety checks.

## Assigning a node number

While a layout is connected, follow the module's own pushbutton procedure to
put it into setup mode: a new module entering FLiM, or a FLiM module that should
change its node number. When the module requests a node number, Workbench opens
**Assign Node Number** automatically. You don't need to choose a menu command
first.

The dialog shows the module's current node number ("None" for a new module), its
CAN ID and, if the module reports them, its manufacturer, module and version. It
offers the module's current node number, or for a new module the lowest unused
number from 256 upwards; you can change it.
**Assign** is unavailable, with a reason, when:

- the number is reserved (0, 100–127, 65534, 65535);
- the number belongs to a node that is currently Online;
- more than one module appears to be in setup mode at once (take the others out
  of setup mode, cancel, and press the module's button again);
- the connection is busy writing, restoring or refreshing a node.

A number belonging to an Offline node is allowed with a warning, for example
when a module has been replaced. Workbench checks only nodes it has discovered
or saved, so a powered-off module may still use the number.

After **Assign**, Workbench waits for the module's acknowledgement. Only then
does it report success, close the dialog and discover the node so it appears
in Navigator with its parameters, NVs and events. If the module doesn't
acknowledge, reports an error or the connection closes, the dialog explains
that the result is uncertain; use **Layouts → Refresh** to check, or press the
module's button again. **Cancel** sends nothing: the module stays in setup mode
until its button is pressed again. After a renumber, the old number becomes
Offline at the next check; its saved data and backups stay under the old number.

Only one Assign Node Number dialog is open at a time. A request on another
connection meanwhile is ignored, and the status bar says so.

## Observed events

The layout **Events** tab lists identities in the observed-event catalogue, populated
by ON/OFF events received while connected and by named events imported from MMC.
Saved layout event names supply descriptions where available.
Annotations alone never add entries.
Events are shown as `nodeNumber:eventNumber`; short events use node
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

To tidy the catalogue, right-click an event in the layout **Events** tab or in a
node's **Produced Events** and choose **Forget Event**. To clear the whole list,
right-click anywhere in the layout **Events** tab, choose **Forget All Observed
Events…** and confirm. This removes identities only from the selected logical layout's catalogue;
event names, node configuration and backups are kept. A forgotten event that is
seen again is added back automatically with its saved name.

## Editing node annotations

Double-click the read-only **Name** label on **Node Details** to open a small
node-name editor. Choose **Save** to update the label and navigator immediately,
or **Cancel** to discard the draft. This also works for offline nodes. Node Details
has no separate annotation action buttons or MDF token list. The navigator shows
the node number, user-defined name (or module type when unnamed), and Online/Offline
status. Node Details keeps the name and module type separate.

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
an existing presentation; use **Refresh Node** to inspect EV forms that are not available.
Token editing is unavailable during NV/EV configuration editing or hardware writes.

Consumed events are listed numerically by node number, then event number.
On **Consumed Events**, double-click an event's **Description** cell to open a
small editor with **Save** and **Cancel**. Saving immediately updates that cell;
blank text clears the annotation. This works offline and never writes to hardware.
A node's consumed-event annotation takes precedence; otherwise the matching layout
event description is displayed, or blank if neither exists. Editing a fallback
saves a node-specific annotation without changing the layout description. Clearing
a node-specific annotation restores the fallback. Displaying a fallback never saves it.
Two nodes can name the same event differently. Offline entries
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
| Ready | All initiated reads for observed nodes succeeded or were inapplicable. Configuration not yet opened is not counted. |
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
the full file path. Firmware letters match case-insensitively: node firmware
`2V` matches `CANACC8-A503-2v.json`. Compatible user MDFs take precedence over
system MDFs. Multiple equally applicable MDFs produce an error, including files
whose firmware versions differ only in letter case.
`None` means no compatible MDF can be established; `Error` means lookup failed
or a matching file is invalid. Error details are recorded in the application log;
an invalid user override does not silently fall back to a system file.
The selected MDF also supplies NV forms when its presentation constructs
are supported. In consumed events, each EV row keeps its raw value and expands to
its supported EV controls, one per row. Where several controls of one EV share a
title, each is prefixed with its MDF group title, for example `Output 1 — Polarity`.

**Online** means the node responded during discovery or its latest presence check.
Known nodes start **Offline** and return to Offline after one failed check or
when the layout disconnects. Disabling periodic polling keeps the last status
until fresh evidence arrives or the layout disconnects.

To reread one node, right-click it in the node list and choose **Refresh Node**.
This works for an Offline node while its layout connection is active. It rereads
identity, parameters, NVs, consumed events and EVs using that connection, without
reconnecting or discovering other nodes. The status bar reports completion,
incomplete reads or a node that did not respond. Unconfirmed values remain unknown;
annotations, saved identification metadata and backups are preserved.
Refresh waits until discovery, polling, editing, writes, restores and learn mode
have finished. Hover over a disabled action for its reason. Refresh only rereads
hardware; it does not retry configuration writes.

To reread the whole selected connection, choose **Layouts → Refresh** below
**Disconnect**. This repeats node discovery and reads parameters, NVs, consumed
events and EVs. Existing entries remain in the navigator; nodes that do not respond
become Offline, and old configuration is not presented as newly confirmed. The
status bar reports completion or incomplete results. Annotations, saved metadata
and backups are preserved. Other layout connections, including connections sharing
the same logical layout, are unaffected. The same idle-operation safeguards apply
as for Refresh Node. Neither action disconnects or reconnects the transport.

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

1. Open **Node Variables** on a connected FLiM node and wait for its NVs to be read.
2. Choose **Edit** on **Node Variables**. Only this editor becomes active;
   the Events tabs remain available for read-only browsing.
3. Enter NV values from 0 to 255. Switch tabs freely; your edits are retained.
4. Choose **Save** or **Cancel** on **Node Variables**. Cancel discards the
   NV draft without writing. Events actions cannot save or discard this draft.

Some MDF settings, such as servo positions, are marked `outputOnWrite`: the
node moves its output whenever the value is written. While editing, a change to
one of these is written to the node immediately, so you can see the effect.
Save keeps that value without writing it again. Cancel writes the original value
back; if that fails, the message says so and the node may still hold the edited
value. These rows have a **Test** button, available in and out of Edit, that
writes the current value again to repeat the output. Test is refused while
another edit, write or discovery is in progress. Each of these writes is verified
by readback, but stored events are not refreshed afterwards. Normal Save still
refreshes them.

The active editor is locked during Save. Progress and the final result appear
on its tab. NV Save compares values in ascending NV order and writes only
explicit changes. Each write requires WRACK followed by matching NV readback.
It then reads only the NVs linked by that NV's MDF definition. Missing or empty
links cause no additional NV reads. Firmware changes to untouched linked NVs
are accepted; explicitly edited values retain their requested values.

After verified NV writes, stored events and EVs are refreshed once so firmware
changes appear automatically. This also runs after a partial Save when safe.
No parameters, unrelated NVs or full node discovery are requested. No changed
NVs means no automatic event refresh. The display returns to confirmed values
on completion. Use **Refresh Node** for a complete configuration reread.
Backup Restore retains complete-configuration reconciliation and final verification.

If an acknowledged NV write's verification read times out, Workbench makes one
additional read without repeating the write. A matching value allows application
to continue, and the final result reports that verification required recovery.
If the additional read fails or differs, NV Save stops further writes. A failed
linked-NV read also stops remaining writes. Stored events are refreshed after
verified writes only when the connection and protocol state permit it. The result and
comparison report show the failure; cached values remain last-confirmed evidence.

Automatic NV discovery and refresh also make one additional read after a timeout,
including during Save and Restore. Workbench waits for that NV before continuing;
if the second read times out, discovery remains incomplete. These reads never
repeat a write or change the response timeout.

Applying a complete target through Restore can remove firmware-created events
or reconstruct an event to clear EVs. NV Save refreshes stored events and EVs
but does not write them. There is no rollback. Do not use another configuration tool
on the network during application. Earlier writes may remain applied after
failure. Use **Refresh Node** or
**Layouts → Refresh**, when safe, to reread hardware and compare before
retrying. Refreshing does not retry failed writes or clear protocol safety blocks.
A disconnect during Save reports a partial, unverified result; resolve the connection
failure before reconnecting and comparing.

Cancel is unavailable after Save begins. Disconnecting or selecting another node
before Save discards unsaved edits. Backup restoration remains available outside
editing sessions.

## Editing events and event variables (EVs)

The live node's **Events** tab shows known produced events alongside consumed
events. Expand a consumed event to see its EV values. Normal view shows only
confirmed numeric EV values, including zero.

Choosing **Edit** on the consumed Events tab exposes every supported EV position.
The NV tab remains readable, with its editing actions unavailable until this
session ends. Enter values from 0 to 255. Clearing a numeric EV requests absence
in the desired configuration; entering `0` requests numeric zero. Unchanged
values and event identities are preserved. Use this tab's **Cancel** to discard
the Events draft or **Save** to apply it. Ordinary EV changes use targeted
teaching and identity-based readback, without NV reads or event rediscovery.
Unchanged events, descriptions and annotations are preserved.

Unknown and confirmed-absent values can both appear blank during discovery, so
editing requires complete discovery, including confirmation of every EV position.

Sparse EV positions remain sparse. For example, setting EV4 to 3 when only
EV1=65 is defined requests `[65, null, null, 3]`; EV2 and EV3 are not written.
Entering zero explicitly teaches and verifies zero, rather than requesting absence.
Editable MDF controls work for undefined EVs and update the same raw values.
The first masked edit starts other bits of that byte at zero; it does not fill
other EV positions.

Clearing an existing EV requires removing and reconstructing that event through
the existing verified writer. Other numeric EV values are retained, and event
rediscovery verifies removal before teaching and checks the reconstructed event.
A request that cannot safely recreate the event is rejected without removing it.
Ordinary edits verify only the requested bytes; use **Refresh Node** to inspect
other firmware side effects.

A partial Events Save stops further writes and opens the existing comparison
report. **Retry**, when safe, first reads fresh stored events and EVs without
reading NVs or parameters. It applies only remaining explicit edits; already
matching edits are skipped and untouched values follow fresh hardware state.
Ambiguous writes or unconfirmed learn-mode cleanup retain the existing safety
block. Refreshing does not clear that block. There is no automatic write retry
or rollback.

## Teaching and deleting consumed events

On a connected node's **Consumed Events** tab, **New Event** (also in the
right-click menu) opens a small dialog for a long or short event identity. On
**OK** the event is added as a pending row, expanded and selected, with EV1 set
to 0 and later EVs undefined, and the tab enters its normal **Edit** mode. Configure its EVs with the raw rows or MDF
controls, then **Save** to teach and verify it through the ordinary Events
Save, or **Cancel** to discard it without writing anything.

A new event needs at least one nonzero EV before **Save**: CBUS cannot teach an
event without an EV, and some nodes acknowledge a zero EV without creating the
event. The nonzero EV is taught first. What each EV does depends on the module.
EVs you leave blank keep the node's own defaults and are shown after Save.

From the layout **Events** tab, right-click an event and choose
**Teach to Node…**. The identity is shown read-only; choose an online node by
node number and name (or module type when unnamed). Only nodes that can be
edited now are listed. If some online consumer nodes have not been read yet,
Workbench reads them before showing the list. If the chosen node already consumes the event, the dialog
says so and **OK** is unavailable. Workbench then opens that node's **Consumed
Events** tab with the event pending, as for **New Event**.

**Delete Event** asks for confirmation, then immediately unlearns the selected
event, removing all of its EVs from the node. It succeeds only after the node has
left learn mode and event rediscovery shows the event absent.

Both actions need the same conditions as **Edit**: connected, discovery
complete and no other Save or Restore running. Success appears in the tab's
status line and in the refreshed event list. Failures also show a warning (or,
for Save, the usual comparison report); uncertain learn-mode cleanup keeps the
existing safety block, which requires reconnecting before further writes.

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
learn-mode warning before refreshing and comparing again. Refreshing rereads
hardware state; it does not retry failed writes or clear safety blocks. Reconnect
after resolving genuine connection failures.

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
warning before using **Layouts → Refresh** to reread hardware and compare
again. Refreshing does not retry failed writes or clear safety blocks. Reconnect
when the transport has failed; a report from a disconnected service cannot retry
through a replacement connection. Ordinary backup Compare has no Retry.

## Diagnostics and application directories

**Messages / Diagnostics** shows sent and received CBUS frames, labels supported
opcodes and shows raw frames for others. Double-click a frame to see its complete,
copyable raw message and a decimal breakdown: priority, CAN ID, opcode and all data
bytes, including the opcode. For opcodes the workbench labels, the data is also split
into named fields such as node number, event number or NV index, and standard codes
(manufacturer, module type, flags, parameter index, CMDERR error and some
parameter values) are named. Unknown
values stay numeric. Use **View** to show or hide the panel.
**View → Logging Level** changes logging detail. The choice is remembered and
applies from the start of the next session, so startup and auto-connect are logged
at that level too.

For raw frame sending, connect a layout and choose
**Layouts → Send GridConnect Frame…**. Enter a complete GridConnect frame. Raw
commands can change node configuration; use them only when you understand the command.

**Help → Application Directories…** shows the settings, logs and Data locations.
Settings are stored in Qt's configuration directory and logs in its state directory.
If migrating an existing `settings.yaml` from an older location, move it to the
shown configuration directory manually.
