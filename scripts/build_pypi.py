#!/usr/bin/env python3
"""Build the selected PyPI distributions and print their publishing matrix."""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from version import ROOT, current_version, project_files, project_metadata, validate


REPOSITORY = "https://github.com/Pinchana/pinchana-api"


def publishable_projects() -> dict[str, Path]:
    return {
        project_metadata(path)[0]: path
        for path in project_files()
        if path.parent.name in {"pinchana-core", "pinchana-scraper"}
        or path.parent.parent == ROOT / "scrapers"
    }


def select_projects(selection: str, projects: dict[str, Path]) -> list[str]:
    if selection.strip() == "all":
        return list(projects)
    requested = [name.strip() for name in selection.split(",")]
    unknown = set(requested) - projects.keys()
    if unknown:
        raise ValueError(f"Unknown PyPI projects: {', '.join(repr(name) for name in sorted(unknown))}")
    return list(dict.fromkeys(requested))


def publishing_environment(name: str) -> str:
    return "pypi" if name == "pinchana-core" else f"pypi-{name}"


def stage_project(manifest: Path, destination: Path) -> None:
    source = manifest.read_text(encoding="utf-8")
    metadata = tomllib.loads(source)["project"]
    directory = manifest.parent
    destination.mkdir()
    shutil.copyfile(directory / metadata["readme"], destination / metadata["readme"])
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE")
    shutil.copytree(
        directory / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*", "secrets"),
    )
    # Leave local paths in the checkout and build portable source archives.
    source = re.sub(r"(?ms)^\[tool\.uv\.sources\][ \t]*\n.*?(?=^\[|\Z)", "", source)
    if "license" not in metadata:
        source, count = re.subn(
            r"(?m)^requires-python = [^\n]+$",
            lambda match: match[0] + '\nlicense = "MIT"\nlicense-files = ["LICENSE"]',
            source,
            count=1,
        )
        if count != 1:
            raise ValueError(f"Could not set license metadata for {manifest}")
    if "urls" not in metadata:
        source += f'\n[project.urls]\nRepository = "{REPOSITORY}"\nIssues = "{REPOSITORY}/issues"\n'
    (destination / "pyproject.toml").write_text(source, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", default="all", help="comma-separated project names or all")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--tag", help="require the release tag to match VERSION")
    args = parser.parse_args()
    try:
        projects = publishable_projects()
        selection = select_projects(args.projects, projects)
        errors = validate(current_version(), args.tag)
        if errors:
            raise ValueError("\n".join(errors))
        output = args.out_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        for name in selection:
            if (output / name).exists():
                raise ValueError(f"Output for {name} already exists at {output / name}")

        with (
            tempfile.TemporaryDirectory(prefix="pinchana-pypi-source-") as staging,
            tempfile.TemporaryDirectory(prefix=".build-", dir=output) as build_output,
        ):
            for name in selection:
                source = Path(staging) / name
                stage_project(projects[name], source)
                package_output = Path(build_output) / name
                subprocess.run(
                    ["uv", "build", "--no-sources", "--no-create-gitignore",
                     "--out-dir", str(package_output), str(source)],
                    check=True,
                    stdout=sys.stderr,
                )
            for name in selection:
                (Path(build_output) / name).rename(output / name)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps({"include": [
        {"project": name, "environment": publishing_environment(name)}
        for name in selection
    ]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
