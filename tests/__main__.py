"""Run unittest with Qt's harmless offscreen-plugin warnings filtered out.

Takes the same arguments as ``python -m unittest``, e.g.
``python -m tests discover -s tests -b -q``.
"""

import os
import sys
import tempfile
import unittest

# Isolate per-user application directories for the whole run, before anything
# resolves them. Without this, tests that do not patch paths write into the real
# ~/.local/share under the name PySide gives the app: the first test module to
# create QApplication (e.g. test_annotations.py). Removed when the run ends.
# Linux only: Qt reads XDG variables there, and CI runs on Linux.
isolated = tempfile.TemporaryDirectory(prefix="cbus-workbench-tests-")
for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
    os.environ[f"XDG_{kind}_HOME"] = os.path.join(isolated.name, kind.lower())

from PySide6.QtCore import qFormatLogMessage, qInstallMessageHandler

# The offscreen platform has no window manager, so Qt warns whenever a widget
# asks for one of these. They say nothing about the code under test, and GUI
# tests trigger hundreds of them.
OFFSCREEN_NOISE = {
    "This plugin does not support propagateSizeHints()",
    "This plugin does not support raise()",
    "This plugin does not support grabbing the keyboard",
}


def filter_offscreen_noise(mode, context, message):
    if message in OFFSCREEN_NOISE:
        return
    # Write to the real stderr so other Qt messages stay visible even while
    # `-b` is capturing test output.
    print(qFormatLogMessage(mode, context, message), file=sys.__stderr__, flush=True)


if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    qInstallMessageHandler(filter_offscreen_noise)

with isolated:
    unittest.main(module=None)
