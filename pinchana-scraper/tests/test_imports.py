import subprocess
import sys
import unittest
from importlib import import_module

import pinchana_scraper


class BundleImportTests(unittest.TestCase):
    def test_importing_one_scraper_does_not_load_the_others(self):
        subprocess.run(
            [sys.executable, "-B", "-c", """
import sys

import pinchana_scraper

assert {name for name in sys.modules if name.startswith("pinchana_")} == {"pinchana_scraper"}
assert "shorts" in dir(pinchana_scraper)
from pinchana_scraper import shorts
from pinchana_scraper.shorts import scrape

assert pinchana_scraper.shorts is shorts
assert shorts.scrape is scrape
assert {name for name in sys.modules if name.startswith("pinchana_") and "." not in name} == {
    "pinchana_core",
    "pinchana_scraper",
    "pinchana_shorts",
}
"""],
            check=True,
        )

    def test_submodules_expose_the_scrapers_public_functions(self):
        self.assertEqual(len(pinchana_scraper.__all__), 13)
        for name in pinchana_scraper.__all__:
            with self.subTest(scraper=name):
                module = import_module(f"pinchana_scraper.{name}")
                package = import_module(f"pinchana_{'inst' if name == 'instagram' else name}")
                self.assertEqual(set(module.__all__), set(package.__all__) - {"router"})
                for operation in module.__all__:
                    self.assertIs(getattr(module, operation), getattr(package, operation))
