#!/usr/bin/env python3
"""Manage, synchronize, and publish the Pinchana rolling CalVer version.

VERSION uses YY.MM.ITERATION and is the source of truth for releases and
Docker images. Python package metadata uses the equivalent PEP 440 spelling.

By default, `set` and `bump` are release operations: they synchronize all git
submodules, refresh package versions and uv.lock files, commit and push each
submodule, then commit and push the parent repository. Use --local-only to keep
the old file-only behavior. Add --publish to also create/push the matching tag
and publish a GitHub Release through gh.
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
PUBLISH_SCRIPT = ROOT / "scripts" / "publish_release.py"
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


@dataclass(frozen=True)
class SubmoduleState:
    path: Path
    branch: str


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def output(command: list[str], *, cwd: Path = ROOT) -> str:
    return run(command, cwd=cwd, capture=True).stdout.strip()


def git(
    *args: str,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, capture=capture, check=check)


def git_output(*args: str, cwd: Path = ROOT) -> str:
    return output(["git", *args], cwd=cwd)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required")


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
    iteration = (
        version.iteration + 1
        if (version.year, version.month) == (year, month)
        else 1
    )
    return parse_version(f"{year:02d}.{month:02d}.{iteration}")


def current_version() -> Version:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ValueError(f"missing {VERSION_FILE.relative_to(ROOT)}") from exc
    return parse_version(value)


def comparable_pep440(
    value: str,
) -> tuple[tuple[int, ...], str | None, int | None] | None:
    """Return the subset of normalized PEP 440 used by this repository."""
    match = PEP440_PATTERN.fullmatch(value)
    if match is None:
        return None
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    number = match.group("number")
    return (
        tuple(release),
        match.group("stage"),
        int(number) if number is not None else None,
    )


def project_files() -> list[Path]:
    return sorted(ROOT.glob("pinchana-*/pyproject.toml"))


def submodule_paths() -> list[Path]:
    result = git(
        "config",
        "--file",
        ".gitmodules",
        "--get-regexp",
        r"^submodule\..*\.path$",
        capture=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        _, path = line.split(None, 1)
        paths.append(ROOT / path.strip())
    if not paths:
        raise RuntimeError("no git submodules configured")
    return paths


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
            package.get("version")
            for package in packages
            if package.get("name") == name
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
        raise RuntimeError(
            f"could not update project.version in {path.relative_to(ROOT)}"
        )
    path.write_text(updated, encoding="utf-8")


def set_version(version: Version) -> None:
    require_tool("uv")
    projects = project_files()
    if not projects:
        raise RuntimeError("no Python submodule projects found")

    VERSION_FILE.write_text(f"{version.value}\n", encoding="utf-8")
    for path in projects:
        replace_project_version(path, version.pep440)
    for path in projects:
        run(
            ["uv", "lock", "--directory", str(path.parent), "--no-progress"],
            cwd=ROOT,
        )


def docker_tags(version: Version) -> list[str]:
    return [version.value, f"{version.year:02d}.{version.month:02d}", "stable"]


def ensure_root_clean() -> None:
    status = git_output(
        "status", "--porcelain", "--untracked-files=normal", "--ignore-submodules=all"
    )
    if status:
        raise RuntimeError(
            "parent worktree has uncommitted non-submodule changes; commit or stash first"
        )


def ensure_submodule_clean(path: Path) -> None:
    status = git_output("status", "--porcelain", cwd=path)
    if status:
        raise RuntimeError(
            f"submodule {path.relative_to(ROOT)} has uncommitted changes; "
            "commit or stash them first"
        )


def remote_default_branch(path: Path) -> str:
    symbolic = git(
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        cwd=path,
        capture=True,
        check=False,
    )
    if symbolic.returncode == 0 and symbolic.stdout.strip():
        return symbolic.stdout.strip().removeprefix("origin/")

    for candidate in ("main", "master"):
        probe = git(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{candidate}",
            cwd=path,
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError(
        f"cannot determine default remote branch for {path.relative_to(ROOT)}"
    )


def is_ancestor(path: Path, older: str, newer: str) -> bool:
    result = git(
        "merge-base", "--is-ancestor", older, newer, cwd=path, check=False
    )
    return result.returncode == 0


def synchronize_submodules() -> list[SubmoduleState]:
    """Initialize submodules and move stale pins to remote heads safely.

    A pinned commit behind origin/<default> is fast-forwarded to the remote head.
    A pinned commit ahead of the remote is kept so the release push can publish
    it. Divergent histories are rejected instead of being rewritten.
    """
    require_tool("git")
    ensure_root_clean()
    git("submodule", "sync", "--recursive")
    git("submodule", "update", "--init", "--recursive")

    states: list[SubmoduleState] = []
    for path in submodule_paths():
        ensure_submodule_clean(path)
        git("fetch", "origin", "--prune", cwd=path)
        branch = remote_default_branch(path)
        local_head = git_output("rev-parse", "HEAD", cwd=path)
        remote_ref = f"origin/{branch}"
        remote_head = git_output("rev-parse", remote_ref, cwd=path)

        if local_head != remote_head:
            if is_ancestor(path, local_head, remote_head):
                git("checkout", "--detach", remote_ref, cwd=path)
            elif not is_ancestor(path, remote_head, local_head):
                raise RuntimeError(
                    f"submodule {path.relative_to(ROOT)} diverged from {remote_ref}; "
                    "resolve it manually before releasing"
                )

        states.append(SubmoduleState(path=path, branch=branch))
    return states


def has_staged_changes(path: Path) -> bool:
    result = git("diff", "--cached", "--quiet", cwd=path, check=False)
    return result.returncode != 0


def commit_submodule_versions(version: Version) -> None:
    message = f"release: {version.value}"
    for project_path in project_files():
        path = project_path.parent
        git("add", "pyproject.toml", "uv.lock", cwd=path)
        if has_staged_changes(path):
            git("commit", "-m", message, cwd=path)


def push_submodules(states: list[SubmoduleState]) -> None:
    for state in states:
        ensure_submodule_clean(state.path)
        git(
            "push",
            "origin",
            f"HEAD:refs/heads/{state.branch}",
            cwd=state.path,
        )


def root_branch() -> str:
    branch = git_output("branch", "--show-current")
    if not branch:
        raise RuntimeError("parent repository must be on a branch")
    return branch


def commit_and_push_parent(version: Version, states: list[SubmoduleState]) -> None:
    branch = root_branch()
    relative_paths = [str(state.path.relative_to(ROOT)) for state in states]
    git("add", "VERSION", *relative_paths)
    if not has_staged_changes(ROOT):
        raise RuntimeError(
            f"release {version.value} produced no parent changes; "
            "the version may already be fully synchronized"
        )
    git("commit", "-m", f"release: {version.value}")
    git("push", "origin", f"HEAD:refs/heads/{branch}")


def create_release_tag(version: Version) -> str:
    tag = f"v{version.value}"
    probe = git("rev-parse", "--verify", f"refs/tags/{tag}", capture=True, check=False)
    head = git_output("rev-parse", "HEAD")
    if probe.returncode == 0:
        tag_head = git_output("rev-parse", f"{tag}^{{commit}}")
        if tag_head != head:
            raise RuntimeError(
                f"local tag {tag} already points to {tag_head}, not current HEAD {head}"
            )
        return tag

    git("tag", "-a", tag, "-m", f"release: {version.value}")
    return tag


def publish_release(version: Version, args: argparse.Namespace) -> None:
    require_tool("gh")
    tag = create_release_tag(version)
    command = [sys.executable, str(PUBLISH_SCRIPT), "--tag", tag]
    if args.release_title:
        command += ["--title", args.release_title]
    if args.description is not None:
        command += ["--description", args.description]
    elif args.description_file is not None:
        command += ["--description-file", str(args.description_file.expanduser().resolve())]
    if args.draft:
        command.append("--draft")
    if args.prerelease:
        command.append("--prerelease")
    run(command)


def perform_release_update(version: Version, args: argparse.Namespace) -> None:
    states = synchronize_submodules()
    set_version(version)
    errors = validate(version)
    if errors:
        raise RuntimeError("\n".join(errors))

    commit_submodule_versions(version)
    push_submodules(states)
    commit_and_push_parent(version, states)

    print(
        f"released version metadata {version.value} (Python {version.pep440}); "
        "submodules and parent were pushed"
    )
    if args.publish:
        publish_release(version, args)


def add_release_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="only edit VERSION/package metadata/lockfiles; do not sync, commit, or push",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="after pushing version commits, create the tag and publish a GitHub Release",
    )
    parser.add_argument("--release-title", help="GitHub Release title")
    notes = parser.add_mutually_exclusive_group()
    notes.add_argument("-n", "--description", help="GitHub Release description/body")
    notes.add_argument(
        "-F",
        "--description-file",
        type=Path,
        help="read the GitHub Release description/body from a file",
    )
    parser.add_argument("--draft", action="store_true", help="publish the release as draft")
    parser.add_argument(
        "--prerelease", action="store_true", help="publish the release as prerelease"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show", help="print the product CalVer")
    subparsers.add_parser("pep440", help="print the Python package version")
    subparsers.add_parser("next", help="print the next rolling release version")

    check_parser = subparsers.add_parser("check", help="validate all version sources")
    check_parser.add_argument("--tag", help="also require an exact v-prefixed release tag")

    set_parser = subparsers.add_parser(
        "set", help="set a version, synchronize submodules, commit, and push"
    )
    set_parser.add_argument("version")
    add_release_options(set_parser)

    bump_parser = subparsers.add_parser(
        "bump", help="advance the monthly iteration, synchronize, commit, and push"
    )
    add_release_options(bump_parser)

    subparsers.add_parser("docker-tags", help="print release Docker tag suffixes")
    args = parser.parse_args()

    try:
        if args.command in {"set", "bump"}:
            version = (
                parse_version(args.version)
                if args.command == "set"
                else next_version(current_version())
            )
            if args.local_only:
                if args.publish:
                    raise RuntimeError("--publish cannot be combined with --local-only")
                set_version(version)
                errors = validate(version)
                if errors:
                    raise RuntimeError("\n".join(errors))
                print(
                    f"set product version {version.value} (Python {version.pep440}) locally"
                )
            else:
                perform_release_update(version, args)
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
