"""Module descriptor display follows live discovery and existing offline behaviour."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
)
from test_cbus_service import ConnectionStub

from workbench.cbus_service import CbusService
from workbench.layout_view import LayoutView
from workbench.mdfs import MdfRepository
from workbench.node_backup_files import backup_directory
from workbench.node_metadata import save_metadata
from workbench.window import MainWindow

FIXTURES = Path(__file__).parent / "fixtures" / "mdfs"
ACE = "CANACE3-A504-2g.json"
GATE = "CANGATE-A54B-1b.json"


class NodeMdfDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.system = self.root / "system"
        self.user = self.root / "user"
        self.system.mkdir()
        self.user.mkdir()
        data_paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": self.root / "data"},
        )
        data_paths.start()
        self.addCleanup(data_paths.stop)
        self.layout = LayoutView(empty=True)
        self.addCleanup(self.layout.close)
        self.view = self.layout.node_view
        self.view.mdf_repository = MdfRepository(self.system, self.user)
        self.details = self.view.details
        self.label = self.details.details_page.module_descriptor
        self.connection = ConnectionStub("MDF test")
        self.service = CbusService(self.connection, can_id=126)
        self.addCleanup(self.service.close)
        self.details.cbus_service = self.service
        self.view.state_lookup = self.service.node_states.get
        self.service.node_discovered.connect(self.view.show_identity)
        self.service.node_updated.connect(self.view.show_identity)
        self.service.node_state_updated.connect(self.view.refresh_state)
        self.layout.set_connected(True)

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def discover(self, number=42, module=4, major=2, minor="g"):
        self.reply(f"B6{number:04X}A5{module:02X}04")
        for index, value in ((1, 165), (3, module), (7, major), (2, ord(minor))):
            self.reply(f"9B{number:04X}{index:02X}{value:02X}")

    def supported_descriptor(self):
        data = json.loads((FIXTURES / ACE).read_text())
        data["nodeVariables"] = [
            {
                "type": "NodeVariableTabs",
                "tabPanels": [
                    {"displayTitle": "Mode", "items": data["nodeVariables"]},
                    {
                        "displayTitle": "Timing",
                        "items": [
                            {
                                "type": "NodeVariableNumber",
                                "nodeVariableIndex": 2,
                                "displayTitle": "Delay",
                            }
                        ],
                    },
                ],
            }
        ]
        (self.system / ACE).write_text(json.dumps(data))

    def test_large_mdf_scrolls_without_resizing_main_window_on_node_selection(self):
        for filename in (ACE, "CANACE8C-A505-2q.json"):
            shutil.copy(FIXTURES / filename, self.system / filename)
        with patch(
            "workbench.window.load_settings",
            return_value={"default_layout": None, "layouts": {}},
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window.layout_stack.addWidget(self.layout)
        window.layout_stack.setCurrentWidget(self.layout)
        self.details.tabs.setCurrentWidget(self.details.variables_page)
        window.show()
        QTest.qWait(100)  # Let posted layout requests reach the top-level window.
        normal_height = window.height()
        self.assertLessEqual(
            normal_height, window.screen().availableGeometry().height()
        )

        self.discover()  # Small CANACE3 MDF, selected first.
        self.discover(number=43, module=5, major=2, minor="q")
        for row in (1, 0, 1):  # Large, small, then large again.
            self.view.node_list.setCurrentRow(row)
            mdf = self.details.mdf_values
            self.assertIs(self.details.variables.currentWidget(), mdf)
            self.assertIs(mdf.pages.currentWidget(), mdf.raw_values)
            QTest.qWait(100)
            self.assertEqual(window.height(), normal_height)

            mdf.navigation.setCurrentRow(1)
            QTest.qWait(100)
            self.assertEqual(window.height(), normal_height)
            if row == 1:
                settings = mdf.pages.currentWidget()
                groups = settings.findChildren(QGroupBox)
                self.assertEqual(len(groups), 9)
                viewport = settings.viewport()
                self.assertTrue(
                    viewport.rect().contains(groups[0].mapTo(viewport, QPoint(0, 0)))
                )
                scrollbar = settings.verticalScrollBar()
                self.assertGreater(scrollbar.maximum(), 0)
                scrollbar.setValue(scrollbar.maximum())
                QTest.qWait(100)
                bottom = groups[-1].mapTo(viewport, QPoint(0, groups[-1].height() - 1))
                self.assertTrue(viewport.rect().contains(bottom))
                self.assertEqual(window.height(), normal_height)

    def test_live_forms_follow_selection_discovery_and_raw_access(self):
        self.supported_descriptor()
        self.discover()
        view = self.details.mdf_values
        self.assertIs(self.details.variables.currentWidget(), view)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(3)],
            ["Raw Values", "Mode", "Timing"],
        )
        view.navigation.setCurrentRow(1)
        combo = view.pages.currentWidget().findChild(QComboBox)
        self.assertEqual(combo.currentIndex(), -1)
        self.reply("9B002A0602")  # Confirm two NVs, neither read yet.
        self.assertEqual(view.navigation.currentRow(), 1)
        self.service.record_nv(42, 1, 0)  # Confirmed zero is a real option.
        self.assertEqual(combo.currentData(), 0)
        self.service.record_nv(42, 2, 12)
        view.navigation.setCurrentRow(2)
        self.assertEqual(
            view.pages.currentWidget().findChild(QDoubleSpinBox).value(), 12
        )
        view.navigation.setCurrentRow(0)
        self.assertEqual(
            [view.raw_values.item(i, 1).text() for i in range(2)], ["0", "12"]
        )
        self.assertFalse(combo.isEnabled())
        self.discover(number=43, module=0x4B, major=1, minor="b")
        self.view.node_list.setCurrentRow(1)
        self.assertIs(self.details.variables.currentWidget(), self.details.raw_values)
        self.view.node_list.setCurrentRow(0)
        self.assertIs(self.details.variables.currentWidget(), view)
        view.navigation.setCurrentRow(1)
        self.assertEqual(
            view.pages.currentWidget().findChild(QComboBox).currentData(), 0
        )

    def test_partial_forms_preserve_order_omit_empty_panels_and_keep_raw_access(self):
        self.supported_descriptor()
        path = self.system / ACE
        data = json.loads(path.read_text())
        panels = data["nodeVariables"][0]["tabPanels"]
        unsupported = {"type": "NodeVariableUnknown"}
        panels[0]["items"] = [
            unsupported,
            *panels[0]["items"],
            unsupported,
            {
                "type": "NodeVariableNumber",
                "nodeVariableIndex": 2,
                "displayTitle": "Last",
            },
            unsupported,
        ]
        panels[1]["items"] = [unsupported]
        panels.append({"displayTitle": "Empty", "items": []})
        path.write_text(json.dumps(data))
        self.discover()
        self.service.record_nv(42, 1, 0)
        self.service.record_nv(42, 2, 12)
        view = self.details.mdf_values
        self.assertIs(self.details.variables.currentWidget(), view)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(view.navigation.count())],
            ["Raw Values", "Mode"],
        )
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        layout = form.widget().layout()
        self.assertEqual(
            [
                layout.itemAt(i, layout.ItemRole.LabelRole).widget().text()
                for i in range(layout.rowCount())
            ],
            ["Mode Select:", "Last:"],
        )
        self.assertEqual(form.findChild(QComboBox).currentData(), 0)
        self.assertEqual(form.findChild(QDoubleSpinBox).value(), 12)
        self.assertFalse(form.findChild(QDoubleSpinBox).isEnabled())
        view.navigation.setCurrentRow(0)
        self.assertEqual(view.raw_values.item(1, 1).text(), "12")

        # A valid descriptor with no supported settings has just the raw view.
        panels[0]["items"] = [unsupported]
        path.write_text(json.dumps(data))
        self.view.refresh_state(42)
        self.assertIs(self.details.variables.currentWidget(), self.details.raw_values)
        self.assertEqual(view.navigation.count(), 1)
        self.assertEqual(self.details.raw_values.item(1, 1).text(), "12")
        self.assertEqual(self.label.text(), f"{ACE} (System)")

    def test_system_mdf_appears_when_firmware_is_confirmed(self):
        shutil.copy(FIXTURES / ACE, self.system)
        self.assertEqual(self.label.text(), "None")
        self.reply("B6002AA50404")
        self.assertEqual(self.label.text(), "None")
        self.reply("9B002A0702")
        self.assertEqual(self.label.text(), "None")
        self.reply("9B002A0267")
        self.assertEqual(self.label.text(), f"{ACE} (System)")
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANACE3 (Online)")
        self.assertEqual(self.details.module_type.text(), "CANACE3")
        self.assertEqual(self.details.summary.title(), "Node 42 — CANACE3")
        self.assertEqual(self.label.toolTip(), str(self.system / ACE))
        self.assertEqual(self.details.status.text(), "Online")
        # The real flat fixture used to fall back to Raw Values only.
        view = self.details.mdf_values
        self.assertIs(self.details.variables.currentWidget(), view)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(2)],
            ["Raw Values", "Settings"],
        )
        view.navigation.setCurrentRow(1)
        combo = view.pages.currentWidget().findChild(QComboBox)
        self.assertEqual(combo.currentIndex(), -1)
        self.service.record_nv(42, 1, 2)
        self.assertEqual(combo.currentData(), 2)
        view.navigation.setCurrentRow(0)
        self.assertEqual(view.raw_values.item(0, 1).text(), "2")

    def test_names_refresh_after_discovery_restores_selection(self):
        for filename in (ACE, GATE):
            shutil.copy(FIXTURES / filename, self.system)
        self.discover()
        self.discover(number=43, module=0x4B, major=1, minor="b")
        self.view.node_list.setCurrentRow(1)

        for status in ("Configuration ready", "Discovery incomplete"):
            with self.subTest(status=status):
                self.view.begin_discovery()
                self.discover()
                self.discover(number=43, module=0x4B, major=1, minor="b")
                self.service.record_nv(42, 1, 12)
                self.service.record_nv(43, 1, 34)
                self.view.refresh_state(42)
                self.view.refresh_state(43)
                self.assertIsNone(self.view.node_list.currentItem())
                self.assertEqual(self.details.node.node_number, 43)
                self.assertEqual(self.label.text(), f"{GATE} (System)")
                self.assertEqual(
                    self.view.node_list.item(0).text(), "42 - CANACE3 (Online)"
                )
                self.assertEqual(
                    self.view.node_list.item(1).text(), "43 - CANGATE (Online)"
                )
                self.view.finish_discovery(status)
                self.assertEqual(
                    self.view.node_list.item(0).text(), "42 - CANACE3 (Online)"
                )
                self.assertEqual(
                    self.view.node_list.item(1).text(), "43 - CANGATE (Online)"
                )
                self.assertEqual(self.details.node.node_number, 43)
                self.assertEqual(self.details.module_type.text(), "CANGATE")
                self.assertEqual(self.details.summary.title(), "Node 43 — CANGATE")
                self.assertEqual(self.label.text(), f"{GATE} (System)")

        # Subsequent replies still resolve fresh firmware evidence for both nodes.
        self.reply("9B002A0703")
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANACE3 (Online)")
        self.assertEqual(self.details.module_type.text(), "CANGATE")
        self.reply("9B002B0702")
        self.assertEqual(self.view.node_list.item(1).text(), "43 - CANGATE (Online)")
        self.assertEqual(self.label.text(), "None")
        self.reply("9B002B0701")
        self.assertEqual(self.view.node_list.item(1).text(), "43 - CANGATE (Online)")
        self.assertEqual(self.label.text(), f"{GATE} (System)")

    def test_cancmd_groups_display_confirmed_values(self):
        # Complete real CANCMD 4d descriptor, including bit-conditioned controls.
        filename = "CANCMD-A50A-4d.json"
        shutil.copy(FIXTURES / filename, self.system)
        self.discover(number=259, module=10, major=4, minor="d")
        self.reply("9B01030610")  # Confirm 16 NVs, including unread values.
        self.service.record_nv(259, 2, 129)
        self.service.record_nv(259, 5, 25)
        self.service.record_nv(259, 16, 100)
        view = self.details.mdf_values
        self.assertEqual(self.label.text(), f"{filename} (System)")
        self.assertIs(self.details.variables.currentWidget(), view)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(view.navigation.count())],
            ["Raw Values", "Settings"],
        )
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        labels = [label.text() for label in form.findChildren(QLabel)]
        self.assertEqual(
            [g.title() for g in form.findChildren(QGroupBox)],
            [
                "Running",
                "Shuttles",
                "Event Control",
                "Track Power Control",
                "Not Implemented",
            ],
        )
        self.assertIn("SoD Delay:", labels)
        self.assertIn("Honk Interval:", labels)
        self.assertEqual(
            [control.value() for control in form.findChildren(QDoubleSpinBox)][:2],
            [25, 76.9],
        )
        checks = form.findChildren(QCheckBox)
        self.assertTrue(checks[0].isChecked())
        self.assertTrue(checks[5].isChecked())  # Enable Shuttles, NV2 bit 7.
        self.assertTrue(all(not c.isEnabled() for c in checks))
        view.navigation.setCurrentRow(0)
        self.assertEqual(view.raw_values.item(1, 1).text(), "129")

    def test_user_precedence_and_invalid_override_are_visible(self):
        shutil.copy(FIXTURES / ACE, self.system)
        override = Path(shutil.copy(FIXTURES / ACE, self.user))
        data = json.loads(override.read_text())
        data["moduleName"] = "Custom ACE"
        override.write_text(json.dumps(data))
        self.discover()
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANACE3 (Online)")
        self.assertEqual(self.details.module_type.text(), "CANACE3")
        self.assertEqual(self.label.text(), f"{ACE} (User)")
        self.assertEqual(self.label.toolTip(), str(override))

        override.write_text("invalid JSON")
        self.view.refresh_state(42)
        self.assertEqual(self.label.text(), "Error")
        self.assertIn(str(override), self.label.toolTip())
        self.assertEqual(self.details.status.text(), "Online")

        override.unlink()
        self.view.refresh_state(42)
        self.assertEqual(self.label.text(), f"{ACE} (System)")
        self.assertEqual(self.label.toolTip(), str(self.system / ACE))

    def test_no_matching_mdf_keeps_node_information_and_raw_view(self):
        self.discover()
        self.assertEqual(self.label.text(), "None")
        self.assertEqual(self.label.toolTip(), "")
        self.assertEqual(self.details.firmware.text(), "2g")
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANACE3 (Online)")
        self.assertEqual(self.details.module_type.text(), "CANACE3")
        self.assertEqual(self.details.details_page.module_identifier.text(), "A504")
        self.assertIs(self.details.variables.currentWidget(), self.details.raw_values)

    def test_static_names_override_compatible_mdf_and_unknown_types_use_it(self):
        for module_type, expected in (
            (8, "CANSOL"),
            (36, "CANCDU"),
            (251, "Descriptor only"),
        ):
            with self.subTest(module_type=module_type):
                filename = f"Test-A5{module_type:02X}-2g.json"
                (self.system / filename).write_text(
                    json.dumps({"moduleName": "Descriptor only", "nodeVariables": []})
                )
                self.discover(module=module_type)
                self.assertEqual(
                    self.view.node_list.item(0).text(), f"42 - {expected} (Online)"
                )
                self.assertEqual(self.details.module_type.text(), expected)
                self.assertEqual(self.label.text(), f"{filename} (System)")
                (self.system / filename).unlink()
                self.view.refresh_state(42)
                fallback = "251" if module_type == 251 else expected
                self.assertEqual(
                    self.view.node_list.item(0).text(), f"42 - {fallback} (Online)"
                )
                self.assertEqual(self.details.module_type.text(), fallback)
                self.assertEqual(self.label.text(), "None")

    def test_no_matching_mdf_retains_translated_module_name(self):
        self.reply("B6002AA52004")
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANMIO (Online)")
        self.assertEqual(self.details.module_type.text(), "-")

        self.discover(module=32)
        self.view.refresh_state(42)
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANMIO (Online)")
        self.assertEqual(self.details.module_type.text(), "CANMIO")
        self.assertEqual(self.label.text(), "None")
        self.assertIs(self.details.variables.currentWidget(), self.details.raw_values)

    def test_switching_nodes_and_unselected_updates_do_not_leave_stale_mdfs(self):
        shutil.copy(FIXTURES / ACE, self.system)
        shutil.copy(FIXTURES / GATE, self.system)
        self.discover()
        self.discover(number=43, module=0x4B, major=1, minor="b")
        self.assertEqual(self.label.text(), f"{ACE} (System)")
        self.view.node_list.setCurrentRow(1)
        self.assertEqual(self.label.text(), f"{GATE} (System)")
        self.assertEqual(self.view.node_list.item(1).text(), "43 - CANGATE (Online)")
        self.assertEqual(self.details.module_type.text(), "CANGATE")
        self.assertEqual(self.label.toolTip(), str(self.system / GATE))
        self.reply("9B002A0703")  # Unselected node changes firmware.
        self.assertEqual(self.view.node_list.item(0).text(), "42 - CANACE3 (Online)")
        self.assertEqual(self.label.text(), f"{GATE} (System)")
        self.view.node_list.setCurrentRow(0)
        self.assertEqual(self.label.text(), "None")
        self.assertEqual(self.label.toolTip(), "")
        self.view.node_list.setCurrentRow(1)
        self.assertEqual(self.label.text(), f"{GATE} (System)")

    def test_identity_firmware_and_processor_updates_refresh_selection(self):
        shutil.copy(FIXTURES / ACE, self.system)
        specific = self.system / "CANACE3-A504-2g--P21.json"
        shutil.copy(FIXTURES / ACE, specific)
        self.discover()
        self.assertEqual(self.label.text(), f"{ACE} (System)")
        for payload, expected in (
            ("9B002A0915", f"{specific.name} (System)"),
            ("9B002A0917", f"{ACE} (System)"),
            ("9B002A0703", "None"),
            ("9B002A0702", f"{ACE} (System)"),
            ("9B002A0268", "None"),
            ("9B002A0267", f"{ACE} (System)"),
            ("B6002AFA0404", "None"),
            ("B6002AA50404", f"{ACE} (System)"),
        ):
            with self.subTest(payload=payload):
                self.reply(payload)
                self.assertEqual(self.label.text(), expected)

    def test_disconnected_inventory_preserves_saved_details_without_mdf_compatibility(
        self,
    ):
        shutil.copy(FIXTURES / ACE, self.system)
        self.layout.show_live_layout("yard", list)
        self.discover()
        save_metadata("yard", self.service.node_states[42])
        metadata_path = backup_directory("yard", 42).parent / "metadata.yaml"
        metadata_before = metadata_path.read_bytes()

        self.layout.set_connected(False)
        # Changing connection status alone retains the displayed node information.
        self.assertEqual(self.details.status.text(), "Offline")
        self.assertEqual(self.details.firmware.text(), "2g")
        self.assertEqual(self.label.text(), f"{ACE} (System)")
        self.assertFalse(self.details.edit_button.isEnabled())

        # The normal disconnect flow then rebuilds the saved-only inventory.
        self.details.cbus_service = None
        self.view.clear_identities()
        self.view.show_saved_nodes("yard")
        self.assertEqual(self.view.node_list.item(0).text(), "42 (Offline)")
        self.assertEqual(self.details.module_type.text(), "CANACE3")
        self.assertIsNone(self.details.live_state)
        self.assertEqual(self.details.status.text(), "Offline")
        self.assertEqual(self.details.firmware.text(), "2g")
        self.assertEqual(self.details.manufacturer.text(), "MERG")
        self.assertEqual(self.details.details_page.module_identifier.text(), "A504")
        self.assertEqual(self.label.text(), "None")
        self.assertEqual(self.label.toolTip(), "")
        self.assertFalse(self.details.edit_button.isEnabled())
        self.assertFalse(self.details.backup_buttons["Restore"].isEnabled())
        self.assertEqual(metadata_path.read_bytes(), metadata_before)

        # Fresh live discovery must not borrow firmware from the saved metadata.
        self.view.state_lookup = self.service.node_states.get
        self.service.node_states[42].parameters.clear()
        self.layout.set_connected(True)
        self.view.show_identity(self.service.node_states[42].identity)
        self.assertEqual(self.details.firmware.text(), "-")
        self.assertEqual(self.label.text(), "None")
        self.assertFalse(self.details.edit_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
