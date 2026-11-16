"""Persistent log file behaviour across application runs."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux XDG paths")
class LogFileTests(unittest.TestCase):
    def run_application_logging(self, state: Path, message: str) -> None:
        # A subprocess gives each "run" its own one-time logging configuration.
        code = (
            "import logging; "
            "from PySide6.QtCore import QCoreApplication; "
            "from workbench.logging_config import configure_logging; "
            "QCoreApplication.setApplicationName('cbus-workbench'); "
            "configure_logging(); "
            f"logging.getLogger('workbench.test').info({message!r})"
        )
        env = os.environ.copy()
        env["XDG_STATE_HOME"] = str(state)
        subprocess.run([sys.executable, "-c", code], env=env, check=True)

    def test_each_run_starts_new_file_and_keeps_previous_run(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            logs = state / "cbus-workbench" / "logs"

            self.run_application_logging(state, "first run")
            self.assertIn("first run", (logs / "cbus-workbench.log").read_text())
            self.assertFalse((logs / "cbus-workbench.log.1").exists())

            self.run_application_logging(state, "second run")
            current = (logs / "cbus-workbench.log").read_text()
            self.assertIn("second run", current)
            self.assertNotIn("first run", current)
            self.assertIn("first run", (logs / "cbus-workbench.log.1").read_text())


if __name__ == "__main__":
    unittest.main()
