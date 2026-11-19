"""CW's unmodified discovery and editing workflows against simulated nodes."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from layout_fixture import sample_settings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from workbench.app_settings import save_settings
from workbench.cbus_service import CbusService, DiscoveryProgress, DiscoveryStatus
from workbench.layout_backup_compare import LayoutBackupCompare
from workbench.layout_restore_workflow import LayoutRestoreWorkflow
from workbench.node_backup_diff import compare_live_node
from workbench.node_backup_files import (
    backup_directory,
    load_layout_node,
    load_node_backup,
    node_backup,
)
from workbench.simulator_connection import SimulatorConnection
from workbench.window import MainWindow

# Saved positional parameters: 4 events, 3 EVs per event, 4 NVs; flags 0x1F
# (consumer, producer, FLiM, bootloader, consume own events).
LEGACY = [8, 165, 100, 32, 4, 3, 4, 3, 0x1F]
# The same module advertising VLCB (parameter 8 bit 6).
VLCB = [8, 165, 100, 32, 4, 3, 4, 3, 0x5F]

# A complete backup in the format CW saves from physical hardware. Trailing
# confirmed-absent EVs are omitted, as legacy nodes report CMDERR 5 for them.
PHYSICAL_BACKUP = """\
format_version: 1
complete: true
partOfLayoutBackup: false
node: 256
nvs: [1, 0, 200, 4]
events:
- nodeNumber: 300
  eventNumber: 5
  eventVariables: [1, 0, 9]
- nodeNumber: 0
  eventNumber: 7
  eventVariables: [2]
