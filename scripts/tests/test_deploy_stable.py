import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

with mock.patch.object(sys, "path", [str(Path(__file__).parents[1]), *sys.path]):
    import deploy_stable
    from update_rolling import ImagePin


class DeployStableTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.env = self.root / ".env"
        self.original = "SERVER_IMAGE=old\nOTHER_SETTING=keep\n"
        self.env.write_text(self.original, encoding="utf-8")
        self.env.chmod(0o640)
        self.health_url = "http://127.0.0.1:8080/health"
        self.target = "26.11.17"
        self.installed = dict.fromkeys(deploy_stable.SERVICES, "26.11.16")
        self.patch("latest_release", return_value=self.target)
        self.versions = self.patch("running_versions", return_value=self.installed)
        self.ready = self.patch("docker_release_ready", return_value=True)
        self.resolve = self.patch(
            "resolve_pins",
            return_value=(self.target, [ImagePin("SERVER_IMAGE", self.target, "new")]),
        )
        self.run_command = self.patch("run", return_value="")
        self.converge = self.patch("converge")

    def patch(self, name, **kwargs):
        patcher = mock.patch.object(deploy_stable, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_waits_for_docker_workflow_before_pulling_or_changing_pins(self):
        self.ready.return_value = False

        deploy_stable.deploy(self.env, self.state, self.health_url)

        self.resolve.assert_not_called()
        self.converge.assert_not_called()
        self.assertEqual(self.env.read_text(), self.original)

    def test_does_not_downgrade_a_newer_running_service(self):
        self.installed["dlp-api"] = "26.11.18"

        deploy_stable.deploy(self.env, self.state, self.health_url)

        self.ready.assert_not_called()
        self.converge.assert_not_called()

    def test_active_dlp_worker_defers_restart(self):
        self.run_command.side_effect = ["", "running-worker"]

        deploy_stable.deploy(self.env, self.state, self.health_url)

        self.converge.assert_not_called()
        self.assertEqual(self.env.read_text(), self.original)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_success_waits_for_all_running_image_versions_and_keeps_backup(self):
        self.versions.side_effect = [self.installed, dict.fromkeys(deploy_stable.SERVICES, self.target)]
        self.patch("inspect_image")
        self.patch("image_version", return_value=self.target)

        deploy_stable.deploy(self.env, self.state, self.health_url)

        self.resolve.assert_called_once_with(self.original, dlp=True, version=self.target)
        self.converge.assert_called_once()
        self.assertEqual(self.env.read_text(), "SERVER_IMAGE=new\nOTHER_SETTING=keep\n")
        previous = self.state / "previous.json"
        self.assertEqual(json.loads(previous.read_text())["env"], self.original)
        self.assertEqual(previous.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.state / "pending.json").exists())

    def test_failed_health_check_restores_pins_and_backs_off(self):
        self.converge.side_effect = [RuntimeError("Gateway unhealthy"), None]

        with self.assertRaisesRegex(RuntimeError, "Gateway unhealthy"):
            deploy_stable.deploy(self.env, self.state, self.health_url)

        self.assertEqual(self.env.read_text(), self.original)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.state / "pending.json").exists())
        self.assertEqual(json.loads((self.state / "failed.json").read_text())["version"], self.target)

        deploy_stable.deploy(self.env, self.state, self.health_url)

        self.resolve.assert_called_once()
        self.assertEqual(self.converge.call_count, 2)


if __name__ == "__main__":
    unittest.main()
