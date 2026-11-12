"""MDF selection contracts using small, unmodified MMC release descriptors."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from workbench.mdfs import MdfError, MdfRepository
from workbench.pnn import Pnn

FIXTURES = Path(__file__).parent / "fixtures" / "mdfs"
ACE = "CANACE3-A504-2g.json"
GATE = "CANGATE-A54B-1b.json"


class MdfTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.system = self.root / "system"
        self.user = self.root / "user"
        self.system.mkdir()
        self.user.mkdir()
        self.repository = MdfRepository(self.system, self.user)
        self.identity = Pnn(42, 0xA5, 0x04, 0)
        self.parameters = {2: ord("g"), 7: 2}

    def test_selects_real_descriptors_with_optional_event_variables(self):
        for filename, identity, parameters in (
            (ACE, self.identity, self.parameters),
            (GATE, Pnn(43, 0xA5, 0x4B, 0), {2: ord("b"), 7: 1}),
        ):
            with self.subTest(filename=filename):
                path = Path(shutil.copy(FIXTURES / filename, self.system))
                result = self.repository.lookup(identity, parameters)
                self.assertEqual(result.path, path)
                self.assertEqual(result.data, json.loads(path.read_text()))

    def test_firmware_letters_match_in_either_case(self):
        for filename_minor, node_minor in (("v", "V"), ("V", "v")):
            with self.subTest(filename_minor=filename_minor, node_minor=node_minor):
                path = self.system / f"CANACC8-A503-2{filename_minor}.json"
                shutil.copy(FIXTURES / ACE, path)
                result = self.repository.lookup(
                    Pnn(42, 0xA5, 0x03, 0), {2: ord(node_minor), 7: 2}
                )
                self.assertEqual(result.path, path)
                path.unlink()

    def test_user_overrides_same_identity_even_with_different_display_name(self):
        shutil.copy(FIXTURES / ACE, self.system)
        custom = self.user / "CUSTOM-A504-2G.json"
        data = json.loads((FIXTURES / ACE).read_text())
        data["moduleName"] = "Custom controls"
        custom.write_text(json.dumps(data))
        result = self.repository.lookup(self.identity, self.parameters)
        self.assertEqual(result.path, custom)
        self.assertEqual(result.data["moduleName"], "Custom controls")
        # Removing an override takes effect on the next lookup without a reload API.
        custom.unlink()
        self.assertEqual(
            self.repository.lookup(self.identity, self.parameters).path,
            self.system / ACE,
        )

    def test_missing_directories_and_incompatible_identity_return_no_mdf(self):
        absent = MdfRepository(self.root / "missing-system", self.root / "missing-user")
        self.assertIsNone(absent.lookup(self.identity, self.parameters))
        shutil.copy(FIXTURES / ACE, self.system)
        for identity, parameters in (
            (None, self.parameters),
            (self.identity, {7: 2}),
            (self.identity, {2: ord("g")}),
            (Pnn(42, 0xFA, 0x04, 0), self.parameters),
            (Pnn(42, 0xA5, 0x05, 0), self.parameters),
            (self.identity, {**self.parameters, 7: 3}),
            (self.identity, {**self.parameters, 1: 0xFA}),
        ):
            with self.subTest(identity=identity, parameters=parameters):
                self.assertIsNone(self.repository.lookup(identity, parameters))

    def test_beta_parameter_does_not_affect_selection(self):
        shutil.copy(FIXTURES / ACE, self.system)
        for beta_parameters in ({}, {20: 0}, {20: 1}):
            with self.subTest(beta_parameters=beta_parameters):
                result = self.repository.lookup(
                    self.identity, {**self.parameters, **beta_parameters}
                )
                self.assertEqual(result.path, self.system / ACE)

    def lookup_in_new_session(self, system, user):
        """Use a fresh process to test the application-session diagnostic contract."""
        code = """
import logging
import sys
from pathlib import Path
from workbench.mdfs import MdfRepository
from workbench.pnn import Pnn

logging.basicConfig(level=logging.WARNING, format='%(levelname)s:%(message)s')
repository = MdfRepository(Path(sys.argv[1]), Path(sys.argv[2]))
for current in (repository, repository, MdfRepository(Path(sys.argv[1]), Path(sys.argv[2]))):
    result = current.lookup(Pnn(42, 0xA5, 4, 0), {2: ord('g'), 7: 2})
    print(result.path.name if result else 'None')
