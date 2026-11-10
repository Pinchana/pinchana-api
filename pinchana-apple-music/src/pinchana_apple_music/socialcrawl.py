"""Track-only Apple Music metadata lookup with idempotent paid requests."""

import asyncio
import os
import random
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import HTTPException

ENDPOINT = "https://www.socialcrawl.dev/v1/apple_music/track"


def track_id(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname != "music.apple.com"
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise HTTPException(400, "Invalid Apple Music track URL")
    match = re.fullmatch(r"/(?:[a-zA-Z]{2}/)?(song|album)/(?:(?:[^/]+)/)?(\d+)/?", parsed.path)
    if not match:
        raise HTTPException(400, "Only Apple Music track links are supported")
    kind, identifier = match.groups()
    selected = parse_qs(parsed.query, keep_blank_values=True).get("i")
    if kind == "album":
        if not selected or len(selected) != 1 or not re.fullmatch(r"\d+", selected[0]):
            raise HTTPException(400, "Apple Music albums are unsupported; select an individual track")
        return selected[0]
    if selected:
        raise HTTPException(400, "Ambiguous Apple Music song URL")
    return identifier


class SocialCrawlResolver:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def resolve(self, url: str) -> dict | None:
        identifier = track_id(url)
        key = os.environ.get("SOCIALCRAWL_API_KEY", "").strip()
        if not key:
            raise HTTPException(503, "SOCIALCRAWL_API_KEY is not configured")
        # One logical request, including all timeout/upstream retries.
        headers = {"x-api-key": key, "Idempotency-Key": str(uuid.uuid4())}
        async with httpx.AsyncClient(timeout=60.0, transport=self.transport) as client:
            for attempt in range(4):
                retry_after = None
                try:
                    async with asyncio.timeout(60):
                        response = await client.get(ENDPOINT, params={"id": identifier}, headers=headers)
                except (httpx.TimeoutException, TimeoutError):
                    if attempt == 3:
                        raise HTTPException(504, "Apple Music metadata request timed out") from None
                except httpx.RequestError:
                    raise HTTPException(503, "Apple Music metadata request failed") from None
                else:
                    try:
                        payload = response.json()
                    except ValueError:
                        raise HTTPException(502, "Invalid Apple Music metadata response") from None
                    if not isinstance(payload, dict):
                        raise HTTPException(502, "Invalid Apple Music metadata response")
                    if payload.get("success") is True and response.is_success:
                        return self._metadata(payload, identifier)
                    error = payload.get("error")
                    error = error if isinstance(error, dict) else {}
                    kind = error.get("type")
                    if kind == "RESOURCE_NOT_FOUND":
                        return None
                    if kind == "INVALID_REQUEST" and error.get("retryable") is not True:
                        raise HTTPException(400, "Socialcrawl rejected the Apple Music track request")
                    retry_after = response.headers.get("Retry-After")
                    retryable = error.get("retryable") is True
                    if kind == "SERVICE_UNAVAILABLE" and retry_after is None:
                        retryable = False
                    if not retryable or attempt == 3:
                        raise HTTPException(503, "Apple Music metadata unavailable")
                delay = 2 ** attempt + random.uniform(0, 1)
                if retry_after is not None:
                    try:
                        delay = max(0.0, float(retry_after))
                    except ValueError:
                        raise HTTPException(502, "Invalid upstream Retry-After header") from None
                await asyncio.sleep(delay)
        raise HTTPException(503, "Apple Music metadata unavailable")

    @staticmethod
    def _metadata(payload: dict, identifier: str) -> dict | None:
        data = payload.get("data")
        post = data.get("post") if isinstance(data, dict) else None
        if not post:
            return None
        if not isinstance(post, dict):
            raise HTTPException(502, "Invalid Apple Music track metadata")
        if str(post.get("id", identifier)) != identifier:
            raise HTTPException(502, "Apple Music returned a different track")
        content, author = post.get("content"), post.get("author")
        if not isinstance(content, dict) or not isinstance(author, dict):
            raise HTTPException(502, "Invalid Apple Music track metadata")
        title = content.get("text")
        artist = author.get("display_name") or author.get("username")
        if not isinstance(title, str) or not title.strip() or not isinstance(artist, str) or not artist.strip():
            raise HTTPException(502, "Apple Music track title or artist is missing")
        # Preview media_urls are deliberately ignored: audio comes from YT Music.
        duration = content.get("duration_seconds")
        try:
            duration = max(0, int(duration)) if duration is not None else None
        except (ValueError, TypeError, OverflowError):
            duration = None
        return {"id": f"am-{identifier}", "title": title.strip(), "artist": artist.strip(),
                "duration": duration, "cover_url": None, "album": None}
