# Pinchana Scraper

`pinchana-scraper` installs all 13 Pinchana scrapers under one import
namespace. Python loads each scraper when you import or access its module.
You can use the scrapers in a script without a running API gateway.

```python
import asyncio

from pinchana_scraper import shorts


async def main():
    result = await shorts.scrape(
        "https://www.youtube.com/shorts/VIDEO_ID",
        cache_dir="./downloads",
    )
    print(result.caption, result.media_path(result.video_url))


asyncio.run(main())
```

You can also import a function directly with
`from pinchana_scraper.shorts import scrape`.

The available modules are `apple_music`, `bluesky`, `coub`, `deezer`,
`instagram`, `shorts`, `soundcloud`, `spotify`, `threads`, `tiktok`,
`twitter`, `ytgroups`, and `ytmusic`. Each exports `scrape()` along with
its available metadata and playlist functions.

For local development, run `uv sync --locked` from this directory.
Set `VPN_ENABLED=false` before importing a scraper if you run outside
Gluetun. See the project guide for platform credentials, local tools, and
the Python result types. [Pinchana Python API guide](https://github.com/Pinchana/pinchana-api#python-api)
