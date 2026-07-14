#!/usr/bin/env python3
"""Pull the latest DLP images and pin their immutable digests in an env file."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_IMAGES = {
    "DLP_API_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-api",
    "DLP_ORCHESTRATOR_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-orchestrator",
    "DLP_WORKER_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-worker",
}
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise RuntimeError(message)


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_image_repositories(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    expected = set(DEFAULT_IMAGES)
    for number, source in enumerate(env_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = source.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in expected:
            continue
        if name in values:
            fail(f"{env_file}:{number}: duplicate {name} assignment")
        values[name] = image_repository(unquote(value))

    return {name: values.get(name, default) for name, default in DEFAULT_IMAGES.items()}


def image_repository(reference: str) -> str:
    reference = reference.split("@", 1)[0]
    last_slash = reference.rfind("/")
    last_colon = reference.rfind(":")
    if last_colon > last_slash:
        reference = reference[:last_colon]
    if not reference or "/" not in reference:
        fail(f"Invalid DLP image reference: {reference!r}")
    return reference


def run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, capture_output=capture_output, text=True)
    if result.returncode:
        fail(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def pull_digest(repository: str, tag: str) -> str:
    tagged_reference = f"{repository}:{tag}"
    print(f"Pulling {tagged_reference} ...", flush=True)
    run(["docker", "pull", tagged_reference])
    result = run(
        ["docker", "image", "inspect", tagged_reference, "--format", "{{json .RepoDigests}}"],
        capture_output=True,
    )
    try:
        repo_digests = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Docker returned invalid digest metadata for {tagged_reference}: {exc}")

    if not isinstance(repo_digests, list):
        fail(f"Docker returned no repository digest for {tagged_reference}")
    matches = []
    for candidate in repo_digests:
        if not isinstance(candidate, str) or "@" not in candidate:
            continue
        candidate_repository, digest = candidate.rsplit("@", 1)
        if candidate_repository.lower() == repository.lower() and DIGEST_PATTERN.fullmatch(digest):
            matches.append(f"{repository}@{digest}")
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        fail(f"Expected one repository digest for {tagged_reference}, found {len(matches)}")
    return matches[0]


def replace_env_values(env_file: Path, replacements: dict[str, str]) -> None:
    source = env_file.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    found: set[str] = set()
    assignment = re.compile(r"^(?P<prefix>\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=).*$")

    for index, line in enumerate(lines):
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        body = line[: -len(newline)] if newline else line
        match = assignment.match(body)
        if not match or match.group("name") not in replacements:
            continue
        name = match.group("name")
        if name in found:
            fail(f"{env_file}: duplicate {name} assignment")
        found.add(name)
        lines[index] = f"{match.group('prefix')}{replacements[name]}{newline}"

    missing = [name for name in replacements if name not in found]
    if missing:
        if lines and not lines[-1].endswith(("\n", "\r\n")):
            lines[-1] += "\n"
        lines.extend(f"{name}={replacements[name]}\n" for name in missing)

    mode = stat.S_IMODE(env_file.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{env_file.name}.", dir=env_file.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary:
            temporary.writelines(lines)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.fchmod(temporary.fileno(), mode)
        os.replace(temporary_name, env_file)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull current DLP images and replace their .env values with immutable sha256 digests."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--tag", default="latest", help="Source tag to resolve (default: latest)")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and print pins without editing the env file")
    args = parser.parse_args()

    if not args.env_file.exists():
        fail(f"Environment file does not exist: {args.env_file}")
    env_file = args.env_file.expanduser().resolve(strict=True)
    if not env_file.is_file():
        fail(f"Environment file is not a regular file: {env_file}")
    if not args.tag or any(character.isspace() for character in args.tag):
        fail("The source tag must be a non-empty value without whitespace")

    repositories = read_image_repositories(env_file)
    replacements = {
        name: pull_digest(repository, args.tag)
        for name, repository in repositories.items()
    }

    if args.dry_run:
        print("Dry run; no file was changed.")
    else:
        replace_env_values(env_file, replacements)
        print(f"Updated {env_file} with immutable DLP image digests.")
    for name, reference in replacements.items():
        print(f"{name}={reference}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as exc:
        print(f"DLP image pin update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
