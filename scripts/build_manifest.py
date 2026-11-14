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
    for path in git("ls-tree", "-d", "--name-only", "HEAD").splitlines():
        if not path.startswith("pinchana-"):
            continue
        name = NAME_OVERRIDES.get(path, path.removeprefix("pinchana-"))
        result[name] = {
            "commit": git("log", "-1", "--format=%H", "HEAD", "--", path),
            "repository": REPOSITORY,
        }
    return result


if __name__ == "__main__":
    print(json.dumps(manifest(), separators=(",", ":"), sort_keys=True))
