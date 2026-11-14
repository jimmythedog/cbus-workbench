"""Manual refresh reads only hardware evidence on the selected connection."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_cbus_service import ConnectionStub

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.layout_view import LayoutView
from workbench.node_backup_files import backup_directory, node_backup, save_backup
from workbench.node_metadata import save_metadata
from workbench.pnn import Pnn


def answer_refresh(connection, number=42):
    """Small hardware fixture: one NV and one consumed event with one EV."""
    parameters = {0: 8, 1: 13, 2: 1, 3: 34, 4: 8, 5: 1, 6: 1, 7: 2, 8: 5}
    cursor = len(connection.sent) - 1
    while cursor < len(connection.sent):
        frame = connection.sent[cursor].decode()
        payload = frame[7:-1]
        assert payload[2:6] == f"{number:04X}", frame
        opcode = payload[:2]
        if opcode == "73":
            index = int(payload[6:8], 16)
            reply = f"9B{number:04X}{index:02X}{parameters[index]:02X}"
        elif opcode == "71":
            reply = f"97{number:04X}0109"
        elif opcode == "58":
            reply = f"74{number:04X}01"
        elif opcode == "57":
            reply = f"F2{number:04X}000A001407"
        elif opcode == "9C":
            reply = f"B5{number:04X}07010B"
        else:
            raise AssertionError(frame)
        connection.frame_received.emit(f":SB040N{reply};".encode())
        cursor += 1


class RefreshNodeTests(unittest.TestCase):
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
        self.outcomes = []
        self.service.refresh_reported.connect(
            lambda n, text: self.outcomes.append((n, text))
        )

    def test_targeted_refresh_replaces_stale_values_and_leaves_other_nodes(self):
        old = Pnn(42, 1, 2, 0)
        self.service.nodes[42] = old
        self.service.node_states[42] = NodeState(
            old, parameters={6: 7}, nv_values={7: 99}
        )
        self.service.presence[42] = True
        other = NodeState(Pnn(43, 1, 3, 4), parameters={6: 1}, nv_values={1: 77})
        self.service.node_states[43] = other
        original = deepcopy(other)
        self.service.refresh_node(42)
        # An unsolicited PNN must not enroll an unrelated node in this refresh.
        self.connection.frame_received.emit(b":SB040NB6002C010204;")
        self.service.poll_presence()
        answer_refresh(self.connection)
        self.app.processEvents()
        state = self.service.node_states[42]
        self.assertEqual(state.identity, Pnn(42, 13, 34, 5))
        self.assertEqual(state.nv_values, {1: 9})
        self.assertEqual(state.event_identities, {7: (10, 20)})
        self.assertEqual(state.ev_values, {7: {1: 11}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(other, original)
        self.assertNotIn(44, self.service.node_states)
        self.assertFalse(self.service.discovery_pending())
        self.assertEqual(self.outcomes[-1], (42, "Refresh Node complete"))

    def test_offline_node_returns_online_and_preserves_local_files(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for module in ("node_backup_files", "annotations"):
            patcher = patch(
                f"workbench.{module}.application_directories",
                return_value={"Data": Path(temporary.name)},
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        save_metadata("yard", NodeState(Pnn(42, 1, 2, 0)))
        save_backup(
            "yard",
            {
                "format_version": 1,
                "node": 42,
                "complete": False,
                "partOfLayoutBackup": False,
                "nvs": [],
                "events": [],
            },
        )
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        view.show_live_layout("yard", list)
        view.set_connected(True)
        view.annotations.save({"name": "Yard lights"}, 42)
        directory = backup_directory("yard", 42).parent
        files = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        nodes = view.node_view
        nodes.details.cbus_service = self.service
        nodes.state_lookup = self.service.node_states.get
        self.service.node_updated.connect(nodes.show_identity)
        self.service.node_state_updated.connect(nodes.refresh_state)
        self.service.presence_changed.connect(nodes.refresh_presence)
        self.service.discovery_status_changed.connect(nodes.discovery_status_changed)
        self.service.presence[42] = False
        view.show()
        self.app.processEvents()
        timer = QTimer()
        timer.setSingleShot(True)

        def choose_refresh():
            menu = self.app.activePopupWidget()
            action = menu.actions()[0]
            self.assertEqual(action.text(), "Refresh Node")
            self.assertTrue(action.isEnabled())
            menu.setActiveAction(action)
            QTest.keyClick(menu, Qt.Key.Key_Return)

        timer.timeout.connect(choose_refresh)
        timer.start(0)
        item = nodes.node_list.item(0)
        nodes.show_node_menu(nodes.node_list.visualItemRect(item).center())
        self.assertEqual(self.connection.sent, [b":SBFC0N73002A00;"])
        answer_refresh(self.connection)
        self.app.processEvents()
        self.assertTrue(self.service.presence[42])
        self.assertIn("Online", nodes.node_list.item(0).text())
        self.assertIn("Yard lights", nodes.node_list.item(0).text())
        self.assertEqual(nodes.details.live_state.nv_values, {1: 9})
        self.assertEqual(nodes.details.live_state.ev_values, {7: {1: 11}})
        self.assertEqual(
            files, {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        )

    def test_missing_node_finishes_offline_without_cached_values(self):
        old = Pnn(42, 1, 2, 5)
        self.service.nodes[42] = old
        self.service.node_states[42] = NodeState(
            old, parameters={6: 1}, nv_values={1: 99}
        )
        self.service.presence[42] = True
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        view.set_connected(True)
        nodes = view.node_view
        nodes.details.cbus_service = self.service
        nodes.state_lookup = self.service.node_states.get
        nodes.show_identity(old)
        self.service.node_state_updated.connect(nodes.refresh_state)
        self.service.presence_changed.connect(nodes.refresh_presence)
        self.service.discovery_status_changed.connect(nodes.discovery_status_changed)
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.refresh_node(42)
            QTest.qWait(80)
        self.assertFalse(self.service.discovery_pending())
        self.assertFalse(self.service.presence[42])
        self.assertEqual(self.service.node_states[42].parameters, {})
        self.assertEqual(self.service.node_states[42].nv_values, {})
        self.assertIn("did not respond", self.outcomes[-1][1])
        self.assertEqual(nodes.details.summary_mode.text(), "Mode: -")
        self.assertEqual(nodes.details.status.text(), "Offline")
        self.assertEqual(
            nodes.details.node_events.consumed_table.topLevelItemCount(), 0
        )
        self.assertEqual(self.connection.state, "Connected")

    def test_partial_identity_does_not_use_cached_consumer_or_nv_counts(self):
        old = Pnn(42, 1, 2, 4)  # Previously not a consumer.
        self.service.nodes[42] = old
        self.service.node_states[42] = NodeState(old, parameters={6: 7})
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.refresh_node(42)
            self.connection.frame_received.emit(b":SB040N9B002A0008;")
            QTest.qWait(30)  # Parameter phase fails; fresh consumer flag unknown.
            self.assertEqual(self.connection.sent[-1], b":SBFC0N58002A;")
            self.connection.frame_received.emit(b":SB040N74002A00;")
        self.assertTrue(self.service.presence[42])
        self.assertEqual(self.service.node_states[42].nv_values, {})
        self.assertEqual(self.outcomes[-1][1], "Refresh Node incomplete")
        self.assertFalse(self.service.discovery_pending())

    def test_safe_refresh_reads_state_but_preserves_ev_write_safety_block(self):
        identity = Pnn(42, 13, 34, 5)
        self.service.nodes[42] = identity
        self.service.node_states[42] = NodeState(identity, can_id=2)
        self.service.ev_write.blocked = True
        self.assertEqual(self.service.refresh_unavailable_reason(), "")
        self.service.refresh_node(42)
        answer_refresh(self.connection)
        self.app.processEvents()
        self.assertEqual(self.outcomes[-1], (42, "Refresh Node complete"))
        self.assertEqual(self.service.node_states[42].ev_values, {7: {1: 11}})
        with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
            self.service.restore.check(42, node_backup(self.service.node_states[42]))

    def test_refresh_refuses_incompatible_owners_without_sending(self):
        for owner, attribute in (
            (self.service.restore, "active"),
            (self.service.nv_write, "active"),
            (self.service.ev_write, "active"),
            (self.service.ev_write, "refreshing"),
        ):
            with self.subTest(owner=type(owner).__name__, attribute=attribute):
                setattr(owner, attribute, True)
                with self.assertRaises(ValueError):
                    self.service.refresh_node(42)
                setattr(owner, attribute, False)
        self.service.node_states[43] = NodeState(Pnn(43, 1, 2, 0x20))
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)
        self.service.node_states.clear()
        self.service.polling_allowed = lambda: False  # UI edit/modal ownership.
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)
        self.service.polling_allowed = lambda: True
        self.assertEqual(self.connection.sent, [])
        self.service.discover_nodes()
        before = self.connection.sent.copy()
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)
        self.assertEqual(self.connection.sent, before)
        self.connection.state = "Disconnected"
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)

    def test_menu_disables_refresh_with_reason_when_disconnected_or_writing(self):
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        nodes = view.node_view
        nodes.details.logical_layout = "yard"
        nodes.details.cbus_service = self.service
        nodes.show_identity(Pnn(42, 1, 2, 4))
        view.show()
        self.app.processEvents()
        offered = []
        timer = QTimer()
        timer.setSingleShot(True)

        def inspect_menu():
            menu = self.app.activePopupWidget()
            action = menu.actions()[0]
            offered.append((action.isEnabled(), action.toolTip()))
            menu.close()

        timer.timeout.connect(inspect_menu)
        for connected, writing in ((False, False), (True, True), (True, False)):
            self.connection.state = "Connected" if connected else "Disconnected"
            self.service.nv_write.active = writing
            timer.start(0)
            item = nodes.node_list.item(0)
            nodes.show_node_menu(nodes.node_list.visualItemRect(item).center())
        self.service.nv_write.active = False
        self.assertEqual([enabled for enabled, _ in offered], [False, False, True])
        self.assertIn("connected", offered[0][1])
        self.assertIn("writes", offered[1][1])
        self.assertEqual(self.connection.sent, [])

    def test_inflight_poll_blocks_refresh_until_response(self):
        self.service.set_node_poll_seconds(10)
        self.service.presence[42] = False
        self.service.poll_presence()
        with self.assertRaises(ValueError):
            self.service.refresh_node(42)
        self.assertEqual(self.connection.sent, [b":SBFC0N73002A03;"])
        self.connection.frame_received.emit(b":SB040N9B002A0322;")
        self.service.refresh_node(42)
        answer_refresh(self.connection)
        self.assertEqual(self.outcomes[-1][1], "Refresh Node complete")
