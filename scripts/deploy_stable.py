#!/usr/bin/env python3
"""Deploy the latest stable Pinchana release to an existing DLP-enabled stack."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from update_rolling import (
    CALVER_PATTERN,
    image_version,
    inspect_image,
    resolve_pins,
    run,
    write_env,
    write_pins,
)


GITHUB_API = "https://api.github.com/repos/Pinchana/pinchana-api"
ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("server", "dlp-api", "dlp-orchestrator")
RETRY_DELAY = 30 * 60


def request_json(url: str, *, timeout: int) -> dict:
    request = Request(url, headers={"User-Agent": "pinchana-stable-deploy"})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected response from {url}")
    return result


def latest_release() -> str:
    release = request_json(f"{GITHUB_API}/releases/latest", timeout=15)
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or not (
        isinstance(tag, str) and tag.startswith("v") and CALVER_PATTERN.fullmatch(tag[1:])
    ):
        raise RuntimeError("GitHub's latest release is not a stable Pinchana version")
    return tag[1:]


def docker_release_ready(version: str) -> bool:
    query = urlencode(
        {"branch": f"v{version}", "event": "push", "status": "success", "per_page": 1}
    )
    url = f"{GITHUB_API}/actions/workflows/docker-publish.yml/runs?{query}"
    result = request_json(url, timeout=15)
    return any(
        job.get("head_branch") == f"v{version}" and job.get("conclusion") == "success"
        for job in result.get("workflow_runs", [])
    )


def compose_args(env_file: Path) -> list[str]:
    return [
        "docker", "compose", "--project-directory", str(env_file.parent),
        "--env-file", str(env_file), "--profile", "dlp",
    ]


def running_versions(compose: list[str]) -> dict[str, str]:
    versions = {}
    for service in SERVICES:
        container = run(compose + ["ps", "--quiet", service], capture=True)
        if not container:
            raise RuntimeError(f"Compose service {service} is not running")
        image = run(["docker", "inspect", "--format", "{{.Image}}", container], capture=True)
        versions[service] = image_version(inspect_image(image), service)
    return versions


def converge(compose: list[str], health_url: str) -> None:
    run(compose + ["up", "--detach", "--wait", "--wait-timeout", "180"])
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            if request_json(health_url, timeout=5).get("status") == "healthy":
                return
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(2)
    raise RuntimeError("Gateway did not report healthy after Compose finished")


def rollback(env_file: Path, pending: Path, failed: Path, health_url: str) -> None:
    record = json.loads(pending.read_text(encoding="utf-8"))
    print(f"Restoring image pins from before {record['version']}", flush=True)
    write_env(env_file, record["env"], mode=record["mode"])
    converge(compose_args(env_file), health_url)
    pending.replace(failed)
    failed.touch()
    print("Previous stack is healthy", flush=True)


def deploy(env_file: Path, state: Path, health_url: str) -> None:
    pending = state / "pending.json"
    failed = state / "failed.json"
    if pending.exists():
        rollback(env_file, pending, failed, health_url)

    version = latest_release()
    compose = compose_args(env_file)
    installed = set(running_versions(compose).values())
    if installed == {version}:
        print(f"Stable {version} is already deployed")
        return
    target = tuple(map(int, version.split(".")))
    if any(tuple(map(int, value.split("."))) > target for value in installed):
        print(f"Stable {version} is older than a running image")
        return
    if failed.exists() and time.time() - failed.stat().st_mtime < RETRY_DELAY:
        if json.loads(failed.read_text(encoding="utf-8"))["version"] == version:
            print(f"Waiting to retry {version} after rollback")
            return
    if not docker_release_ready(version):
        print(f"Waiting for all Docker images for {version}")
        return

    source = env_file.read_text(encoding="utf-8")
    _, pins = resolve_pins(source, dlp=True, version=version)
    with tempfile.NamedTemporaryFile(dir=env_file.parent, prefix=".pinchana-deploy-") as file:
        staged = Path(file.name)
        write_pins(staged, source, pins)
        run(compose_args(staged) + ["config", "--quiet"])
        if run(["docker", "ps", "--quiet", "--filter", "label=pinchana.dlp.job"], capture=True):
            print(f"Deferring {version} while a DLP worker is active")
            return
        if env_file.read_text(encoding="utf-8") != source:
            raise RuntimeError("The Compose environment changed while preparing the release")

        mode = stat.S_IMODE(env_file.stat().st_mode)
        record = {"version": version, "env": source, "mode": mode}
        write_env(pending, json.dumps(record), mode=0o600)
        try:
            write_env(env_file, staged.read_text(encoding="utf-8"), mode=mode)
            converge(compose, health_url)
            versions = running_versions(compose)
            worker = run(
                compose + ["exec", "-T", "dlp-orchestrator", "printenv", "WORKER_IMAGE"],
                capture=True,
            )
            versions["dlp-worker"] = image_version(inspect_image(worker), "dlp-worker")
            if set(versions.values()) != {version}:
                raise RuntimeError(f"Compose started unexpected image versions: {versions}")
        except (Exception, KeyboardInterrupt):
            rollback(env_file, pending, failed, health_url)
            raise
        pending.replace(state / "previous.json")
        print(f"Deployed stable {version}. Gateway and DLP checks passed", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    state_home = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local/state")
    parser.add_argument("--state-dir", type=Path, default=state_home / "pinchana-stable")
    parser.add_argument("--health-url", default="http://127.0.0.1:8080/health")
    args = parser.parse_args()

    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.state_dir / "deploy.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("A stable update is already in progress")
            return
        deploy(ROOT / ".env", args.state_dir, args.health_url)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Stable deployment check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
