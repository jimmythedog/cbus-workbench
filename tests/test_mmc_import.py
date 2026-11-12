"""MMC migration preserves local data and never becomes a hardware operation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit
from test_window_startup import RecordingTcpConnection

from workbench.annotations import annotation_path, load_annotations, save_annotations
from workbench.app_settings import SettingsError, load_settings, save_settings
from workbench.layout_settings import LayoutSettingsDialog
from workbench.mmc_import import plan_import, save_import
from workbench.mmc_import_dialog import MmcImportDialog
from workbench.mmc_layouts import find_mmc_layouts, mmc_layouts_directory
from workbench.node_backup_files import saved_node_numbers
from workbench.observed_events import EventIdentity, ObservedEvents
from workbench.pnn import Pnn
from workbench.window import MainWindow


class MmcImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "cw"
        self.settings = self.root / "settings.yaml"
        for module in (
            "annotations",
            "node_backup_files",
            "observed_events",
        ):
            patcher = patch(
                f"workbench.{module}.application_directories",
                return_value={"Data": self.data},
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch(
            "workbench.app_settings.settings_path", return_value=self.settings
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.root / "mmc" / "layouts"

    def fixture(self, folder="Yard", connection=None):
        data = {
            "layoutDetails": {
                "title": folder,
                "subTitle": "Not imported",
                "baseNodeNumber": 200,
            },
            "connectionDetails": connection
            or {"mode": "Network", "host": "hub", "hostPort": "5551"},
            "nodeDetails": {
                "42": {
                    "name": " West yard ",
                    "moduleIdentifer": "ignored",
                    "moduleName": "ignored",
                    "group": "ignored",
                    "channels": {
                        "1": {"channelName": "Old"},
                        "2": {"channelName": "Lamp"},
                    },
                    "tokens": {
                        "Channel": {"userNames": {"01": " Signal "}},
                        "palette": {"userNames": {"1": "Red", "2": " "}},
                    },
                },
                "43": {},
            },
            "eventDetails": {
                "002A0001": {"name": " Route ", "group": "ignored"},
                "00000002": {"name": "Short"},
                "002A0003": {"name": " "},
            },
            "settings": {"ignored": True},
        }
        path = self.source / folder / "layoutData.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def new_settings(self, source, logical_layout):
        return {
            "logical_layout": logical_layout,
            "auto_connect": False,
            "connection": dict(source.connection),
        }

    def window(self):
        window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_import_menu_returns_from_real_dialog_with_destination_visible(self):
        self.fixture("New yard")
        self.fixture("Test Layout")
        save_settings(sample_settings())
        window = self.window()
        window.show()

        # First create a destination, then import a batch ending in an existing
        # destination. Use real modal event loops and the actual menu actions.
        for destination in ("New yard", "Test Layout", None):
            with self.subTest(destination=destination):
                home = next(
                    action
                    for action in window.layout_group.actions()
                    if action.data() == "Home"
                )
                home.trigger()
                errors = []
                handled = set()

                def interact(destination=destination, handled=handled, errors=errors):
                    dialog = self.app.activeModalWidget()
                    if dialog is None or dialog in handled:
                        return
                    handled.add(dialog)
                    try:
                        if isinstance(dialog, MmcImportDialog):
                            if destination is None:
                                dialog.reject()
                                return
                            dialog.load_source(self.source)
                            if destination == "New yard":
                                for row, source in enumerate(dialog.sources):
                                    if source.title == "Test Layout":
                                        dialog.table.item(row, 0).setCheckState(
                                            Qt.CheckState.Unchecked
                                        )
                            # Let this timer callback finish before the click opens
                            # the nested settings dialog, so it can handle that too.
                            QTimer.singleShot(0, dialog.import_button.click)
                        elif isinstance(dialog, LayoutSettingsDialog):
                            if dialog.name_edit.text() == "New yard":
                                dialog.logical_layout_combo.setCurrentText("new-yard")
                            dialog.accept()
                        else:
                            raise TypeError(
                                f"Unexpected dialog: {dialog.windowTitle()}"
                            )
                    except (AssertionError, OSError, ValueError, TypeError) as error:
                        errors.append(error)
                        dialog.reject()

                timer = QTimer()
                timer.timeout.connect(interact)
                timer.start(10)
                try:
                    next(
                        action
                        for action in window.layout_menu.actions()
                        if action.text() == "Import MMC layouts…"
                    ).trigger()
                finally:
                    timer.stop()
                self.app.processEvents()
                self.assertEqual(errors, [])
                selected = destination or "Home"
                self.assertEqual(window.layout_group.checkedAction().data(), selected)
                self.assertEqual(window.layout_status.text(), selected)
                view = window.layouts[selected]
                self.assertIs(window.layout_stack.currentWidget(), view)
                self.assertTrue(view.isVisible())
                self.assertEqual(window.connection_status.text(), "Disconnected")
                if destination is not None:
                    logical = "new-yard" if selected == "New yard" else "test-layout"
                    self.assertEqual(view.node_view.details.logical_layout, logical)
                    self.assertEqual(
                        window.layout_settings[selected]["logical_layout"], logical
                    )
                    self.assertEqual(view.node_view.node_list.count(), 2)
                    self.assertEqual(view.layout_events.table.topLevelItemCount(), 2)
                self.assertFalse(window.connections)
                self.assertFalse(window.cbus_services)

    def test_preview_selected_row_details_follow_destination_and_resize(self):
        self.fixture("Home")
        self.fixture("Yard", {"mode": "SerialPort", "serialPort": "/dev/ttyACM2"})
        save_settings(sample_settings())
        before = self.settings.read_bytes()
        dialog = MmcImportDialog()
        self.addCleanup(dialog.close)
        dialog.load_source(self.source)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(
            [
                dialog.table.horizontalHeaderItem(column).text()
                for column in range(dialog.table.columnCount())
            ],
            ["MMC layout", "CW layout name", "Annotation changes"],
        )
        self.assertTrue(dialog.table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable)
        counts = [dialog.table.item(row, 2).text() for row in range(2)]
        details = dialog.details.toPlainText()
        self.assertIn("Existing CW layout — Home", details)
        self.assertIn("Imported nodes: 2", details)
        self.assertIn("TCP/IP — host: (not set); port: 5550", details)
        self.assertIn("Existing connection settings retained", details)
        self.assertIn("layoutDetails.subTitle", details)
        dialog.table.setCurrentCell(1, 2)
        self.assertIn("New CW layout — Yard", dialog.details.toPlainText())
        self.assertIn("Serial — device: /dev/ttyACM2", dialog.details.toPlainText())
        self.assertEqual([dialog.table.item(row, 2).text() for row in range(2)], counts)
        dialog.resize(500, 400)
        self.app.processEvents()
        self.assertTrue(dialog.details.isReadOnly())
        self.assertEqual(
            dialog.details.lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.assertIn("nodeDetails.moduleIdentifer", dialog.details.toPlainText())
        dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertIn("New CW layout — Yard", dialog.details.toPlainText())
        dialog.table.item(1, 1).setText("Test Layout")
        self.assertIn("Existing CW layout — Test Layout", dialog.details.toPlainText())
        self.assertIn("TCP/IP — host: (not set)", dialog.details.toPlainText())
        self.assertEqual(self.settings.read_bytes(), before)

    def test_real_mmc_mixed_objects_import_only_node_and_event_records(self):
        # Reduced from real TEST/UMBERLEIGH/DEFAULT LAYOUT files: complete TEST
        # node records, node-shaped metadata, non-events and a null event name.
        source = find_mmc_layouts(
            Path(__file__).parent / "fixtures" / "mmc-layout.json"
        )[0]
        self.assertEqual(set(source.nodes), {258})
        self.assertEqual(
            source.annotations,
            {"events": {"258:1": "Close button", "258:2": "Throw button"}},
        )
        plan = plan_import(
            [(source, "Real MMC")],
            False,
            {"Real MMC": self.new_settings(source, "real-mmc")},
        )
        save_import(plan)
        logical = plan.targets[0].logical_layout
        self.assertEqual(saved_node_numbers(logical), [258])
        self.assertFalse(annotation_path(logical, 0).parent.exists())
        self.assertFalse(
            annotation_path(logical)
            .parent.joinpath("nodes", "updateTimestamp")
            .exists()
        )
        self.assertEqual(
            load_annotations(logical, 258),
            {
                "tokens": {
                    "channel": {
                        "1": "Button close",
                        "2": "Button throw",
                        "3": "LED Thrown",
                        "4": "LED Closed",
                        "8": "Turnout servo",
                    }
                }
            },
        )
        self.assertEqual(load_annotations(logical), source.annotations)

    def test_dialog_imports_selected_layouts_restart_offline_and_no_connection(self):
        self.fixture()
        self.fixture("Branch", {"mode": "SerialPort", "serialPort": "COM3"})
        self.fixture("Omitted")
        window = self.window()
        source_bytes = {
            p: p.read_bytes() for p in self.source.glob("*/layoutData.json")
        }

        def confirm(dialog):
            self.assertFalse(dialog.overwrite.isChecked())
            dialog.load_source(self.source)
            for row, source in enumerate(dialog.sources):
                if source.title == "Yard":
                    dialog.table.item(row, 1).setText("My yard")
                if source.title == "Omitted":
                    dialog.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            self.assertTrue(dialog.import_button.isEnabled())
            dialog.import_button.click()
            return dialog.result()

        def review(dialog):
            self.assertFalse(dialog.auto_connect_check.isChecked())
            self.assertFalse(dialog.auto_connect_check.isEnabled())
            self.assertEqual(dialog.logical_layout_combo.currentText(), "")
            self.assertFalse(self.settings.exists())
            if dialog.name_edit.text() == "Branch":
                self.assertEqual(dialog.connection_type_combo.currentText(), "Serial")
                self.assertEqual(dialog.serial_port_edit.text(), "COM3")
                dialog.name_edit.setText("Branch reviewed")
                dialog.logical_layout_combo.setCurrentText("branch-data")
                dialog.serial_port_edit.setText("COM4")
            else:
                self.assertEqual(dialog.name_edit.text(), "My yard")
                self.assertEqual(dialog.host_edit.text(), "hub")
                self.assertEqual(dialog.port_spin.value(), 5551)
                dialog.logical_layout_combo.setCurrentText("yard-data")
                dialog.host_edit.setText("reviewed-hub")
            return QDialog.DialogCode.Accepted

        with (
            patch.object(MmcImportDialog, "exec", confirm),
            patch.object(LayoutSettingsDialog, "exec", review),
        ):
            window.import_mmc_layouts()
        self.app.processEvents()
        saved = load_settings()
        self.assertEqual(set(saved["layouts"]), {"My yard", "Branch reviewed"})
        yard = saved["layouts"]["My yard"]
        serial = saved["layouts"]["Branch reviewed"]
        self.assertNotEqual(yard["logical_layout"], serial["logical_layout"])
        self.assertFalse(yard["auto_connect"])
        self.assertEqual(yard["connection"]["port"], 5551)
        self.assertEqual(serial["connection"]["serial_port"], "COM4")
        self.assertEqual(serial["logical_layout"], "branch-data")
        self.assertEqual(yard["logical_layout"], "yard-data")
        self.assertEqual(yard["connection"]["host"], "reviewed-hub")
        self.assertEqual(window.layout_group.checkedAction().data(), "My yard")
        self.assertEqual(window.layout_status.text(), "My yard")
        self.assertIs(window.layout_stack.currentWidget(), window.layouts["My yard"])
        self.assertEqual(window.layouts["My yard"].node_view.node_list.count(), 2)
        self.assertEqual(
            window.layouts["My yard"].layout_events.table.topLevelItemCount(), 2
        )
        self.assertEqual(window.connections, {})
        self.assertEqual(window.cbus_services, {})
        window.close()
        reopened = self.window()
        self.app.processEvents()
        self.assertEqual(reopened.connections, {})
        logical = yard["logical_layout"]
        self.assertEqual(
            load_annotations(logical, 42),
            {
                "name": "West yard",
                "tokens": {
                    "channel": {"1": "Signal", "2": "Lamp"},
                    "palette": {"1": "Red"},
                },
            },
        )
        self.assertEqual(saved_node_numbers(logical), [42, 43])
        view = reopened.layouts["My yard"]
        action = next(
            action
            for action in reopened.layout_group.actions()
            if action.data() == "My yard"
        )
        action.setChecked(True)
        reopened.select_layout(action)
        self.assertEqual(view.node_view.node_list.count(), 2)
        self.assertIn("Offline", view.node_view.node_list.item(0).text())
        self.assertIsInstance(
            view.node_view.node_list.item(0).data(Qt.ItemDataRole.UserRole), int
        )
        table = view.layout_events.table
        self.assertEqual(
            {
                table.topLevelItem(i).text(0): table.topLevelItem(i).text(1)
                for i in range(table.topLevelItemCount())
            },
            {"0:2": "Short", "42:1": "Route"},
        )
        self.assertEqual(
            ObservedEvents(logical).events, {EventIdentity(42, 1), EventIdentity(0, 2)}
        )
        produced = view.node_view.details.node_events
        produced.show_produced_events(42)
        self.assertEqual(produced.produced_table.rowCount(), 1)
        self.assertEqual(produced.produced_table.item(0, 0).text(), "42:1")
        self.assertEqual(produced.produced_table.item(0, 1).text(), "Route")
        produced.show_produced_events(43)
        self.assertEqual(produced.produced_table.rowCount(), 0)
        self.assertFalse(
            list(annotation_path(logical).parent.glob("nodes/*/metadata.yaml"))
        )
        view.node_view.show_identity(Pnn(42, 13, 1, 5))
        view.node_view.refresh_annotation_names()
        self.assertIn("West yard", view.node_view.node_list.item(0).text())
        self.assertEqual(
            load_annotations(logical, 42)["tokens"]["channel"]["1"], "Signal"
        )
        self.assertEqual({p: p.read_bytes() for p in source_bytes}, source_bytes)

    def test_existing_layout_merge_overwrite_counts_and_unrelated_data(self):
        source = find_mmc_layouts(self.fixture())[0]
        save_settings(sample_settings())
        save_annotations(
            "home",
            {"events": {"42:1": "Existing", "42:3": "Keep blank", "99:1": "Unrelated"}},
        )
        save_annotations(
            "home",
            {
                "name": "Existing node",
                "tokens": {"channel": {"1": "Existing channel", "9": "Keep"}},
                "consumedEvents": {"0:1": "Keep consumed"},
            },
            42,
        )
        directory = annotation_path("home", 42).parent
        metadata = directory / "metadata.yaml"
        metadata.write_text("parameters: [null, 13]\ncanId: 20\n")
        backups = directory / "backups"
        backups.mkdir()
        backup = backups / "saved.yaml"
        backup.write_text("unchanged backup")
        observations = ObservedEvents("home")
        observations.observe(EventIdentity(99, 1))
        unchanged = {p: p.read_bytes() for p in (self.settings, metadata, backup)}
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                plan = plan_import([(source, "hOmE")], overwrite)
                target = plan.targets[0]
                self.assertFalse(target.new)
                self.assertEqual(target.logical_layout, "home")
                if not overwrite:
                    self.assertEqual(
                        target.counts, {"added": 3, "replaced": 0, "preserved": 3}
                    )
                else:
                    self.assertEqual(
                        target.counts, {"added": 0, "replaced": 6, "preserved": 0}
                    )
                save_import(plan)
                self.assertEqual(
                    load_annotations("home", 42)["name"],
                    "West yard" if overwrite else "Existing node",
                )
                self.assertEqual(
                    load_annotations("home", 42)["tokens"]["channel"]["1"],
                    "Signal" if overwrite else "Existing channel",
                )
                self.assertEqual(
                    load_annotations("home")["events"]["42:1"],
                    "Route" if overwrite else "Existing",
                )
                self.assertEqual(
                    load_annotations("home")["events"]["42:3"], "Keep blank"
                )
                self.assertEqual(
                    load_annotations("home")["events"]["99:1"], "Unrelated"
                )
                self.assertEqual(
                    load_annotations("home", 42)["tokens"]["channel"]["9"], "Keep"
                )
                self.assertEqual(
                    load_annotations("home", 42)["consumedEvents"],
                    {"0:1": "Keep consumed"},
                )
                self.assertEqual({p: p.read_bytes() for p in unchanged}, unchanged)
                self.assertEqual(
                    ObservedEvents("home").events,
                    {EventIdentity(99, 1), EventIdentity(42, 1), EventIdentity(0, 2)},
                )
                persisted = observations.path.read_bytes()
                save_import(plan_import([(source, "Home")], overwrite))
                self.assertEqual(observations.path.read_bytes(), persisted)

    def test_unnamed_mmc_events_preserve_existing_descriptions_with_overwrite(self):
        path = self.fixture()
        data = json.loads(path.read_text())
        data["eventDetails"] = {
            "002A0001": {},
            "002A0002": {"name": None},
            "002A0003": {"name": "  \t"},
        }
        path.write_text(json.dumps(data))
        save_settings(sample_settings())
        existing = {"events": {"42:1": "Missing", "42:2": "Null", "42:3": "Blank"}}
        save_annotations("home", existing)
        source = find_mmc_layouts(path)[0]
        self.assertEqual(source.annotations, {})
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                save_import(plan_import([(source, "Home")], overwrite))
                self.assertEqual(load_annotations("home"), existing)
                self.assertEqual(ObservedEvents("home").events, set())

    def test_connected_import_keeps_received_events_live_in_both_panes(self):
        source = find_mmc_layouts(self.fixture())[0]
        settings = sample_settings()
        settings["layouts"]["Home"]["connection"]["host"] = "test-hub"
        save_settings(settings)
        window = self.window()
        with patch("workbench.window.TcpConnection", RecordingTcpConnection):
            window.toggle_connection()
        connection = window.connections["Home"]
        service = window.cbus_services["Home"]
        sent_before = list(connection.sent)
        plan = plan_import([(source, "Home")], False)

        def import_dialog(dialog):
            save_import(plan)
            dialog.result_plan = plan
            return QDialog.DialogCode.Accepted

        with patch.object(MmcImportDialog, "exec", import_dialog):
            window.import_mmc_layouts()
        self.assertIs(window.cbus_services["Home"], service)
        self.assertEqual(window.connection_status.text(), "Connected")
        self.assertEqual(connection.sent, sent_before)
        view = window.layouts["Home"]
        for row in range(view.node_view.node_list.count()):
            item = view.node_view.node_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == 42:
                view.node_view.node_list.setCurrentItem(item)
                break
        produced = view.node_view.details.node_events.produced_table
        self.assertEqual(produced.rowCount(), 1)
        connection.frame_received.emit(b":SB040N90002A0004;")
        table = view.layout_events.table
        self.assertEqual(
            {
                table.topLevelItem(row).text(0)
                for row in range(table.topLevelItemCount())
            },
            {"0:2", "42:1", "42:4"},
        )
        self.assertEqual(
            {produced.item(row, 0).text() for row in range(produced.rowCount())},
            {"42:1", "42:4"},
        )
        self.assertEqual(
            ObservedEvents("home").events,
            {EventIdentity(0, 2), EventIdentity(42, 1), EventIdentity(42, 4)},
        )

    def test_existing_open_layout_refreshes_imported_events_and_restart(self):
        source = find_mmc_layouts(self.fixture())[0]
        save_settings(sample_settings())
        save_annotations("home", {"events": {"42:1": "Existing", "99:1": "Keep"}})
        ObservedEvents("home").observe(EventIdentity(99, 1))
        window = self.window()
        plan = plan_import([(source, "Home")], False)

        def import_dialog(dialog):
            save_import(plan)
            dialog.result_plan = plan
            return QDialog.DialogCode.Accepted

        with patch.object(MmcImportDialog, "exec", import_dialog):
            window.import_mmc_layouts()
        table = window.layouts["Home"].layout_events.table
        self.assertEqual(
            {
                table.topLevelItem(i).text(0): table.topLevelItem(i).text(1)
                for i in range(table.topLevelItemCount())
            },
            {"0:2": "Short", "42:1": "Existing", "99:1": "Keep"},
        )
        self.assertFalse(window.connections)
        self.assertFalse(window.cbus_services)
        window.close()
        restarted = self.window()
        table = restarted.layouts["Home"].layout_events.table
        self.assertEqual(table.topLevelItemCount(), 3)
        produced = restarted.layouts["Home"].node_view.details.node_events
        produced.show_produced_events(42)
        self.assertEqual(produced.produced_table.rowCount(), 1)
        self.assertEqual(produced.produced_table.item(0, 0).text(), "42:1")
        self.assertEqual(produced.produced_table.item(0, 1).text(), "Existing")
        produced.show_produced_events(99)
        self.assertEqual(produced.produced_table.item(0, 0).text(), "99:1")
        self.assertEqual(produced.produced_table.item(0, 1).text(), "Keep")

    def test_cancel_layout_review_leaves_batch_untouched(self):
        self.fixture("First")
        self.fixture("Home")
        self.fixture("Last")
        save_settings(sample_settings())
        save_annotations("home", {"name": "Original"}, 42)
        before = self.settings.read_bytes()
        dialog = MmcImportDialog()
        self.addCleanup(dialog.close)
        dialog.load_source(self.source)
        dialog.overwrite.setChecked(True)

        def review(settings_dialog):
            if settings_dialog.name_edit.text() == "Last":
                return QDialog.DialogCode.Rejected
            settings_dialog.logical_layout_combo.setCurrentText("first-data")
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", review):
            dialog.import_button.click()
        self.assertIsNone(dialog.result_plan)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(load_annotations("home", 42), {"name": "Original"})
        self.assertFalse(annotation_path("first-data").parent.exists())
        for row, source in enumerate(dialog.sources):
            if source.title != "Home":
                dialog.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        with patch.object(
            LayoutSettingsDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            dialog.import_button.click()
        self.assertIsNone(dialog.result_plan)
        self.assertEqual(load_annotations("home", 42), {"name": "Original"})

        def confirm_existing(settings_dialog):
            self.assertEqual(settings_dialog.name_edit.text(), "Home")
            self.assertEqual(settings_dialog.logical_layout_combo.currentText(), "home")
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", confirm_existing):
            dialog.import_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_plan.targets[0].logical_layout, "home")
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(load_annotations("home", 42)["name"], "West yard")

    def test_every_proposal_is_reviewed_and_confirmed_id_controls_destination(self):
        sources = {name: self.fixture(name) for name in ("Home", "New MMC")}
        saved = sample_settings()
        saved["layouts"]["Home"]["connection"]["host"] = "home-hub"
        save_settings(saved)
        save_annotations("home", {"name": "Keep original destination"}, 42)
        save_annotations("test-layout", {"name": "Keep target annotation"}, 42)
        window = self.window()

        for proposed, confirmed, logical in (
            ("Home", "Home", "test-layout"),
            ("New MMC", "Reviewed new", "test-layout"),
        ):
            with self.subTest(proposed=proposed):

                def confirm(dialog, proposed=proposed):
                    dialog.load_source(sources[proposed])
                    dialog.import_button.click()
                    return dialog.result()

                def review(
                    settings_dialog,
                    proposed=proposed,
                    confirmed=confirmed,
                    logical=logical,
                ):
                    self.assertEqual(settings_dialog.name_edit.text(), proposed)
                    self.assertEqual(
                        settings_dialog.logical_layout_combo.currentText(),
                        "home" if proposed == "Home" else "",
                    )
                    self.assertEqual(
                        settings_dialog.host_edit.text(),
                        "home-hub" if proposed == "Home" else "hub",
                    )
                    settings_dialog.name_edit.setText(confirmed)
                    settings_dialog.logical_layout_combo.setCurrentText(logical)
                    settings_dialog.host_edit.setText("reviewed-hub")
                    return QDialog.DialogCode.Accepted

                with (
                    patch.object(MmcImportDialog, "exec", confirm),
                    patch.object(LayoutSettingsDialog, "exec", review),
                ):
                    window.import_mmc_layouts()
                self.assertEqual(
                    window.layout_settings[confirmed]["logical_layout"], logical
                )
                self.assertEqual(
                    window.layouts[confirmed].node_view.details.logical_layout, logical
                )
                self.assertEqual(window.layout_group.checkedAction().data(), confirmed)
                self.assertEqual(window.layout_status.text(), confirmed)
                self.assertIs(
                    window.layout_stack.currentWidget(), window.layouts[confirmed]
                )
                self.assertEqual(
                    window.layouts[confirmed].node_view.node_list.count(), 2
                )
                self.assertEqual(
                    window.layouts[confirmed].layout_events.table.topLevelItemCount(), 2
                )
                current = load_settings()["layouts"][confirmed]
                self.assertEqual(current["logical_layout"], logical)
                self.assertEqual(current["connection"]["host"], "reviewed-hub")
                self.assertEqual(
                    load_annotations(logical, 42)["name"],
                    "Keep target annotation"
                    if logical == "test-layout"
                    else "West yard",
                )
        with patch.object(
            MmcImportDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            window.import_mmc_layouts()
        self.assertEqual(window.layout_group.checkedAction().data(), "Reviewed new")
        self.assertEqual(window.layout_status.text(), "Reviewed new")
        self.assertIs(
            window.layout_stack.currentWidget(), window.layouts["Reviewed new"]
        )
        self.assertFalse(window.connections)
        self.assertFalse(window.cbus_services)
        self.assertEqual(
            load_annotations("home", 42)["name"], "Keep original destination"
        )

    def test_unsupported_connection_and_confirmed_directory_reuse(self):
        source = find_mmc_layouts(self.fixture(connection={"mode": "Auto"}))[0]
        save_settings(sample_settings())
        orphan = self.data / "layouts" / "orphan"
        orphan.mkdir(parents=True)
        marker = orphan / "keep.txt"
        marker.write_text("keep")
        preview = plan_import([(source, "New")], True)
        with self.assertRaises(SettingsError):
            save_import(preview)
        for logical in ("", "..", "../outside"):
            with self.assertRaises(ValueError):
                plan_import(
                    [(source, "New")], True, {"New": self.new_settings(source, logical)}
                )
        plan = plan_import(
            [(source, "New")], True, {"New": self.new_settings(source, "orphan")}
        )
        save_import(plan)
        self.assertEqual(plan.targets[0].logical_layout, "orphan")
        self.assertEqual(marker.read_text(), "keep")
        self.assertFalse(load_settings()["layouts"]["New"]["auto_connect"])
        self.assertEqual(load_annotations("orphan", 42)["name"], "West yard")
        for connection in (
            None,
            {},
            {"mode": "Unknown"},
            {"mode": "Network", "host": "hub", "hostPort": "bad"},
        ):
            path = self.source / "Yard" / "layoutData.json"
            data = json.loads(path.read_text())
            data["connectionDetails"] = connection
            path.write_text(json.dumps(data))
            self.assertTrue(
                plan_import([(find_mmc_layouts(path)[0], "New")], False).targets
            )

    def test_invalid_input_cancel_and_failed_saves_leave_no_partial_annotations(self):
        source = find_mmc_layouts(self.fixture())[0]
        save_settings(sample_settings())
        save_annotations("home", {"events": {"42:1": "Original"}})
        save_annotations("home", {"name": "Original node"}, 42)
        original_settings = self.settings.read_bytes()
        original_layout = load_annotations("home")
        original_node = load_annotations("home", 42)
        observations = ObservedEvents("home")
        observations.observe(EventIdentity(99, 1))
        original_observations = observations.path.read_bytes()
        window = self.window()
        with patch.object(
            MmcImportDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            window.import_mmc_layouts()
        self.assertEqual(self.settings.read_bytes(), original_settings)
        bad = self.source / "Bad" / "layoutData.json"
        bad.parent.mkdir()
        for contents in (
            "{",
            '{"nodeDetails":{"-1":{}}}',
            '{"nodeDetails":{"65536":{}}}',
            '{"nodeDetails":{"42":null}}',
            '{"nodeDetails":{"42":{"name":123}}}',
            '{"eventDetails":{"002A0001":{"name":123}}}',
        ):
            bad.write_text(contents)
            with self.assertRaises((ValueError, TypeError)):
                find_mmc_layouts(self.source)
            self.assertEqual(load_annotations("home"), original_layout)
        with self.assertRaises(ValueError):
            plan_import([(source, "Home"), (source, "home")], False)
        for failure in ("annotation", "observations", "settings"):
            plan = plan_import(
                [(source, "Home"), (source, "New")],
                True,
                {
                    "Home": load_settings()["layouts"]["Home"],
                    "New": self.new_settings(source, "new-import"),
                },
            )
            real_save = save_annotations
            real_observe = ObservedEvents.observe

            def observe(
                collection, identity, failure=failure, real_observe=real_observe
            ):
                real_observe(collection, identity)
                if failure == "observations":
                    raise OSError("Observed-event save failed")

            def save(logical, data, number=None, failure=failure, real_save=real_save):
                if failure == "annotation" and logical != "home" and number == 42:
                    raise OSError("Disk write failed")
                real_save(logical, data, number)

            with (
                patch("workbench.mmc_import.save_annotations", side_effect=save),
                patch.object(ObservedEvents, "observe", observe),
                patch(
                    "workbench.mmc_import.save_settings",
                    side_effect=SettingsError("Settings write failed"),
                ),
                self.assertRaises((OSError, SettingsError)),
            ):
                save_import(plan)
            self.assertEqual(self.settings.read_bytes(), original_settings)
            self.assertEqual(load_annotations("home"), original_layout)
            self.assertEqual(load_annotations("home", 42), original_node)
            self.assertEqual(observations.path.read_bytes(), original_observations)
            self.assertFalse(annotation_path("home", 43).exists())
            self.assertFalse(
                annotation_path(plan.targets[1].logical_layout).parent.exists()
            )

    def test_directory_detection_os_defaults_custom_and_read_only_fallback(self):
        home = self.root / "home"
        home.mkdir()
        base = home / "MMC-SERVER"
        layouts = base / "layouts"
        layouts.mkdir(parents=True)
        custom = self.root / "custom"
        (custom / "layouts").mkdir(parents=True)
        original_read = Path.read_text
        original_iter = Path.iterdir
        for platform in ("linux", "darwin", "win32"):
            # On Linux, the Windows spelling is a relative path; resolve it inside
            # this fixture to exercise the actual Windows base constant safely.
            def redirected_read(path, *args, **kwargs):
                if str(path) == "C:/ProgramData/MMC-SERVER/appSettings.json":
                    path = base / "appSettings.json"
                return original_read(path, *args, **kwargs)

            def redirected_iter(path):
                if str(path) == "C:/ProgramData/MMC-SERVER/layouts":
                    return original_iter(layouts)
                return original_iter(path)

            with (
                patch("workbench.mmc_layouts.sys.platform", platform),
                patch("pathlib.Path.home", return_value=home),
                patch.object(Path, "read_text", redirected_read),
                patch.object(Path, "iterdir", redirected_iter),
            ):
                expected = (
                    Path("C:/ProgramData/MMC-SERVER/layouts")
                    if platform == "win32"
                    else layouts
                )
                settings = base / "appSettings.json"
                settings.write_text(
                    json.dumps(
                        {"userDataMode": "APP", "customUserDirectory": str(custom)}
                    )
                )
                self.assertEqual(mmc_layouts_directory(), expected)
                settings.write_text(
                    json.dumps(
                        {"userDataMode": "CUSTOM", "customUserDirectory": str(custom)}
                    )
                )
                before = settings.read_bytes()
                self.assertEqual(mmc_layouts_directory(), custom / "layouts")
                self.assertEqual(settings.read_bytes(), before)
                with patch.object(
                    Path, "iterdir", side_effect=PermissionError("Cannot list")
                ):
                    self.assertEqual(mmc_layouts_directory(), home)
                for invalid in ("", None, str(self.root / "missing")):
                    settings.write_text(
                        json.dumps(
                            {"userDataMode": "CUSTOM", "customUserDirectory": invalid}
                        )
                    )
                    self.assertEqual(mmc_layouts_directory(), expected)
                settings.write_text("bad json")
                self.assertEqual(mmc_layouts_directory(), expected)
        with patch("pathlib.Path.home", return_value=self.root / "absent"):
            self.assertEqual(mmc_layouts_directory(), self.root / "absent")
            self.assertFalse((self.root / "absent").exists())
