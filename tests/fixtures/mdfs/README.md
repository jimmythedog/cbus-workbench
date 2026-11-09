These two small JSON descriptors are unmodified files from MMC-SERVER `v0.23.2`:

- [CANACE3-A504-2g.json](https://github.com/david284/MMC-SERVER/blob/v0.23.2/VLCB-server/config/modules/CANACE3-A504-2g.json): NV choices, with no optional EV list.
- [CANGATE-A54B-1b.json](https://github.com/david284/MMC-SERVER/blob/v0.23.2/VLCB-server/config/modules/CANGATE-A54B-1b.json): EV entries and an empty NV list.

They are selection/structure fixtures, not a vendored system MDF collection.
Tests also copy them under different filenames to exercise processor restrictions
and user precedence without introducing large generated descriptors.

`nv-value-controls.json` contains unchanged NV control entries extracted from
MMC-SERVER v0.23.2 `INDEXTEST-0003-1a.json` (the Number test group's items) and
`CANSCAN-A531-4b.json` (Startup Actions selection). It tests value interpretation
without requiring the optional downloaded system collection.

`canmio-3d-flags.json` contains the unchanged Channel 1 Flags entry from
MMC-SERVER v0.23.2 `CANMIO-A520-3d.json`. NV16 selects labels; NV17 supplies
the flags. Tests use this extract without the optional downloaded collection.

`CANCMD-A50A-4d.json` is the complete, unchanged MMC-SERVER v0.23.2 MDF.
It exercises independent NV2 bit conditions for SoD Delay and Honk Interval,
alongside the other supported controls and groups.

`CANACE8C-A505-2q.json` is the complete, unchanged MMC-SERVER v0.23.2 MDF.
It checks the native group presentation for General and all eight channel groups.

`canlever-io-type.json` contains the unchanged IO Type & Default Events group
from MMC-SERVER's `CANLEVER-A550-1a.json` (the downloaded MDF collection).
It exercises JLL equality, inequality, membership and conjunction in the NV UI.

`canmio-3d-ev2.json` extracts the EV2 Action/Simultaneous group from
MMC-SERVER v0.23.2 `CANMIO-A520-3d.json`. It retains the first eleven Action
options (unchanged) to cover masked values and NV-dependent labels without
copying repetitive options for every channel.
