#!/usr/bin/env python3
"""Print the public commit manifest baked into the gateway image."""

from __future__ import annotations

import json
import subprocess


REPOSITORY = "https://github.com/Pinchana/pinchana-api"
NAME_OVERRIDES = {
    "pinchana-inst": "instagram",
    "pinchana-server": "gateway",
}


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], text=True).strip()


def manifest() -> dict[str, dict[str, str]]:
    result = {
        "api": {
            "commit": git("rev-parse", "HEAD"),
            "repository": REPOSITORY,
        }
    }
    entries = git("config", "--file", ".gitmodules", "--get-regexp", "^submodule\\..*\\.path$")
    for entry in entries.splitlines():
        key, path = entry.split(maxsplit=1)
        section = key.removesuffix(".path")
        repository = git("config", "--file", ".gitmodules", "--get", f"{section}.url").removesuffix(".git")
        name = NAME_OVERRIDES.get(path, path.removeprefix("pinchana-"))
        result[name] = {
            "commit": git("rev-parse", f"HEAD:{path}"),
            "repository": repository,
        }
    return result


if __name__ == "__main__":
    print(json.dumps(manifest(), separators=(",", ":"), sort_keys=True))
