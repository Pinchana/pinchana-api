"""Deezer music downloader plugin.

Resolves Deezer URLs via the Deezer API, searches YouTube Music
for the best matching track, and downloads audio via yt-dlp.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Callable

import deezer
from fastapi import APIRouter, FastAPI, HTTPException
from ytmusicapi import YTMusic

from pinchana_core.models import ScrapeRequest, ScrapeResponse
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


def _search_ytmusic(query: str) -> str | None:
    """Search YouTube Music and return the best videoId."""
    try:
        ytm = YTMusic()
        results = ytm.search(query, filter="songs", limit=5)
        for r in results:
            vid = r.get("videoId")
            if vid:
                return vid
    except Exception as e:
        logger.warning("YTMusic search failed: %s", e)
    return None


class DeezerDownloader(MusicDownloader):
    """Deezer → YT Music search → yt-dlp download."""

    def __init__(self, base_dir: str | os.PathLike | Callable[[], str | os.PathLike], proxy: str | None = None, gluetun=None):
        super().__init__(base_dir, proxy, gluetun=gluetun)
        self.dz = deezer.Client()

    async def resolve(self, url: str) -> tuple[str, dict]:
        loop = asyncio.get_running_loop()

        # Resolve short links
        if "deezer.page.link" in url or "link.deezer.com" in url:
            import requests
            try:
                resp = requests.head(url, allow_redirects=True, timeout=10)
            except Exception as e:
                if any(s in str(e).lower() for s in ("timeout", "timed out", "connection", "refused")):
                    raise RateLimitError(f"Deezer short link resolve blocked: {e}")
                raise MusicDownloadError(f"Deezer short link resolve failed: {e}")
            url = resp.url

        track_match = re.search(r"track/(\d+)", url)
        album_match = re.search(r"album/(\d+)", url)

        if track_match:
            track_id = int(track_match.group(1))
            try:
                track = await loop.run_in_executor(None, lambda: self.dz.get_track(track_id))
            except Exception as e:
                if any(s in str(e).lower() for s in ("403", "429", "rate limit", "too many requests", "timeout", "connection", "blocked", "quota")):
                    raise RateLimitError(f"Deezer track API blocked: {e}")
                raise MusicDownloadError(f"Deezer track API failed: {e}")
            if not track:
                raise MusicDownloadError("Deezer track not found")

            title = track.title
            artist = track.artist.name
            album = track.album.title
            duration = track.duration
            cover_url = track.album.cover_xl or track.album.cover_big or track.album.cover_medium

            query = f"{artist} {title} official audio"
            video_id = await loop.run_in_executor(None, _search_ytmusic, query)
            if not video_id:
                raise MusicDownloadError("No YouTube Music match found")

            meta = {
                "id": f"dz-{track_id}",
                "title": title,
                "artist": artist,
                "album": album,
                "duration": duration,
                "cover_url": cover_url,
            }
            return f"https://www.youtube.com/watch?v={video_id}", meta

        if album_match:
            album_id = int(album_match.group(1))
            try:
                album_obj = await loop.run_in_executor(None, lambda: self.dz.get_album(album_id))
            except Exception as e:
                if any(s in str(e).lower() for s in ("403", "429", "rate limit", "too many requests", "timeout", "connection", "blocked", "quota")):
                    raise RateLimitError(f"Deezer album API blocked: {e}")
                raise MusicDownloadError(f"Deezer album API failed: {e}")
            if not album_obj:
                raise MusicDownloadError("Deezer album not found")

            album_name = album_obj.title
            artist_name = album_obj.artist.name
            cover_url = album_obj.cover_xl or album_obj.cover_big or album_obj.cover_medium

            tracks = list(album_obj.tracks or [])
            if not tracks:
                raise MusicDownloadError("Album has no tracks")

            first = tracks[0]
            title = first.title
            duration = first.duration

            query = f"{artist_name} {title} official audio"
            video_id = await loop.run_in_executor(None, _search_ytmusic, query)
            if not video_id:
                raise MusicDownloadError("No YouTube Music match found for album track")

            meta = {
                "id": f"dz-album-{album_id}",
                "title": title,
                "artist": artist_name,
                "album": album_name,
                "duration": duration,
                "cover_url": cover_url,
            }
            return f"https://www.youtube.com/watch?v={video_id}", meta

        raise MusicDownloadError("Unsupported Deezer URL type")


dz_downloader = DeezerDownloader(lambda: storage.base_path, proxy=proxy, gluetun=gluetun)


@router.post("/scrape", response_model=ScrapeResponse)
async def process_scrape_request(request: ScrapeRequest):
    # singleflight includes the request cache scope, isolating different users.
    return await storage.singleflight(
        str(request.url), lambda: _process_scrape_request(request)
    )


async def _process_scrape_request(request: ScrapeRequest):
    url = str(request.url)
    if not re.match(r"(?:https?://)?(?:www\.)?(?:deezer\.com|deezer\.page\.link|link\.deezer\.com)/[^\s]+", url):
        raise HTTPException(status_code=400, detail="Invalid Deezer URL")

    try:
        mp3_path, meta = await dz_downloader.download(url)
    except MusicDownloadError as e:
        raise HTTPException(status_code=503, detail=str(e))

    shortcode = meta.get("id", "dz")
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
        thumbnail_url=f"/media/deezer/{shortcode}/cover.jpg" if dest_cover.exists() else "",
        audio_url=f"/media/deezer/{shortcode}/audio.mp3",
        cover_url=f"/media/deezer/{shortcode}/cover.jpg" if dest_cover.exists() else None,
        duration=int(meta.get("duration", 0)) if meta.get("duration") else None,
        title=meta.get("title"),
        album=meta.get("album"),
    )
    storage.save_metadata(shortcode, response.model_dump())
    return response


@router.post("/playlist")
async def playlist_metadata(request: ScrapeRequest):
    """Internal metadata-only listing for web playlist jobs."""
    from itertools import islice
    from urllib.parse import urlsplit

    parsed = urlsplit(str(request.url))
    match = re.fullmatch(r"/(?:[a-z]{2}/)?(playlist|album)/(\d+)/?", parsed.path)
    if parsed.hostname not in {"deezer.com", "www.deezer.com"} or not match:
        raise HTTPException(400, "Invalid Deezer playlist URL")
    kind, identifier = match.groups()

    def listing():
        collection = (dz_downloader.dz.get_playlist(int(identifier)) if kind == "playlist"
                      else dz_downloader.dz.get_album(int(identifier)))
        tracks = list(islice(collection.get_tracks(), 101))
        if len(tracks) > 100:
            raise HTTPException(400, "Playlists are limited to 100 items")
        urls = []
        for track in tracks:
            if not str(track.id).isdigit():
                raise HTTPException(400, "Playlist contains an unavailable track")
            urls.append(f"https://www.deezer.com/track/{track.id}")
        return {"title": collection.title, "urls": urls}

    try:
        return await asyncio.to_thread(listing)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Deezer playlist listing failed: %s", exc)
        raise HTTPException(503, "Could not read Deezer playlist") from exc


@router.get("/health")
async def health_check():
    try:
        status = await gluetun.get_vpn_status()
        vpn_status = status.get("status", "").lower()
        if gluetun.enabled and vpn_status != "running":
            raise HTTPException(status_code=503, detail=f"VPN not running: {vpn_status}")
        return {"status": "healthy", "service": "deezer", "vpn": status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {e}")


registry.register(
    ScraperPlugin(
        name="deezer",
        router=router,
        route_patterns=["deezer.com", "deezer.page.link", "link.deezer.com"],
    )
)

app = FastAPI(title="Pinchana Deezer", version="0.1.0")
app.include_router(router)
