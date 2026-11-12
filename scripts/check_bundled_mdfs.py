"""Verify PyInstaller copied the complete pinned MDF collection unchanged."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_bundled_mdfs(source: Path, bundle_root: Path) -> int:
    """Check the resource layout used by system_mdf_directory at runtime."""
    originals = {path.name: path for path in source.glob("*.json") if path.is_file()}
    if not originals:
        raise ValueError(f"MDF collection is missing or empty: {source}")
    destination = bundle_root / "resources" / "mdfs"
    bundled = {path.name: path for path in destination.glob("*.json") if path.is_file()}
    if originals.keys() != bundled.keys():
        raise ValueError(f"Packaged MDF collection differs from source: {destination}")
    for name, original in originals.items():
        if original.read_bytes() != bundled[name].read_bytes():
            raise ValueError(f"Packaged MDF contents differ: {bundled[name]}")
    return len(originals)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    args = parser.parse_args()
    count = check_bundled_mdfs(ROOT / "resources" / "mdfs", args.bundle_root)
    print(f"Verified {count} bundled MDFs under {args.bundle_root}")


if __name__ == "__main__":
    main()
