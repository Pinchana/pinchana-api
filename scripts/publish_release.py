#!/usr/bin/env python3
"""Publish the already-created local tag for the current VERSION.

This script is intentionally strict: the tag must already exist locally, match
VERSION, point at HEAD, and the version metadata/lockfiles must validate before
anything is pushed. It then pushes the current branch and tag, and creates or
updates the GitHub Release with gh.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
VERSION_SCRIPT = ROOT / "scripts" / "version.py"


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


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required")


def current_tag() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION is empty")
    return f"v{version}"


def current_branch() -> str:
    branch = output(["git", "branch", "--show-current"])
    if not branch:
        raise RuntimeError("release publishing requires a checked-out branch")
    return branch


def ensure_clean() -> None:
    status = output(["git", "status", "--porcelain"])
    if status:
        raise RuntimeError("working tree is not clean; commit or stash changes first")


def ensure_submodules_pinned() -> None:
    result = output(["git", "submodule", "status", "--recursive"])
    bad = [line for line in result.splitlines() if line[:1] in {"-", "+", "U"}]
    if bad:
        raise RuntimeError(
            "submodules are not pinned to the parent commit:\n" + "\n".join(bad)
        )


def validate_release(tag: str) -> None:
    run([sys.executable, str(VERSION_SCRIPT), "check", "--tag", tag])

    try:
        tag_commit = output(["git", "rev-parse", f"{tag}^{{commit}}"])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"local tag {tag} does not exist") from exc

    head = output(["git", "rev-parse", "HEAD"])
    if tag_commit != head:
        raise RuntimeError(f"{tag} points to {tag_commit}, but HEAD is {head}")


def release_exists(tag: str) -> bool:
    result = run(
        ["gh", "release", "view", tag, "--json", "tagName"],
        capture=True,
        check=False,
    )
    return result.returncode == 0


def notes_args(description: str | None, description_file: Path | None) -> list[str]:
    if description is not None:
        return ["--notes", description]
    if description_file is not None:
        return ["--notes-file", str(description_file)]
    return ["--generate-notes"]


def publish(
    *,
    tag: str,
    title: str | None,
    description: str | None,
    description_file: Path | None,
    draft: bool,
    prerelease: bool,
) -> None:
    branch = current_branch()

    run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"])
    run(["git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}"])

    exists = release_exists(tag)
    command = ["gh", "release", "edit" if exists else "create", tag]
    if not exists:
        command.append("--verify-tag")

    command += ["--title", title or tag]

    if exists:
        if description is not None:
            command += ["--notes", description]
        elif description_file is not None:
            command += ["--notes-file", str(description_file)]
    else:
        command += notes_args(description, description_file)

    if draft:
        command += ["--draft"] if not exists else ["--draft=true"]
    if prerelease:
        command += ["--prerelease"] if not exists else ["--prerelease=true"]

    run(command)
    action = "updated" if exists else "created"
    print(f"{action} GitHub Release {tag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="local tag to publish; defaults to v<VERSION>")
    parser.add_argument("--title", help="GitHub Release title; defaults to the tag")
    notes = parser.add_mutually_exclusive_group()
    notes.add_argument("-n", "--description", help="GitHub Release description/body")
    notes.add_argument(
        "-F",
        "--description-file",
        type=Path,
        help="read GitHub Release description/body from a file",
    )
    parser.add_argument("--draft", action="store_true", help="create/edit as draft")
    parser.add_argument(
        "--prerelease", action="store_true", help="create/edit as prerelease"
    )
    args = parser.parse_args()

    try:
        require_tool("git")
        require_tool("gh")
        tag = args.tag or current_tag()
        description_file = (
            args.description_file.expanduser().resolve()
            if args.description_file is not None
            else None
        )
        if description_file is not None and not description_file.is_file():
            raise RuntimeError(f"description file not found: {description_file}")

        ensure_clean()
        ensure_submodules_pinned()
        validate_release(tag)
        publish(
            tag=tag,
            title=args.title,
            description=args.description,
            description_file=description_file,
            draft=args.draft,
            prerelease=args.prerelease,
        )
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"publish error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
