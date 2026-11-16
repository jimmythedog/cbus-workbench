# Development guide

This document records established development decisions and, as the application takes shape, will explain its architecture and important execution flows. It is not an inventory of source files. For application operating instructions, see
the [user guide](user-guide.md); end-user installation is covered only by the
[installation guide](installation.md).

## Observed network events

Observed events are separate from persisted annotations and from
consumed-event configuration. `MainWindow` owns one `ObservedEvents` collection
per logical layout and binds each connection/view to it. This prevents different
layouts from mixing traffic or storage; connections intentionally sharing a logical
layout also share observed identities.
All updates run through Qt's existing GUI-thread connection/service path.

```text
connection.frame_received -> CbusService -> event_received(identity) --+
connection.frame_sent -> MainWindow.record_frame -> decode_event -----+
    -> layout collection: new identity -> write temporary YAML -> replace file
                          known identity -> no disk write or view refresh
    -> add new identity -> changed -> layout event list
    save failure -> existing ErrorReporter (traceback + dialog); next sighting retries
```

`Data/layouts/<logical-layout>/observed-events.yaml` stores only
`nodeNumber` and `eventNumber`. Older records containing `type` load using their
NN/EN fields; the next new-identity save omits `type` from all records. All
configured layouts load their identities at startup. The collection stores identities only; ON/OFF state, occurrence counts
and timestamps are not tracked.
Disconnect removes the service's receiver, leaving the collection intact;
reconnect uses that collection. Switching a connection's logical layout binds its
views to the destination collection.
The layout event list uses only observed identities. Node Produced Events filter
the same collection by node number, excluding short events (NN zero).
Annotations never create event entries. Both event panes resolve
names from the layout annotations; there is no node-owned produced-event name.

Event sending uses the selected layout's `CbusService.send_event()` for both
context actions and the Send Event dialog. The transport's existing TX signal
records outgoing frames in Diagnostics and adds event identities to the same
collection used by RX; no RX echo is required. Short identities keep NN zero in the UI;
ASON/ASOF frames also use NN zero. Their CAN header uses that layout's configured
CAN ID, independently of the event node number. Long events default to the first
discovered node when the dialog opens or switches to the long type.

