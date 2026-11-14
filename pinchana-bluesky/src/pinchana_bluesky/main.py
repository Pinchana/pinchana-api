"""Read public Bluesky posts through AppView and cache Telegram-ready media."""

import asyncio
import hashlib
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, FastAPI, HTTPException
from pinchana_core.models import MediaItem, ScrapeRequest
from pinchana_core.plugins import ScraperPlugin, registry
from pinchana_core.storage import MediaStorage

HOST = "bsky.app"
APPVIEW = "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread"
COLLECTION = "app.bsky.feed.post"
HANDLE = r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+"
AT_DID = r"did:(?:plc:[a-z0-9]+|web:[a-zA-Z0-9.-]+)"
RKEY = r"[a-zA-Z0-9_-]{1,128}"
POST_PATH = re.compile(rf"/profile/({HANDLE}|{AT_DID})/post/({RKEY})/?")
POST_URI = re.compile(rf"at://({AT_DID})/{re.escape(COLLECTION)}/({RKEY})")
RESTRICTED_LABELS = {"!hide", "!no-unauthenticated", "porn", "sexual", "graphic-media"}
VIDEO_TIMEOUT = 50
VIDEO_MAX_BYTES = 100 * 1024**2
logger = logging.getLogger(__name__)
_video_slots = asyncio.Semaphore(4)
_cache_eviction_lock = asyncio.Lock()
router = APIRouter()
storage = MediaStorage(
    base_path=os.getenv("CACHE_PATH", "./cache"),
    max_size_gb=float(os.getenv("CACHE_MAX_SIZE_GB", "10.0")),
)
client: httpx.AsyncClient | None = None


def _post_uri(url: str) -> str:
    parsed = urlsplit(url)
    match = POST_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https" or parsed.hostname != HOST or parsed.port not in {None, 443}
        or parsed.username is not None or parsed.password is not None or match is None
    ):
        raise HTTPException(400, "Expected a public bsky.app post URL")
    actor, key = match.groups()
    authority = actor if actor.startswith("did:") else actor.lower()
    return f"at://{authority}/{COLLECTION}/{key}"


def _restricted(post: dict, record: dict) -> bool:
    return any(
        label.get("val") in RESTRICTED_LABELS and not label.get("neg")
        for labels in (post.get("labels"), post["author"].get("labels"), (record.get("labels") or {}).get("values"))
        for label in labels or []
    )


