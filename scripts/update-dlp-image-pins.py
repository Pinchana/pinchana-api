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


IMAGES = {
    "DLP_API_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-api",
    "DLP_ORCHESTRATOR_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-orchestrator",
    "DLP_WORKER_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-worker",
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(command, check=False, capture_output=capture, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout.strip() if capture else ""


def configured_repository(source: str, name: str, default: str) -> str:
    matches = re.findall(rf"(?m)^\s*(?:export\s+)?{name}\s*=\s*([^#\r\n]+)", source)
    if len(matches) > 1:
        raise RuntimeError(f"Duplicate {name} assignment")
    reference = matches[0].strip().strip("'\"") if matches else default
    reference = reference.split("@", 1)[0]
    if reference.rfind(":") > reference.rfind("/"):
        reference = reference[: reference.rfind(":")]
    if "/" not in reference:
        raise RuntimeError(f"Invalid image repository for {name}: {reference!r}")
    return reference


def latest_digest(repository: str) -> str:
    tagged = f"{repository}:latest"
    print(f"Pulling {tagged} ...", flush=True)
    run(["docker", "pull", tagged])
    values = json.loads(
        run(["docker", "image", "inspect", tagged, "--format", "{{json .RepoDigests}}"], capture=True)
    )
    matches = {
        value.rsplit("@", 1)[1]
        for value in values
        if isinstance(value, str)
        and "@" in value
        and value.rsplit("@", 1)[0].lower() == repository.lower()
        and DIGEST.fullmatch(value.rsplit("@", 1)[1])
    }
    if len(matches) != 1:
        raise RuntimeError(f"Expected one digest for {tagged}, found {len(matches)}")
    return f"{repository}@{matches.pop()}"


def write_pins(env_file: Path, source: str, pins: dict[str, str]) -> None:
    for name, reference in pins.items():
        assignment = re.compile(rf"(?m)^(\s*(?:export\s+)?{name}\s*=).*$")
        if assignment.search(source):
            source = assignment.sub(lambda match: f"{match.group(1)}{reference}", source)
        else:
            source = f"{source.rstrip()}\n{name}={reference}\n"

    mode = stat.S_IMODE(env_file.stat().st_mode)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as output:
            temporary = output.name
            output.write(source)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, env_file)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_file = args.env_file.expanduser().resolve(strict=True)
    if not env_file.is_file():
        raise RuntimeError(f"Environment file is not a regular file: {env_file}")
    source = env_file.read_text(encoding="utf-8")
    pins = {
        name: latest_digest(configured_repository(source, name, default))
        for name, default in IMAGES.items()
    }
    if args.dry_run:
        print("Dry run; no file was changed.")
    else:
        write_pins(env_file, source, pins)
        print(f"Updated {env_file} with immutable DLP image digests.")
    for name, reference in pins.items():
        print(f"{name}={reference}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"DLP image pin update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
