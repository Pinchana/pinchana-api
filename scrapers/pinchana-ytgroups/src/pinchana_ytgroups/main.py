"""Download a compact, streamable YouTube video for Telegram groups."""

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, FastAPI, HTTPException
from pinchana_core.models import ScrapeRequest, ScrapeResponse
from pinchana_core.plugins import ScraperPlugin, registry
from pinchana_core.storage import MediaStorage
from pinchana_core.vpn import GluetunController
from pinchana_core.youtube_cookies import runtime_cookiefile
from yt_dlp import YoutubeDL

from pinchana_core.ytdlp import ManagedYoutubeDL
from yt_dlp.utils import DownloadError


logger = logging.getLogger(__name__)
router = APIRouter()
gluetun = GluetunController()
storage = MediaStorage(
    base_path=os.getenv("CACHE_PATH", "./cache"),
    max_size_gb=float(os.getenv("CACHE_MAX_SIZE_GB", "10.0")),
)
slots = asyncio.Semaphore(max(1, int(os.getenv("YTDLP_CONCURRENCY", "2"))))
MAX_BYTES = 2_000_000_000
DOWNLOAD_SECONDS = 540
TARGET_BYTES_PER_MINUTE = 15_000_000
RESOLUTION_LIMITS = ((1080, 1920), (720, 1280), (480, 854), (360, 640), (240, 426))
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
WATCH_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
YDL_OPTIONS = {
    "quiet": True, "noprogress": True, "no_warnings": True, "noplaylist": True,
    "socket_timeout": 15, "retries": 1, "fragment_retries": 1,
    "skip_unavailable_fragments": False,
}
if (deno := Path(sys.executable).with_name("deno")).is_file():
    YDL_OPTIONS["js_runtimes"] = {"deno": {"path": str(deno)}}


def video_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.port not in (None, 443):
        return None
    if parsed.hostname in WATCH_HOSTS and parsed.path == "/watch":
        ids = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        identifier = ids[0] if len(ids) == 1 else ""
    elif parsed.hostname in WATCH_HOSTS and (match := re.fullmatch(
        r"/(?:embed|v|live)/([A-Za-z0-9_-]{11})/?", parsed.path
    )):
        identifier = match[1]
    elif parsed.hostname in SHORT_HOSTS and (match := re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", parsed.path)):
        identifier = match[1]
    else:
        return None
    return identifier if VIDEO_ID.fullmatch(identifier) else None


def require_full_video(info: dict | None, identifier: str) -> dict:
    if not info or info.get("id") != identifier or info.get("_type", "video") != "video":
        raise HTTPException(422, "Could not verify this YouTube video")
    if info.get("media_type") != "video" or info.get("live_status") not in {"not_live", "was_live"}:
        raise HTTPException(422, "Only completed full-format YouTube videos are supported")
    if info.get("availability") not in {"public", "unlisted"}:
        raise HTTPException(403, "Only public or unlisted YouTube videos are supported")
    return info


def estimated_size(fmt: dict, duration: float) -> float | None:
    return fmt.get("filesize") or fmt.get("filesize_approx") or (
        fmt["tbr"] * 125 * duration if fmt.get("tbr") and duration > 0 else None
    )


def select_formats(ydl: YoutubeDL, context: dict, duration: float, *, max_edge: int = 1080):
    """Choose a Telegram-compatible MP4, favoring lower bitrate at each resolution."""
    formats = context["formats"]
    audio = next(
        (fmt for fmt in reversed(formats) if fmt.get("ext") == "m4a"
         and fmt.get("vcodec") == "none" and (fmt.get("acodec") or "").startswith("mp4a")),
        None,
    )
    choose = ydl.build_format_selector("bv+ba/b")
    compact_limit = min(MAX_BYTES * 0.95, TARGET_BYTES_PER_MINUTE * duration / 60)
    for short_edge, long_edge in RESOLUTION_LIMITS:
        if short_edge > max_edge:
            continue
        candidates = []
        for fmt in formats:
            if fmt.get("ext") != "mp4" or not (fmt.get("vcodec") or "").startswith("avc1"):
                continue
            width, height = fmt.get("width") or 0, fmt.get("height") or 0
            if not (0 < min(width, height) <= short_edge and max(width, height) <= long_edge):
                continue
            if (fmt.get("fps") or 30) > 30:
                continue
            separate_audio = fmt.get("acodec") == "none"
            if separate_audio and audio is None:
                continue
            if not separate_audio and not (fmt.get("acodec") or "").startswith("mp4a"):
                continue
            size = estimated_size(fmt, duration)
            audio_size = estimated_size(audio, duration) if separate_audio else 0
            total = size + audio_size if size is not None and audio_size is not None else None
            budget = compact_limit if short_edge == 1080 else MAX_BYTES * 0.95
            if short_edge == 1080 and (min(width, height) <= 720 or total is None):
                continue
            if total is not None and total > budget:
                continue
            candidates.append((total is None, -(width * height), total or 0, fmt, separate_audio))
        if candidates:
            _, _, _, video, separate_audio = min(candidates, key=lambda item: item[:3])
            for selected in choose({**context, "formats": [audio, video] if separate_audio else [video]}):
                yield selected, short_edge
            return

    raise HTTPException(413, "No compact H.264/AAC format is available within the Telegram limit")


def download_video(identifier: str, destination: Path) -> dict:
    canonical = f"https://www.youtube.com/watch?v={identifier}"
    deadline = time.monotonic() + DOWNLOAD_SECONDS

    try:
        # Only an anonymous check can authorize opening the operator cookie file.
        with ManagedYoutubeDL({**YDL_OPTIONS, "ignore_no_formats_error": True}) as anonymous:
            metadata = require_full_video(anonymous.extract_info(canonical, download=False, process=False), identifier)
        max_edge = RESOLUTION_LIMITS[0][0]
        while max_edge > 0:
            if time.monotonic() >= deadline:
                raise HTTPException(503, "The YouTube download timed out")
            try:
                save_video(canonical, metadata, destination, deadline, max_edge=max_edge)
                return metadata
            except OversizedVideo as exc:
                max_edge = exc.short_edge - 1
        raise HTTPException(413, "The video exceeds the Telegram upload limit")
    except DownloadError as exc:
        logger.warning("YouTube extraction failed for %s (%s)", identifier, type(exc).__name__)
        raise HTTPException(503, "Could not fetch this video from YouTube") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, "The YouTube download timed out") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error("YouTube processing failed for %s (%s)", identifier, type(exc).__name__)
        raise HTTPException(502, "Could not prepare the YouTube video") from exc


