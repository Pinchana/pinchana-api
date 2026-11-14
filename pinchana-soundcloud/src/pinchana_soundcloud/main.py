"""SoundCloud music downloader plugin."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from yt_dlp import YoutubeDL

from pinchana_core.models import ScrapeRequest, ScrapeResponse, TrackItem
from pinchana_core.music import MusicDownloader, MusicDownloadError, RateLimitError
from pinchana_core.plugins import ScraperPlugin, registry
from pinchana_core.storage import MediaStorage
from pinchana_core.vpn import GluetunController, VpnRotationError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
gluetun = GluetunController()
storage = MediaStorage(
    base_path=os.getenv("CACHE_PATH", "./cache"),
    max_size_gb=float(os.getenv("CACHE_MAX_SIZE_GB", "10.0")),
)
proxy = os.getenv("PROXY")


class SoundCloudDownloader(MusicDownloader):
    """SoundCloud: direct yt-dlp extraction."""

    async def resolve(self, url: str) -> tuple[str, dict]:
        # Resolve on.soundcloud.com short links
        if "on.soundcloud.com" in url:
            url = await self._resolve_redirect(url)
            if not url:
                raise RateLimitError("Could not resolve SoundCloud short link (likely network/timeout)")

        loop = asyncio.get_running_loop()
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "proxy": proxy,
        }
        try:
            info = await loop.run_in_executor(
                None,
                lambda: self._extract_info(url, opts),
            )
        except Exception as e:
            if any(s in str(e).lower() for s in ("403", "429", "rate limit", "too many requests", "timeout", "timed out", "connection", "blocked")):
                raise RateLimitError(f"SoundCloud extract blocked: {e}")
            raise MusicDownloadError(f"SoundCloud extract failed: {e}")
        if not info:
            raise MusicDownloadError("Could not extract SoundCloud track info")

        track_id = info.get("id") or self._slugify(info.get("title", "track"))
        meta = {
            "id": track_id,
            "title": info.get("title", "Unknown"),
            "artist": info.get("uploader") or info.get("artist") or "Unknown Artist",
            "album": info.get("album") or info.get("title"),
            "duration": info.get("duration"),
            "cover_url": info.get("thumbnail"),
        }
        return url, meta

    @staticmethod
    async def _resolve_redirect(url: str) -> str | None:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return str(resp.url)
        except Exception as e:
            logger.warning("Failed to resolve SoundCloud short link: %s", e)
            return None

    @staticmethod
    def _extract_info(url: str, opts: dict):
        with YoutubeDL(opts) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=False))


sc_downloader = SoundCloudDownloader(lambda: storage.base_path, proxy=proxy, gluetun=gluetun)


@router.post("/scrape", response_model=ScrapeResponse)
async def process_scrape_request(request: ScrapeRequest):
    # singleflight includes the request cache scope, isolating different users.
    return await storage.singleflight(
        str(request.url), lambda: _process_scrape_request(request)
    )


async def _process_scrape_request(request: ScrapeRequest):
    url = str(request.url)
    if not re.match(r"(?:https?://)?(?:www\.|on\.)?soundcloud\.com/[^\s]+", url):
        raise HTTPException(status_code=400, detail="Invalid SoundCloud URL")

    try:
        mp3_path, meta = await sc_downloader.download(url)
    except MusicDownloadError as e:
        raise HTTPException(status_code=503, detail=str(e))

    shortcode = meta.get("id", "sc")
    post_dir = storage._post_dir(shortcode)

    # MusicDownloader already created post_dir, cover.jpg, and {id}.mp3
    dest_mp3 = post_dir / "audio.mp3"
    dest_cover = post_dir / "cover.jpg"
    if mp3_path != dest_mp3:
        mp3_path.rename(dest_mp3)

    response = ScrapeResponse(
        shortcode=shortcode,
        caption=meta.get("title", ""),
        author=meta.get("artist", ""),
        media_type="audio",
        thumbnail_url=f"/media/soundcloud/{shortcode}/cover.jpg" if dest_cover.exists() else "",
        audio_url=f"/media/soundcloud/{shortcode}/audio.mp3",
        cover_url=f"/media/soundcloud/{shortcode}/cover.jpg" if dest_cover.exists() else None,
        duration=int(meta.get("duration", 0)) if meta.get("duration") else None,
        title=meta.get("title"),
        album=meta.get("album"),
    )
    storage.save_metadata(shortcode, response.model_dump())
    return response


@router.get("/health")
async def health_check():
    try:
        status = await gluetun.get_vpn_status()
        vpn_status = status.get("status", "").lower()
        if gluetun.enabled and vpn_status != "running":
            raise HTTPException(status_code=503, detail=f"VPN not running: {vpn_status}")
        return {"status": "healthy", "service": "soundcloud", "vpn": status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"VPN check failed: {e}")


registry.register(
    ScraperPlugin(
        name="soundcloud",
        router=router,
        route_patterns=["soundcloud.com", "on.soundcloud.com"],
    )
)

app = FastAPI(title="Pinchana SoundCloud", version="0.1.0")
app.include_router(router)