"""
        return subprocess.run(
            [sys.executable, "-c", code, str(system), str(user)],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_missing_system_directory_warns_once_across_repositories_and_continues(
        self,
    ):
        missing_system = self.root / "missing-system"
        missing_user = self.root / "missing-user"
        result = self.lookup_in_new_session(missing_system, missing_user)
        self.assertEqual(result.stdout.splitlines(), ["None"] * 3)
        self.assertEqual(
            result.stderr.splitlines(),
            [f"WARNING:System MDF directory is missing: {missing_system.absolute()}"],
        )
        # A new application session reports the missing installation again.
        missing_user.mkdir()
        shutil.copy(FIXTURES / ACE, missing_user)
        next_session = self.lookup_in_new_session(missing_system, missing_user)
        self.assertEqual(next_session.stderr, result.stderr)
        self.assertEqual(next_session.stdout.splitlines(), [ACE] * 3)

    def test_missing_user_directory_is_quiet_and_system_lookup_succeeds(self):
        shutil.copy(FIXTURES / ACE, self.system)
        result = self.lookup_in_new_session(self.system, self.root / "missing-user")
        self.assertEqual(result.stdout.splitlines(), [ACE] * 3)
        self.assertEqual(result.stderr, "")

    def test_incompatible_and_unrelated_invalid_user_files_do_not_override(self):
        shutil.copy(FIXTURES / ACE, self.system)
        (self.user / "CUSTOM-A504-3g.json").write_text("invalid JSON")
        (self.user / "OTHER-FA04-2g.json").write_text("invalid JSON")
        self.assertEqual(
            self.repository.lookup(self.identity, self.parameters).path,
            self.system / ACE,
        )

    def test_invalid_matching_user_descriptor_reports_error_without_fallback(self):
        shutil.copy(FIXTURES / ACE, self.system)
        override = self.user / ACE
        for contents in (
            "invalid JSON",
            "[]",
            '{"moduleName":"ACE","nodeVariables":{}}',
            '{"moduleName":"ACE","nodeVariables":[],"eventVariables":{}}',
            '{"moduleName":"ACE","nodeVariables":[42]}',
            '{"moduleName":"ACE","nodeVariables":[{}]}',
        ):
            with self.subTest(contents=contents):
                override.write_text(contents)
                with self.assertRaises(MdfError) as error:
                    self.repository.lookup(self.identity, self.parameters)
                self.assertIn(str(override), str(error.exception))

    def test_processor_specific_descriptor_requires_matching_confirmed_processor(self):
        specific = self.system / "CANACE3-A504-2G--P23.json"
        shutil.copy(FIXTURES / ACE, specific)
        self.assertIsNone(self.repository.lookup(self.identity, self.parameters))
        self.assertIsNone(
            self.repository.lookup(self.identity, {**self.parameters, 9: 21})
        )
        self.assertEqual(
            self.repository.lookup(self.identity, {**self.parameters, 9: 23}).path,
            specific,
        )
        shutil.copy(FIXTURES / ACE, self.system)
        self.assertEqual(
            self.repository.lookup(self.identity, {**self.parameters, 9: 23}).path,
            specific,
        )
        self.assertEqual(
            self.repository.lookup(self.identity, {**self.parameters, 9: 21}).path,
            self.system / ACE,
        )
        # User precedence applies before processor specificity in the system layer.
        shutil.copy(FIXTURES / ACE, self.user)
        self.assertEqual(
            self.repository.lookup(self.identity, {**self.parameters, 9: 23}).path,
            self.user / ACE,
        )

    def test_ambiguous_user_descriptors_report_error_without_arbitrary_choice(self):
        shutil.copy(FIXTURES / ACE, self.system)
        shutil.copy(FIXTURES / ACE, self.user)
        shutil.copy(FIXTURES / ACE, self.user / "OTHER-A504-2G.json")
        with self.assertRaises(MdfError):
            self.repository.lookup(self.identity, self.parameters)

    def test_incompatible_processor_specific_user_mdf_does_not_override_system(self):
        system_path = self.system / "CANACE3-A504-2g--P21.json"
        user_path = self.user / "CANACE3-A504-2G--P23.json"
        shutil.copy(FIXTURES / ACE, system_path)
        shutil.copy(FIXTURES / ACE, user_path)
        result = self.repository.lookup(self.identity, {**self.parameters, 9: 21})
        self.assertEqual(result.path, system_path)


if __name__ == "__main__":
    unittest.main()
