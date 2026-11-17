"""Run unittest with Qt's harmless offscreen-plugin warnings filtered out.

Takes the same arguments as ``python -m unittest``, e.g.
``python -m tests discover -s tests -b -q``.
"""

import os
import sys
import unittest

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

unittest.main(module=None)
