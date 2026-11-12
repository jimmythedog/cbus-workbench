"""Names are local, scoped to layout/node, and durable through UI refreshes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

from workbench.annotations import Annotations, annotation_path, load_annotations
from workbench.cbus_service import NodeState
from workbench.layout_view import LayoutView
from workbench.mdfs import MdfRepository
from workbench.node_metadata import save_metadata
from workbench.observed_events import EventIdentity, ObservedEvents
from workbench.pnn import Pnn


class AnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for module in ("annotations", "observed_events", "node_backup_files"):
            patcher = patch(
                f"workbench.{module}.application_directories",
                return_value={"Data": self.root},
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.annotations = Annotations("test")
        self.observations = ObservedEvents("test")
        self.observations.observe(EventIdentity(42, 1))
        self.observations.observe(EventIdentity(0, 1))
        self.view = self.open_view()

    def open_view(self):
        view = LayoutView(empty=True)
        view.events[42] = {1: {}}
        self.addCleanup(view.close)
        view.set_observed_events(ObservedEvents("test"))
        view.set_annotations(self.annotations)
        view.show_live_layout("test", list)
        return view

    def show_state(self, number=42, mdf=None):
        state = NodeState(
            Pnn(number, 13, 1, 5),
            parameters={1: 13, 2: 97, 3: 1, 5: 1, 6: 1, 7: 1},
            nv_values={1: 4},
            event_identities={1: (0, 1)},
            ev_values={1: {1: 5}},
        )
        self.view.node_view.show_identity(state.identity)
        for row in range(self.view.node_view.node_list.count()):
            item = self.view.node_view.node_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole).node_number == number:
                self.view.node_view.node_list.setCurrentItem(item)
        self.view.node_view.details.show_live_state(state, mdf)
        return state

    def edit_layout_description(
        self,
        view,
        description,
        *,
        identity="42:1",
        produced=False,
        save=True,
        column=1,
        new_observation=None,
    ):
        shown = []

        def respond(dialog):
            shown.append(dialog.windowTitle())
            dialog.findChild(QLineEdit).setText(description)
            if new_observation is not None:
                view.observed_events.observe(new_observation)
            dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Save
                if save
                else QDialogButtonBox.StandardButton.Cancel
            ).click()
            return dialog.result()

        view.show()
        if produced:
            view.tabs.setCurrentWidget(view.node_view)
            view.node_view.details.tabs.setCurrentWidget(
                view.node_view.details.produced_events_page
            )
            table = view.node_view.details.node_events.produced_table
            row = next(
                row
                for row in range(table.rowCount())
                if table.item(row, 0).text() == identity
            )
            header = table.horizontalHeader()
            item = table.item(row, 0)
        else:
            view.tabs.setCurrentWidget(view.layout_events)
            table = view.layout_events.table
            item = next(
                table.topLevelItem(row)
                for row in range(table.topLevelItemCount())
                if table.topLevelItem(row).text(0) == identity
            )
            header = table.header()
        self.app.processEvents()
        position = QPoint(
            header.sectionViewportPosition(column) + 25,
            table.visualItemRect(item).center().y(),
        )
        with patch.object(QDialog, "exec", respond):
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)
            QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)
        return shown

    def test_layout_and_produced_description_save_cancel_sync_and_offline_restart(self):
        state = self.show_state()
        save_metadata("test", state)
        editor = self.view.layout_events
        self.assertEqual(editor.findChildren(QPushButton), [])
        self.edit_layout_description(self.view, "Ignored", save=False)
        self.assertEqual(load_annotations("test"), {})
        self.edit_layout_description(self.view, "Short event", identity="0:1")
        # New traffic can rebuild the tree while a contextual draft is open.
        self.edit_layout_description(
            self.view, "Produced event", new_observation=EventIdentity(42, 2)
        )
        events = self.view.node_view.details.node_events
        self.assertEqual(
            events.produced_table.horizontalHeaderItem(1).text(), "Description"
        )
        self.assertEqual(events.produced_table.item(0, 1).text(), "Produced event")
        self.assertEqual(
            load_annotations("test"),
            {"events": {"0:1": "Short event", "42:1": "Produced event"}},
        )
        self.edit_layout_description(self.view, "Ignored", produced=True, save=False)
        self.assertEqual(editor.table.topLevelItem(1).text(1), "Produced event")
        self.edit_layout_description(self.view, "From produced view", produced=True)
        self.assertEqual(editor.table.topLevelItem(1).text(1), "From produced view")
        self.assertEqual(events.produced_table.item(0, 1).text(), "From produced view")
        # Clearing/recreating observations never owns or deletes the names.
        self.view.observed_events.path.unlink()
        fresh = ObservedEvents("test")
        fresh.observe(EventIdentity(42, 1))
        self.view.set_observed_events(fresh)
        self.assertEqual(editor.table.topLevelItemCount(), 1)
        self.assertEqual(editor.table.topLevelItem(0).text(0), "42:1")
        self.assertEqual(editor.table.topLevelItem(0).text(1), "From produced view")
        reopened = self.open_view()
        self.assertIsInstance(reopened.node_view.details.node, int)
        self.edit_layout_description(reopened, "Offline edit", produced=True)
        self.assertEqual(
            reopened.layout_events.table.topLevelItem(0).text(1), "Offline edit"
        )
        self.assertEqual(editor.table.topLevelItem(0).text(1), "Offline edit")
        self.assertEqual(load_annotations("other"), {})

    def edit_node_name(self, details, name, *, save=True):
        def respond(dialog):
            dialog.findChild(QLineEdit).setText(name)
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(
                QDialogButtonBox.StandardButton.Save
                if save
                else QDialogButtonBox.StandardButton.Cancel
            ).click()
            return dialog.result()

        with patch.object(QDialog, "exec", respond):
            QTest.mouseDClick(details.node_name, Qt.MouseButton.LeftButton)

    def click_consumed_cell(self, details, identity="0:1", *, column=1, child=False):
        details.window().show()
        details.tabs.setCurrentWidget(details.consumed_events_page)
        tree = details.node_events.consumed_table
        item = next(
            tree.topLevelItem(row)
            for row in range(tree.topLevelItemCount())
            if tree.topLevelItem(row).text(0) == identity
        )
        if child:
            item.setExpanded(True)
            item = item.child(0)
        self.app.processEvents()
        position = QPoint(
            tree.header().sectionViewportPosition(column) + 25,
            tree.visualItemRect(item).center().y(),
        )
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)

    def edit_consumed_description(
        self,
        details,
        description,
        *,
        save=True,
        identity="0:1",
        column=1,
        child=False,
        initial=None,
    ):
        shown = []

        def respond(dialog):
            shown.append(dialog.windowTitle())
            if initial is not None:
                self.assertEqual(dialog.findChild(QLineEdit).text(), initial)
            dialog.findChild(QLineEdit).setText(description)
            dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Save
                if save
                else QDialogButtonBox.StandardButton.Cancel
            ).click()
            return dialog.result()

        with patch.object(QDialog, "exec", respond):
            self.click_consumed_cell(details, identity, column=column, child=child)
        return shown

    def test_node_name_and_consumed_names_save_cancel_offline_restart_rediscovery(self):
        state = self.show_state()
        details = self.view.node_view.details
        self.edit_node_name(details, "Cancelled", save=False)
        self.assertEqual(load_annotations("test", 42), {})
        self.edit_node_name(details, "West yard")
        self.assertEqual(details.node_name.text(), "West yard")
        self.assertIn("West yard", self.view.node_view.node_list.currentItem().text())
        self.assertEqual(details.action_area.widget(0).findChildren(QPushButton), [])
        events = details.node_events
        self.edit_consumed_description(details, "Ignored", save=False)
        self.assertEqual(events.consumed_table.topLevelItem(0).text(1), "")
        self.edit_consumed_description(details, "Set route")
        self.show_state(43)
        self.edit_consumed_description(details, "Light lamp")
        self.assertEqual(
            load_annotations("test", 42)["consumedEvents"]["0:1"], "Set route"
        )
        self.assertEqual(
            load_annotations("test", 43)["consumedEvents"]["0:1"], "Light lamp"
        )
        save_metadata("test", state)
        saved = self.annotations.load(42)
        saved["consumedEvents"].update(
            {"10:1": "Ten", "2:10": "Second", "2:2": "First"}
        )
        self.annotations.save(saved, 42)
        reopened = self.open_view()
        offline = reopened.node_view.details
        tree = offline.node_events.consumed_table
        self.assertEqual(
            [tree.topLevelItem(row).text(0) for row in range(tree.topLevelItemCount())],
            ["0:1", "2:2", "2:10", "10:1"],
        )
        self.assertIsInstance(offline.node, int)
        self.assertEqual(offline.node_name.text(), "West yard")
        self.assertTrue(offline.node_name.isEnabled())
        self.assertEqual(
            offline.node_events.consumed_table.topLevelItem(0).text(1), "Set route"
        )
        self.edit_consumed_description(offline, "Offline route")
        self.assertEqual(
            offline.node_events.consumed_table.topLevelItem(0).text(1), "Offline route"
        )
        self.edit_node_name(offline, "Offline name")
        self.assertEqual(offline.node_name.text(), "Offline name")
        self.assertIn("Offline name", reopened.node_view.node_list.currentItem().text())
        self.view.set_connected(True)
        self.show_state()
        self.view.set_connected(False)
        self.assertEqual(details.node_name.text(), "Offline name")
        self.assertIn(
            "Offline name", self.view.node_view.node_list.currentItem().text()
        )
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).text(1), "Offline route"
        )

    def test_consumed_description_dialog_is_local_and_retains_hardware_ev_editing(self):
        from test_nv_write import Connection

        from workbench.cbus_service import CbusService, DiscoveryProgress
        from workbench.node_backup_files import node_backup

        state = self.show_state()
        state.can_id = 2
        state.stored_event_count = 1
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        connection = Connection()
        service = CbusService(connection, 126)
        self.addCleanup(service.close)
        service.node_states[42] = state
        service.nodes[42] = state.identity
        details = self.view.node_view.details
        details.cbus_service = service
        self.view.node_view.state_lookup = service.node_states.get
        self.view.set_connected(True)
        details.show_live_state(state)
        before = node_backup(state)
        self.annotations.save(
            {
                "name": "Keep name",
                "tokens": {"channel": {"1": "Keep token"}},
                "consumedEvents": {"0:9": "Other event"},
            },
            42,
        )
        self.annotations.save({"events": {"0:1": "Layout name"}})
        self.assertEqual(details.events_edit_button.text(), "Edit")
        self.assertEqual(details.node_events.findChildren(QPushButton), [])
        self.assertEqual(
            details.node_events.consumed_table.headerItem().text(1), "Description"
        )
        self.assertEqual(
            self.edit_consumed_description(details, "Ignored", column=0), []
        )
        self.assertEqual(
            self.edit_consumed_description(details, "Ignored", child=True), []
        )
        self.edit_consumed_description(details, "Set route")
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).text(1), "Set route"
        )
        saved = load_annotations("test", 42)
        self.assertEqual(
            saved,
            {
                "name": "Keep name",
                "tokens": {"channel": {"1": "Keep token"}},
                "consumedEvents": {"0:9": "Other event", "0:1": "Set route"},
            },
        )
        self.assertEqual(load_annotations("test"), {"events": {"0:1": "Layout name"}})
        self.assertEqual(node_backup(state), before)
        self.assertEqual(connection.sent, [])
        self.assertEqual(
            self.edit_layout_description(self.view, "Ignored", produced=True, column=0),
            [],
        )
        self.edit_layout_description(self.view, "From layout")
        self.assertEqual(
            details.node_events.produced_table.item(0, 1).text(), "From layout"
        )
        self.edit_layout_description(self.view, "From produced", produced=True)
        self.assertEqual(
            self.view.layout_events.table.topLevelItem(1).text(1), "From produced"
        )
        self.assertEqual(load_annotations("test", 42), saved)
        self.assertEqual(node_backup(state), before)
        self.assertEqual(connection.sent, [])
        details.tabs.setCurrentWidget(details.consumed_events_page)
        details.events_edit_button.click()
        self.assertEqual(
            self.edit_consumed_description(
                details, "Blocked during configuration edit"
            ),
            [],
        )
        self.click_consumed_cell(details, child=True)
        editor = self.app.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, "8")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).child(0).text(1), "8"
        )
        self.assertEqual(node_backup(state), before)
        self.assertEqual(connection.sent, [])
        details.events_cancel_button.click()
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).text(1), "Set route"
        )
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).child(0).text(1), "5"
        )
        self.edit_consumed_description(details, "")
        self.assertNotIn("0:1", load_annotations("test", 42)["consumedEvents"])
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).text(1), "Layout name"
        )
        self.assertEqual(connection.sent, [])

    def test_consumed_layout_fallback_refresh_edit_and_offline_restart(self):
        from workbench.node_backup_files import node_backup, save_backup

        state = self.show_state()
        details = self.view.node_view.details
        tree = details.node_events.consumed_table
        self.assertEqual(tree.topLevelItem(0).text(1), "")
        layout_names = {"events": {"0:1": "Layout route", "99:9": "Unconsumed"}}
        self.annotations.save(layout_names)
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertEqual(tree.topLevelItem(0).text(1), "Layout route")
        self.assertEqual(load_annotations("test", 42), {})
        self.edit_consumed_description(
            details, "Discarded", save=False, initial="Layout route"
        )
        self.assertEqual(load_annotations("test", 42), {})
        self.edit_consumed_description(details, "Node route", initial="Layout route")
        self.assertEqual(
            load_annotations("test", 42), {"consumedEvents": {"0:1": "Node route"}}
        )
        self.assertEqual(load_annotations("test"), layout_names)
        self.annotations.save({"events": {"0:1": "Updated layout route"}})
        self.assertEqual(tree.topLevelItem(0).text(1), "Node route")
        self.edit_consumed_description(details, "", initial="Node route")
        self.assertEqual(tree.topLevelItem(0).text(1), "Updated layout route")
        save_metadata("test", state)
        save_backup("test", node_backup(state))
        reopened = self.open_view()
        offline = reopened.node_view.details
        offline_tree = offline.node_events.consumed_table
        self.assertEqual(offline_tree.topLevelItem(0).text(1), "Updated layout route")
        self.assertEqual(load_annotations("test", 42), {})
        self.annotations.save({"events": {"0:1": "Offline layout route"}})
        self.assertEqual(offline_tree.topLevelItem(0).text(1), "Offline layout route")
        self.edit_consumed_description(
            offline, "Offline node route", initial="Offline layout route"
        )
        self.assertEqual(
            load_annotations("test", 42),
            {"consumedEvents": {"0:1": "Offline node route"}},
        )
        self.assertEqual(
            load_annotations("test"), {"events": {"0:1": "Offline layout route"}}
        )

    def test_consumed_description_failed_save_keeps_draft_and_saved_value(self):
        self.annotations.save({"consumedEvents": {"0:1": "Saved"}}, 42)
        self.show_state()
        details = self.view.node_view.details
        shown = {}

        def respond(dialog):
            dialog.show()
            self.app.processEvents()
            editor = dialog.findChild(QLineEdit)
            editor.setText("Draft")
            dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Save
            ).click()
            shown["open"] = dialog.isVisible()
            shown["draft"] = editor.text()
            dialog.reject()
            return dialog.result()

        with (
            patch.object(QDialog, "exec", respond),
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            patch("PySide6.QtWidgets.QMessageBox.warning") as warning,
        ):
            self.click_consumed_cell(details)
        self.assertEqual(shown, {"open": True, "draft": "Draft"})
        self.assertEqual(
            load_annotations("test", 42), {"consumedEvents": {"0:1": "Saved"}}
        )
        self.assertEqual(
            details.node_events.consumed_table.topLevelItem(0).text(1), "Saved"
        )
        self.assertIn("disk full", warning.call_args.args[2])

    def edit_token_label(self, label, values, *, save=True, activate=None):
        shown = {}

        def respond(dialog):
            fields = dialog.findChildren(QLineEdit)
            shown["fields"] = {
                field.accessibleName(): field.placeholderText() for field in fields
            }
            shown["context"] = [widget.text() for widget in dialog.findChildren(QLabel)]
            for field in fields:
                if field.accessibleName() in values:
                    field.setText(values[field.accessibleName()])
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(
                QDialogButtonBox.StandardButton.Save
                if save
                else QDialogButtonBox.StandardButton.Cancel
            ).click()
            return QDialog.DialogCode.Accepted if save else QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", respond):
            if activate:
                activate()
            else:
                QTest.mouseDClick(label, Qt.MouseButton.LeftButton)
        return shown

    def token_mdf(self, title="Palette entry ${palette 1}"):
        from workbench.mdfs import Mdf

        data = {
            "moduleName": "Test",
            "tokens": {"palette": {"defaultNames": {"1": "Black / off"}}},
            "nodeVariables": [
                {
                    "type": "NodeVariableNumber",
                    "nodeVariableIndex": 1,
                    "displayTitle": title,
                }
            ],
            "eventVariables": [
                {
                    "type": "EventVariableNumber",
                    "eventVariableIndex": 1,
                    "displayTitle": "Use ${palette1} now",
                }
            ],
        }
        return Mdf(self.root / "Test-0D01-1a.json", data)

    @staticmethod
    def label_with_text(parent, text):
        return next(
            label for label in parent.findChildren(QLabel) if label.text() == text
        )

    def test_offline_mdf_label_edit_save_cancel_defaults_and_nv_ev_occurrences(self):
        mdf = self.token_mdf()
        system = self.root / "mdfs"
        system.mkdir()
        (system / mdf.path.name).write_text(json.dumps(mdf.data))
        self.view.node_view.mdf_repository = MdfRepository(system, self.root / "user")
        state = self.show_state(mdf=mdf)
        save_metadata("test", state)
        self.view.node_view.clear_identities()
        self.view.node_view.show_saved_nodes("test")
        details = self.view.node_view.details
        self.assertEqual(details.details_page.findChildren(QTableWidget), [])
        label = self.label_with_text(details.mdf_values, "Palette entry Black / off:")
        shown = self.edit_token_label(label, {"palette1": "Ignored"}, save=False)
        self.assertEqual(shown["fields"], {"palette1": "Black / off"})
        self.assertEqual(load_annotations("test", 42), {})
        self.edit_token_label(label, {"palette1": "Signal red"})
        self.assertEqual(
            load_annotations("test", 42)["tokens"], {"palette": {"1": "Signal red"}}
        )
        self.label_with_text(details.mdf_values, "Palette entry Signal red:")
        state = self.show_state(mdf=mdf)
        details.node_events.consumed_table.topLevelItem(0).setExpanded(True)
        label = self.label_with_text(
            details.node_events.consumed_table, "Use Signal red now:"
        )
        self.edit_token_label(label, {"palette1": "Signal green"})
        self.label_with_text(details.mdf_values, "Palette entry Signal green:")
        self.label_with_text(
            details.node_events.consumed_table, "Use Signal green now:"
        )
        label = self.label_with_text(details.mdf_values, "Palette entry Signal green:")
        self.edit_token_label(label, {"palette1": ""})
        self.assertNotIn("tokens", load_annotations("test", 42))
        self.label_with_text(details.mdf_values, "Palette entry Black / off:")
        self.assertEqual(
            mdf.data["nodeVariables"][0]["displayTitle"], "Palette entry ${palette 1}"
        )

    def test_multiple_tokens_edit_separately_and_structural_placeholders_are_not_fields(
        self,
    ):
        mdf = self.token_mdf(
            "Output ${index}: ${palette1} / ${channel 2} / ${palette 1}"
        )
        self.show_state(mdf=mdf)
        details = self.view.node_view.details
        label = self.label_with_text(
            details.mdf_values, "Output ${index}: Black / off / channel2 / Black / off:"
        )
        shown = self.edit_token_label(label, {"palette1": "Red", "channel2": "Turnout"})
        self.assertEqual(
            shown["fields"], {"palette1": "Black / off", "channel2": "channel2"}
        )
        self.label_with_text(
            details.mdf_values, "Output ${index}: Red / Turnout / Red:"
        )
        self.assertEqual(
            load_annotations("test", 42)["tokens"],
            {"palette": {"1": "Red"}, "channel": {"2": "Turnout"}},
        )

        saved = load_annotations("test", 42)
        label = self.label_with_text(
            details.mdf_values, "Output ${index}: Red / Turnout / Red:"
        )
        with (
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            patch("workbench.token_label_edit.QMessageBox.warning") as warning,
        ):
            self.edit_token_label(label, {"palette1": "Unsaved"})
        self.assertEqual(load_annotations("test", 42), saved)
        self.assertIn("disk full", warning.call_args.args[2])

    def test_page_group_and_displayed_selection_tokens_are_contextually_editable(self):
        from PySide6.QtWidgets import QComboBox, QGroupBox

        mdf = self.token_mdf()
        mdf.data["nodeVariables"] = [
            {
                "type": "NodeVariableTabs",
                "tabPanels": [
                    {
                        "displayTitle": "${channel1} settings",
                        "items": [
                            {
                                "type": "NodeVariableGroup",
                                "displayTitle": "Route ${palette1}",
                                "groupItems": [
                                    {
                                        "type": "NodeVariableSelect",
                                        "nodeVariableIndex": 1,
                                        "displayTitle": "Choice",
                                        "options": [
                                            {
                                                "value": 4,
                                                "label": "Selected ${palette1}",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        state = self.show_state(mdf=mdf)
        before = dict(state.nv_values)
        details = self.view.node_view.details
        self.view.show()
        details.tabs.setCurrentWidget(details.variables_page)
        self.app.processEvents()
        nav = details.mdf_values.navigation
        item = nav.item(1)

        def activate_page():
            position = nav.visualItemRect(item).center()
            QTest.mouseClick(nav.viewport(), Qt.MouseButton.LeftButton, pos=position)
            QTest.mouseDClick(nav.viewport(), Qt.MouseButton.LeftButton, pos=position)

        shown = self.edit_token_label(
            None, {"channel1": "West"}, activate=activate_page
        )
        self.assertEqual(shown["fields"], {"channel1": "channel1"})
        self.assertEqual(nav.item(1).text(), "West settings")
        form = details.mdf_values.pages.widget(1)
        group = next(
            group
            for group in form.findChildren(QGroupBox)
            if group.title() == "Route Black / off"
        )
        self.edit_token_label(
            group,
            {"palette1": "Red"},
            activate=lambda: QTest.mouseDClick(
                group, Qt.MouseButton.LeftButton, pos=QPoint(12, 10)
            ),
        )
        form = details.mdf_values.pages.widget(1)
        combo = form.findChild(QComboBox)
        self.assertFalse(
            combo.isEnabled()
        )  # Token editing never enables hardware controls.
        shown = self.edit_token_label(
            None,
            {"palette1": "Green"},
            activate=lambda: self.app.sendEvent(
                combo,
                QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    QPoint(2, 2),
                    combo.mapToGlobal(QPoint(2, 2)),
                ),
            ),
        )
        self.assertEqual(shown["fields"], {"palette1": "Black / off"})
        self.assertEqual(
            details.mdf_values.pages.widget(1).findChild(QComboBox).currentText(),
            "Selected Green",
        )
        self.assertEqual(state.nv_values, before)
        self.assertEqual(
            load_annotations("test", 42)["tokens"],
            {"channel": {"1": "West"}, "palette": {"1": "Green"}},
        )

    def test_backups_include_annotations_without_changing_hardware_comparison(self):
        from workbench.cbus_service import DiscoveryProgress
        from workbench.layout_backup_workflow import create_layout_backup
        from workbench.node_backup_diff import compare_live_node
        from workbench.node_backup_files import load_layout_node, node_backup

        state = self.show_state()
        state.stored_event_count = 1
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.annotations.save({"events": {"0:1": "Layout name"}})
        node_names = {
            "name": "West yard",
            "tokens": {"channel": {"1": "Turnout"}},
            "consumedEvents": {"0:1": "Set route"},
        }
        self.annotations.save(node_names, 42)
        with patch(
            "workbench.layout_backup_workflow.QInputDialog.getText",
            return_value=("", True),
        ):
            path = create_layout_backup(self.view, "test", [state])
        manifest = yaml.safe_load(path.read_text())
        self.assertEqual(manifest["annotations"], {"events": {"0:1": "Layout name"}})
        saved = load_layout_node(path, 42)
        self.assertEqual(saved["annotations"], node_names)
        self.assertEqual(
            compare_live_node(state, saved),
            compare_live_node(state, node_backup(state)),
        )
        details = self.view.node_view.details
        with patch(
            "workbench.node_backup_workflow.QInputDialog.getText",
            return_value=("", True),
        ):
            details.backup_workflow.create_live(state, "test")
        newest = details.node_backups.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole)
        self.assertEqual(yaml.safe_load(newest.read_text())["annotations"], node_names)

    def test_offline_restore_checkbox_and_cancel_preserve_hardware_and_legacy_backups(
        self,
    ):
        from PySide6.QtWidgets import QMessageBox
        from test_nv_write import Connection

        from workbench.cbus_service import CbusService
        from workbench.node_backup_files import node_backup, save_backup

        state = self.show_state()
        backup = node_backup(state)
        backup["annotations"] = {
            "name": "Backup name",
            "tokens": {"channel": {"1": "Turnout"}},
            "consumedEvents": {"0:1": "Route"},
        }
        save_backup("test", backup)
        save_metadata("test", state)
        view = self.open_view()
        details = view.node_view.details
        connection = Connection()
        service = CbusService(connection, 126)
        self.addCleanup(service.close)
        details.cbus_service = service
        details.node_backups.setCurrentItem(details.node_backups.topLevelItem(0))
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())
        self.annotations.save({"name": "Existing"}, 42)

        def answer(checked=True, accepted=True):
            def respond(dialog):
                self.assertEqual(dialog.checkBox().text(), "Restore annotations")
                self.assertTrue(dialog.checkBox().isChecked())
                configuration = next(
                    box
                    for box in dialog.findChildren(QCheckBox)
                    if box.text() == "Restore configuration"
                )
                self.assertTrue(configuration.isChecked())
                configuration.setChecked(False)
                dialog.checkBox().setChecked(checked)
                self.assertEqual(
                    dialog.button(QMessageBox.StandardButton.Yes).isEnabled(), checked
                )
                return (
                    QMessageBox.StandardButton.Yes
                    if accepted
                    else QMessageBox.StandardButton.No
                )

            with patch("workbench.node_backup_workflow.QMessageBox.exec", respond):
                details.restore_backup()

        answer(accepted=False)
        self.assertEqual(load_annotations("test", 42), {"name": "Existing"})
        answer(checked=False)
        self.assertEqual(load_annotations("test", 42), {"name": "Existing"})
        answer()
        self.assertEqual(load_annotations("test", 42), backup["annotations"])
        self.assertEqual(details.node_name.text(), "Backup name")
        self.assertEqual(connection.sent, [])
        self.annotations.save({"name": "Keep after failure"}, 42)
        with (
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            patch("workbench.node_backup_workflow.QMessageBox.warning") as warning,
        ):
            answer()
        self.assertEqual(load_annotations("test", 42), {"name": "Keep after failure"})
        self.assertIn("Local annotations could not be saved", warning.call_args.args[2])
        self.assertEqual(connection.sent, [])
        # A legacy backup cannot request annotation restoration.
        legacy = dict(backup)
        del legacy["annotations"]
        save_backup("test", legacy)
        details.node_backups.show_live_node("test", 42)
        details.node_backups.setCurrentItem(details.node_backups.topLevelItem(0))
        self.assertFalse(details.backup_buttons["Restore"].isEnabled())

    def test_save_failure_preserves_saved_names_and_editable_draft(self):
        self.annotations.save({"name": "Saved"}, 42)
        self.show_state()
        details = self.view.node_view.details
        shown = {}

        def respond(dialog):
            dialog.show()
            self.app.processEvents()
            editor = dialog.findChild(QLineEdit)
            editor.setText("Draft")
            dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Save
            ).click()
            shown["open"] = dialog.isVisible()
            shown["draft"] = editor.text()
            dialog.reject()
            return dialog.result()

        with (
            patch.object(QDialog, "exec", respond),
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            patch("workbench.node_name_edit.QMessageBox.warning") as warning,
        ):
            QTest.mouseDClick(details.node_name, Qt.MouseButton.LeftButton)
        self.assertEqual(shown, {"open": True, "draft": "Draft"})
        self.assertEqual(details.node_name.text(), "Saved")
        self.assertIn("disk full", warning.call_args.args[2])
        self.assertEqual(
            yaml.safe_load(annotation_path("test", 42).read_text()), {"name": "Saved"}
        )

    def test_annotation_dialogs_open_at_least_450_pixels_wide_and_remain_resizable(
        self,
    ):
        mdf = self.token_mdf("${palette1}")
        mdf.data["tokens"]["palette"]["defaultNames"]["1"] = "X"
        self.show_state(mdf=mdf)
        details = self.view.node_view.details
        previous_font = self.app.font()
        self.addCleanup(lambda: self.app.setFont(previous_font))
        font = details.font()
        font.setPointSize(16)
        self.app.setFont(font)
        details.setFont(font)
        shown = {}

        def inspect(dialog):
            try:
                initial = dialog.size()  # Actual shown size, before any resizing.
                minimum_width = dialog.minimumWidth()
                dialog.resize(
                    initial
                    + QSize(
                        dialog.fontMetrics().height(), dialog.fontMetrics().height()
                    )
                )
                self.app.processEvents()
                resizable = (
                    dialog.width() > initial.width()
                    and dialog.height() > initial.height()
                )
                shown[dialog.windowTitle()] = (
                    initial.width(),
                    minimum_width,
                    resizable,
                )
            finally:
                dialog.reject()

        # Schedule measurement only when exec begins, then enter the real modal
        # loop so width reflects the shown window rather than a layout hint.
        real_exec = QDialog.exec

        def open_dialog(dialog):
            QTimer.singleShot(0, lambda: inspect(dialog))
            return real_exec(dialog)

        with patch.object(QDialog, "exec", open_dialog):
            QTest.mouseDClick(details.node_name, Qt.MouseButton.LeftButton)
            QTest.mouseDClick(
                self.label_with_text(details.mdf_values, "X:"),
                Qt.MouseButton.LeftButton,
            )
            self.click_consumed_cell(details)
        self.assertEqual(
            set(shown), {"Edit node name", "Edit token names", "Edit event description"}
        )
        for title, (width, minimum_width, resizable) in shown.items():
            with self.subTest(dialog=title):
                self.assertGreaterEqual(width, 450)
                self.assertGreaterEqual(minimum_width, 450)
                self.assertTrue(resizable)
