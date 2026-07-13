#!/usr/bin/env python3
"""Fail-closed production preflight for the Pinchana DLP Compose profile."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


PLACEHOLDER_FRAGMENTS = ("replace-with", "disabled-change-me", "your_private_key_here")
DLP_IMAGES = ("DLP_API_IMAGE", "DLP_ORCHESTRATOR_IMAGE", "DLP_WORKER_IMAGE", "DLP_VPN_IMAGE")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, source in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = source.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    values.update(os.environ)
    return values


def fail(message: str) -> None:
    raise RuntimeError(message)


def require_secret(environment: dict[str, str], name: str, minimum: int = 32) -> str:
    value = environment.get(name, "")
    lowered = value.lower()
    if len(value) < minimum or any(fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS):
        fail(f"{name} must be a non-placeholder secret of at least {minimum} characters")
    return value


def compose_config(env_file: Path) -> dict[str, object]:
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "--profile", "dlp", "config", "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail("Docker Compose could not render the DLP production profile")
    return json.loads(result.stdout)


def validate_compose(config: dict[str, object], phase: str) -> None:
    services = config.get("services")
    networks = config.get("networks")
    if not isinstance(services, dict) or not isinstance(networks, dict):
        fail("Compose output is missing services or networks")

    required_services = {"server", "dlp-redis", "dlp-api", "dlp-orchestrator", "dlp-vpn"}
    if not required_services.issubset(services):
        fail("Compose output is missing one or more DLP services")
    for name in required_services - {"server"}:
        service = services[name]
        if not isinstance(service, dict) or service.get("ports"):
            fail(f"{name} must not publish host ports")

    for name in ("dlp-backend", "dlp-gateway", "dlp-worker"):
        network = networks.get(name)
        if not isinstance(network, dict) or network.get("internal") is not True:
            fail(f"{name} must remain an internal Docker network")

    api_volumes = json.dumps(services["dlp-api"].get("volumes", []))
    orchestrator_volumes = json.dumps(services["dlp-orchestrator"].get("volumes", []))
    if "docker.sock" in api_volumes or "docker.sock" not in orchestrator_volumes:
        fail("The Docker socket must be mounted only into the DLP orchestrator")
    api_environment = services["dlp-api"].get("environment", {})
    if not str(api_environment.get("DLP_DOH_URL", "")).startswith("https://"):
        fail("The DLP API must use an HTTPS DNS-over-HTTPS resolver")
    if api_environment.get("DLP_DOH_PROXY_URL") != "http://dlp-vpn:8888":
        fail("The DLP API must resolve public targets through the dedicated DLP VPN")
    orchestrator = services["dlp-orchestrator"]
    if set(orchestrator.get("cap_drop", [])) != {"ALL"} or set(orchestrator.get("cap_add", [])) != {"CHOWN"}:
        fail("The DLP orchestrator must drop all capabilities and add back only CHOWN")
    if "dlp-worker" in services.get("gluetun", {}).get("networks", {}):
        fail("Existing scraper VPN traffic must remain isolated from DLP workers")

    expected = "true" if phase == "enable" else "false"
    server_environment = services["server"].get("environment", {})
    if str(server_environment.get("DLP_ENABLED", "")).lower() != expected:
        fail(f"DLP_ENABLED must be {expected} during the {phase} phase")


def validate_images(environment: dict[str, str], skip_check: bool) -> None:
    for name in DLP_IMAGES:
        image = environment.get(name, "")
        if not image:
            fail(f"{name} is required")
        if image.endswith(":latest") or ":latest@" in image:
            fail(f"{name} must use an immutable release tag or digest, not latest")
        if not skip_check:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode:
                fail(f"Required image is not present locally: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--phase", choices=("infra", "enable"), default="infra")
    parser.add_argument("--skip-image-check", action="store_true")
    args = parser.parse_args()

    if not args.env_file.is_file():
        fail(f"Environment file does not exist: {args.env_file}")
    environment = load_env(args.env_file)
    secrets = [
        require_secret(environment, "DLP_GATEWAY_TOKEN"),
        require_secret(environment, "DLP_OWNER_SECRET"),
        require_secret(environment, "DLP_REDIS_PASSWORD"),
    ]
    if len(set(secrets)) != len(secrets):
        fail("DLP gateway, owner, and Redis secrets must be distinct")
    require_secret(environment, "TURNSTILE_SESSION_SECRET")
    require_secret(environment, "TURNSTILE_SECRET_KEY", minimum=10)
    if not environment.get("TURNSTILE_EXPECTED_HOSTNAME", "").strip():
        fail("TURNSTILE_EXPECTED_HOSTNAME is required")
    require_secret(environment, "WIREGUARD_PRIVATE_KEY", minimum=20)

    jobs_dir = Path(environment.get("DLP_HOST_JOBS_DIR", ""))
    if not jobs_dir.is_absolute() or not jobs_dir.is_dir() or jobs_dir.is_symlink():
        fail("DLP_HOST_JOBS_DIR must be an existing absolute, non-symlink directory")
    mode = stat.S_IMODE(jobs_dir.stat().st_mode)
    if mode & stat.S_IWOTH:
        fail("DLP_HOST_JOBS_DIR must not be world-writable")

    validate_images(environment, args.skip_image_check)
    validate_compose(compose_config(args.env_file), args.phase)
    print(f"DLP production preflight passed for phase={args.phase}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"DLP production preflight failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
