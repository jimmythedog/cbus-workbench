#!/usr/bin/env bash
# Build a .deb from the PyInstaller onedir bundle in "dist/CBUS Workbench".
# Usage: packaging/linux/build_deb.sh <version> <output.deb>  (run from the repo root)
set -euo pipefail

version="$1"
output="$2"
bundle="dist/CBUS Workbench"

# PEP 440 pre-releases (0.1.0a1) must sort before the final release in Debian,
# which needs a tilde: 0.1.0~a1.
deb_version="$(sed -E 's/(a|b|rc)([0-9]+)$/~\1\2/' <<<"$version")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
chmod 755 "$stage"

mkdir -p "$stage/opt" "$stage/usr/bin" "$stage/usr/share/applications" "$stage/DEBIAN"
cp -a "$bundle" "$stage/opt/cbus-workbench"
chmod -R u=rwX,go=rX "$stage/opt/cbus-workbench"
# The PyInstaller bootloader resolves its real path, so a symlink finds _internal.
ln -s "/opt/cbus-workbench/CBUS Workbench" "$stage/usr/bin/cbus-workbench"
install -m 644 packaging/linux/cbus-workbench.desktop "$stage/usr/share/applications/"
for size in 16 24 32 48 64 128 256 512; do
    install -D -m 644 "assets/icons/cbus-workbench-$size.png" \
        "$stage/usr/share/icons/hicolor/${size}x${size}/apps/cbus-workbench.png"
done
install -D -m 644 assets/icons/cbus-workbench.svg \
    "$stage/usr/share/icons/hicolor/scalable/apps/cbus-workbench.svg"

# PyInstaller leaves out the graphics stack (GL, EGL, xcb, Wayland, DRM), which
# must match the host. It also cannot bundle Qt's xcb helper libraries when the
# build machine lacks them (the GitHub runner does), so they are declared too.
# Bundled fontconfig needs the host's configuration and fonts.
# Verified by packaging/linux/check_deb.sh in a clean Ubuntu container.
cat >"$stage/DEBIAN/control" <<EOF
Package: cbus-workbench
Version: $deb_version
Architecture: amd64
Maintainer: Kevin Gibbs <github@kgibbs.co.uk>
Installed-Size: $(du -sk --exclude=DEBIAN "$stage" | cut -f1)
Section: electronics
Priority: optional
Homepage: https://github.com/jimmythedog/cbus-workbench
Depends: libgl1, libegl1, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0,
 libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxcb-util1, libxcb-xkb1,
 libxkbcommon-x11-0, libwayland-client0, libwayland-cursor0, libwayland-egl1,
 libdrm2, fontconfig-config, xkb-data
Description: Configure and maintain CBUS/VLCB networks
 Desktop utility for discovering, configuring and backing up CBUS/VLCB
 modules. Bundles Python, Qt and the MMC module descriptor collection.
EOF

dpkg-deb --build --root-owner-group "$stage" "$output"
