"""Apple Music metadata → YouTube Music match → shared MP3 pipeline."""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from ytmusicapi import YTMusic

from pinchana_core.models import ScrapeRequest, ScrapeResponse
from pinchana_core.music import MusicDownloader, MusicDownloadError
from pinchana_core.plugins import ScraperPlugin, registry
from pinchana_core.storage import MediaStorage

from .artwork import spotify_artwork
from .socialcrawl import SocialCrawlResolver, track_id

router = APIRouter()
storage = MediaStorage(base_path=os.getenv("CACHE_PATH", "./cache"),
                       max_size_gb=float(os.getenv("CACHE_MAX_SIZE_GB", "10.0")))
resolver = SocialCrawlResolver()


def search_ytmusic(query: str) -> str | None:
    results = YTMusic().search(query, filter="songs", limit=5)
    return next((item["videoId"] for item in results if item.get("videoId")), None)


class AppleMusicDownloader(MusicDownloader):
    def __init__(self, metadata: dict):
        super().__init__(storage.base_path, proxy=os.getenv("PROXY"))
        self.metadata = metadata

    async def resolve(self, url: str) -> tuple[str, dict]:
        meta = self.metadata
        query = f"{meta['artist']} {meta['title']} official audio"
        video_id = await asyncio.to_thread(search_ytmusic, query)
        if not video_id:
            raise MusicDownloadError("No YouTube Music match found")
        return f"https://www.youtube.com/watch?v={video_id}", meta


@router.post("/scrape", response_model=ScrapeResponse)
async def process_scrape_request(request: ScrapeRequest):
    url = str(request.url)
    shortcode = f"am-{track_id(url)}"

    async def prepare():
        cached = storage.load_metadata(shortcode)
        if cached and storage.audio_path(shortcode).is_file():
            return ScrapeResponse(**cached)
        # Resolve once, outside MusicDownloader's VPN/download retry loop.
        metadata = await resolver.resolve(url)
        if metadata is None:
            raise HTTPException(404, "Apple Music track not found")
        metadata = await spotify_artwork(metadata)
        try:
            mp3, meta = await AppleMusicDownloader(metadata).download(url)
        except MusicDownloadError:
            raise HTTPException(503, "Could not download the matching YouTube Music track") from None
        audio = storage.audio_path(shortcode)
        if mp3 != audio:
            mp3.replace(audio)
        cover = audio.with_name("cover.jpg")
        cover_url = f"/media/apple_music/{shortcode}/cover.jpg" if cover.is_file() else None
        response = ScrapeResponse(
            shortcode=shortcode, caption=meta["title"], author=meta["artist"],
            media_type="audio", thumbnail_url=cover_url or "", cover_url=cover_url,
            album=meta.get("album"),
            audio_url=f"/media/apple_music/{shortcode}/audio.mp3",
            title=meta["title"], duration=meta.get("duration"),
        )
        storage.save_metadata(shortcode, response.model_dump())
        return response

    return await storage.singleflight(shortcode, prepare)


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "apple_music",
            "socialcrawl_configured": bool(os.getenv("SOCIALCRAWL_API_KEY", "").strip())}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await storage.close()


registry.register(ScraperPlugin(name="apple_music", router=router, route_patterns=["music.apple.com"]))
app = FastAPI(title="Pinchana Apple Music", lifespan=lifespan)
app.include_router(router)
