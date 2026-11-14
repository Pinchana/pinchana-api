import asyncio
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from pinchana_core.storage import MediaStorage
from pinchana_ytgroups import main as ytgroups
from yt_dlp import YoutubeDL

from pinchana_server import main
from pinchana_server.media_probe import MediaDimensionProbe


VIDEO_ID = "abcdefghijk"
WATCH = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _format(identifier, width, height, size, *, fps=30):
    return {
        "format_id": identifier, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a.40.2",
        "width": width, "height": height, "filesize": size, "fps": fps,
    }


@pytest.mark.parametrize(("size", "expected"), [(10_000_000, "1080"), (60_000_000, "720")])
def test_compact_1080p_and_720p_fallback(size, expected):
    formats = [
        _format("720", 1280, 720, 12_000_000),
        _format("1080", 1920, 1080, size),
        _format("1080-60", 1920, 1080, 8_000_000, fps=60),
        _format("4k", 3840, 2160, 8_000_000),
    ]
    with YoutubeDL({"quiet": True}) as ydl:
        chosen = list(ytgroups.select_formats(ydl, {"formats": formats}, 60))
    assert [fmt["format_id"] for fmt, _ in chosen] == [expected]


def test_format_selection_rejects_every_resolution_over_the_upload_cap():
    with YoutubeDL({"quiet": True}) as ydl, pytest.raises(HTTPException) as error:
        list(ytgroups.select_formats(ydl, {
            "formats": [_format("720", 1280, 720, ytgroups.MAX_BYTES + 1)],
        }, 60))
    assert error.value.status_code == 413


@pytest.mark.parametrize("metadata", [
    {"media_type": "short"},
    {"live_status": "is_live"},
    {"availability": "private"},
    {"availability": None},
])
def test_rejected_metadata_never_opens_shared_cookies(monkeypatch, tmp_path, metadata):
    downloader = Mock()
    downloader.__enter__ = Mock(return_value=downloader)
    downloader.__exit__ = Mock(return_value=False)
    downloader.extract_info.return_value = {
        "id": VIDEO_ID, "media_type": "video", "live_status": "not_live", "availability": "public",
        **metadata,
    }
    factory = Mock(return_value=downloader)
    cookies = Mock()
    monkeypatch.setattr(ytgroups, "YoutubeDL", factory)
    monkeypatch.setattr(ytgroups, "runtime_cookiefile", cookies)
    with pytest.raises(HTTPException):
        ytgroups.download_video(VIDEO_ID, tmp_path / "video.mp4")
    assert "cookiefile" not in factory.call_args.args[0]
    cookies.assert_not_called()


def test_confirmed_full_video_opens_shared_cookie_only_on_second_extraction(monkeypatch, tmp_path):
    cookie = tmp_path / "copy.txt"
    metadata = {
        "id": VIDEO_ID, "media_type": "video", "live_status": "not_live", "availability": "public",
        "title": "Example", "duration": 60,
    }
    calls = []

    @contextmanager
    def cookies():
        assert calls == ["anonymous"]
        yield cookie

    @contextmanager
    def downloader(options):
        instance = Mock()
        if "cookiefile" in options:
            assert options["cookiefile"] == str(cookie)
            calls.append("authenticated")
            source = Path(options["outtmpl"].replace("%(ext)s", "mp4"))
            instance.process_ie_result.side_effect = lambda *_args, **_kwargs: source.write_bytes(b"source")
        else:
            calls.append("anonymous")
        instance.extract_info.return_value = metadata
        yield instance

    def remux(command, **_kwargs):
        destination = tmp_path / "video.mp4"
        assert not destination.exists()
        Path(command[-1]).write_bytes(b"mp4")

    monkeypatch.setattr(ytgroups, "runtime_cookiefile", cookies)
    monkeypatch.setattr(ytgroups, "YoutubeDL", downloader)
    monkeypatch.setattr(ytgroups.subprocess, "run", remux)
    video = tmp_path / "video.mp4"
    assert ytgroups.download_video(VIDEO_ID, video) == metadata
    assert video.read_bytes() == b"mp4"


def test_groups_are_bot_only_and_release_their_transient_media(monkeypatch, tmp_path):
    monkeypatch.setenv("PINCHANA_API_KEYS", '{"bot":"bot-key","other":"other-key"}')
    monkeypatch.setenv("PINCHANA_TELEGRAM_CLIENTS", "bot")
    storage = MediaStorage(base_path=str(tmp_path))
    monkeypatch.setattr(main, "storage", storage)
    monkeypatch.setattr(ytgroups, "storage", storage)
    probe = MediaDimensionProbe(tmp_path)
    monkeypatch.setattr(probe, "_probe_video", lambda _: None)
    monkeypatch.setattr(main, "dimension_probe", probe)

    def download(identifier, destination):
        assert identifier == VIDEO_ID
        destination.write_bytes(b"video")
        return {"title": "Example", "duration": 60}

    worker = Mock(side_effect=download)
    monkeypatch.setattr(ytgroups, "download_video", worker)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://gateway",
            headers={"X-API-Key": "bot-key"},
        ) as client:
            endpoint = "/v1/bot/ytgroups"
            denied = await client.post(endpoint, json={"url": WATCH}, headers={"X-API-Key": "other-key"})
            assert denied.status_code == 403
            assert (await client.post("/v1/scrape", json={"url": WATCH})).status_code == 400
            for url in (
                f"https://youtube.com/shorts/{VIDEO_ID}",
                WATCH.replace("www.", "music."),
                "https://www.youtube.com/playlist?list=PL0",
            ):
                assert (await client.post(endpoint, json={"url": url})).status_code == 400
            worker.assert_not_called()

            response = await client.post(endpoint, json={"url": f"https://youtu.be/{VIDEO_ID}?si=tracking"})
            assert response.status_code == 200
            scope = response.headers["X-Pinchana-Cache-Scope"]
            post = response.json()["data"]
            assert post["source"]["platform"] == "ytgroups"
            assert post["media"][0]["duration_seconds"] == 60
            url = post["media"][0]["url"]
            assert url.startswith(f"/media/ytgroups/.transient/{scope}/ytgroups-{VIDEO_ID}/")
            assert (await client.get(url)).content == b"video"
            assert (await client.delete(f"/v1/bot/cache/{scope}")).status_code == 204
            assert not (tmp_path / ".transient" / scope).exists()

    asyncio.run(run())


def test_an_oversized_download_retries_below_the_selected_resolution(monkeypatch, tmp_path):
    with YoutubeDL({"quiet": True}) as ydl:
        chosen = list(ytgroups.select_formats(ydl, {"formats": [
            _format("720", 1280, 720, 10_000_000),
            _format("480", 854, 480, 7_000_000),
        ]}, 60, max_edge=719))
    assert [fmt["format_id"] for fmt, _ in chosen] == ["480"]
    metadata = {
        "id": VIDEO_ID, "media_type": "video", "live_status": "not_live", "availability": "public",
    }
    anonymous = Mock()
    anonymous.extract_info.return_value = metadata

    @contextmanager
    def downloader(_options):
        yield anonymous

    edges = []

    def save(*_args, max_edge):
        edges.append(max_edge)
        if len(edges) == 1:
            raise ytgroups.OversizedVideo(720)

    monkeypatch.setattr(ytgroups, "YoutubeDL", downloader)
    monkeypatch.setattr(ytgroups, "save_video", save)
    assert ytgroups.download_video(VIDEO_ID, tmp_path / "video.mp4") == metadata
    assert edges == [1080, 719]
