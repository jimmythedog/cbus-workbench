"""Show an MDF's NV settings pages with chosen NV values, for visual inspection.

Development utility only: it uses the application's own renderer with editing
enabled, but edits change in-memory values only. Nothing is written to hardware
or saved. Run from the repository root:

    python -m scripts.show_mdf resources/mdfs/MMCTEST-0001-1a.json 5=55 7=77
"""

import argparse
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from workbench.mdf_tokens import substitute_tokens
from workbench.node import Node
from workbench.node_variables import MdfNodeVariables


def nv_assignment(text: str) -> tuple[int, int]:
    index, _, value = text.partition("=")
    try:
        index, value = int(index), int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected NV=value, got {text!r}")
    if not 1 <= index <= 255 or not 0 <= value <= 255:
        raise argparse.ArgumentTypeError(f"NV must be 1-255 and value 0-255: {text}")
    return index, value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mdf", type=Path)
    parser.add_argument(
        "values", nargs="*", type=nv_assignment, help="NV=value (others are 0)"
    )
    args = parser.parse_args()
    data = json.loads(args.mdf.read_text())
    values = {index: 0 for index in range(1, 256)} | dict(args.values)

    app = QApplication([])
    view = MdfNodeVariables()
    # Default token names, as for a node without saved annotations.
    view.set_definition(substitute_tokens(data, {}), source=data)
    view.show_node(Node(0, data.get("moduleName", args.mdf.stem), 0, "", True), values)
    view.set_editing(True)
    view.setWindowTitle(f"{args.mdf.name} (in-memory values only)")
    view.resize(1000, 700)
    view.show()
    app.exec()


if __name__ == "__main__":
    main()
