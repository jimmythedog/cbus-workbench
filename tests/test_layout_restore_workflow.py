"""Batch contracts at the existing discovery and NodeRestore boundaries."""

import os
import unittest
from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QTreeWidget
from test_layout_restore_selection import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.layout_backup_compare import LayoutBackupCompare
from workbench.layout_restore_workflow import LayoutRestoreWorkflow
from workbench.layout_view import LayoutView
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn


class LayoutRestoreWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        self.view = LayoutView(empty=True)
        self.view.node_view.details.cbus_service = self.service
        self.service.restore.finished.connect(
            self.view.node_view.details.finish_restore
        )
        done = DiscoveryProgress.COMPLETE
        skipped = DiscoveryProgress.SKIPPED
        for number in (1, 2, 3):
            identity = Pnn(number, 1, 2, 4)
            self.service.nodes[number] = identity
            self.service.node_states[number] = NodeState(
                identity,
                parameters={6: 1},
                nv_values={1: 7},
                parameter_progress=done,
                nv_progress=done,
                event_progress=skipped,
                ev_progress=skipped,
                can_id=number,
            )
        self.desired = {n: node_backup(self.service.node_states[n]) for n in (1, 3)}
        for backup in self.desired.values():
            backup["nvs"] = [4]
        self.original = deepcopy(self.desired)
        self.hardware = {1: 7, 2: 7, 3: 7}
        self.commands = []
        self.reports = []
        self.warnings = []
        self.retry_states = []
        self.retry_once = False
        self.before_retry = None
        self.use_real_engine = False
        self.node_online = True
        self.disappear = False
        self.failure = False
        self.blocked = False
        self.disconnect = False
        self.confirm = True

    def tearDown(self):
        self.service.close()
        self.view.deleteLater()
        self.connection.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def presence(self, numbers):
        number = next(iter(numbers))
        QTimer.singleShot(
            0, lambda: self.service.presence_checked.emit(number, self.node_online, 2)
        )

    def discover(self, number):
        def complete():
            self.service.node_states[number].nv_values = {1: self.hardware[number]}
            self.service.node_refresh_finished.emit(number)

        QTimer.singleShot(0, complete)

    def restore(self, number, desired, *, allow_incomplete):
        # Keep the real NodeRestore safety contract. Operation results are stubbed;
        # NV/EV exchanges are already covered by the single-node restore tests.
        self.service.restore.check(number, desired)
        self.commands.append((number, desired["nvs"][0]))

        def complete():
            failed = number == 1 and (
                self.failure or self.blocked or self.disconnect or self.disappear
            )
            if self.disappear:
                self.node_online = False
            if not failed:
                self.hardware[number] = 4
            if self.blocked:
                self.service.ev_write.blocked = True
            if self.disconnect:
                self.connection.state = "Disconnected"
                self.connection.state_changed.emit("Disconnected")
            self.service.restore.finished.emit(
                number,
                not failed,
                "Independent change failed" if failed else "Verified",
            )

        QTimer.singleShot(0, complete)

    def show_comparison(self, dialog):
        tree = dialog.findChild(QTreeWidget)
        rows = []

        def visit(item):
            rows.append(tuple(item.text(i) for i in range(3)))
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(index))
        self.reports.append(rows)
        self.warnings.append(
            " ".join(label.text() for label in dialog.findChildren(QLabel))
        )
        self.assertNotIn("Result", {row[0] for row in rows})
        self.retry_states.append(
            (dialog.retry_button.isHidden(), dialog.retry_button.isEnabled())
        )
        if self.retry_once and len(self.reports) == 1:
            self.assertEqual(self.retry_states[-1], (False, True))
            if self.before_retry is not None:
                self.before_retry()
            dialog.retry_button.click()
            return QDialog.DialogCode.Accepted
        dialog.reject()
        return QDialog.DialogCode.Rejected

    def run_workflow(self):
        def confirm(*_args):
            self.assertEqual(self.reports, [])
            self.assertEqual(self.commands, [])
            return (
                QMessageBox.StandardButton.Yes
                if self.confirm
                else QMessageBox.StandardButton.No
            )

        with (
            nullcontext()
            if self.use_real_engine
            else patch.object(self.service, "check_presence", self.presence),
            nullcontext()
            if self.use_real_engine
            else patch.object(self.service, "rediscover_node", self.discover),
            nullcontext()
            if self.use_real_engine
            else patch.object(self.service.restore, "begin", self.restore),
            patch.object(
                LayoutBackupCompare, "exec", lambda dialog: self.show_comparison(dialog)
            ),
            patch("workbench.layout_restore_workflow.QMessageBox.question", confirm),
        ):
            LayoutRestoreWorkflow(self.view, self.service, self.desired).run()

    def test_selected_subset_requires_confirmation_and_leaves_unselected_hardware_unchanged(
        self,
    ):
        self.confirm = False
        self.run_workflow()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.reports, [])
        self.confirm = True
        # A selection read can still be in flight when Restore selected is pressed.
        self.service.check_presence([2])
        self.service.cancel_presence_checks()
        QTimer.singleShot(
            0, lambda: self.connection.frame_received.emit(b":SB040N9B00020302;")
        )
        self.run_workflow()
        self.assertEqual(self.commands, [(1, 4), (3, 4)])
        self.assertEqual(self.hardware, {1: 4, 2: 7, 3: 4})
        self.assertEqual(self.desired, self.original)
        self.assertEqual(len(self.reports), 1)
        self.assertTrue(self.retry_states[-1][0])
        self.assertNotIn("Node 2", {row[0] for row in self.reports[-1]})

    def test_safe_failure_continues_and_final_comparison_shows_remaining_difference(
        self,
    ):
        self.failure = True
        self.run_workflow()
        self.assertEqual(self.commands, [(1, 4), (3, 4)])
        self.assertIn(("NV 1", "4", "7"), self.reports[-1])
        self.assertIsNone(self.view.node_view.details.failure_report)
        self.assertFalse(
            any(
                "Independent change failed" in text
                for row in self.reports[-1]
                for text in row
            )
        )
        self.assertIn(("No differences found", "", ""), self.reports[-1])

    def test_existing_safety_block_prevents_further_restores(self):
        self.blocked = True
        self.run_workflow()
        self.assertEqual(self.commands, [(1, 4)])
        self.assertEqual(self.hardware[3], 7)
        self.assertIn("Protocol safety unresolved", self.warnings[-1])
        self.assertEqual(self.retry_states[-1], (False, False))

    def test_disconnect_keeps_failed_and_unattempted_nodes_visible_with_unknown_actual(
        self,
    ):
        self.disconnect = True
        self.run_workflow()
        self.assertEqual(self.commands, [(1, 4)])
        rows = self.reports[-1]
        self.assertTrue({"Node 1", "Node 3"}.issubset({row[0] for row in rows}))
        self.assertIn(("NV 1", "4", "Unknown"), rows)
        self.assertNotIn(("NV 1", "4", "7"), rows)
        self.assertEqual(sum(row[0] == "Offline" for row in rows), 2)
        self.assertEqual(self.retry_states[-1], (False, False))

    def test_retry_uses_real_engine_and_fresh_reads_to_write_only_remaining_changes(
        self,
    ):
        self.use_real_engine = True
        self.retry_once = True
        state = self.service.node_states[1]
        state.parameters[6] = 2
        state.nv_values = {1: 7, 2: 8}
        self.desired = {1: node_backup(state)}
        self.desired[1]["nvs"] = [4, 5]
        original = deepcopy(self.desired)
        hardware = {1: 7, 2: 8}
        writes = []
        reject_once = True
        send = self.connection.send

        def respond(frame):
            nonlocal reject_once
            send(frame)
            data = bytes.fromhex(frame.decode().split("N")[1][:-1])
            opcode = data[0]
            if opcode == 0x73:
                index = data[3]
                value = {0: 8, 2: 97, 3: 2, 4: 0, 5: 0, 6: 2, 7: 1, 8: 4}[index]
                reply = f"9B0001{index:02X}{value:02X}"
            elif opcode == 0x71:
                index = data[3]
                reply = f"970001{index:02X}{hardware[index]:02X}"
            elif opcode == 0x96:
                index, value = data[3:]
                writes.append((index, value))
                if index == 2 and reject_once:
                    reject_once = False
                    reply = "6F000101"
                else:
                    hardware[index] = value
                    reply = "590001"
            else:
                self.fail(f"Unexpected hardware request: {frame!r}")
            QTimer.singleShot(
                0,
                lambda: self.connection.frame_received.emit(
                    f":SB040N{reply};".encode()
                ),
            )

        def before_retry():
            self.assertEqual(writes, [(1, 4), (2, 5)])
            self.assertIn(("NV 2", "5", "8"), self.reports[-1])
            # Deliberately stale cache: fresh hardware must determine Retry writes.
            state.nv_values = {1: 99, 2: 5}

        self.before_retry = before_retry
        with patch.object(self.connection, "send", respond):
            self.run_workflow()
        self.assertEqual(writes, [(1, 4), (2, 5), (2, 5)])
        self.assertEqual(hardware, {1: 4, 2: 5})
        self.assertEqual(self.desired, original)
        self.assertEqual(len(self.reports), 2)
        self.assertTrue(self.retry_states[-1][0])
        self.assertIn(("No differences found", "", ""), self.reports[-1])

    def test_open_report_disables_retry_for_new_safety_block_and_disconnect(self):
        workflow = LayoutRestoreWorkflow(self.view, self.service, self.desired)
        workflow.actual = {n: self.service.node_states[n] for n in self.desired}
        dialog = workflow.comparison()
        self.assertTrue(dialog.retry_button.isEnabled())
        self.service.ev_write.blocked = True
        self.service.node_state_updated.emit(1)
        self.assertFalse(dialog.retry_button.isEnabled())
        self.service.ev_write.blocked = False
        self.service.node_state_updated.emit(1)
        self.assertTrue(dialog.retry_button.isEnabled())
        self.connection.state = "Disconnected"
        self.connection.state_changed.emit("Disconnected")
        self.assertFalse(dialog.retry_button.isEnabled())
        tree = dialog.findChild(QTreeWidget)
        self.assertTrue(tree.findItems("Offline", Qt.MatchFlag.MatchRecursive))
        dialog.reject()

    def test_matching_known_values_in_incomplete_backup_do_not_offer_retry(self):
        state = self.service.node_states[1]
        state.parameters[6] = 3
        state.nv_values = {1: 7, 2: 8, 3: 9}
        desired = node_backup(state)
        desired["complete"] = False
        desired["nvs"] = [7, None]  # Known, unknown and omitted backup positions.
        workflow = LayoutRestoreWorkflow(self.view, self.service, {1: desired})
        workflow.actual = {1: state}
        dialog = workflow.comparison()
        self.assertTrue(dialog.retry_button.isHidden())
        self.assertFalse(dialog.retry_button.isEnabled())
        tree = dialog.findChild(QTreeWidget)
        row = tree.findItems("NV 2", Qt.MatchFlag.MatchRecursive)[0]
        self.assertEqual((row.text(1), row.text(2)), ("Unknown", "8"))
        dialog.reject()

    def test_offline_node_can_respond_on_retry_and_be_restored(self):
        self.desired = {1: self.desired[1]}
        original = deepcopy(self.desired)
        self.disappear = True
        self.retry_once = True

        def reconnect_node():
            self.assertEqual(self.connection.state, "Connected")
            self.assertIn(("Offline", "", ""), self.reports[-1])
            self.assertIn(("NV 1", "4", "Unknown"), self.reports[-1])
            self.node_online = True
            self.disappear = False

        self.before_retry = reconnect_node
        self.run_workflow()
        self.assertEqual(self.retry_states[0], (False, True))
        self.assertEqual(self.hardware[1], 4)
        self.assertEqual(self.desired, original)
        self.assertIn(("No differences found", "", ""), self.reports[-1])
        self.assertTrue(self.retry_states[-1][0])
