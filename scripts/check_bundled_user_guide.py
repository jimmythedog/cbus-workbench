"""Verify PyInstaller copied the built User Guide unchanged."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_bundled_user_guide(source: Path, bundle_root: Path) -> int:
    """Check the resource layout used by user_guide_path at runtime."""
    if not (source / "user-guide.html").is_file():
        raise ValueError(f"Built user guide is missing: {source}")
    destination = bundle_root / "resources" / "user-guide"
    originals = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    bundled = {
        p.relative_to(destination) for p in destination.rglob("*") if p.is_file()
    }
    if originals != bundled:
        raise ValueError(f"Packaged user guide differs from source: {destination}")
    for path in originals:
        if (source / path).read_bytes() != (destination / path).read_bytes():
            raise ValueError(f"Packaged user guide contents differ: {path}")
    return len(originals)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    args = parser.parse_args()
    count = check_bundled_user_guide(
        ROOT / "resources" / "user-guide", args.bundle_root
    )
    print(f"Verified {count} bundled user guide files under {args.bundle_root}")


if __name__ == "__main__":
    main()
