import asyncio

import httpx

from pinchana_server.main import app


def test_root_serves_the_public_landing_page():
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            page = await client.get("/")
            assert page.status_code == 200
            assert page.headers["content-type"] == "text/html; charset=utf-8"
            assert "⣀⡀" in page.text
            assert "<h1><span>Pinchana API</span></h1>" in page.text
            for path in ("https://allofthe.pinchana.cc/", "/health", "https://github.com/Pinchana"):
                assert f'href="{path}"' in page.text

            head = await client.head("/")
            assert head.status_code == 200
            assert head.content == b""
            assert head.headers["content-length"] == str(len(page.content))

    asyncio.run(check())