The decoder accepts accessory ON/OFF events, their response variants and variants
with one to three data bytes; requests and malformed frames are ignored. Data
bytes are not part of identity. Identity is `(NN, EN)`, displayed as `NN:EN`.
Long events preserve NN; short events use `(0, DN)`, independent of the
ASON/ASOF sender NN. This follows the
[CBUS Developer's Guide 6b](https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf)
short-event addressing rule. Section 5 assigns ordinary FLiM NNs from 1–65535
and reserves NN zero for SLiM consumers and configuration software. No separate
long-NN-zero identity is retained: if such a frame is received, it shares `(0, EN)`
with a short event of that number. This is a limitation of the simplified alpha
catalogue rather than a reason to infer ownership or add another identity field.
The Produced Events pane filters the canonical identity NN, so short events appear
only for NN zero, never under a frame sender inferred as their physical owner.
Even a long NN is an identity filter, not verified physical-producer discovery.
No extra protocol requests or module-specific interpretation are involved.

## Local annotations

`annotations.yaml` sits beside `observed-events.yaml` in the logical layout
and contains `events`, a mapping from `NN:EN` to a name. Each node's
`nodes/<NN>/annotations.yaml` holds optional `name`, `tokens` and
`consumedEvents`. The latter uses the same identity keys but belongs to the
consuming node. Short identities use NN zero, following the existing catalogue
contract above. Observations and metadata never write annotation files.
`MainWindow` shares an `Annotations` notifier between views of one logical layout;
the files remain the source of truth. Atomic replacement precedes notifications.

```text
Edit -> UI draft -> Cancel -> reload saved names
                 -> Save -> validate -> temporary YAML -> replace -> notify views
                                   write failure -> retain file and draft, report
Node Restore confirmation -> optional local annotation save (once)
                          -> existing NV/EV restore -> hardware comparison / Retry
local save failure -> separate annotation error; NV/EV restoration stays independent
```

MDF text follows the [Module Descriptor File Format, issue 0.15, §§12–13](https://github.com/david284/ModuleDescriptor/blob/main/documents/Module%20Descriptor%20File%20Format.pdf).
`tokens` maps the token name to decimal-number string keys and user replacement
strings, e.g. `tokens: {palette: {'1': 'Signal red'}}`. One normalisation function
handles both references and persisted keys: `${palette 1}` equals `${palette1}`;
`channel` is case-insensitive, other names preserve case (the agreed rule where
the specification is silent). Defaults stay in the MDF. Precedence is user
override, `tokens.<name>.defaultNames`, legacy `channelNames` for channels, then
`<name><number>`. Blank overrides are removed. Referenced tokens and MDF defaults
supply editable identifiers; legacy channel counts also remain supported.
Substitution traverses text in a presentation copy once, leaving original definitions
and literal user text intact. This keeps NV and EV labels consistent. Offline
lookup uses saved parameters solely to offer read-only NV forms for token editing,
never to permit hardware writes. The NV/EV builders receive original definitions
alongside the substituted presentation, so existing labels retain their exact
source token identities. Double-clicking a token-bearing label (or right-clicking
a displayed selection name) opens a contextual `QDialog` with `QLineEdit` fields
and Save/Cancel. Repeated tokens share a single field; surrounding label text is
fixed. Non-numbered structural placeholders are excluded. Saving merges only the
label's overrides, then uses existing annotation notifications to refresh all
occurrences. The node name remains a read-only label in Node Details; double-clicking it opens its own small Save/Cancel dialog using the same annotation persistence.

MMC import translates supported names into these same annotations. Display-name
matches prepopulate the existing settings and logical-layout ID; other names start
with MMC details. Every target uses the normal Layout Settings dialog, collection
and validation. The confirmed logical ID determines the annotation destination;
confirmed settings are saved using normal layout persistence. The dialog itself
never saves. All reviews complete before import writes begin; cancelling one leaves
the whole batch untouched. Existing destination annotations use the same merge rule,
even for a new display name sharing a logical ID. Empty node annotations retain
offline nodes without creating confirmed hardware metadata. Valid named MMC events
also merge into the destination's ObservedEvents collection through observe(), regardless
of the description-overwrite option. Existing identities remain; repeat imports
are idempotent. Hardware data are outside the import's write set. The preview and save use the same leaf-value merge
rule, with destination annotations reloaded at confirmation.
MMC's `nodeDetails` and `eventDetails` are loose objects that can also contain
metadata or stale placeholder entries. The importer selects numeric node candidates
and eight-hex-digit event identities before validating their records. Nonnumeric
node keys and non-event keys are ignored; node zero is excluded. Actual node
records still require a valid positive 16-bit number and valid annotations.
An MMC event name of `null` is absent, just like a missing or blank name.

```text
MMC JSON -> validate/preview -> review settings -> merge names -> annotation saves
                                                            -> merge observed identities
                                                            -> settings save
                         save failure -> undo completed saves, remove new directories
                         success -> reload shared observed collection, refresh views
                                    without connecting
```

Rollback restores both annotation files and the previous observed-event file.
This rollback handles ordinary write failures, not process crashes or a disk that
also refuses rollback writes; those failures are logged and reported. Settings are
published last, so interrupted imports can leave unpublished directories.

New backups add a separate `annotations` mapping, including an empty mapping so
restoration can explicitly clear saved names. Layout manifests carry layout names;
associated node files carry node annotations. Legacy backups lacking the key never
restore annotations. The restore checkbox is applied once after confirmation,
outside the existing hardware engine; comparison and Retry remain NV/EV-only.

## Running from source

These instructions are for developers. End users install release builds, which bundle Python and application dependencies; see the [installation guide](installation.md).

### Standard development setup (Windows, macOS and conventional Linux)

Follow the [source instructions](../README.md#running-from-source)
to install locked dependencies and run the application. The exact supported Python
versions are defined in `pyproject.toml`.

To add a Python runtime dependency, use `uv add <package>`; to add a development dependency, use `uv add --dev <package>`. Commit changes to both `pyproject.toml` and `uv.lock`, but never commit `.venv/`.

Help → About prefers the installed distribution version, then reads
`[project].version` from the source checkout, and shows `Development` if neither
is available. Use `uv version` for version bumps; `pyproject.toml` remains the
single source of truth. Hatchling supplies distribution metadata for installed
and portable builds; PyInstaller includes it with `--copy-metadata`. Direct
NixOS development runs require no project installation.

### NixOS development

NixOS may not load the native libraries included in PySide6's PyPI wheels without extra compatibility setup. For local NixOS development, we use Nix-provided Python and PySide6 instead.

Install and enable `direnv` with `nix-direnv`, then from the repository directory run:

```sh
direnv allow
python main.py
```

The repository's `.envrc` loads `.shell.nix`, which provides Python, PySide6, uv and Ruff. **Use `python main.py` rather than `uv run python main.py` on NixOS**: the latter selects uv's virtual environment and may load the incompatible PyPI Qt wheels.

The NixOS setup is a development-environment exception, not a separate application implementation. The application code remains cross-platform. Dependencies installed only into uv's `.venv/` will not automatically be available to Nix-provided Python; when adding dependencies, verify the NixOS setup as well.

### MDF collection for development and portable builds

Run `make mdfs` to download the MMC-SERVER release pinned by
`[tool.cbus-workbench].mmc_version` in `pyproject.toml` (currently `v0.23.2`).
Use `make mdfs MMC_VERSION=<tag>` to try another explicit release without changing
the pin. The script can also be run as `python scripts/fetch_mdfs.py`, with an
optional `--version <tag>`.

The [upstream release](https://github.com/david284/MMC-SERVER/releases/tag/v0.23.2)
has no separately uploaded assets. Its GitHub source tarball contains the JSON
MDF collection in `VLCB-server/config/modules/`. Only those JSON files are copied
into `resources/mdfs/`, a generated application-resource directory explicitly
ignored by Git. Do not commit the downloaded MDFs.
Each successful fetch replaces the previous collection and reports the release
tag and MDF count. Download, archive and missing/empty collection errors return
a nonzero status; download/extraction failures leave the previous collection intact.
The packaging workflow runs this same script without a version override before
PyInstaller packaging on Windows, Linux and macOS. An unsuccessful or empty fetch
fails the build. `--add-data "resources/mdfs:resources/mdfs"` places the collection
under the bundle resource root: `_internal/` in Windows/Linux onedir builds and
`Contents/Resources/` in the macOS app. These are the locations exposed at runtime
through `sys._MEIPASS`. The post-build check compares every JSON filename and its
contents with the fetched source collection before uploading artifacts.

To refresh MDFs for a subsequent release, change `mmc_version` in `pyproject.toml`
to an explicit MMC-SERVER release tag, run `make mdfs`, review compatibility and
run `make check`. Build the portable artifacts and manually check offline MDF
presentation and a user override on each target platform before releasing.
Changing `MMC_VERSION` locally does not change the release pin. The application
never downloads MDFs at runtime.

### Release packaging

`.github/workflows/portable-builds.yml` runs on manual dispatch, or as part of
`release.yml` when a version tag is pushed. Each matrix
job (Windows x64, Linux x64, macOS Intel, macOS Apple Silicon) builds one
PyInstaller onedir bundle natively on its runner and wraps that same bundle in a
native installer, so the portable and installed applications are identical:

    pyproject version + pinned MDFs -> PyInstaller bundle -> MDF check
        -> portable artifact (-portable)
        -> Windows: Inno Setup setup.exe  (packaging/windows/cbus-workbench.iss)
           Linux:   .deb                  (packaging/linux/build_deb.sh)
           macOS:   .dmg with .app and an Applications link (hdiutil)
        -> install/open, MDF check, launch, uninstall -> installer artifact

Artifact names include `[project].version`. When the workflow runs on a tag, the
job fails if the tag is not `v<version>`. Releases are drafted automatically and
published manually; see [Release procedure](#release-procedure). There is no
auto-updater.

Each installer is checked in CI after it is built. The checks are against the
installed or mounted result, not the build directory:

- **Windows:** silent per-machine install to Program Files, Start Menu shortcut,
  MDF check, a ten-second launch, then silent uninstall. The installer's `AppId`
  must never change, because Windows uses it to upgrade an existing installation.
  An upgrade deletes the previous `_internal/` before copying the new one.
- **Linux:** the package contents are extracted and MDF-checked. Then
  `packaging/linux/check_deb.sh` installs the package into a clean `ubuntu:24.04`
  container, so only the declared `Depends` are present. There it checks that
  every bundled library resolves, launches `cbus-workbench` under Xvfb and removes
  the package. PyInstaller leaves out the graphics stack (GL, EGL, xcb, Wayland,
  DRM), which must come from the host, and it can only bundle Qt's xcb helper
  libraries when the build machine has them. The GitHub runner does not, so they
  are declared in `Depends` too. Bundled fontconfig needs the host's
  configuration and fonts. If a
  PySide6 or PyInstaller upgrade changes this, the container check fails and
  `Depends` in `build_deb.sh` needs updating. Building on Ubuntu 24.04 sets the
  minimum glibc to 2.39.
- **macOS:** the DMG is mounted, then its app signature is verified (PyInstaller
  signs ad hoc), the MDFs are checked and the app is launched from the image.
  Intel (`macos-x64`) and Apple Silicon (`macos-arm64`) are separate native builds,
  not a universal binary.

User data lives in Qt's per-user locations, never in the installation directory,
so uninstalling or removing the package leaves it in place. Windows and macOS
builds are unsigned; the [installation guide](installation.md) documents the
resulting SmartScreen and Gatekeeper prompts. It is the single source of end-user
installation, update and uninstall instructions; other documents and release
notes link to it rather than repeating them.

### Release procedure

Pushing a tag `v<version>` runs `.github/workflows/release.yml`, which builds every
platform from the tagged commit and creates a **draft** GitHub release. Publishing
is always manual.

    push tag v$V
      -> validate: tag is v<major>.<minor>.<patch>[a|b|rc<n>], commit is on main
      -> build: portable-builds.yml, all four platforms; each job checks the tag
         matches the project version, then builds and checks its installer
      -> release: download artifacts, zip the Linux/Windows portable bundles,
         create the draft with generated notes and eight assets
         (build or validation failure: no release; release creation failure:
         inspect for an incomplete draft)
    review the draft -> Publish release (manual, in GitHub)

A **draft** is visible only to people with write access until it is published. A
**pre-release** is a published release that GitHub does not show as the latest.
Alpha, beta and release-candidate tags (`a`, `b`, `rc`, e.g. `v0.1.0a1`) create a
draft pre-release. Final tags (e.g. `v0.1.0`) create a draft stable release.

Before starting, every issue in the milestone is closed and CI passes on `main`.
`uv version` sets the version in `pyproject.toml` and `uv.lock` only. It never
commits or creates a Git tag.

1. **Bump the version** on an issue branch. Use `uv version --bump alpha` (or
   `beta`, `rc`, `stable`, `patch`, …), or set it explicitly with `uv version <version>`.
2. **Run `make check`.**
3. **Commit** `pyproject.toml` and `uv.lock`. No other file holds the version.
4. **Merge** the branch into `main` through a PR.
5. **Tag `main`** with `v` plus the project version. The build fails if the tag does
   not match `pyproject.toml`.
6. **Push the tag** to start the release workflow.

For example, to advance from `0.1.0a1` to `0.1.0a2`:

    git switch -c issue/<number>-release-0.1.0a2 main
    uv version --bump alpha            # 0.1.0a1 => 0.1.0a2
    make check
    git commit -am "#<number> Bump version to 0.1.0a2"
    # open a PR and merge it into main, then:
    git switch main && git pull --ff-only
    V="$(uv version --short)"          # 0.1.0a2
    git tag -a "v$V" -m "CBUS Workbench $V"
    git push origin "v$V"

Then review and publish the draft:

7. **Watch the release workflow.** `gh run list --workflow release.yml`, then
   `gh run watch <run-id>`. Validation, all four builds and the release job must
   pass.
8. **Smoke-test.** Download the draft's assets with
   `gh release download "v$V" --dir release-assets`. On each platform available,
   install, launch, check Help → About and MDF presentation, restart, uninstall,
   and confirm that user data survives. Note any platform not tested.
9. **Review the draft.** Open it with `gh release view "v$V" --web`. Check that it
   is marked as a pre-release only for an `a`, `b` or `rc` version, and that eight
   assets are attached: four installers (Windows, Linux and two macOS) and four
   portable archives. The generated notes list PRs merged since the previous
   release (for the first release, every PR). Above that list, add a short
   summary, a link to the installation guide
   (`https://github.com/jimmythedog/cbus-workbench/blob/main/docs/installation.md`)
   and the known limitations: alpha status where applicable, unsigned Windows and
   macOS builds, and untested platforms.
10. **Publish** with the draft's **Publish release** button in GitHub. For a final
    version, leave **Set as the latest release** checked.

**If the workflow fails,** no release is created; the tag already exists. Read the
failed job's log. For a transient runner or network failure, use **Re-run failed
jobs** on the run. If the release job fails after a draft was partly created,
delete that draft (`gh release delete "v$V"`, which keeps the tag) before
re-running.

**If the tagged code or version is wrong** (a build fails because of it, or a
problem is found while reviewing the draft), reuse the version while its release
is unpublished. Fix the problem through a PR to `main`, then remove the draft and
the old tag and recreate the tag on the corrected commit:

    gh release list                    # every draft for v$V must go; drafts can share a tag
    gh release delete "v$V" --yes      # repeat until no draft for v$V remains
    git push --delete origin "v$V"
    git tag -d "v$V"
    git switch main && git pull --ff-only
    git tag -a "v$V" -m "CBUS Workbench $V"
    git push origin "v$V"

The new push runs the release workflow again and creates a fresh draft. Delete the
draft first: a leftover draft keeps its old assets and would sit beside the new
one.

Once a release has been published, its tag must never be moved or reused. Users
and GitHub's release notes depend on it. Fix problems through a PR, then release
the next version (for example `0.1.0a2`).

### MDF form visual reference

The UI specification is the prototype screenshots in
[`screenshots/prototype/NV Globals.png`](screenshots/prototype/NV%20Globals.png),
[`NV Channel1.png`](screenshots/prototype/NV%20Channel1.png) and
[`EVs.png`](screenshots/prototype/EVs.png). Preserve their compact native forms
and left-hand NV navigation. Live NV forms use the descriptor already selected
by `NodeView`. Root `NodeVariableTabs` panels become left-hand navigation entries;
flat definitions share a Settings page. Mixed flat runs and root tabs retain their
order, using Settings, Settings 2, etc. for the flat runs. `NodeVariableGroup`
uses native `QGroupBox` borders with a compact `QFormLayout` inside each box,
including nested groups. Ancestor visibility conditions apply to every descendant
row. Empty groups and groups without visible children are omitted. Nested tabs inside groups or
panels remain an explicit unsupported structure; no nested navigation is created.
The supported leaves remain selection, byte-number, slider, dual-byte number, single-bit and bit-array. Unsupported controls are skipped with their type, panel and
original item number logged; supported controls retain MDF order. Panels with
no supported controls are omitted. If none remain, the raw table is shown.
Entries with unsupported visibility conditions are also skipped, including all
children when the entry is a group; their visibility is never guessed. Malformed
structures, invalid supported definitions and unsupported containers remain
errors and leave Raw Values available. Configured offline prototypes
still use representative definitions. Raw Values retains editing of the existing
shared working copy. Visibility uses the Qt-independent `mdf_visibility.evaluate_visibility()` for
byte/bit comparisons and the supported JLL comparisons, membership and boolean
combinations. It reads the same confirmed values or editing working copy; no
separate visibility state is kept. Conditions on controls and ancestor groups
hide complete rows, including within tab panels, only when a condition is false.
Unknown conditions leave rows read-only
and visible with a `Visibility unknown` tooltip. Invalid or unsupported conditions
are logged and skip only their entry/subtree, preserving supported siblings.

Number and Slider use the same compact numeric control. MMC-SERVER v0.23.2's bundled
client (`public/js/641.397e101a.js`, `NodeVariableSlider`) defines raw `min`/`max`
(default 0/255), optional `startBit`/`endBit` (default 0/7), and displayed value
`raw * displayScale + displayOffset` (default scale 1, offset 0). Sub-unit scales
use MMC's 1/2/3 decimal-place display rounding; units are a suffix. An observed
value outside the MDF limits is displayed intact with a tooltip and warning log;
the display range temporarily includes it to prevent Qt clamping.
Number uses the same extraction/scale/offset order, but MMC's `getDisplayValue()`
always rounds scales >= 1 to zero decimal places. Its raw maximum is the smaller
of `max` and the selected bit-field's capacity. Slider retains fractional precision
at scales >= 1 and uses `max` directly. Select matches `NV & bitMask` without
shifting (default mask 255); an unknown or unmatched result has no selection.
These differences follow the v0.23.2 bundled Number/Select components and
`getDisplayValue()` helper, rather than inferring semantics from labels.


Dual uses that same numeric widget in read-only mode. The v0.23.2 `NodeVariableDual`
component combines the explicitly named `nodeVariableIndexHigh` and
`nodeVariableIndexLow` as `(high << 8) + low`; indices need not be adjacent.
It then extracts `startBit`–`endBit` (defaults 0–15), scales and offsets using
Number's rounding rules. Default raw limits are 0–65535, with the maximum capped
by the selected bit width. Either missing byte leaves the field blank; observed
outliers remain visible with the usual range warning. Both bytes come from the
same confirmed values or working edit copy as other controls. Dual remains
read-only during Raw Values editing. The focused fixture is an unchanged extract
of the Dual controls in v0.23.2 `MMCTEST-0001-1a.json`.
Unsupported Dual properties are logged and ignored, including `linkedVariables`,
subtitles and comments. Text tokens use the annotation substitution described
above; no Dual writing or restore behaviour is added.


### Runtime MDF lookup

`MdfRepository` in `workbench/mdfs.py` resolves two separate locations:

- **System:** `resources/mdfs/` under the source root during development, or
  `resources/mdfs/` under PyInstaller's bundle root (`sys._MEIPASS`). This collection
  is treated as read-only.
- **User:** `mdfs/` under `application_directories()["Data"]`, using Qt's
  `QStandardPaths.AppDataLocation`, for example
  `$XDG_DATA_HOME/cbus-workbench/mdfs/` on Linux (normally
  `~/.local/share/cbus-workbench/mdfs/`). Help → Application Directories shows
  the Data parent directory. Lookup does not create directories; create the user
  folder manually when adding descriptors. Fetching system MDFs never touches it.

Call `repository.lookup(state.identity, state.parameters)` with the current live
`NodeState`'s confirmed PNN identity and PARAN values. It returns an `Mdf` containing
the selected path and JSON data, or `None` when no compatible descriptor exists.
Lookup is independent of the settings widgets and all configuration writing.
`NodeView` calls it when displaying selected live discovery state, including
identity and parameter updates, and passes the result to the existing Module
descriptor field in Node Details. Saved metadata is never used for lookup; MDF
results are not persisted. The selected descriptor also supplies NV
forms when its presentation constructs are supported.

    NodeView lookup -> NodeDetails -> MdfNodeVariables definitions
    confirmed NodeState.nv_values ------> both raw tables and MDF forms
    Edit -> desired_configuration["nvs"] -> both raw tables and MDF forms
    Cancel -> confirmed values; NV-only Save -> NvSave; event Save -> NodeRestore

No presentation-owned NV copy is created. Discovery updates refresh the confirmed
view; an active Edit keeps its existing definitions and desired working copy.

MMC filenames encode identity as `<name>-<manufacturer/type hex>-<major><minor>.json`,
optionally ending in `--P<decimal processor>.json`. Names are not identity keys.
Matching requires the confirmed manufacturer/type and exact major/minor firmware,
comparing firmware characters case-insensitively with `casefold()`; there is no
nearest-version fallback. For example, node firmware `2V` matches
`CANACC8-A503-2v.json`. Following
MMC-SERVER v0.23.2, parameter 20 (beta version) does not affect selection and need
not be present. Missing major/minor firmware replies and conflicting PNN/PARAN
identity return `None`. Processor-restricted files additionally require the
matching confirmed parameter 9; unrestricted files need no processor value.

Lookup checks compatible user files first, then compatible system files. Within
each directory a matching processor-specific descriptor takes precedence over an
unrestricted one. Files for other firmware or identities do not override a match.
Multiple equally applicable files are an error, rather than an arbitrary choice.

```text
confirmed identity + firmware
  -> compatible user file?   -> validate -> MDF or MdfError (stop)
  -> compatible system file? -> validate -> MDF or MdfError (stop)
  -> None (raw editing remains available)
```

Matching unreadable files, invalid JSON or invalid top-level descriptor structure
raise `MdfError` with the path and write an exception traceback to the application
log. Directory read errors also raise `MdfError`. An invalid matching user override
never silently falls back to system data. Callers should report the error and
retain raw editing. Validation here checks the descriptor object, `moduleName`,
NV/optional EV lists and their typed entries; interpreting nested controls and
their constraints belongs to a later stage. Unknown descriptor fields and control
types are preserved unchanged.

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
| `make mdfs` | Download the pinned development MDF collection |
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
with metadata or saved backups as “<node-number> (Offline)”. These entries hold
an integer rather than a cached PNN or NodeState. `node_metadata` stores confirmed
parameters (a positional list including index zero, with null gaps) and optional
last-observed `canId` in `layouts/<logical-layout>/nodes/<number>/metadata.yaml`.
PNN and parameter update signals merge confirmed fields; missing replies preserve
saved values, and equal records are not rewritten. No reachability status is saved.

    PNN / PARAN -> merge metadata -> write only if changed
    open layout -> metadata + backup inventory -> offline navigator/details
    reconnect   -> fresh NodeState -> live details and write eligibility

Presence lives separately in the connection's `CbusService.presence` dictionary,
seeded Offline from the saved inventory. PNN establishes Online without another
initial scan. Each layout's `node_poll_seconds` setting defaults to 10 when
absent from YAML. Its existing timer starts a bounded pass over known numbers;
only one RQNPN(3) poll enters the shared queue at a time. Saving the interval
updates the live service timer; zero stops it and discards unsent polls, while
an in-flight read drains normally. Explicit Restore checks remain available.
Discovery, writers,
restore, editing and modal operations defer further polls. Polls do not change
configuration discovery progress or suspend node selection. Disconnect clears
Online evidence. This status never grants write permission: Restore retains its
immediate reachability and identity checks.

    polling opportunity -> idle? -> one RQNPN(3) -> PARAN / timeout
                                 -> Online / Offline -> next node if idle

Manual **Refresh Node** acquires the idle connection through
`refresh_unavailable_reason()` and delegates to the existing `rediscover_node()`
FIFO. It also honours the UI's polling permission (edit/modal ownership) and
known learn mode. An unresolved EV write-safety block alone does not prevent
read-only refresh, and refresh does not clear that block. A running poll must
drain before refresh starts;
further polls wait until the refresh releases ownership. No QNN is sent.
RQNPN responses supply fresh identity fields (1, 3, 8) and the sender CAN ID;
parameter 8 determines whether consumed-event discovery is needed. The prior
identity, or an address-only provisional carrier for a remembered node, never
supplies refresh capabilities. Unsolicited PNNs cannot enroll unrelated nodes
while the targeted operation owns discovery. Live values are cleared first,
while metadata persistence is suppressed for this manual read. Partial results
remain partial and existing write-failure latches are not cleared.

    Refresh Node -> idle ownership check -> clear selected live configuration
                 -> RQNPN -> existing parameter/NV/event/EV queue
                 -> replies / bounded timeouts -> complete / incomplete / Offline
                 -> release ownership -> selection and details updated

**Layouts → Refresh** uses the same idle-ownership check, then repeats
`discover_nodes()` on the selected service. It clears live values and the PNN
registry before QNN so even unchanged identities initiate normal parameter/NV/
event/EV discovery. Address-only state is retained for previously discovered nodes;
PNN confirms identity again. The quiet discovery window and shared FIFO define
completion. Missing nodes become Offline and leave the result incomplete. Metadata
writes are suppressed throughout the manual pass, without touching annotations or
backups. Other services, even those sharing a logical layout, are unaffected.
Writer uncertainty markers survive both kinds of refresh: reading configuration
cannot establish that an earlier unacknowledged transaction succeeded.

    Refresh Layout -> idle check -> clear live values -> QNN on selected connection
                   -> PNN -> existing parameter/NV/event/EV queue
                   -> quiet window + FIFO drained -> Ready / Incomplete
                   -> mark missing nodes Offline, release refresh ownership

Offline metadata is loaded independently of connections and shown in the existing
details fields. It never seeds live discovery or hardware-write eligibility.
Missing nodes are retained, and backup-only directories remain supported.
Selecting a saved node also loads the ordinary backup list.
Forgetting an offline entry deletes its node directory only after copying its
historical layout snapshots unchanged to `backups/nodes/<number>/<filename>`.
`load_layout_node()` falls back to that location so layout view, compare and
restore still work without recreating a saved node. Manifests remain unchanged.
The UI removes the entry only after successful deletion; no service calls occur.
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
backup deletion remains disabled; Layout Restore coordinates the existing single-node engine for selected nodes.

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
proves absence elsewhere on the logical layout. Delete remains disabled.

Layout Restore loads the manifest and associated node files, then automatically
queues read-only RQNPN(3) checks while configuration is selected and connected.
The `presence` request kind shares the sender, PARAN decoder and timeout but does
not change discovery progress or trigger NV/event discovery. Eligibility uses the
response plus existing discovered capabilities, never invented hardware metadata.
NodeRestore and its pre-write checks are unchanged.

The dialog keeps selection distinct from hardware eligibility. A row can be selected
for backed-up annotations even if hardware checks fail. Selection passes both the
selected backup dictionaries and the positively eligible hardware subset to the
workflow. Local names are saved once for the selected nodes; only the hardware subset
enters discovery, comparison and Retry. Annotation-only choices return without these
hardware operations. Offline restoration has no service or hardware identities.

    selected backups -> annotations.save() -> local names (also offline)
                     -> selected AND hardware-eligible -> existing restore / Retry

    configuration checked -> Checking -> shared FIFO RQNPN(3)
                                              |             |
                                          PARAN(3)        timeout
                                              |             |
                                      capability checks   Offline
                                              |
                                      Online / mismatch reason

Unchecking configuration or closing removes unsent presence requests; an in-flight
read drains normally. Rechecking configuration starts a fresh scan. Disconnect
invalidates hardware eligibility while preserving annotation selection. Checkbox
availability never establishes permission to write; only positive hardware eligibility
allows a node into the hardware workflow, whose existing checks revalidate it.

After confirmation, the coordinator uses a straightforward loop and local Qt event
loops to wait for existing service completion signals. This keeps network processing
responsive while the existing window is disabled to prevent competing user operations.
Signal observers detach before advancing; there is no second restore planner or
retry algorithm. NodeDetails suppresses its single-node failure popup while the batch
owns reporting. A node failure is recorded and the next selected node is considered;
NodeRestore's existing safety gates remain authoritative.

    selected original snapshots -> explicit confirmation
                                                    |
                         for each selected node: RQNPN(3) + rediscover_node
                                                    |
                                    NodeRestore.begin -> finished outcome
                                                    |
                                    next node (including after failure)
                                                    |
                         fresh read of each available selected target
                                                    |
                         LayoutBackupCompare (differences / unknown / offline)
                                                    |
                                     explicit Retry, when safe
                                                    |
                                     repeat the same restore pass

The original desired dictionaries are retained throughout, without reloading files
or replacing them with hardware readbacks. Final reads clear old configuration via
existing rediscovery. Unavailable nodes are compared against an unknown partial
configuration through the same comparison engine. Disconnecting an open report
also marks selected nodes offline and replaces actual values with unknowns.
The comparison displays confirmed matches, differences and unknown values directly;
operation outcomes remain in diagnostics. Only protocol-safety or learn-mode warnings
are shown separately because configuration equality cannot establish protocol safety.

Layout results alone may expose Retry. The dialog uses the existing comparison
result's differences/uncertainty to decide whether to show it; service signals update
connection, busy and writer/learn-mode safety availability without polling. Offline
nodes may be retried on an active connection; target identity is revalidated by
`read_target()` before writes rather than used to gate the Retry button.
Retry closes the report and repeats `restore_selected()` on the same workflow object,
retaining original desired dictionaries and target identities. Each pass clears its
prior actual-state collection, reads targets afresh and delegates differences to
NodeRestore. Final reads rebuild the comparison; there is no automatic retry or
retry-specific write orchestration. Ordinary layout backup comparison is unchanged.

Incomplete records use `complete: false` and positional YAML `null` for
unconfirmed known values. Descriptions are omitted when blank. Backup creation
adds local annotations separately from the captured hardware configuration;
discovery completeness cannot establish that all physical nodes were found.

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
           confirmed mismatch -> record; continue events
           incomplete -> stop before event restoration
      -> remove extra events by identity (EVULN), freeing event-table capacity
      -> process backed-up identities (NN, EN)
           missing -> EVLRN numeric EVs
           matching -> no operation
           numeric differences -> EVLRN changed EVs
           confirmed extra EV -> EVULN -> learn exit -> event/EV rediscovery
             absence confirmed -> re-enter learn -> EVLRN all saved numeric EVs
             present -> record failure; skip dependent teaching
             incomplete discovery -> stop without teaching
         each operation -> existing learn exit -> event/EV refresh -> verify
      -> full parameter/NV/event/EV rediscovery -> compare known backup data
           complete backup + no uncertainty/differences -> full success
           incomplete + known data verified -> success with explicit uncertainty
           otherwise -> partial result with write/removal counts
      resolved failure -> existing learn cleanup -> full rediscovery
                       -> complete + same identity -> independent operations
                       -> incomplete / changed identity -> stop writes
      unresolved failure -> stop writes, cleanup -> rediscover -> partial result
      disconnect -> existing writer cleanup -> unverified partial result

Writers distinguish resolved operation failures from unresolved protocol uncertainty.
`NodeRestore` accumulates operation errors without replacing the desired configuration.
After a resolved EV failure and confirmed learn-mode exit, full rediscovery must
complete before another operation. Remaining EVs of an established event are compared
again; failed creation or removal skips dependent teaching. A planner refusal (such as
an unreconstructable empty event) is local to that event. Final comparison still
reports all remaining differences; errors remain visible even if later reads match.
No service safety gates are bypassed or weakened.

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
a recovery count for the final result. A second timeout or transmission failure
uses the existing stop-and-rediscover path. NVSET is never retried. A confirmed
mismatch records the actual value. An ordinary mismatch or CMDERR resolves
the transaction, but a recovery-read mismatch or CMDERR retains uncertainty because
a response from the other NVRD could still be outstanding. Resolved failures clear
only their own uncertainty marker;
the coordinator performs full rediscovery before continuing at the next saved NV.

    NVSET -> WRACK -> NVRD -> timeout -> one NVRD
                                         matching -> higher-NV refresh -> continue
                                         mismatch -> stop -> full rediscovery
                                         timeout  -> stop -> full rediscovery

Each saved index is visited once. Firmware may also change earlier NVs: the full
verification records these differences without retry or rollback, then continues
independent event changes. The
ascending order is a generic policy, not an assumption about firmware dependencies.
The final full configuration discovery after event restoration remains required;
EV teaching that changes an NV cannot produce a successful result.

TRACE records comparisons, refresh ranges, verified write counts and failures.
Save involving event edits and backup Restore continue through event
reconciliation and final verification. NV-only editing Save uses the targeted
workflow described below; the Restore engine is unchanged.

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
or interrupted verification prevents dependent teaching. A confirmed retained
identity after safe exit allows independent events to continue; incomplete or
unsafe outcomes stop further writes. For reconstruction the same
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

New Event and Teach to Node… only choose an identity (and target). They start
the ordinary Events Edit session with a pending event appended to the desired
configuration (`NodeEvents.add_pending_event()`), so the existing raw/MDF EV
controls, `EventSave.begin()`, Restore event planning and `EvWrite` teach it.
`EventSave.begin()` requires each new identity to have a nonzero edited EV:
hardware testing showed a legacy node acknowledging a zero EVLRN with WRACK
without creating the event (REQEV then returned CMDERR 7, invalid event), as
the nonzero-first rule used by Restore already allows for. EVs left blank keep
the node's defaults, so a new event's step is verified against its configured
EVs only. REQEV stays inside learn mode: legacy CBUSlib `FliM.c` handles REQEV
and EVLRN only in learn mode, so readback after NNULN would go unanswered.

Delete Event is an immediate, confirmed `EventSave.delete_event()`: the same
checks (`check_complete()`), `write_evs()` ownership and learn-mode handling,
with success only on rediscovered absence. Its result uses `delete_finished`, so
neither the editor Save result nor the Restore failure report is involved.
Teach to Node… lists only online nodes passing `check_complete()`.

```text
New Event / Teach to Node -> identity dialog -> Events Edit with pending event
  -> Save -> EventSave.begin() (new event needs a nonzero EV)
  -> NNLRN -> EVLRN(nonzero EV first) -> WRACK -> REQEV -> EVANS
  -> remaining EVs -> NNULN -> event rediscovery -> configured EVs match?
Delete Event -> confirm -> NNLRN -> EVULN -> NNULN -> rediscovery -> absent?
```

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
the unresolved-transaction marker that requires reconnecting before another application.
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
      -> initiating coordinator.begin(requested dictionary)
      -> existing reconciliation/writers -> same updated comparison dialog
```

Retry is disabled during this attempt and after verified success. Another
configuration application invalidates older reports. Existing service/connection
signals update availability without polling. Closing or replacing a report
disconnects its observers and cancels the deferred write handoff. Read-only
rediscovery may finish, but cannot start a Retry for a closed report; an already
active writer retains responsibility for finishing protocol cleanup. There is no
automatic retry, rollback or independent write path. Layout Retry reuses the same
NodeRestore engine through the layout workflow described above.

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
not confirm that the write succeeded.

Replies caused by another application (for example MMC) are passive evidence.
They never complete Workbench's outstanding request. PARAN updates the
parameter. NVANS and NEVAL refresh only values already confirmed by discovery,
and are ignored while a write, Save or Restore runs or while that node's NV/EV
pass is in progress. NEVAL names an event only by slot, so it is applied only
while event discovery is complete. An observed ENRSP that contradicts the
discovered slot map marks event discovery incomplete, without changing the event
list, until Refresh Node rereads it. EVANS carries no sender node number and is
not used passively. Live connection state stays separate for
each layout, including layouts that share a logical-layout data directory.

QNN/PNN node discovery, parameter, NV, stored-event identity and
EV value discovery, and verified NV writes are implemented. Other CBUS operations will follow
incrementally as their UI needs are defined. The service uses Qt's
existing asynchronous event loop; add a `QThread` only if processing later
proves to require it.

The service listens to one connection's frame signal, keeps PNN-confirmed node
identities in memory and emits signals only for new or changed identities. A PNN
for NN 0 (a module without a node number) is ignored: NN 0 belongs to
commissioning through RQNN, never to the inventory, polling or persistence. When a
layout connects, `MainWindow` creates its service using the configured PC CAN ID
(100–127) and sends one QNN. Leaving Connected detaches and clears that service;
reconnecting starts discovery with empty state. The caller must choose a CAN ID
unique on the network. Discovery is visible in the status bar, Diagnostics and logs.

The service emits `discovery_status_changed`; the window reads the selected
connection's service, independently of its logical layout. Two single-shot Qt
timers provide a QNN response boundary and defer status aggregation until reply
handlers finish queuing dependent work; neither timer polls. Discovery starts are
announced synchronously before intermediate state updates or requests. Each
`NodeView` follows this same status for Connect, event Save and node/layout restore,
reusing its discovery guard to defer MDF presentation. List selection is cleared
with Qt signals blocked, preserving visible details, editor copies and progress.
On ready/incomplete, selection returns and confirmed state is refreshed; disconnect
clears the live display instead. Editing and discovery both lock the navigator.
NV-only Save retains selection and the existing descriptor, deferring value
presentation until its completion without starting this navigator refresh cycle.

    service busy -> suspend selection/MDF updates (retain details and progress)
                 -> chained requests and verification
                 -> deferred ready/incomplete -> restore selection + refresh
                 -> disconnect -> clear live details

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
Sparse positions stay absent unless explicitly assigned, including numeric zero.
The Restore planner and exact post-discovery comparison remain unchanged.
MDF controls are editors of those raw values, not a second configuration model.
Select, Number, Slider, BitSingle and BitArray edits update the desired bytes and
notify both raw NV tables and existing MDF forms. Refresh blocks widget signals
so displaying a value cannot cause another edit. Masked edits merge into the
current desired byte, preserving unrelated bits. Undefined EV controls remain
editable with their existing unset displays; the first edit starts other bits
at zero. Unknown NV bytes remain read-only through partial MDF fields. Dual-byte MDF controls remain
read-only. Visibility and overloaded labels use desired values during Edit.
NVs and Events have separate Edit/Save/Cancel actions. Only one session can own
`desired_configuration` at a time; the other tab remains available for read-only
browsing. Its actions cannot save or discard the owning tab's draft. Live updates
do not replace the editable copy. Cancel or disconnect discards the active draft.

Events Save uses `EventSave`, retaining explicit `(event NN, EN, EV)` changes
between the original and desired snapshots. It overlays those changes on current
hardware values and calls `plan_event_restore()` for affected events only. Ordinary
numeric edits use `EvWrite` with post-write event discovery disabled; WRACK plus
identity-based EVANS and normal learn-mode cleanup complete verification. Clearing
a defined EV uses the planner's existing reconstruction, including discovery to
prove removal and verify the reconstructed event. Sparse absences remain distinct
from numeric zero. No NV writes, NV reads, parameters or full-node discovery run.
`EvWrite` retains post-write discovery by default for Node and Layout Restore.

```text
Events Edit -> original + desired -> explicit changed EV positions
  -> affected event -> planner -> numeric changes -> EVLRN/WRACK/REQEV/EVANS
                             -> clear EV -> unlearn -> verify absence
                                         -> teach retained values -> rediscover
  -> cleanup -> next affected event -> final result on Events tab
  -> failure -> stop -> report -> Retry (if safe)
                               -> fresh event/EV discovery
                               -> overlay explicit edits -> skip matching values
```

The active editor stays locked until its coordinator finishes. Validation
rejection preserves the draft; completion displays confirmed hardware state.
Descriptions and annotations are outside this hardware operation.

NV Save uses `NvSave`, capturing pre-edit and desired NV lists, the selected MDF,
and a fixed set of explicitly edited indices. After each verified write,
`linkedVariables.NV` from that NV's MDF definitions supplies the additional read
indices. Nested MDF panels are searched directly; missing/empty links cause no
additional reads. The normal discovery FIFO performs these targeted reads with
its existing timeout/recovery handling. Live values follow hardware; untouched
draft values adopt firmware changes, while outstanding explicit edits retain their
requested values. No higher-index fallback or final all-NV pass is performed.

```text
NV Edit -> original + desired + explicit edits + MDF
  -> Save -> ascending comparison -> equal: skip
                                  -> NVSET -> WRACK -> NVRD -> matching NVANS
                                    -> read MDF-linked NVs only
                                    -> reconcile untouched values, preserve edits
                                    -> next comparison
  -> success or first failure -> stop writes
    -> any verified writes and safe connection?
       yes -> NNEVN -> NERD (if events exist) -> REVAL for current slots/EVs
       no  -> retain evidence and protocol safety markers
    -> one final result, display confirmed values
```

Event refresh reuses `CbusService._restart_event_discovery()`, clearing only the
node's stored event count, identities and EV values before normal event discovery.
It does not request parameters, unrelated NVs, QNN or change the layout's observed
events catalogue. It runs once after verified writes, including partial saves
with resolved failures. Ambiguous writes, protocol blocks, known learn mode or
disconnection prevent this refresh and are reported. Event/EV read failures use
the existing partial-save report. No changed NVs means no event refresh.

MDF `outputOnWrite` NVs drive a node output (e.g. a servo position) whenever they
are written, so `NodeDetails` writes them during the ordinary NV Edit session
rather than adding a separate mode. Each write is a one-NV `NvSave` run, with the
editor locked and `output_write` routing its result away from the normal Save
handling. `original_configuration` is never changed: it stays the Cancel baseline.
Save compares outputOnWrite NVs with their edited value, so it skips them.
Test rewrites the confirmed value with the same one-NV run, in or out of Edit,
but only when no other edit session, write or discovery is active. These runs
pass `refresh_events=False`: they verify the write and read MDF-linked NVs, but
skip the stored event/EV refresh. On the CANMIO rig the module dropped an EV read
while moving its servo, failing an otherwise verified Test. Normal Save keeps the
refresh. Failures are shown on the NV tab; there is no failure report or Retry.

```text
Edit: outputOnWrite NV changed -> NvSave {nv} -> verified: keep editing
                                              -> failed: show error, draft = hardware
Save   -> NvSave ordinary edits only (outputOnWrite skipped)
Cancel -> any outputOnWrite NV differs from original?
            no  -> discard draft
            yes -> NvSave {nv: original} -> close session, show restored / failure
Test   -> NvSave {nv: confirmed value} (pre-edit unknown forces the write)
(all of the above except Save: no stored event/EV refresh)
```

While `NvSave` or `EventSave` owns the operation, `NodeView` skips intermediate presentation and
the selection-suspension/completion sweep. Completion updates the existing NV and
event views without navigator MDF lookups. `NvWrite.write_finished` and
`discovery_finished` report to the coordinator, never directly to the editor.

`CbusService.write_nvs()` accepts active `NvSave` or `NodeRestore` ownership;
`write_evs()` accepts active `EventSave` or `NodeRestore` ownership. Both use the existing verified writers.
NV failures reuse `NodeFailureReport`, including its explicit refresh before
Retry. Retry returns to `NvSave` with the original explicit edits and MDF linkage.
Comparisons use freshly discovered hardware values; untouched NVs adopt that
baseline so Retry does not undo confirmed firmware changes. Events Retry uses
the same report, retaining its explicit changes and refreshing only events/EVs
before re-planning. It never invokes Node Restore. Resolved failures permit Retry;
uncertain writes or learn-mode cleanup retain the existing protocol block.

The Developer's Guide 6b teaching/readback sections define the wire sequence;
no learn mode is needed. WRACK and CMDERR carry no NV index or transaction ID.
Serialisation prevents ambiguity between Workbench's own requests; another tool
must not write the same node concurrently. Each reply uses the shared response
timeout. Writes are never retried or rolled back; only the bounded NV read
recovery described above is automatic. Unresolved failures retain their
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

### Node number assignment

Each `CbusService` owns a `NodeNumberAssignment` that observes every frame. The
first RQNN with no request open records the reported NN and sender CAN ID and
emits `requested`; no menu action or waiting mode precedes it. `MainWindow`
opens one window-modal `NodeNumberDialog` for the whole application, because
RQNP and SNN carry no NN: every module in setup mode would act on them, and two
connections may reach the same physical network. A request arriving on another
connection while a dialog is active is cancelled; it is reported in the status
bar unless that connection shares the dialog's logical layout (probably the same
RQNN seen twice). Like other modal dialogs, it defers presence polling while open.

Repeated identical RQNNs are ignored. An RQNN with a different NN or CAN ID, or
PARAMS from another CAN ID, marks the request ambiguous and blocks SNN until the
user cancels and retries. PARAMS from the requester's CAN ID only adds
identification. Validation refuses the Developer's Guide reserved NNs and NNs
known Online on connections sharing the logical layout; Offline known NNs only
warn because a module may have been replaced. The dialog offers the RQNN's
non-zero NN; otherwise suggestions start at 256.

```text
RQNN -> requested -> MainWindow: dialog already active? -> cancel + status bar
                                  else -> dialog.open() -> RQNP
     PARAMS (same CAN ID) -> identification
     RQNN differing / PARAMS other CAN ID -> ambiguous -> Assign disabled
Assign -> validation + busy check -> SNN -> single-shot response timeout
     NNACK(target) from requester CAN ID, not ambiguous
          -> finished(success) -> target NN already live? rediscover_node(target)
          -> discover_nodes() (QNN) -> unchanged PNNs ignored; new PNN -> normal FIFO
     NNACK from another CAN ID / while ambiguous / CMDERR from old or target NN /
     timeout / disconnect -> finished(failure, uncertain state advice)
Cancel (before SNN only) -> forget request; module remains in setup mode
```

If the target NN already has live state (the module kept its number, or an
Offline node's number was reused), the existing `rediscover_node()` rereads it,
replacing its queued work; other nodes keep their state. A renumbered module's
old NN becomes Offline through normal polling after the dialog closes. The module
self-enumerates before RQNN (guide §7.2.1), so NNACK must match both the target
NN and the RQNN sender's CAN ID; a mismatch is reported as uncertain rather than
success. Saved data is never moved to the new NN.

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
change signals filter PNNs only when both identity and observed CAN ID are unchanged. The navigator
shows PNN identities for each layout. Node Details reads that layout's service
state to show confirmed PARAN parameters for the selected node. Manufacturer,
module type and the combined module identifier use parameters 1 and 3. NodeView
resolves the MDF once per live refresh. `module_name()` prefers the static
manufacturer/type dictionary, then the compatible MDF's `moduleName`, then numeric
type. The navigator uses PNN identity; without an MDF, details retain confirmed
parameters 1 and 3 as their identity source.

The static table contains the 94 explicit MERG entries from MMC-SERVER's
`VLCB-server/config/mergConfig.json` (jimmythedog/MMC-SERVER, commit f4242d92),
with the developer-confirmed rename of type 8 from CANACC4_2 to CANSOL. Type 34
also remains CANSOL; these are distinct numeric identities. Static CANCDU (36)
prevails over its MDF's CANACC4, and CANPAN (29) over firmware-specific CANPAN3.
Type 252 retains the table's CANDEV name; a bundled older CBUS header also calls
this ID VLCB. These descriptor/header differences do not override the static table.
MDF filenames do not establish new static entries. No runtime scan builds this table.

Saved-only nodes retain their existing metadata display without MDF lookup.
Parameter 0 supplies the supported count: the normal queue reads every index
from 1 through that count once, preserving the existing priority order before
appending remaining indices. A parameter timeout retains confirmed live values,
marks the pass incomplete and abandons remaining parameter reads for that node,
as before. Confirmed responses are saved immediately; missing values preserve
older metadata without becoming live evidence. PNN still supplies node numbers and operational
flags; those flags are not inferred from parameters. Saved entries use persisted
parameters, but unknown live values remain `-` without cached fallback. Each live node state also holds sparse confirmed NV values and
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
Node details has separate full-width Produced Events and Consumed Events tabs.
`NodeEvents` coordinates the existing produced table and consumed tree for both
configured and live nodes; moving between tabs does not rebuild either view.
The consumed tab has its own Events Edit/Save/Cancel actions;
produced descriptions use the same contextual editor as the layout event list,
with their shared layout annotations. Consumed descriptions select the node's
annotation scope. Local saves notify both produced views without CBUS traffic.
For live nodes, the views read `NodeState` on
selection and state-update signals. Consumed event rows and editor working copies use stable event identities;
internal table indices are resolved from current discovery only. Expanded rows
remain associated with their event even when rediscovery changes its index. The layout event
collection of observed identities supplies produced events; layout annotations supply
any available descriptions. The
display clears with the selected identity on disconnect; it keeps no separate
discovery model.

With a matching MDF, each supported EV has one inline widget containing its raw
value and MDF controls. EVs remain leaf rows; only events expand. Raw rows are
built immediately; inline widgets are built on first expansion and retained across
collapse/expansion. An unchanged live refresh keeps the existing tree. A value
snapshot detects confirmed context changes; changed context rebuilds raw rows and
constructs controls only for previously expanded events.

During Edit, first expansion reads the current desired NVs and that event's EVs,
including raw changes made before expansion. Notifications refresh only existing
forms; collapsed events never need construction to synchronise configuration.
Conditional controls are retained, hidden when false, and can reappear during
editing. Unknown conditions leave controls visible and read-only. One or two
controls share a horizontal line with the raw value; larger sets use vertical
forms. The threshold counts supported widgets, including currently hidden ones,
so visibility changes do not require rebuilding layouts.

    event expansion -> construct inline editors from current raw context
    raw or MDF edit -> desired EV bytes -> refresh existing event forms
    desired NV edit --------------------> refresh existing EV labels/visibility
    collapsed event --------------------> no construction until expansion

Raw EV text commits on focus loss through the existing tree-item path. MDF edits
use that same path. Stable event identities locate desired records; EV row order
supplies the one-based EV number. Unsupported definitions leave raw rows available.
Refresh retains event expansion and event or EV selection. Outside Edit, all MDF
controls show confirmed hardware values and remain read-only.

### Verified EV writing

The editor updates the shared desired configuration described above; it does not
call `CbusService.write_evs()` directly. The coordinator uses that transaction API
with `(event NN, event number, EV index)` keys. Live nodes use
raw EV rows and supported MDF editors; the configured-node MDF form remains prototype data, not a live MDF
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
       resolved failure + confirmed exit -> full rediscovery -> independent changes
       unresolved failure / unconfirmed exit -> require reconnect
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

Protocol references: [CBUS Guide 6c and CBUS 5.0 Rev A1](https://github.com/cbus-traincontrol/cbus-traincontrol.github.io),
[MERG Developer’s Guide 6b, §7.2.7 and opcode definitions](https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf),
[VLCB Event Teach and Opcode specifications](https://github.com/Versatile-LCB/VLCB-documents).
