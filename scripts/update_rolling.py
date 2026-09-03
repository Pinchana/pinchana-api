#!/usr/bin/env python3
"""Atomically pull and pin Pinchana rolling release and Gluetun images."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


API_IMAGES = {
    "SERVER_IMAGE": "ghcr.io/pinchana/pinchana-api/server",
    "TIKTOK_IMAGE": "ghcr.io/pinchana/pinchana-api/tiktok",
    "INSTAGRAM_IMAGE": "ghcr.io/pinchana/pinchana-api/instagram",
    "SHORTS_IMAGE": "ghcr.io/pinchana/pinchana-api/shorts",
    "SOUNDCLOUD_IMAGE": "ghcr.io/pinchana/pinchana-api/soundcloud",
    "YTMUSIC_IMAGE": "ghcr.io/pinchana/pinchana-api/ytmusic",
    "SPOTIFY_IMAGE": "ghcr.io/pinchana/pinchana-api/spotify",
    "DEEZER_IMAGE": "ghcr.io/pinchana/pinchana-api/deezer",
    "THREADS_IMAGE": "ghcr.io/pinchana/pinchana-api/threads",
    "TWITTER_IMAGE": "ghcr.io/pinchana/pinchana-api/twitter",
    "COUB_IMAGE": "ghcr.io/pinchana/pinchana-api/coub",
}
DLP_IMAGES = {
    "DLP_API_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-api",
    "DLP_ORCHESTRATOR_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-orchestrator",
    "DLP_WORKER_IMAGE": "ghcr.io/pinchana/pinchana-api/dlp-worker",
}
EXTERNAL_IMAGES = {
    "GLUETUN_IMAGE": ("qmcgaw/gluetun", "latest"),
}
DLP_EXTERNAL_IMAGES = {
    "DLP_VPN_IMAGE": ("qmcgaw/gluetun", "latest"),
}
CALVER_PATTERN = re.compile(r"^\d{2}\.(?:0[1-9]|1[0-2])\.(?:[1-9]\d*)$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_LABEL = "org.opencontainers.image.version"


@dataclass(frozen=True)
class ImagePin:
    name: str
    version: str
    reference: str


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(command, check=False, capture_output=capture, text=True)
    if result.returncode:
        detail = result.stderr.strip() if capture else ""
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}{suffix}")
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


def inspect_image(reference: str) -> dict[str, object]:
    payload = json.loads(run(["docker", "image", "inspect", reference], capture=True))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError(f"Unexpected Docker inspection result for {reference}")
    return payload[0]


def image_version(metadata: dict[str, object], reference: str) -> str:
    config = metadata.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    version = labels.get(VERSION_LABEL) if isinstance(labels, dict) else None
    if not isinstance(version, str) or not CALVER_PATTERN.fullmatch(version):
        raise RuntimeError(f"{reference} has no valid {VERSION_LABEL} CalVer label")
    return version


def immutable_reference(repository: str, metadata: dict[str, object], reference: str) -> str:
    values = metadata.get("RepoDigests")
    if not isinstance(values, list):
        raise RuntimeError(f"{reference} has no repository digests")
    digests = {
        value.rsplit("@", 1)[1]
        for value in values
        if isinstance(value, str)
        and "@" in value
        and value.rsplit("@", 1)[0].lower() == repository.lower()
        and DIGEST_PATTERN.fullmatch(value.rsplit("@", 1)[1])
    }
    if len(digests) != 1:
        raise RuntimeError(f"Expected one digest for {reference}, found {len(digests)}")
    return f"{repository}@{digests.pop()}"


def resolve_pin(name: str, repository: str) -> ImagePin:
    rolling = f"{repository}:stable"
    print(f"Discovering {name} from {rolling} ...", flush=True)
    run(["docker", "pull", rolling])
    version = image_version(inspect_image(rolling), rolling)

    versioned = f"{repository}:{version}"
    print(f"Pulling {versioned} ...", flush=True)
    run(["docker", "pull", versioned])
    metadata = inspect_image(versioned)
    if image_version(metadata, versioned) != version:
        raise RuntimeError(f"Version label changed while resolving {name}")
    return ImagePin(name, version, immutable_reference(repository, metadata, versioned))


def resolve_external_pin(name: str, repository: str, tag: str) -> ImagePin:
    """Resolve a third-party rolling tag without requiring Pinchana CalVer labels."""
    rolling = f"{repository}:{tag}"
    print(f"Discovering {name} from {rolling} ...", flush=True)
    run(["docker", "pull", rolling])
    metadata = inspect_image(rolling)
    return ImagePin(name, tag, immutable_reference(repository, metadata, rolling))


def write_pins(env_file: Path, source: str, pins: list[ImagePin]) -> None:
    for pin in pins:
        assignment = re.compile(rf"(?m)^(\s*(?:export\s+)?{pin.name}\s*=).*$")
        if assignment.search(source):
            source = assignment.sub(lambda match: f"{match.group(1)}{pin.reference}", source)
        else:
            source = f"{source.rstrip()}\n{pin.name}={pin.reference}\n"

    mode = stat.S_IMODE(env_file.stat().st_mode)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=env_file.parent, delete=False
        ) as output:
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
    parser.add_argument(
        "--dlp",
        action="store_true",
        help="include DLP API, orchestrator, and worker images",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_file = args.env_file.expanduser().resolve(strict=True)
    if not env_file.is_file():
        raise RuntimeError(f"Environment file is not a regular file: {env_file}")
    source = env_file.read_text(encoding="utf-8")
    selected = dict(API_IMAGES)
    if args.dlp:
        selected.update(DLP_IMAGES)

    release_pins = [
        resolve_pin(name, configured_repository(source, name, default))
        for name, default in selected.items()
    ]
    versions = {pin.version for pin in release_pins}
    if len(versions) != 1:
        details = ", ".join(f"{pin.name}={pin.version}" for pin in release_pins)
        raise RuntimeError(f"Rolling images are not from one release: {details}")

    external = dict(EXTERNAL_IMAGES)
    if args.dlp:
        external.update(DLP_EXTERNAL_IMAGES)
    external_pins = [
        resolve_external_pin(
            name,
            configured_repository(source, name, default_repository),
            tag,
        )
        for name, (default_repository, tag) in external.items()
    ]
    pins = release_pins + external_pins
    version = versions.pop()
    if args.dry_run:
        print("Dry run; no file was changed.")
    else:
        write_pins(env_file, source, pins)
        print(f"Updated {env_file} to rolling release {version}.")
    for pin in pins:
        print(f"{pin.name}={pin.reference}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Rolling image update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
