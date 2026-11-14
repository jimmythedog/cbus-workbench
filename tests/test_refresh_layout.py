"""Full manual discovery retains local inventory and owns only its connection."""

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_cbus_service import ConnectionStub
from test_refresh_node import answer_refresh

from workbench.cbus_service import CbusService, DiscoveryStatus, NodeState
from workbench.pnn import Pnn


class RefreshLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = ConnectionStub("yard")
        self.connection.state = "Connected"
        self.service = CbusService(self.connection, 126)
        self.addCleanup(self.service.close)
        self.service.set_node_poll_seconds(0)
        for number in (42, 43):
            identity = Pnn(number, 1, 2, 5)
            self.service.nodes[number] = identity
            self.service.node_states[number] = NodeState(
                identity,
                parameters={6: 5},
                nv_values={5: 99},
                stored_event_count=1,
                event_identities={1: (2, 3)},
                ev_values={1: {1: 99}},
            )
            self.service.presence[number] = True
        self.outcomes = []
        self.service.layout_refresh_reported.connect(self.outcomes.append)

    def respond(self, number):
        self.connection.frame_received.emit(f":SB040NB6{number:04X}0D2205;".encode())
        answer_refresh(self.connection, number)

    def test_full_refresh_rediscovers_configuration_and_isolates_other_connection(self):
        other_connection = ConnectionStub("other connection to yard")
        other_connection.state = "Connected"
        other = CbusService(other_connection, 125)
        self.addCleanup(other.close)
        other.node_states = deepcopy(self.service.node_states)
        other.presence = self.service.presence.copy()
        original = deepcopy(other.node_states)
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.refresh_layout()
            self.assertEqual(self.connection.sent, [b":SBFC0N0D;"])
            for number in (42, 43):
                self.respond(number)
            QTest.qWait(30)
        for number in (42, 43):
            state = self.service.node_states[number]
            self.assertEqual(state.identity, Pnn(number, 13, 34, 5))
            self.assertEqual(state.nv_values, {1: 9})
            self.assertEqual(state.event_identities, {7: (10, 20)})
            self.assertEqual(state.ev_values, {7: {1: 11}})
        self.assertEqual(self.service.presence, {42: True, 43: True})
        self.assertEqual(self.service.discovery_status, DiscoveryStatus.READY)
        self.assertFalse(self.service.discovery_pending())
        self.assertEqual(
            self.outcomes, ["Refreshing Layout…", "Refresh Layout complete"]
        )
        self.assertEqual(other.node_states, original)
        self.assertEqual(other.presence, {42: True, 43: True})
        self.assertEqual(other_connection.sent, [])
        self.assertEqual(self.connection.state, "Connected")

    def test_missing_nodes_become_offline_without_cached_configuration(self):
        self.service.presence[44] = False  # Remembered, never discovered this session.
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.refresh_layout()
            self.respond(42)
            QTest.qWait(30)
        self.assertEqual(self.service.presence, {42: True, 43: False, 44: False})
        missing = self.service.node_states[43]
        self.assertEqual(missing.parameters, {})
        self.assertEqual(missing.nv_values, {})
        self.assertEqual(missing.event_identities, {})
        self.assertIsNone(missing.stored_event_count)
        self.assertEqual(self.service.discovery_status, DiscoveryStatus.INCOMPLETE)
        self.assertIn("2 nodes did not respond", self.outcomes[-1])
        self.assertFalse(self.service.discovery_pending())

    def test_busy_operations_and_known_learn_mode_refuse_refresh(self):
        original = deepcopy(self.service.node_states)
        for owner, attribute in (
            (self.service.restore, "active"),
            (self.service.nv_write, "active"),
            (self.service.nv_write, "refreshing"),
            (self.service.ev_write, "active"),
            (self.service.ev_write, "refreshing"),
        ):
            with self.subTest(owner=type(owner).__name__, attribute=attribute):
                setattr(owner, attribute, True)
                with self.assertRaises(ValueError):
                    self.service.refresh_layout()
                setattr(owner, attribute, False)
        self.service.node_states[42].parameters[8] = 0x25
        with self.assertRaises(ValueError):
            self.service.refresh_layout()
        del self.service.node_states[42].parameters[8]
        self.service.polling_allowed = lambda: False
        with self.assertRaises(ValueError):
            self.service.refresh_layout()
        self.service.polling_allowed = lambda: True
        self.assertEqual(self.connection.sent, [])
        self.assertEqual(self.service.node_states, original)
        self.connection.state = "Disconnected"
        with self.assertRaises(ValueError):
            self.service.refresh_layout()

    def test_poll_and_refresh_cannot_interleave(self):
        self.service.set_node_poll_seconds(10)
        self.service.poll_presence()
        with self.assertRaises(ValueError):
            self.service.refresh_layout()
        self.connection.frame_received.emit(b":SB040N9B002A0322;")
        # The second presence poll must also drain before refresh can own the wire.
        self.connection.frame_received.emit(b":SB040N9B002B0322;")
        self.service.refresh_layout()
        before = self.connection.sent.copy()
        self.service.poll_presence()
        with self.assertRaises(ValueError):
            self.service.refresh_layout()
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)
        self.assertEqual(self.connection.sent, before)

    def test_refresh_reads_current_nv_without_clearing_failed_write_uncertainty(self):
        self.service.nv_write.unverified.add((42, 1))
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.refresh_layout()
            self.respond(42)
            QTest.qWait(30)
        self.assertEqual(self.service.node_states[42].nv_values, {1: 9})
        self.assertEqual(self.service.nv_write.unverified, {(42, 1)})
        from workbench.node_backup_files import node_backup

        with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
            self.service.restore.check(42, node_backup(self.service.node_states[42]))

    def test_query_send_failure_reports_incomplete_and_releases_ownership(self):
        self.connection.send_error = OSError("Transport write failed")
        with self.assertRaises(OSError):
            self.service.refresh_layout()
        self.assertFalse(self.service.discovery_pending())
        self.assertEqual(self.service.discovery_status, DiscoveryStatus.INCOMPLETE)
        self.assertIn("Refresh Layout incomplete", self.outcomes[-1])
        self.assertEqual(self.service.presence, {42: False, 43: False})
