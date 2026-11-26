"""Pinchana YouTube Shorts scraper plugin."""

from .main import plugin, router

scrape = plugin.scrape
scrape_playlist_item = plugin.scrape_playlist_item

__all__ = ["scrape", "scrape_playlist_item", "router"]
