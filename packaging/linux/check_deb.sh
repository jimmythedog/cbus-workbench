#!/usr/bin/env bash
# Install, launch and remove the .deb inside a clean Ubuntu container, so the
# package's Depends are checked without the build machine's libraries.
# Usage: docker run --rm -v "$PWD:/repo" ubuntu:24.04 /repo/packaging/linux/check_deb.sh /repo/<package.deb>
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq --no-install-recommends "$1"

# Every bundled library must resolve from the bundle or the declared Depends.
# The GTK3 theme plugin is optional: Qt loads it only on GTK desktops.
internal=/opt/cbus-workbench/_internal
missing="$(find "$internal" -name '*.so*' -type f ! -name libqgtk3.so -print0 |
    LD_LIBRARY_PATH="$internal:$internal/PySide6/Qt/lib" xargs -0 ldd 2>/dev/null |
    grep 'not found' | sort -u || true)"
if [ -n "$missing" ]; then
    echo "Unresolved libraries after installing Depends:" >&2
    echo "$missing" >&2
    exit 1
fi

# Launch from the installed command on X11; timeout's 124 means it was still running.
apt-get install -y -qq --no-install-recommends xvfb xauth
export HOME=/tmp/cw-home
status=0
timeout 10 xvfb-run -a cbus-workbench || status=$?
if [ "$status" -ne 124 ]; then
    echo "cbus-workbench exited early with status $status" >&2
    exit 1
fi

# Removal deletes the installed files but leaves per-user data alone.
apt-get remove -y -qq cbus-workbench
test ! -e /opt/cbus-workbench
test ! -e /usr/bin/cbus-workbench
test -f "$HOME/.local/state/cbus-workbench/logs/cbus-workbench.log"
echo "Package installed, launched and removed cleanly"
