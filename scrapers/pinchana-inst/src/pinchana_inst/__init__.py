"""Instagram scraper plugin for Pinchana."""

from .main import plugin, router

scrape = plugin.scrape

__all__ = ["scrape", "router"]
