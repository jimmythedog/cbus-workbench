# CBUS Workbench

CBUS Workbench is a cross-platform desktop application for configuring and maintaining MERG CBUS/VLCB networks.

Built with Python and Qt, it provides a native graphical interface for discovering modules, configuring node variables and events, managing layouts, and backing up and restoring configurations.

## Features

- Discover and inspect modules on a CBUS network.
- Configure node variables (NVs) and consumed events using module descriptors (MDFs).
- Commission modules and assign node numbers.
- Back up, compare and restore node and layout configurations.
- Name nodes and events.
- Monitor CBUS traffic and send diagnostic messages.

## Installation

Download the appropriate installer from the GitHub Releases page.

Windows, Linux and macOS builds are available. Portable builds are also provided.

## Documentation

- [User guide](docs/user-guide.md): for everyday operation and the Development Guide
  for contributing, building and testing.
- [Development guide](docs/development.md): for environment setup, checks, architecture,
  protocol implementation and diagnostics.

## Installing a release build

Release builds bundle Python, Qt and the pinned MDF collection; Python and uv are not
needed. Builds are produced for Windows x64, Linux x64, and macOS on
both Apple Silicon and Intel. Uninstalling
leaves your settings, layouts, backups, annotations and logs in place.

- **Windows:** run `cbus-workbench-<version>-windows-x64-setup.exe`. It installs for
  all users in Program Files (administrator approval needed) and adds a Start Menu
  entry; uninstall from Settings → Apps. The installer is not code-signed, so
  SmartScreen may warn: choose More info → Run anyway.
- **Ubuntu 24.04+:** `sudo apt install ./cbus-workbench-<version>-linux-x64.deb`,
  then start CBUS Workbench from the application menu or run `cbus-workbench`.
  Remove with `sudo apt remove cbus-workbench`. Serial adapters need membership of
  the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and back in).
  Other Debian-based distributions with glibc 2.39+, such as Debian 13, may work but are untested.
- **macOS:** download `cbus-workbench-<version>-macos-arm64.dmg` for Apple Silicon
  (M-series) Macs or `cbus-workbench-<version>-macos-x64.dmg` for Intel Macs; Apple
  menu → About This Mac shows which you have. Open the `.dmg` and drag CBUS Workbench
  to Applications. The app is not signed with an Apple Developer ID or notarised, so
  macOS blocks the first launch: try to open it once, then choose Open Anyway in
  System Settings → Privacy & Security.
- **Portable:** each platform also has a `-portable` build that runs without
  installation. The Linux bundle suits distributions where the `.deb` does not; it
  needs glibc 2.39 or newer plus the host's OpenGL/EGL, xcb and Wayland libraries.
  NixOS cannot run it directly; a compatibility layer such as `nix-ld` or `steam-run`
  is needed (not yet validated). If the Linux executable will not start from a
  GitHub Actions artifact, which drops Unix permissions, run `chmod +x "CBUS Workbench"`.

## Running from source

To run from source, install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/),
clone this repository and change into its directory. Then run:

```sh
uv sync --locked
uv run python main.py
```

`uv` manages the project's virtual environment; manual activation is unnecessary.
Help → About displays the application version.
Portable builds include the pinned MDF collection for offline use. For source runs,
use `make mdfs` to fetch it. See [MDF sourcing and release refresh instructions](docs/development.md#mdf-collection-for-development-and-portable-builds).
On NixOS, follow the [NixOS development setup](docs/development.md#nixos-development)
instead, using Nix-provided Python and PySide6.
