"""The details form keeps node display and name editing in the existing tab."""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidgetItem, QScrollArea

from workbench.cbus_service import CbusService, NodeState
from workbench.layout_view import LayoutView
from workbench.node import Node
from workbench.node_details import NodeDetails
from workbench.node_details_form import NodeDetailsForm
from workbench.node_view import NodeView
from workbench.pnn import Pnn
from workbench.tcp_connection import TcpConnection


class NodeDetailsFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.details = NodeDetails({})
        self.addCleanup(self.details.close)

    def select(self, node):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.details.show_node(item)
        return item

    def test_navigator_and_summary_names_refresh_without_changing_selection(self):
        view = NodeView({})
        self.addCleanup(view.close)
        first = NodeState(Pnn(258, 165, 32, 5), parameters={1: 165, 3: 32})
        second = NodeState(Pnn(259, 165, 254, 5), parameters={1: 165, 3: 254})
        states = {258: first, 259: second}
        view.state_lookup = states.get
        view.show_identity(first.identity)
        selected = view.node_list.currentItem()
        self.assertEqual(selected.text(), "258 - CANMIO")
        self.assertEqual(view.details.summary.title(), "Node 258 — CANMIO")
        view.show_identity(second.identity)
        self.assertIs(view.node_list.currentItem(), selected)
        self.assertEqual(view.node_list.item(1).text(), "259 - EMPTY")

        # An update to an unselected node must not replace the selected details.
        second.identity = Pnn(259, 165, 32, 5)
        second.parameters[3] = 32
        view.refresh_state(259)
        self.assertEqual(view.node_list.item(1).text(), "259 - CANMIO")
        self.assertIs(view.node_list.currentItem(), selected)
        self.assertEqual(view.details.summary.title(), "Node 258 — CANMIO")

        first.identity = Pnn(258, 1, 32, 5)
        view.refresh_state(258)
        self.assertEqual(selected.text(), "258 - 32")
        self.assertEqual(view.details.summary.title(), "Node 258 — CANMIO")
        self.assertEqual(selected.data(Qt.ItemDataRole.UserRole).module_type, 32)
        self.assertIs(view.node_list.currentItem(), selected)

        first.identity = Pnn(258, 165, 32, 5)
        view.show_identity(first.identity)
        self.assertEqual(selected.text(), "258 - CANMIO")
        self.assertEqual(view.details.summary.title(), "Node 258 — CANMIO")
        self.assertIs(view.node_list.currentItem(), selected)
        view.node_list.setCurrentRow(1)
        self.assertEqual(view.details.summary.title(), "Node 259 — CANMIO")
        view.details.show_node(None)
        self.assertEqual(view.details.summary.title(), "Node details")
        self.select(260)
        self.assertEqual(self.details.summary.title(), "Node 260 (offline)")

    def test_confirmed_identity_names_and_unknown_fallbacks(self):
        for manufacturer, module_type, name, module, identifier in (
            (165, 32, "MERG", "CANMIO", "A520"),
            (165, 254, "MERG", "EMPTY", "A5FE"),
            (1, 32, "1", "32", "0120"),
            (255, 255, "unknown", "255", "FFFF"),
        ):
            with self.subTest(manufacturer=manufacturer, module_type=module_type):
                identity = Pnn(42, manufacturer, module_type, 5)
                self.select(identity)
                self.assertEqual(self.details.manufacturer.text(), "-")
                self.assertEqual(self.details.module_type.text(), "-")
                self.assertEqual(
                    self.details.details_page.module_identifier.text(), "-"
                )
                state = NodeState(
                    identity, parameters={1: manufacturer, 3: module_type}
                )
                self.details.show_live_state(state)
                self.assertEqual(self.details.manufacturer.text(), name)
                self.assertEqual(self.details.module_type.text(), module)
                self.assertEqual(state.identity.manufacturer, manufacturer)
                self.assertEqual(state.identity.module_type, module_type)
        self.details.show_node(None)
        self.assertEqual(self.details.manufacturer.text(), "-")
        self.assertEqual(self.details.module_type.text(), "-")

    def test_module_identifier_uses_confirmed_bytes(self):
        form = self.details.details_page
        self.assertEqual(form.module_identifier.text(), "-")
        for manufacturer, module_type, expected in (
            (165, 32, "A520"),
            (0, 1, "0001"),
            (255, 255, "FFFF"),
            (None, 32, "-"),
            (165, None, "-"),
            (256, 32, "-"),
            (165, -1, "-"),
        ):
            with self.subTest(manufacturer=manufacturer, module_type=module_type):
                form.show_module_identifier(manufacturer, module_type)
                self.assertEqual(form.module_identifier.text(), expected)
        self.select(Pnn(42, 165, 32, 0x1F))
        self.assertEqual(form.module_identifier.text(), "-")
        self.assertNotIn(
            "Flags:", [label.text() for label in form.findChildren(QLabel)]
        )
        for label in (
            form.producer,
            form.consumer,
            form.consumes_own_events,
            form.supports_bootloading,
        ):
            self.assertEqual(label.text(), "Yes")
        self.assertEqual(form.node_mode.text(), "FLiM")
        self.select(Node(43, "CANMIO", 12, "3d", True))
        self.assertEqual(form.module_identifier.text(), "-")
        self.assertEqual(form.module_descriptor.text(), "None")
        self.assertEqual(form.module_descriptor.toolTip(), "")
        self.details.show_node(None)
        self.assertEqual(form.module_identifier.text(), "-")

    def test_can_id_visibility_and_identity_follow_discovery_and_selection(self):
        view = NodeView({})
        self.addCleanup(view.close)
        first = NodeState(Pnn(42, 165, 32, 5), parameters={10: 1}, can_id=7)
        second = NodeState(Pnn(43, 1, 2, 5), parameters={10: 2}, can_id=9)
        states = {42: first, 43: second}
        view.state_lookup = states.get
        view.show()
        details = view.details
        form = details.details_page
        caption = form.group.layout().labelForField(form.can_id)

        def assert_can(visible, value):
            self.app.processEvents()
            self.assertEqual(form.can_id.isVisible(), visible)
            self.assertEqual(caption.isVisible(), visible)
            self.assertEqual(details.summary_can_id.isVisible(), visible)
            self.assertEqual(form.can_id.text(), value)
            self.assertEqual(details.summary_can_id.text(), f"CAN ID: {value}")

        view.show_identity(first.identity)
        view.show_identity(second.identity)
        assert_can(True, "7")
        layout = form.group.layout()
        self.assertEqual(
            layout.getWidgetPosition(form.can_id)[0],
            layout.getWidgetPosition(form.interface)[0] + 1,
        )
        view.node_list.setCurrentRow(1)
        assert_can(False, "9")
        self.assertEqual(form.module_identifier.text(), "-")
        for interface, visible in (
            (None, False),
            (3, False),
            (4, False),
            (99, False),
            (1, True),
        ):
            second.parameters = {} if interface is None else {10: interface}
            view.refresh_state(43)
            assert_can(visible, "9")
        view.node_list.setCurrentRow(0)
        assert_can(True, "7")
        view.clear_identities()
        assert_can(False, "-")
        self.assertEqual(form.module_identifier.text(), "-")
        # Reconnection starts with a fresh identity and unconfirmed interface.
        first = NodeState(Pnn(42, 13, 3, 5), can_id=11)
        states[42] = first
        view.state_lookup = states.get
        view.show_identity(first.identity)
        assert_can(False, "11")
        self.assertEqual(form.module_identifier.text(), "-")
        first.parameters[10] = 1
        view.refresh_state(42)
        assert_can(True, "11")

    def test_vlcb_identification_uses_confirmed_parameter_8(self):
        self.select(Pnn(258, 13, 34, 0x43))
        for parameters, expected in (
            ({}, "-"),
            ({8: 0}, "No"),
            ({8: 0x43}, "Yes"),
            ({}, "-"),
        ):
            with self.subTest(parameters=parameters):
                self.details.show_parameters(parameters)
                self.assertEqual(self.details.details_page.vlcb.text(), expected)

    def test_stored_event_count_displays_unknown_zero_and_nonzero(self):
        state = NodeState(Pnn(258, 13, 34, 0x03))
        self.select(state.identity)
        for count, expected in ((None, "-"), (0, "0"), (7, "7"), (None, "-")):
            with self.subTest(count=count):
                state.stored_event_count = count
                self.details.show_live_state(state)
                self.assertEqual(
                    self.details.details_page.stored_events.text(), expected
                )

    def test_stored_event_count_refreshes_and_follows_selected_node(self):
        view = NodeView({})
        self.addCleanup(view.close)
        connection = TcpConnection("test", view)
        service = CbusService(connection, 100)
        self.addCleanup(service.close)
        first = NodeState(Pnn(258, 13, 34, 0x03), stored_event_count=7)
        second = NodeState(Pnn(259, 13, 35, 0x03))
        service.node_states = {258: first, 259: second}
        view.state_lookup = service.node_states.__getitem__
        service.node_state_updated.connect(view.refresh_state)
        view.show_identity(first.identity)
        view.show_identity(second.identity)
        label = view.details.details_page.stored_events
        self.assertEqual(label.text(), "7")
        first.stored_event_count = 0
        service.node_state_updated.emit(258)
        self.assertEqual(label.text(), "0")
        view.node_list.setCurrentRow(1)
        self.assertEqual(label.text(), "-")
        first.stored_event_count = 9
        service.node_state_updated.emit(258)
        self.assertEqual(label.text(), "-")
        second.stored_event_count = 3
        service.node_state_updated.emit(259)
        self.assertEqual(label.text(), "3")
        view.node_list.setCurrentRow(0)
        self.assertEqual(label.text(), "9")
        view.clear_identities()
        self.assertEqual(label.text(), "-")

    def test_form_is_the_details_page_and_labels_remain_accessible(self):
        details = self.details
        self.assertIsInstance(details.details_page, NodeDetailsForm)
        self.assertIs(details.tabs.widget(0), details.details_page)
        self.assertIs(details.node_number, details.details_page.node_number)
        self.assertIs(details.node_name, details.details_page.node_name)
        self.assertEqual(details.node_number.text(), "-")
        self.assertEqual(details.summary.title(), "Node details")

    def test_large_font_details_remain_readable_and_scroll_to_last_row(self):
        details = self.details
        details.details_page.show_module_descriptor(
            "CANMIO-A520-3d.json (System)",
            "/application/resources/mdfs/CANMIO-A520-3d.json",
        )
        font = details.font()
        font.setPointSize(14)
        details.setFont(font)
        details.resize(850, 600)
        details.show()
        self.app.processEvents()

        self.assertEqual(details.height(), 600)
        for label in details.details_page.group.findChildren(QLabel):
            if label.isVisible():
                self.assertGreaterEqual(
                    label.height(), label.minimumSizeHint().height()
                )

        scroll = details.details_page.findChild(QScrollArea)
        last = details.details_page.module_descriptor
        scroll.ensureWidgetVisible(last)
        self.app.processEvents()
        self.assertTrue(
            scroll.viewport()
            .rect()
            .contains(last.mapTo(scroll.viewport(), last.rect().bottomLeft()))
        )

    def test_large_font_backup_actions_fit_in_requested_window(self):
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        font = view.font()
        font.setPointSize(14)
        view.setFont(font)
        view.resize(1000, 700)
        view.show()
        details = view.node_view.details

        for tabs, page, buttons in (
            (details.tabs, details.node_backups, details.backup_buttons),
            (view.tabs, view.backups_page, view.backup_buttons),
        ):
            tabs.setCurrentWidget(page)
            self.app.processEvents()
            self.assertEqual(view.height(), 700)
            for button in buttons.values():
                self.assertTrue(button.isVisible())
                self.assertGreaterEqual(button.height(), button.sizeHint().height())
                self.assertTrue(
                    view.rect().contains(button.mapTo(view, button.rect().topLeft()))
                )
                self.assertTrue(
                    view.rect().contains(
                        button.mapTo(view, button.rect().bottomRight())
                    )
                )

    def test_configured_zero_ev_is_visible(self):
        node = Node(42, "Configured", 12, "1a", False)
        node.consumed_events = {"42:10": "Signal"}
        node.ev_values = {"42:10": {1: 0, 2: 7}}
        self.select(node)
        event = self.details.node_events.consumed_table.topLevelItem(0)
        self.assertEqual(event.child(0).text(1), "0")
        self.assertFalse(event.child(0).isHidden())

    def test_details_stay_grouped_at_top_when_switching_node_types(self):
        details = self.details
        details.resize(850, 950)
        details.show()

        for node in (
            Node(42, "Configured", 12, "1a", False),
            Pnn(258, 13, 34, 0x03),
            Node(43, "Other", 13, "1b", False),
        ):
            with self.subTest(node=node):
                self.select(node)
                self.app.processEvents()
                name_bottom = details.node_name_stack.mapTo(
                    details.details_page, details.node_name_stack.rect().bottomLeft()
                ).y()
                number_top = details.node_number.mapTo(
                    details.details_page, details.node_number.rect().topLeft()
                ).y()
                self.assertLess(number_top - name_bottom, 20)

        details.start_name_editing()
        self.app.processEvents()
        editor_bottom = details.node_name_editor.mapTo(
            details.details_page, details.node_name_editor.rect().bottomLeft()
        ).y()
        number_top = details.node_number.mapTo(
            details.details_page, details.node_number.rect().topLeft()
        ).y()
        self.assertLess(number_top - editor_bottom, 20)
        details.cancel_name_editing()
        self.app.processEvents()

        button_corner = details.details_edit_button.mapTo(
            details, details.details_edit_button.rect().bottomRight()
        )
        self.assertLess(details.width() - button_corner.x(), 50)
        self.assertLess(details.height() - button_corner.y(), 50)

    def test_configured_name_editing_updates_header_and_restores_tabs(self):
        node = Node(42, "Test module", 12, "1a", False)
        item = self.select(node)
        details = self.details
        self.assertEqual(details.node_number.text(), "42")
        self.assertEqual(details.summary.title(), "Node 42 — Test module")

        details.start_name_editing()
        self.assertIs(details.node_name_stack.currentWidget(), details.node_name_editor)
        for page in (
            details.variables_page,
            details.produced_events_page,
            details.consumed_events_page,
            details.node_backups,
        ):
            self.assertFalse(details.tabs.isTabEnabled(details.tabs.indexOf(page)))

        details.node_name_editor.setText("  Garden  ")
        details.save_name_editing()
        self.assertEqual(node.name, "Garden")
        self.assertEqual(details.node_name.text(), "Garden")
        self.assertEqual(details.summary.title(), "Node 42 — Test module — Garden")
        self.assertEqual(item.text(), "42 - Test module — Garden")
        for page in (
            details.variables_page,
            details.produced_events_page,
            details.consumed_events_page,
            details.node_backups,
        ):
            self.assertTrue(details.tabs.isTabEnabled(details.tabs.indexOf(page)))

    def test_switching_to_live_identity_and_no_node_updates_tabs_and_header(self):
        details = self.details
        self.select(Node(42, "Test module", 12, "1a", False))
        self.select(Pnn(258, 13, 34, 0x03))
        self.assertEqual(details.node_number.text(), "258")
        self.assertEqual(details.summary.title(), "Node 258 — -")
        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.variables_page))
        )
        self.assertIs(details.variables.currentWidget(), details.raw_values)
        self.assertIs(details.tabs.currentWidget(), details.details_page)

        details.show_node(None)
        self.assertEqual(details.node_number.text(), "-")
        self.assertEqual(details.summary.title(), "Node details")
        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.variables_page))
        )

    def test_configured_node_without_discovery_cannot_edit_nvs(self):
        node = Node(42, "Test module", 12, "1a", False, nv_values={1: 7})
        self.select(node)
        self.assertFalse(self.details.edit_button.isEnabled())
        self.details.start_editing()
        self.assertIsNone(self.details.desired_configuration)
        self.assertEqual(node.nv_values, {1: 7})

    def test_available_tabs_survive_configured_node_changes(self):
        details = self.details
        first = Node(42, "First", 12, "1a", False)
        second = Node(43, "Second", 13, "1b", False)
        self.select(first)

        for page in (
            details.details_page,
            details.variables_page,
            details.produced_events_page,
            details.consumed_events_page,
            details.node_backups,
        ):
            with self.subTest(tab=details.tabs.tabText(details.tabs.indexOf(page))):
                details.tabs.setCurrentWidget(page)
                self.select(second)
                self.assertIs(details.tabs.currentWidget(), page)
                self.select(first)

    def test_node_variables_tab_survives_live_and_configured_changes(self):
        details = self.details
        self.select(Node(42, "Configured", 12, "1a", False))
        details.tabs.setCurrentWidget(details.variables_page)

        self.select(Pnn(258, 13, 34, 0x03))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)
        self.select(Pnn(259, 13, 35, 0x03))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)
        self.select(Node(43, "Other", 13, "1b", False))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)

    def test_live_backup_tab_remains_available(self):
        details = self.details
        configured = Node(42, "Configured", 12, "1a", False)
        live = Pnn(258, 13, 34, 0x03)
        self.select(configured)

        self.assertTrue(
            details.tabs.isTabEnabled(
                details.tabs.indexOf(details.consumed_events_page)
            )
        )

        details.tabs.setCurrentWidget(details.node_backups)
        self.select(live)
        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.node_backups))
        )
        self.assertIs(details.tabs.currentWidget(), details.node_backups)
        self.select(configured)
