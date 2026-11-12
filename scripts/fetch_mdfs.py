"""Fetch development and packaged MDFs from a pinned MMC-SERVER release source archive."""

import argparse
import logging
import shutil
import tarfile
import tempfile
import tomllib
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "resources" / "mdfs"
LOGGER = logging.getLogger(__name__)


def extract_mdfs(archive: Path, destination: Path) -> int:
    """Copy only regular MDF JSON files; never unpack arbitrary archive paths."""
    count = 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            # GitHub supplies one generated root directory; MMC's MDF folder is flat.
            if path.parts[1:4] != ("VLCB-server", "config", "modules"):
                continue
            if path.suffix != ".json":
                continue
            if len(path.parts) != 5 or path.is_absolute() or not member.isfile():
                raise ValueError(f"Unsafe MDF archive entry: {member.name}")
            target = destination / path.name
            if target.exists():
                raise ValueError(f"Duplicate MDF archive entry: {member.name}")
            with source.extractfile(member) as contents, target.open("wb") as output:
                shutil.copyfileobj(contents, output)
            count += 1
    if not count:
        raise ValueError("Release archive contains no MDF JSON files")
    return count


def fetch_mdfs(version: str, destination: Path | None = None) -> int:
    """Download and stage the collection before replacing the previous fetch."""
    if destination is None:
        destination = DESTINATION
    url = "https://api.github.com/repos/david284/MMC-SERVER/tarball/" + quote(
        version, safe=""
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "release.tar.gz"
        LOGGER.info("Downloading MMC-SERVER %s from %s", version, url)
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        collection = staging / "mdfs"
        collection.mkdir()
        LOGGER.info("Extracting MDFs for MMC-SERVER %s", version)
        count = extract_mdfs(archive, collection)
        if destination.exists():
            shutil.rmtree(destination)
        collection.rename(destination)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="MMC release tag (default: pyproject.toml)")
    args = parser.parse_args(argv)
    version = args.version
    try:
        if version is None:
            with (ROOT / "pyproject.toml").open("rb") as config:
                version = tomllib.load(config)["tool"]["cbus-workbench"]["mmc_version"]
        if not isinstance(version, str) or not version.strip():
            raise ValueError("MMC release version must be a nonempty string")
        count = fetch_mdfs(version)
    except (
        OSError,
        ValueError,
        KeyError,
        tarfile.TarError,
        EOFError,
        HTTPException,
    ):
        LOGGER.exception("MDF fetch failed for MMC-SERVER %s", version)
        return 1
    print(f"MMC-SERVER {version}: extracted {count} MDFs into {DESTINATION}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