"""


def wait_for(test, condition):
    """Process Qt events until condition() holds; fail rather than hang."""
    deadline = time.monotonic() + 5
    while not condition():
        test.assertLess(time.monotonic(), deadline, "Timed out")
        QTest.qWait(5)


def wait_settled(test, service):
    # Starting discovery or loading is announced synchronously, so a settled
    # status means the work just requested has finished (Ready or Incomplete).
    wait_for(test, lambda: service.discovery_status != DiscoveryStatus.DISCOVERING)


class SimulatorWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": Path(temp.name)},
        )
        paths.start()
        self.addCleanup(paths.stop)
        timeout = patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 30)
        timeout.start()
        self.addCleanup(timeout.stop)
        for number, can_id, parameters in ((256, 4, LEGACY), (300, 7, VLCB)):
            path = backup_directory("home", number).parent / "metadata.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({"canId": can_id, "parameters": parameters}))

        self.connection = SimulatorConnection("Bench", self.app)
        self.addCleanup(self.connection.deleteLater)
        self.connection.connect("home")
        self.service = CbusService(self.connection, 126)
        # A test may replace the service; cleanup closes whichever is current.
        self.addCleanup(lambda: self.service.close())
        self.results = []
        for signal in (
            self.service.restore.finished,
            self.service.event_save.finished,
            self.service.event_save.delete_finished,
            self.service.nv_save.finished,
        ):
            signal.connect(lambda *result: self.results.append(result))
        self.discover_all(self.service)

    def discover_all(self, service):
        service.discover_nodes()
        wait_settled(self, service)
        for number in (256, 300):
            service.load_nvs(number)
            service.load_events(number)
        wait_settled(self, service)

    def wait_idle(self):
        wait_settled(self, self.service)

    def finish(self):
        """Wait for the one coordinator result started by the caller."""
        wait_for(self, lambda: self.results)
        self.wait_idle()
        (result,) = self.results
        self.results.clear()
        return result

    def save_events(self, number, events):
        state = self.service.node_states[number]
        desired = node_backup(state)
        desired["events"] = events
        self.service.event_save.begin(number, desired, original=node_backup(state))
        return self.finish()

    def event(self, nn, en, evs):
        return {"nodeNumber": nn, "eventNumber": en, "eventVariables": evs}

    def test_discovery_finds_an_empty_event_table(self):
        state = self.service.node_states[256]
        self.assertEqual(state.stored_event_count, 0)
        self.assertEqual(state.event_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

    def test_events_save_teaches_changes_and_deletes(self):
        _number, success, message = self.save_events(
            256, [self.event(300, 5, [0, 9]), self.event(0, 7, [2])]
        )
        self.assertTrue(success, message)
        state = self.service.node_states[256]
        events = {
            identity: state.ev_values[slot]
            for slot, identity in state.event_identities.items()
        }
        # EVs above the highest taught are confirmed absent on a legacy node.
        self.assertEqual(
            events, {(300, 5): {1: 0, 2: 9, 3: None}, (0, 7): {1: 2, 2: None, 3: None}}
        )

        self.assertTrue(
            self.save_events(256, [self.event(300, 5, [4, 9]), self.event(0, 7, [2])])[
                1
            ]
        )
        self.service.event_save.delete_event(256, (0, 7))
        self.assertTrue(self.finish()[1])

        # An independent full rediscovery reads the same configuration back.
        self.service.rediscover_node(256)
        self.wait_idle()
        state = self.service.node_states[256]
        self.assertEqual(list(state.event_identities.values()), [(300, 5)])
        self.assertEqual(state.ev_values[1], {1: 4, 2: 9, 3: None})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

    def test_nv_save_refreshes_existing_events(self):
        self.assertTrue(self.save_events(256, [self.event(300, 5, [1])])[1])
        desired = node_backup(self.service.node_states[256])
        desired["nvs"] = [0, 0, 6, 0]

        self.service.nv_save.begin(256, desired)

        _number, success, message = self.finish()
        self.assertTrue(success, message)
        state = self.service.node_states[256]
        self.assertEqual(state.nv_values[3], 6)
        self.assertEqual(list(state.event_identities.values()), [(300, 5)])
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

    def test_vlcb_flagged_node_events_need_every_ev(self):
        """Simulated VLCB-flagged nodes use legacy CBUS events (#90 Stage 1).

        They confirm learn mode in parameter 8, so Events Save can teach them.
        CW reads EVs with REVAL and treats CMDERR 5 (no EV) as absence only on
        legacy nodes, so an event without every EV cannot be read completely.
        """
        full = self.event(300, 5, [1, 2, 3])
        _number, success, message = self.save_events(300, [full])
        self.assertTrue(success, message)
        state = self.service.node_states[300]
        self.assertEqual(state.ev_values, {1: {1: 1, 2: 2, 3: 3}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

        _number, success, _message = self.save_events(
            300, [full, self.event(300, 6, [4])]
        )
        # Taught and verified by REQEV, but the refresh stays incomplete.
        self.assertFalse(success)
        state = self.service.node_states[300]
        self.assertEqual(state.ev_values[2], {1: 4})
        self.assertEqual(state.ev_progress, DiscoveryProgress.INCOMPLETE)

    def test_node_restore_applies_a_physical_backup(self):
        metadata = backup_directory("home", 256).parent / "metadata.yaml"
        before = metadata.read_bytes()
        # An event absent from the backup must be removed by Restore.
        self.assertTrue(self.save_events(256, [self.event(400, 1, [3])])[1])
        path = backup_directory("home", 256) / "2026-01-01_00-00-00-000000.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(PHYSICAL_BACKUP)
        backup = load_node_backup(path)

        self.service.restore.begin(256, backup)

        _number, success, message = self.finish()
        self.assertTrue(success, message)
        # A fresh service rediscovers the node independently and compares it.
        self.service.close()
        self.service = CbusService(self.connection, 126)
        self.discover_all(self.service)
        self.assertEqual(
            compare_live_node(self.service.node_states[256], backup), ([], False)
        )
        self.assertEqual(metadata.read_bytes(), before)

        # Another simulator connection to the same logical layout is untouched.
        other = SimulatorConnection("Bench 2", self.app)
        self.addCleanup(other.deleteLater)
        other.connect("home")
        untouched = CbusService(other, 126)
        self.addCleanup(untouched.close)
        self.discover_all(untouched)
        state = untouched.node_states[256]
        self.assertEqual(state.nv_values, {1: 0, 2: 0, 3: 0, 4: 0})
        self.assertEqual(state.stored_event_count, 0)


class SimulatorLayoutRestoreTests(unittest.TestCase):
    """CW's unmodified Layout Restore of a physical layout backup."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data = {"Data": Path(temp.name) / "data"}
        settings_path = Path(temp.name) / "settings.yaml"
        for patcher in (
            patch(
                "workbench.node_backup_files.application_directories", return_value=data
            ),
            patch(
                "workbench.observed_events.application_directories", return_value=data
            ),
            patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 30),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.metadata = {}
        for number, can_id, parameters in (
            (256, 4, LEGACY),
            (257, 5, LEGACY),
            (300, 7, VLCB),
        ):
            path = backup_directory("home", number).parent / "metadata.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({"canId": can_id, "parameters": parameters}))
            self.metadata[path] = path.read_bytes()
        settings = sample_settings()
        settings["layouts"]["Home"]["connection"]["type"] = "Simulator"
        save_settings(settings, settings_path)
        with patch("workbench.app_settings.settings_path", return_value=settings_path):
            self.window = MainWindow()
        self.addCleanup(self.window.close)

    def save_layout_backup(self, nodes):
        """Write a manifest and node files in CW's backup format.

        Real manifests may also carry layout annotations; Restore of hardware
        configuration reads only the node files.
        """
        name = "2026-01-01_00-00-00-000000.yaml"
        manifest = backup_directory("home") / name
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            yaml.safe_dump(
                {"format_version": 1, "complete": True, "nodeNumbers": list(nodes)}
            )
        )
        for number, (nvs, events) in nodes.items():
            path = backup_directory("home", number) / name
            path.parent.mkdir(parents=True)
            path.write_text(
                yaml.safe_dump(
                    {
                        "format_version": 1,
                        "complete": True,
                        "partOfLayoutBackup": True,
                        "node": number,
                        "nvs": nvs,
                        "events": [
                            {"nodeNumber": nn, "eventNumber": en, "eventVariables": evs}
                            for (nn, en), evs in events.items()
                        ],
                    }
                )
            )
        return {number: load_layout_node(manifest, number) for number in nodes}

    def test_layout_restore_of_several_simulated_nodes(self):
        snapshots = self.save_layout_backup(
            {
                256: ([1, 2, 3, 4], {(300, 5): [1, 0, 9], (0, 7): [2]}),
                257: ([0, 0, 0, 9], {(256, 1): [5]}),
                # A VLCB-flagged node needs every EV for complete discovery.
                300: ([7, 0, 0, 0], {(256, 2): [1, 2, 3]}),
            }
        )
        self.window.connect_layout()
        service = self.window.cbus_services["Home"]
        wait_settled(self, service)
        reports = []

        def report(dialog):
            reports.append(dialog)
            return QDialog.DialogCode.Rejected

        workflow = LayoutRestoreWorkflow(
            self.window.layouts["Home"], service, snapshots
        )
        with (
            patch(
                "workbench.layout_restore_workflow.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(LayoutBackupCompare, "exec", report),
        ):
            workflow.run()

        self.assertEqual(len(reports), 1)
        for number, snapshot in snapshots.items():
            with self.subTest(node=number):
                self.assertTrue(
                    workflow.results[number].startswith("Verified"),
                    workflow.results[number],
                )
                self.assertEqual(
                    compare_live_node(workflow.actual[number], snapshot), ([], False)
                )
        self.assertEqual(
            {path: path.read_bytes() for path in self.metadata}, self.metadata
        )


if __name__ == "__main__":
    unittest.main()