async def _fetch_post(client: httpx.AsyncClient, uri: str) -> dict:
    try:
        response = await client.get(
            APPVIEW, params={"uri": uri, "depth": 0, "parentHeight": 0},
            follow_redirects=False, timeout=10,
        )
    except httpx.RequestError as exc:
        raise HTTPException(503, "Bluesky is temporarily unavailable") from exc

    if response.status_code == 404:
        raise HTTPException(404, "Bluesky post not found")
    if response.status_code == 429:
        raise HTTPException(429, "Bluesky is temporarily rate limited")
    if response.status_code == 403:
        raise HTTPException(403, {"code": "restricted_media", "message": "This Bluesky post is restricted"})
    if response.status_code >= 500:
        raise HTTPException(503, "Bluesky is temporarily unavailable")
    try:
        payload = response.json()
        if payload.get("error") == "NotFound":
            raise HTTPException(404, "Bluesky post not found")
        response.raise_for_status()
        thread = payload["thread"]
        if thread.get("notFound"):
            raise HTTPException(404, "Bluesky post not found")
        if thread.get("blocked") or thread.get("$type") == "app.bsky.feed.defs#blockedPost":
            raise HTTPException(403, {"code": "restricted_media", "message": "This Bluesky post is restricted"})
        post = thread["post"]
        if (
            POST_URI.fullmatch(post["uri"]) is None
            or post["record"].get("$type") != COLLECTION
            or not isinstance(post["record"]["text"], str)
        ):
            raise ValueError("Invalid Bluesky post")
        return post
    except (httpx.HTTPStatusError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(502, "Bluesky returned an invalid post response") from exc


def _cdn_url(value: str, host: str, path_prefix: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != host or not parsed.path.startswith(path_prefix):
        raise ValueError("Unexpected Bluesky media URL")
    return value


async def _remux_video(url: str, path: Path) -> None:
    temporary = path.with_name(f".{uuid.uuid4().hex}.mp4")
    try:
        async with asyncio.timeout(VIDEO_TIMEOUT), _video_slots:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "https,tls,tcp",
                "-tls_verify", "1", "-rw_timeout", "12000000", "-f", "hls", "-i", url,
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart",
                "-fs", str(VIDEO_MAX_BYTES), str(temporary),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await process.communicate()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        if process.returncode or not temporary.is_file() or not 0 < temporary.stat().st_size < VIDEO_MAX_BYTES:
            logger.warning("Bluesky video remux failed: %s", stderr.decode(errors="replace")[-500:])
            raise OSError("Bluesky video remux failed")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def _cache_asset(storage: MediaStorage, cache_id: str, url: str, stem: str, *, video: bool = False) -> str:
    fingerprint = hashlib.sha256(url.encode()).hexdigest()[:24]
    filename = f"{stem}-{fingerprint}.{'mp4' if video else 'jpg'}"
    path = storage.base_path / cache_id / filename
    if not path.is_file() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        if video:
            await _remux_video(url, path)
        elif not await storage.download(url, path) or path.stat().st_size == 0:
            raise OSError("Bluesky image download failed")
    return f"/media/bluesky/{cache_id}/{filename}"


async def _download_embed(storage: MediaStorage, cache_id: str, embed: dict, prefix: str) -> list[MediaItem]:
    kind = embed.get("$type")
    if kind == "app.bsky.embed.images#view":
        items = []
        for index, image in enumerate(embed["images"][:4]):
            source = _cdn_url(image["fullsize"], "cdn.bsky.app", "/img/")
            # AppView may return an extensionless URL that defaults to WebP.
            source = source.split("?", 1)[0].rsplit("@", 1)[0] + "@jpeg"
            photo = await _cache_asset(storage, cache_id, source, f"{prefix}image-{index}")
            items.append(MediaItem(index=index, media_type="image", thumbnail_url=photo))
        return items
    if kind == "app.bsky.embed.video#view":
        playlist = _cdn_url(embed["playlist"], "video.bsky.app", "/watch/")
        video = await _cache_asset(storage, cache_id, playlist, f"{prefix}video", video=True)
        thumbnail = ""
        if embed.get("thumbnail"):
            source = _cdn_url(embed["thumbnail"], "video.bsky.app", "/watch/")
            thumbnail = await _cache_asset(storage, cache_id, source, f"{prefix}thumbnail")
        return [MediaItem(index=0, media_type="video", thumbnail_url=thumbnail, video_url=video)]
    return []


def _post_id(uri: str) -> str:
    # Record keys are local to a repository and may be shared by different authors.
    return "bsky-" + hashlib.sha256(uri.encode()).hexdigest()[:32]


def _response(post: dict, record: dict, media: list[MediaItem]) -> dict[str, Any]:
    author = post["author"]
    first = media[0] if media else None
    return {
        "shortcode": _post_id(post["uri"]),
        "caption": record["text"],
        "author": author.get("displayName") or author.get("handle") or "",
        "username": author.get("handle"),
        "avatar_url": author.get("avatar"),
        "created_at": record.get("createdAt"),
        "media_type": first.media_type if first else "text",
        "thumbnail_url": first.thumbnail_url if first else "",
        "video_url": first.video_url if first else None,
        "carousel": [item.model_dump() for item in media] if len(media) > 1 else None,
    }


def _quoted_post(embed: dict) -> dict | None:
    if embed.get("$type") == "app.bsky.embed.recordWithMedia#view":
        embed = embed["record"]
    if embed.get("$type") != "app.bsky.embed.record#view":
        return None
    quote = embed["record"]
    if quote.get("$type") != "app.bsky.embed.record#viewRecord":
        return None
    record = quote.get("value", {})
    if (
        record.get("$type") != COLLECTION
        or not isinstance(record.get("text"), str)
        or _restricted(quote, record)
    ):
        return None
    return quote


def _visual_embed(embed: dict) -> dict:
    return embed["media"] if embed.get("$type") == "app.bsky.embed.recordWithMedia#view" else embed


async def _build_response(post: dict, storage: MediaStorage, *, download_media: bool) -> dict[str, Any]:
    record = post["record"]
    if _restricted(post, record):
        raise HTTPException(403, {"code": "restricted_media", "message": "This Bluesky post is restricted"})
    embed = post.get("embed") or {}
    cache_id = _post_id(post["uri"])
    media = []
    if download_media:
        async with _cache_eviction_lock:
            await asyncio.to_thread(storage.ensure_space)
        media = await _download_embed(storage, cache_id, _visual_embed(embed), "")
    payload = _response(post, record, media)
    if quote := _quoted_post(embed):
        if match := POST_URI.fullmatch(quote["uri"]):
            actor, key = match.groups()
            quote_media = []
            if download_media:
                for attachment in quote.get("embeds") or []:
                    quote_media = await _download_embed(storage, cache_id, _visual_embed(attachment), "quote-")
                    if quote_media:
                        break
            payload["quote"] = _response(quote, quote["value"], quote_media)
            payload["quote"]["source_url"] = f"https://{HOST}/profile/{actor}/post/{key}"
    if download_media:
        await asyncio.to_thread(storage.save_metadata, cache_id, payload)
    return payload


async def _read_post(post: dict, storage: MediaStorage, *, download_media: bool) -> dict[str, Any]:
    try:
        async with asyncio.timeout(100):
            return await _build_response(post, storage, download_media=download_media)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(503, {"code": "media_download_failed", "message": "Could not download Bluesky media"}) from exc
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Bluesky returned an invalid post response") from exc


async def scrape(url: str, client: httpx.AsyncClient, storage: MediaStorage, *, download_media: bool) -> dict[str, Any]:
    post = await _fetch_post(client, _post_uri(url))
    if download_media:
        return await storage.singleflight(
            _post_id(post["uri"]), lambda: _read_post(post, storage, download_media=True)
        )
    return await _read_post(post, storage, download_media=False)


async def _process_request(request: ScrapeRequest, *, download_media: bool) -> dict[str, Any]:
    if client is None:
        raise HTTPException(503, "Bluesky scraper is not ready")
    return await scrape(str(request.url), client, storage, download_media=download_media)


@router.post("/scrape")
async def process_scrape_request(request: ScrapeRequest):
    return await _process_request(request, download_media=True)


@router.post("/inspect")
async def process_inspect_request(request: ScrapeRequest):
    return await _process_request(request, download_media=False)


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "bluesky"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global client
    async with httpx.AsyncClient() as appview:
        client = appview
        try:
            yield
        finally:
            client = None
            await storage.close()


registry.register(ScraperPlugin(name="bluesky", router=router, route_patterns=[HOST]))
app = FastAPI(title="Pinchana Bluesky", lifespan=lifespan)
app.include_router(router)