class OversizedVideo(Exception):
    def __init__(self, short_edge: int):
        self.short_edge = short_edge


def save_video(canonical: str, metadata: dict, destination: Path, deadline: float, *, max_edge: int):
    selected_edge = 0
    stream_sizes = {}

    def check_size(size):
        if size > MAX_BYTES:
            raise OversizedVideo(selected_edge)

    def check_download(progress):
        if time.monotonic() >= deadline:
            raise HTTPException(503, "The YouTube download timed out")
        stream_sizes[progress.get("filename")] = progress.get("downloaded_bytes") or 0
        check_size(sum(stream_sizes.values()))

    def group_format(context):
        nonlocal selected_edge
        for fmt, selected_edge in select_formats(ydl, context, metadata.get("duration") or 0, max_edge=max_edge):
            yield fmt

    with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as folder:
        work = Path(folder)
        with runtime_cookiefile() as cookies:
            options = {
                **YDL_OPTIONS, "format": group_format,
                "outtmpl": str(work / "source.%(ext)s"), "merge_output_format": "mp4",
                "progress_hooks": [check_download],
            }
            if cookies:
                options["cookiefile"] = str(cookies)
            with ManagedYoutubeDL(options) as ydl:
                # Recheck the same item's visibility before downloading any authenticated streams.
                info = require_full_video(ydl.extract_info(canonical, download=False, process=False), metadata["id"])
                ydl.process_ie_result(info, download=True)

        source = work / "source.mp4"
        if not source.is_file():
            raise HTTPException(502, "YouTube did not return a complete video")
        check_size(source.stat().st_size)
        optimized = work / "video.mp4"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map", "0:v:0",
             "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", str(optimized)],
            check=True, capture_output=True, timeout=max(1, deadline - time.monotonic()),
        )
        final_size = optimized.stat().st_size
        check_size(final_size)
        if not final_size:
            raise HTTPException(502, "YouTube did not return a complete video")
        optimized.replace(destination)


@router.post("/scrape", response_model=ScrapeResponse)
async def process_scrape_request(request: ScrapeRequest):
    identifier = video_id(str(request.url))
    if identifier is None:
        raise HTTPException(400, "Only single YouTube watch, embed or shared video URLs are supported")

    async def scrape():
        if slots.locked():
            raise HTTPException(429, "YouTube group downloads are busy")
        async with slots:
            key = f"ytgroups-{identifier}"
            storage.prepare_post_dir(key)
            destination = storage.video_path(key)
            try:
                info = await asyncio.to_thread(download_video, identifier, destination)
                result = ScrapeResponse(
                    shortcode=key, media_type="video", thumbnail_url="",
                    video_url=f"/media/ytgroups/{key}/video.mp4",
                    caption=info.get("title") or identifier,
                    author=info.get("uploader") or info.get("channel") or "",
                    duration=int(info["duration"]) if info.get("duration") is not None else None,
                )
                storage.save_metadata(key, result.model_dump())
                return result
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    return await storage.singleflight(identifier, scrape)


@router.get("/health")
async def health_check():
    status = await gluetun.get_vpn_status()
    if gluetun.enabled and status.get("status", "").lower() != "running":
        raise HTTPException(503, "VPN not running")
    return {"status": "healthy", "service": "ytgroups", "vpn": status}


plugin = ScraperPlugin(
    name="ytgroups",
    router=router,
    scrape_fn=process_scrape_request,
    health_fn=health_check,
    get_storage=lambda: storage,
)
registry.register(plugin)

app = FastAPI(title="Pinchana YouTube Groups", lifespan=plugin.lifespan)
app.include_router(router)
