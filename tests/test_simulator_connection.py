"""Observable contract of the parameterless simulator connection."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from workbench.cbus_service import CbusService, DiscoveryProgress, DiscoveryStatus
from workbench.node_backup_files import backup_directory, node_backup
from workbench.simulator_connection import SimulatorConnection

QNN = b":SBFC0N0D;"
PARAMETERS = [
    20,
    165,
    100,
    32,
    255,
    20,
    4,
    3,
    31,
    13,
    1,
    0,
    8,
    0,
    0,
    134,
    97,
    0,
    0,
    1,
    1,
]


class SimulatorConnectionTests(unittest.TestCase):
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
        self.metadata = backup_directory("home", 256).parent / "metadata.yaml"
        self.metadata.parent.mkdir(parents=True)
        self.metadata.write_text(yaml.safe_dump({"canId": 4, "parameters": PARAMETERS}))

        self.connection = SimulatorConnection("Bench", self.app)
        self.addCleanup(self.connection.deleteLater)
        self.states = []
        self.sent = []
        self.received = []
        self.connection.state_changed.connect(self.states.append)
        self.connection.frame_sent.connect(self.sent.append)
        self.connection.frame_received.connect(self.received.append)

    def test_replies_arrive_after_send_returns(self):
        self.connection.connect("home")
        self.connection.send(QNN)
        # Callers record their outstanding request only after send() returns.
        self.assertEqual(self.received, [])

        QTest.qWait(1)
        self.connection.disconnect()

        self.assertEqual(self.states, ["Connected", "Disconnected"])
        self.assertEqual(self.sent, [QNN])
        self.assertEqual(self.received, [b":SB080NB60100A5201F;"])

    def test_send_rejects_invalid_frames_and_closed_connection(self):
        with self.assertRaises(ConnectionError):
            self.connection.send(QNN)
        self.connection.connect("home")
        with self.assertRaises(ValueError):
            self.connection.send(b":SBFC0N0D")
        self.assertEqual(self.sent, [])

    def test_disconnect_discards_undelivered_replies(self):
        self.connection.connect("home")
        self.connection.send(QNN)
        self.connection.disconnect()
        self.connection.connect("home")
        QTest.qWait(1)

        self.assertEqual(self.received, [])

    def test_unreadable_metadata_fails_the_connection(self):
        self.metadata.write_text("canId: [")
        failures = []
        self.connection.failed.connect(failures.append)

        self.connection.connect("home")

        self.assertEqual(self.states, ["Error"])
        self.assertEqual(len(failures), 1)
        with self.assertRaises(ConnectionError):
            self.connection.send(QNN)

    def discover(self, connection):
        """Connect and read node 256 with the unmodified CBUS service."""
        connection.connect("home")
        service = CbusService(connection, 126)
        self.addCleanup(service.close)
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 30):
            service.discover_nodes()
            QTest.qWait(100)
            self.assertTrue(service.load_nvs(256))
            QTest.qWait(50)
        return service

    def test_cbus_service_discovers_saved_identity_and_zero_nvs(self):
        """The unmodified service discovers simulated nodes over the ordinary path."""
        service = self.discover(self.connection)

        state = service.node_states[256]
        self.assertEqual(state.can_id, 4)
        self.assertEqual(
            (state.identity.manufacturer, state.identity.module_type), (165, 32)
        )
        self.assertEqual(state.parameters, dict(enumerate(PARAMETERS)))
        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.nv_values, {1: 0, 2: 0, 3: 0, 4: 0})
        self.assertEqual(state.nv_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(service.discovery_status, DiscoveryStatus.READY)

    def test_nv_save_writes_simulated_state_for_this_connection_only(self):
        service = self.discover(self.connection)
        results = []
        service.nv_save.finished.connect(lambda *result: results.append(result))
        desired = node_backup(service.node_states[256])
        desired["nvs"] = [0, 9, 0, 200]

        # Event refresh after Save needs event support (a later step).
        service.nv_save.begin(256, desired, refresh_events=False)
        QTest.qWait(50)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][:2], (256, True))
        self.assertEqual(service.node_states[256].nv_values, {1: 0, 2: 9, 3: 0, 4: 200})

        # Another connection to the same logical layout has its own nodes.
        other = SimulatorConnection("Bench 2", self.app)
        self.addCleanup(other.deleteLater)
        self.assertEqual(
            self.discover(other).node_states[256].nv_values, {1: 0, 2: 0, 3: 0, 4: 0}
        )
        # Stopping the simulator discards its state.
        service.close()
        self.connection.disconnect()
        self.assertEqual(
            self.discover(self.connection).node_states[256].nv_values,
            {1: 0, 2: 0, 3: 0, 4: 0},
        )


if __name__ == "__main__":
    unittest.main()
