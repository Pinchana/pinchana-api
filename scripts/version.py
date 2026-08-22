#!/usr/bin/env python3
"""Manage and validate the Pinchana rolling CalVer release version.

VERSION uses YY.MM.ITERATION and is the source of truth for releases and
Docker images. Python package metadata uses the equivalent PEP 440 spelling.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CALVER_PATTERN = re.compile(
    r"^(?P<year>\d{2})\.(?P<month>0[1-9]|1[0-2])\.(?P<iteration>[1-9]\d*)$"
)
PEP440_PATTERN = re.compile(
    r"^(?P<release>\d+(?:\.\d+)*)(?:(?P<stage>a|b|rc)(?P<number>\d+))?$"
)


@dataclass(frozen=True)
class Version:
    value: str
    year: int
    month: int
    iteration: int

    @property
    def pep440(self) -> str:
        return f"{self.year}.{self.month}.{self.iteration}"


def parse_version(value: str) -> Version:
    match = CALVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("version must use YY.MM.ITERATION with a 1-based iteration")
    return Version(
        value=value,
        year=int(match.group("year")),
        month=int(match.group("month")),
        iteration=int(match.group("iteration")),
    )


def next_version(version: Version, now: datetime | None = None) -> Version:
    current = now or datetime.now(timezone.utc)
    year = current.year % 100
    month = current.month
    iteration = version.iteration + 1 if (version.year, version.month) == (year, month) else 1
    return parse_version(f"{year:02d}.{month:02d}.{iteration}")


def current_version() -> Version:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ValueError(f"missing {VERSION_FILE.relative_to(ROOT)}") from exc
    return parse_version(value)


def comparable_pep440(value: str) -> tuple[tuple[int, ...], str | None, int | None] | None:
    """Return the subset of normalized PEP 440 used by this repository."""
    match = PEP440_PATTERN.fullmatch(value)
    if match is None:
        return None
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    number = match.group("number")
    return tuple(release), match.group("stage"), int(number) if number is not None else None


def project_files() -> list[Path]:
    return sorted(ROOT.glob("pinchana-*/pyproject.toml"))


def project_metadata(path: Path) -> tuple[str, str]:
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    return project["name"], project["version"]


def validate(version: Version, tag: str | None = None) -> list[str]:
    errors: list[str] = []
    if tag is not None:
        expected_tag = f"v{version.value}"
        if tag != expected_tag:
            errors.append(f"release tag {tag!r} does not match VERSION ({expected_tag})")

    projects = project_files()
    if not projects:
        errors.append("no Python submodule projects found")

    for path in projects:
        relative = path.relative_to(ROOT)
        try:
            name, package_version = project_metadata(path)
        except (KeyError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{relative}: invalid project metadata: {exc}")
            continue
        if package_version != version.pep440:
            errors.append(
                f"{relative}: project.version is {package_version!r}; "
                f"expected {version.pep440!r}"
            )

        lock_path = path.with_name("uv.lock")
        if not lock_path.exists():
            errors.append(f"{lock_path.relative_to(ROOT)}: missing lockfile")
            continue
        try:
            packages = tomllib.loads(lock_path.read_text(encoding="utf-8"))["package"]
        except (KeyError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{lock_path.relative_to(ROOT)}: invalid lockfile: {exc}")
            continue
        locked_versions = {
            package.get("version") for package in packages if package.get("name") == name
        }
        expected_locked_version = comparable_pep440(version.pep440)
        if not any(
            isinstance(locked_version, str)
            and comparable_pep440(locked_version) == expected_locked_version
            for locked_version in locked_versions
        ):
            errors.append(
                f"{lock_path.relative_to(ROOT)}: {name} is not locked at {version.pep440}"
            )
    return errors


def replace_project_version(path: Path, package_version: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(
        r'(?m)^(version\s*=\s*)"[^"]+"$',
        rf'\g<1>"{package_version}"',
        content,
        count=1,
    )
    if replacements != 1:
        raise RuntimeError(f"could not update project.version in {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")


def set_version(version: Version) -> None:
    if shutil.which("uv") is None:
        raise RuntimeError("uv is required to refresh submodule lockfiles")
    projects = project_files()
    if not projects:
        raise RuntimeError("no Python submodule projects found")

    VERSION_FILE.write_text(f"{version.value}\n", encoding="utf-8")
    for path in projects:
        replace_project_version(path, version.pep440)
    for path in projects:
        subprocess.run(
            ["uv", "lock", "--directory", str(path.parent), "--no-progress"],
            cwd=ROOT,
            check=True,
        )


def docker_tags(version: Version) -> list[str]:
    return [version.value, f"{version.year:02d}.{version.month:02d}", "stable"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show", help="print the product CalVer")
    subparsers.add_parser("pep440", help="print the Python package version")
    subparsers.add_parser("next", help="print the next rolling release version")
    check_parser = subparsers.add_parser("check", help="validate all version sources")
    check_parser.add_argument("--tag", help="also require an exact v-prefixed release tag")
    set_parser = subparsers.add_parser("set", help="set VERSION and refresh Python projects")
    set_parser.add_argument("version")
    subparsers.add_parser("bump", help="advance the monthly iteration and refresh projects")
    subparsers.add_parser("docker-tags", help="print release Docker tag suffixes")
    args = parser.parse_args()

    try:
        if args.command in {"set", "bump"}:
            version = (
                parse_version(args.version)
                if args.command == "set"
                else next_version(current_version())
            )
            set_version(version)
            errors = validate(version)
            if errors:
                raise RuntimeError("\n".join(errors))
            print(f"set product version {version.value} (Python {version.pep440})")
            return 0

        version = current_version()
        if args.command == "show":
            print(version.value)
        elif args.command == "pep440":
            print(version.pep440)
        elif args.command == "next":
            print(next_version(version).value)
        elif args.command == "docker-tags":
            print("\n".join(docker_tags(version)))
        elif args.command == "check":
            errors = validate(version, args.tag)
            if errors:
                print("version validation failed:", file=sys.stderr)
                for error in errors:
                    print(f"- {error}", file=sys.stderr)
                return 1
            print(
                f"version {version.value} is consistent across "
                f"{len(project_files())} Python projects"
            )
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"version error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
