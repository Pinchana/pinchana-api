"""Release metadata for new parent-owned packages must not commit the parent early."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("pinchana_release_version", Path(__file__).parents[1] / "version.py")
version = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = version
SPEC.loader.exec_module(version)


class ParentPackageReleaseTests(unittest.TestCase):
    def test_submodule_commit_skips_parent_owned_package(self):
        core = version.ROOT / "pinchana-core"
        apple = version.ROOT / "pinchana-apple-music"
        with patch.object(version, "submodule_paths", return_value=[core]), \
                patch.object(version, "project_files", return_value=[core / "pyproject.toml", apple / "pyproject.toml"]), \
                patch.object(version, "has_staged_changes", return_value=True), \
                patch.object(version, "git") as git:
            version.commit_submodule_versions(version.Version("26.10.2", 26, 10, 2))
        self.assertEqual(git.call_count, 2)
        self.assertTrue(all(call.kwargs["cwd"] == core for call in git.call_args_list))

    def test_parent_commit_includes_owned_package_metadata(self):
        core = version.ROOT / "pinchana-core"
        apple = version.ROOT / "pinchana-apple-music"
        with patch.object(version, "submodule_paths", return_value=[core]), \
                patch.object(version, "project_files", return_value=[core / "pyproject.toml", apple / "pyproject.toml"]), \
                patch.object(version, "root_branch", return_value="main"), \
                patch.object(version, "has_staged_changes", return_value=True), \
                patch.object(version, "git") as git:
            version.commit_and_push_parent(version.Version("26.10.2", 26, 10, 2),
                                           [version.SubmoduleState(core, "main")])
        self.assertEqual(git.call_args_list[0].args, (
            "add", "VERSION", "pinchana-core", "pinchana-apple-music/pyproject.toml",
            "pinchana-apple-music/uv.lock",
        ))
