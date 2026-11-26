import asyncio
from importlib import import_module

import httpx
import pytest
from pinchana_bluesky import inspect
from pinchana_bluesky import main as bluesky
from pinchana_core import MediaStorage, ScrapeError
from pinchana_server.modules import PACKAGES, modules
from pinchana_shorts import main as shorts
from pinchana_shorts import scrape


@pytest.mark.parametrize("name", PACKAGES)
def test_scrapers_expose_python_api(name):
    package = import_module(PACKAGES[name])
    assert package.scrape == modules[name].plugin.scrape
    assert "scrape" in package.__all__


def test_direct_shorts_calls_keep_concurrent_caches_separate(monkeypatch, tmp_path):
    shortcode = "abcdefghijk"
    url = f"https://www.youtube.com/shorts/{shortcode}"
    monkeypatch.setattr(shorts, "storage", MediaStorage(str(tmp_path / "default")))
    for folder in ("first", "second"):
        storage = MediaStorage(str(tmp_path / folder))
        storage.prepare_post_dir(shortcode)
        storage.video_path(shortcode).write_text(folder)
        storage.save_metadata(shortcode, {
            "shortcode": shortcode,
            "caption": folder,
            "author": "Example",
            "media_type": "video",
            "thumbnail_url": "",
            "video_url": f"/media/shorts/{shortcode}/video.mp4",
            "duration": 12,
        })

    async def run():
        return await asyncio.gather(*(
            scrape(url, cache_dir=tmp_path / folder) for folder in ("first", "second")
        ))

    first, second = asyncio.run(run())
    assert first.caption == first.media_path(first.video_url).read_text() == "first"
    assert second.caption == second.media_path(second.video_url).read_text() == "second"
    assert first.media_path(f"/media/shorts/{shortcode}/%2e%2e/video.mp4") is None
    assert not (tmp_path / "default").exists()


def test_bluesky_inspect_opens_and_closes_client_without_a_server(monkeypatch, tmp_path):
    monkeypatch.setattr(bluesky, "storage", MediaStorage(str(tmp_path)))
    url = "https://bsky.app/profile/example.com/post/example"
    clients = []
    original_client = httpx.AsyncClient

    async def upstream(request):
        await asyncio.sleep(0)
        assert str(request.url.copy_with(query=None)) == bluesky.APPVIEW
        return httpx.Response(200, json={"thread": {"post": {
            "uri": "at://did:plc:example/app.bsky.feed.post/example",
            "author": {"handle": "example.com"},
            "record": {"$type": bluesky.COLLECTION, "text": "Example"},
        }}})

    def client():
        result = original_client(transport=httpx.MockTransport(upstream))
        clients.append(result)
        return result

    monkeypatch.setattr(bluesky.httpx, "AsyncClient", client)

    async def run():
        return await asyncio.gather(inspect(url), inspect(url))

    first, second = asyncio.run(run())
    assert first.caption == second.caption == "Example"
    assert len(clients) == 1 and clients[0].is_closed
    assert bluesky.client is None


def test_direct_calls_report_python_errors():
    with pytest.raises(ScrapeError) as exc:
        asyncio.run(scrape("https://example.com/invalid"))

    assert exc.value.status_code == 400
    assert "Only YouTube Shorts URLs" in str(exc.value)
