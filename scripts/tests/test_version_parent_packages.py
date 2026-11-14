"""Verify that package version changes are released from one checkout."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

SPEC = importlib.util.spec_from_file_location("pinchana_release_version", Path(__file__).parents[1] / "version.py")
version = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = version
SPEC.loader.exec_module(version)


class PackageReleaseTests(unittest.TestCase):
    def test_commits_and_pushes_all_package_versions_together(self):
        projects = [
            version.ROOT / "pinchana-core" / "pyproject.toml",
            version.ROOT / "pinchana-apple-music" / "pyproject.toml",
        ]
        with (
            patch.object(version, "project_files", return_value=projects),
            patch.object(version, "git_output", return_value="VERSION") as git_output,
            patch.object(version, "git") as git,
        ):
            version.commit_and_push_version(version.parse_version("26.10.2"), "main")

        git_output.assert_called_once_with("diff", "--cached", "--name-only")
        self.assertEqual(
            git.call_args_list,
            [
                call(
                    "add", "--", "VERSION",
                    "pinchana-core/pyproject.toml", "pinchana-core/uv.lock",
                    "pinchana-apple-music/pyproject.toml", "pinchana-apple-music/uv.lock",
                ),
                call("commit", "-m", "release: 26.10.2"),
                call("push", "origin", "HEAD:refs/heads/main"),
            ],
        )

    def test_rejects_dirty_package_worktree_before_updating_versions(self):
        with (
            patch.object(version, "git_output", return_value=" M pinchana-core/pyproject.toml"),
            patch.object(version, "set_version") as set_version,
        ):
            with self.assertRaisesRegex(RuntimeError, "worktree has uncommitted changes"):
                version.perform_release_update(version.parse_version("26.10.2"), None)
        set_version.assert_not_called()
