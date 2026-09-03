import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "update_rolling.py"
SPEC = importlib.util.spec_from_file_location("update_rolling", SCRIPT)
assert SPEC and SPEC.loader
update_rolling = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update_rolling
SPEC.loader.exec_module(update_rolling)


class UpdateRollingTests(unittest.TestCase):
    def test_external_pin_uses_digest_without_calver_label(self):
        digest = "sha256:" + "a" * 64

        def fake_run(command, *, capture=False):
            if command[:2] == ["docker", "pull"]:
                return ""
            self.assertEqual(
                command,
                ["docker", "image", "inspect", "qmcgaw/gluetun:v3"],
            )
            self.assertTrue(capture)
            return json.dumps(
                [{"Config": {"Labels": None}, "RepoDigests": [f"qmcgaw/gluetun@{digest}"]}]
            )

        with mock.patch.object(update_rolling, "run", side_effect=fake_run):
            pin = update_rolling.resolve_external_pin(
                "GLUETUN_IMAGE", "qmcgaw/gluetun", "v3"
            )

        self.assertEqual(pin.version, "v3")
        self.assertEqual(pin.reference, f"qmcgaw/gluetun@{digest}")

    def test_main_always_updates_main_gluetun_and_leaves_dlp_without_flag(self):
        observed_external = []

        def release_pin(name, repository):
            return update_rolling.ImagePin(name, "26.09.2", f"{repository}@sha256:release")

        def external_pin(name, repository, tag):
            observed_external.append((name, repository, tag))
            return update_rolling.ImagePin(name, tag, f"{repository}@sha256:external")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as env_file:
            env_file.write("GLUETUN_IMAGE=qmcgaw/gluetun:latest\n")
            env_file.flush()
            argv = ["update_rolling.py", "--env-file", env_file.name, "--dry-run"]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(update_rolling, "resolve_pin", side_effect=release_pin),
                mock.patch.object(
                    update_rolling, "resolve_external_pin", side_effect=external_pin
                ),
            ):
                self.assertEqual(update_rolling.main(), 0)

        self.assertEqual(
            observed_external,
            [("GLUETUN_IMAGE", "qmcgaw/gluetun", "v3")],
        )

    def test_dlp_flag_updates_dedicated_gluetun(self):
        observed_names = []

        def release_pin(name, repository):
            return update_rolling.ImagePin(name, "26.09.2", f"{repository}@sha256:release")

        def external_pin(name, repository, tag):
            observed_names.append(name)
            return update_rolling.ImagePin(name, tag, f"{repository}@sha256:external")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as env_file:
            env_file.write(
                "GLUETUN_IMAGE=qmcgaw/gluetun:latest\n"
                "DLP_VPN_IMAGE=qmcgaw/gluetun:v3.40.0\n"
            )
            env_file.flush()
            argv = [
                "update_rolling.py",
                "--env-file",
                env_file.name,
                "--dry-run",
                "--dlp",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(update_rolling, "resolve_pin", side_effect=release_pin),
                mock.patch.object(
                    update_rolling, "resolve_external_pin", side_effect=external_pin
                ),
            ):
                self.assertEqual(update_rolling.main(), 0)

        self.assertEqual(observed_names, ["GLUETUN_IMAGE", "DLP_VPN_IMAGE"])


if __name__ == "__main__":
    unittest.main()
