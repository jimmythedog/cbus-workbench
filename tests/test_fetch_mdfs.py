"""Contracts for fetching the development MDF collection without network access."""

import io
import tarfile
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from scripts import fetch_mdfs


def release_archive(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, contents in entries.items():
            member = tarfile.TarInfo(f"MMC-SERVER-release/{name}")
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return buffer.getvalue()


class FetchMdfsTests(unittest.TestCase):
    def test_fetch_replaces_collection_with_only_release_mdfs(self):
        data = release_archive(
            {
                "VLCB-server/config/modules/MODULE-A.json": b'{"moduleName":"A"}',
                "VLCB-server/config/modules/MODULE-B.json": b'{"moduleName":"B"}',
                "VLCB-server/config/modules/notes.txt": b"not an MDF",
                "unit_tests/config/example.json": b"{}",
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "resources" / "mdfs"
            destination.mkdir(parents=True)
            (destination / "stale.json").write_text("{}")
            with patch.object(fetch_mdfs, "urlopen", return_value=io.BytesIO(data)):
                count = fetch_mdfs.fetch_mdfs("v-test", destination)
            self.assertEqual(count, 2)
            self.assertEqual(
                {file.name: file.read_bytes() for file in destination.iterdir()},
                {
                    "MODULE-A.json": b'{"moduleName":"A"}',
                    "MODULE-B.json": b'{"moduleName":"B"}',
                },
            )

    def test_failed_fetch_preserves_previous_collection(self):
        cases = [
            URLError("download unavailable"),
            b"not a tar archive",
            release_archive({"README.md": b"no MDFs"}),
            release_archive({"VLCB-server/config/modules/../../escape.json": b"{}"}),
        ]
        for response in cases:
            with (
                self.subTest(response=type(response).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                destination = Path(temporary) / "resources" / "mdfs"
                destination.mkdir(parents=True)
                previous = destination / "previous.json"
                previous.write_bytes(b"previous collection")
                options = (
                    {"side_effect": response}
                    if isinstance(response, Exception)
                    else {"return_value": io.BytesIO(response)}
                )
                with (
                    patch.object(fetch_mdfs, "urlopen", **options),
                    self.assertRaises((OSError, ValueError, tarfile.TarError)),
                ):
                    fetch_mdfs.fetch_mdfs("v-test", destination)
                self.assertEqual(previous.read_bytes(), b"previous collection")
                self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_cli_uses_pin_or_override_and_reports_version_and_count(self):
        self.assertEqual(fetch_mdfs.DESTINATION, fetch_mdfs.ROOT / "resources" / "mdfs")
        with (fetch_mdfs.ROOT / "pyproject.toml").open("rb") as config:
            pinned = tomllib.load(config)["tool"]["cbus-workbench"]["mmc_version"]
        for arguments, version in [([], pinned), (["--version", "v-other"], "v-other")]:
            with self.subTest(arguments=arguments):
                output = io.StringIO()
                url = f"https://api.github.com/repos/david284/MMC-SERVER/tarball/{version}"
                data = release_archive({"VLCB-server/config/modules/A.json": b"{}"})

                def download(requested_url, timeout, expected_url=url, archive=data):
                    if requested_url != expected_url:
                        raise URLError(f"Unexpected release URL: {requested_url}")
                    return io.BytesIO(archive)

                with tempfile.TemporaryDirectory() as temporary:
                    destination = Path(temporary) / "resources" / "mdfs"
                    with (
                        patch.object(fetch_mdfs, "DESTINATION", destination),
                        patch.object(fetch_mdfs, "urlopen", side_effect=download),
                        redirect_stdout(output),
                    ):
                        self.assertEqual(fetch_mdfs.main(arguments), 0)
                    self.assertEqual((destination / "A.json").read_bytes(), b"{}")
                self.assertIn(
                    f"MMC-SERVER {version}: extracted 1 MDFs", output.getvalue()
                )
                self.assertIn(str(destination), output.getvalue())

    def test_cli_returns_failure_with_download_error(self):
        with (
            patch.object(fetch_mdfs, "urlopen", side_effect=URLError("offline")),
            patch.object(fetch_mdfs.LOGGER, "disabled", True),
        ):
            self.assertEqual(fetch_mdfs.main(["--version", "v-test"]), 1)


if __name__ == "__main__":
    unittest.main()
