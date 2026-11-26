"""Best-effort Spotify artwork fallback for an already resolved Apple track."""

import logging
import os
import re
import unicodedata

import httpx

logger = logging.getLogger(__name__)


def normalized(value: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold())


async def spotify_artwork(metadata: dict, *, transport=None) -> dict:
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if metadata.get("cover_url") or not client_id or not secret:
        return metadata
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                auth=(client_id, secret), data={"grant_type": "client_credentials"},
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            response = await client.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": f"track:{metadata['title']} artist:{metadata['artist']}",
                        "type": "track", "limit": 5},
            )
            response.raise_for_status()
            for track in response.json()["tracks"]["items"]:
                if normalized(track["name"]) != normalized(metadata["title"]):
                    continue
                if not any(normalized(artist["name"]) == normalized(metadata["artist"])
                           for artist in track["artists"]):
                    continue
                duration = metadata.get("duration")
                if duration and abs(track.get("duration_ms", duration * 1000) / 1000 - duration) > 5:
                    continue
                album = track["album"]
                cover = next((image["url"] for image in album.get("images", [])
                              if image.get("url", "").startswith("https://")), None)
                if cover:
                    return {**metadata, "cover_url": cover, "album": album.get("name")}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.warning("Spotify artwork lookup unavailable; continuing without artwork")
    return metadata
