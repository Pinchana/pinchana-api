"""Pinchana Coub scraper service."""

from .main import plugin

scrape = plugin.scrape
inspect = plugin.inspect

__all__ = ["scrape", "inspect"]
