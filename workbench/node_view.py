import logging
from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSplitter,
)

from .cbus_service import DiscoveryStatus, NodeState
from .logging_config import trace
from .mdfs import MdfError, MdfRepository
from .node_backup_files import forget_node, saved_node_numbers
from .node_details import NodeDetails
from .node_metadata import load_metadata
from .parameter_names import module_name
from .pnn import Pnn


def node_number(node):
    return node if isinstance(node, int) else node.node_number


logger = logging.getLogger("workbench.ui")


class NodeListItem(QListWidgetItem):
    def __init__(self, text, module_label=""):
        super().__init__(text)
        # Keep the resolved label separate so annotation edits need no MDF lookup.
        self.module_label = module_label

    def __lt__(self, other):
        return node_number(self.data(Qt.ItemDataRole.UserRole)) < node_number(
            other.data(Qt.ItemDataRole.UserRole)
        )


class NodeView(QSplitter):
    def __init__(self, events):
        super().__init__(Qt.Orientation.Horizontal)

        self.node_list = QListWidget()
        self.node_list.setSortingEnabled(True)
        self.node_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.node_list.customContextMenuRequested.connect(self.show_node_menu)

        self.details = NodeDetails(events)
        self.mdf_repository = MdfRepository()
        self.saved_metadata = {}
        self.state_lookup: Callable[[int], NodeState | None] | None = None
        self.discovering = False
        self.editing = False
        self.selection_before_discovery: int | None = None

        self.node_list.currentItemChanged.connect(self.show_selected_node)

        self.details.editing_changed.connect(self.set_editing)

        self.addWidget(self.node_list)
        self.addWidget(self.details)
        self.setSizes([250, 750])

    def show_node_menu(self, position):
        item = self.node_list.itemAt(position)
        if item is None or self.details.logical_layout is None:
            return
        self.node_list.setCurrentItem(item)
        menu = QMenu(self)
        refresh = menu.addAction("Refresh Node")
        service = self.details.cbus_service
        reason = (
            service.refresh_unavailable_reason()
            if service
            else "Refresh Node requires a connected layout"
        )
        if self.editing or self.discovering:
            reason = "Finish editing or discovery before refreshing"
        refresh.setEnabled(not reason)
        refresh.setToolTip(reason or "Reread this node from hardware")
        menu.setToolTipsVisible(True)
        forget = None
        if self.can_forget(item):
            forget = menu.addAction("Forget Node")
        chosen = menu.exec(self.node_list.viewport().mapToGlobal(position))
        if chosen == refresh:
            # Recheck after the menu's nested event loop before taking ownership.
            try:
                if self.editing or self.discovering:
                    raise ValueError("Finish editing or discovery before refreshing")
                service.refresh_node(node_number(item.data(Qt.ItemDataRole.UserRole)))
            except ValueError as error:
                QMessageBox.warning(self, "Cannot refresh node", str(error))
        elif forget is not None and chosen == forget:
            self.forget_saved_node(item)

    def is_online(self, item) -> bool:
        """Online status shown in the navigator, independent of the item's data type."""
        service = self.details.cbus_service
        if service is None:
            return isinstance(item.data(Qt.ItemDataRole.UserRole), Pnn)
        return service.presence.get(
            node_number(item.data(Qt.ItemDataRole.UserRole)), False
        )

    def can_forget(self, item) -> bool:
        # Without a connection every saved node shows Offline, so Offline is
        # only trustworthy while the layout is connected.
        return (
            self.details.connected
            and self.details.cbus_service is not None
            and not self.is_online(item)
            and not self.discovering
            and not self.editing
        )

    def forget_saved_node(self, item):
        number = node_number(item.data(Qt.ItemDataRole.UserRole))
        if not self.can_forget(item):
            return
        logical_layout = self.details.logical_layout
        fields = {"layout": logical_layout, "node_number": number}
        answer = QMessageBox.question(
            self,
            "Forget Node",
            f"Forget {item.text()}?\n\n"
            "Its local persisted directory, annotations and node backups will be "
            "permanently deleted. Historical layout backups will be preserved.\n\n"
            "No CBUS commands will be sent. Normal discovery can add this node again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            trace(logger, "Forget node cancelled", extra={"fields": fields})
            return
        # The confirmation runs a Qt event loop; the layout may have disconnected
        # or the node may have come online.
        if not self.can_forget(item):
            trace(
                logger,
                "Forget node stopped: disconnected, node online or busy",
                extra={"fields": fields},
            )
            return
        try:
            forget_node(logical_layout, number)
        except OSError as error:
            QMessageBox.warning(self, "Cannot forget node", str(error))
            return
        self.saved_metadata.pop(number, None)
        if self.details.cbus_service is not None:
            self.details.cbus_service.presence.pop(number, None)
        self.node_list.takeItem(self.node_list.row(item))
        trace(logger, "Forgotten node removed from navigator", extra={"fields": fields})

    def refresh_annotation_names(self, number=-1):
        annotations = self.details.annotations
        for row in range(self.node_list.count()):
            item = self.node_list.item(row)
            nn = node_number(item.data(Qt.ItemDataRole.UserRole))
            if number not in (-1, nn):
                continue
            name = annotations.load(nn).get("name", "") if annotations else ""
            label = name or item.module_label
            base = f"{nn} - {label}" if label else str(nn)
            base += " (Online)" if self.is_online(item) else " (Offline)"
            item.setText(base)
        if (
            not self.discovering
            and self.details.node is not None
            and number
            in (
                -1,
                self.details.annotation_number(),
            )
        ):
            self.details.refresh_annotations()

    def set_editing(self, editing: bool) -> None:
        self.editing = editing
        self.node_list.setEnabled(not (self.editing or self.discovering))

    def discovery_status_changed(self, status: str) -> None:
        if status == DiscoveryStatus.DISCOVERING:
            self.begin_discovery()
        else:
            self.finish_discovery(status)

    def begin_discovery(self) -> None:
        """Suspend selection and MDF work without disturbing editors or progress."""
        service = self.details.cbus_service
        if service is not None and (
            service.nv_save.active or service.event_save.active
        ):
            # Editing Save changes values only; it retains the selected MDF and
            # updates these views once, without a whole-navigator completion pass.
            return
        if self.discovering:
            return
        current = self.node_list.currentItem()
        self.selection_before_discovery = (
            node_number(current.data(Qt.ItemDataRole.UserRole)) if current else None
        )
        self.discovering = True
        # Keep the visible details and editor session while replies arrive.
        with QSignalBlocker(self.node_list):
            self.node_list.setCurrentItem(None)
        self.node_list.setEnabled(False)
        trace(
            logger,
            "Node selection suspended for discovery",
            extra={"fields": {"node_number": self.selection_before_discovery}},
        )

    def finish_discovery(self, status: str) -> None:
        """Restore selection once, including after incomplete discovery."""
        if not self.discovering or status == DiscoveryStatus.DISCOVERING:
            return
        self.discovering = False
        self.node_list.setEnabled(not self.editing)
        selected = None
        if status != DiscoveryStatus.DISCONNECTED:
            for index in range(self.node_list.count()):
                item = self.node_list.item(index)
                node = item.data(Qt.ItemDataRole.UserRole)
                if selected is None and isinstance(node, Pnn):
                    selected = item
                if node_number(node) == self.selection_before_discovery and (
                    isinstance(node, Pnn)
                    or self.state_lookup is not None
                    and self.state_lookup(node_number(node)) is not None
                ):
                    selected = item
                    break
        self.selection_before_discovery = None
        # Restore selection without its usual lookup: the final pass below resolves
        # every live node once, including the selected node's details.
        with QSignalBlocker(self.node_list):
            self.node_list.setCurrentItem(selected)
        # Re-selecting the same node must not reset Save's editor or result.
        previous = self.details.node
        selected_number = (
            node_number(selected.data(Qt.ItemDataRole.UserRole)) if selected else None
        )
        if (
            previous is None
            or selected is None
            or not isinstance(previous, Pnn)
            or node_number(previous) != selected_number
        ):
            self.details.show_node(selected)
        else:
            self.details.node = selected.data(Qt.ItemDataRole.UserRole)
        if status != DiscoveryStatus.DISCONNECTED and self.state_lookup is not None:
            for index in range(self.node_list.count()):
                node = self.node_list.item(index).data(Qt.ItemDataRole.UserRole)
                self.refresh_state(node_number(node))
        trace(
            logger,
            "Node selection resumed after discovery",
            extra={
                "fields": {
                    "status": status,
                    "node_number": (
                        node_number(selected.data(Qt.ItemDataRole.UserRole))
                        if selected
                        else None
                    ),
                }
            },
        )

    def show_selected_node(self, current, _previous=None) -> None:
        self.details.show_node(current)
        if (
            current is not None
            and isinstance(self.details.node, int)
            and (
                self.state_lookup is None
                or self.state_lookup(self.details.node) is None
            )
        ):
            parameters = {
                index: value
                for index, value in enumerate(
                    self.saved_metadata.get(self.details.node, {}).get("parameters", [])
                )
                if value is not None
            }
            if 1 in parameters and 3 in parameters:
                identity = Pnn(
                    self.details.node,
                    parameters[1],
                    parameters[3],
                    parameters.get(8, 0),
                )
                try:
                    self.details.live_mdf = self.mdf_repository.lookup(
                        identity, parameters
                    )
                except MdfError:
                    logger.exception(
                        "Offline MDF lookup failed node=%s", self.details.node
                    )
                self.details.refresh_annotations()
        if current is not None and self.state_lookup is not None:
            node = current.data(Qt.ItemDataRole.UserRole)
            state = self.state_lookup(node_number(node))
            if state is not None:
                self.show_live_state(state)

    def show_live_state(self, state: NodeState) -> None:
        """Display discovery values and resolve MDFs from the same live evidence."""
        # NV/EV replies do not change the module name. Defer all descriptor work
        # during discovery so it cannot delay the next protocol request.
        if self.discovering:
            return
        form = self.details.details_page
        error_message = None
        try:
            mdf = (
                self.mdf_repository.lookup(state.identity, state.parameters)
                if state.identity_confirmed
                else None
            )
        except MdfError as error:
            # The repository logs the detailed failure; retain node/layout context here.
            logger.error(
                "Module descriptor lookup failed",
                extra={
                    "fields": {
                        "layout": self.details.logical_layout,
                        "node_number": state.identity.node_number,
                        "error": str(error),
                    }
                },
            )
            mdf = None
            error_message = str(error)
        name = module_name(
            state.identity.manufacturer
            if state.identity_confirmed
            else state.parameters.get(1),
            state.identity.module_type
            if state.identity_confirmed
            else state.parameters.get(3),
            mdf.data.get("moduleName") if mdf else None,
        )
        selected = False
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            if (
                node_number(item.data(Qt.ItemDataRole.UserRole))
                == state.identity.node_number
            ):
                item.module_label = name
                selected = item is self.node_list.currentItem()
                break
        trace(
            logger,
            "Resolved live module name node=%s name=%s",
            state.identity.node_number,
            name,
        )
        self.refresh_annotation_names(state.identity.node_number)
        if not selected:
            return
        # Details retain PARAN's unknown marker until module type is confirmed.
        details_name = (
            name
            if mdf
            else module_name(state.parameters.get(1), state.parameters.get(3))
        )
        self.details.show_live_state(state, mdf, module_name=details_name)
        if error_message is not None:
            form.show_module_descriptor("Error", error_message)
            return
        if mdf is None:
            form.show_module_descriptor()
            return
        source = (
            "User"
            if mdf.path.parent == self.mdf_repository.user_directory
            else "System"
        )
        form.show_module_descriptor(
            f"{mdf.path.name} ({source})", str(mdf.path.absolute())
        )

    def refresh_state(self, node_number: int) -> None:
        """Refresh the navigator identity and selected details from service state."""
        service = self.details.cbus_service
        if service is not None and (
            service.nv_save.active or service.event_save.active
        ):
            return
        if self.state_lookup is None:
            return
        state = self.state_lookup(node_number)
        if state is None:
            return
        identity = state.identity
        name = module_name(identity.manufacturer, identity.module_type)
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            node = item.data(Qt.ItemDataRole.UserRole)
            if (node if isinstance(node, int) else node.node_number) == node_number:
                # Remembered addresses are promoted by the identity signal.
                if isinstance(node, Pnn):
                    item.setData(Qt.ItemDataRole.UserRole, identity)
                item.module_label = name
                self.refresh_annotation_names(node_number)
                self.show_live_state(state)
                return

    def show_identity(self, node: Pnn) -> None:
        """Update a PNN identity without changing the selected list item."""
        name = module_name(node.manufacturer, node.module_type)
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            if node_number(item.data(Qt.ItemDataRole.UserRole)) == node.node_number:
                item.setData(Qt.ItemDataRole.UserRole, node)
                item.module_label = name
                if item is self.node_list.currentItem():
                    self.show_selected_node(item)
                else:
                    self.refresh_state(node.node_number)
                self.refresh_annotation_names(node.node_number)
                return

        first_node = self.node_list.count() == 0
        item = NodeListItem(f"{node.node_number} - {name}", name)
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.node_list.addItem(item)
        self.refresh_annotation_names(node.node_number)
        if not first_node or self.discovering:
            self.refresh_state(node.node_number)
        if first_node and not self.discovering:
            self.node_list.setCurrentItem(item)
            trace(
                logger,
                "First discovered node selected",
                extra={"fields": {"node_number": node.node_number}},
            )

    def refresh_presence(self, number: int, _online: bool) -> None:
        self.refresh_annotation_names(number)
        if self.details.node is not None and self.details.annotation_number() == number:
            self.details.update_connection_details()

    def clear_identities(self) -> None:
        self.state_lookup = None
        self.node_list.clear()

    def show_saved_nodes(self, logical_layout):
        """Load saved identification independently of live discovery and backups."""
        self.saved_metadata = {
            number: load_metadata(logical_layout, number)
            for number in saved_node_numbers(logical_layout)
        }
        self.details.saved_metadata = self.saved_metadata
        for number in self.saved_metadata:
            if any(
                node_number(self.node_list.item(i).data(Qt.ItemDataRole.UserRole))
                == number
                for i in range(self.node_list.count())
            ):
                continue
            parameters = self.saved_metadata[number].get("parameters", [])
            name = (
                module_name(parameters[1], parameters[3])
                if len(parameters) > 3 and parameters[3] is not None
                else ""
            )
            item = NodeListItem(f"{number} (Offline)", name)
            item.setData(Qt.ItemDataRole.UserRole, number)
            self.node_list.addItem(item)
        self.refresh_annotation_names()
        if (
            not self.discovering
            and self.node_list.currentItem() is None
            and self.node_list.count()
        ):
            self.node_list.setCurrentRow(0)
