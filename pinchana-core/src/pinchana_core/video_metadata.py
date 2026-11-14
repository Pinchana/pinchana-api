"""Read video metadata from a local media file."""

import json
import math
import subprocess
from pathlib import Path


def duration_seconds(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return math.ceil(seconds) if math.isfinite(seconds) and seconds > 0 else None


def probe_video(path: Path) -> tuple[dict, int | None] | None:
    try:
        process = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration:stream_tags=rotate:"
                "stream_side_data=rotation:format=duration",
                "-of", "json", str(path),
            ],
            stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=5,
        )
        payload = json.loads(process.stdout)
        stream = payload["streams"][0]
        duration = duration_seconds(stream.get("duration")) or duration_seconds(
            (payload.get("format") or {}).get("duration")
        )
        return stream, duration
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
