import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("refresh_events", ROOT / "scripts" / "refresh_events.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["refresh_events"] = mod
SPEC.loader.exec_module(mod)

class PipelineTests(unittest.TestCase):
    def test_extract_jsonld_event(self):
        text = """<html><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Event","name":"Test Fest","startDate":"2026-09-26T12:00:00-05:00"}
        </script></html>"""
        events = mod.extract_jsonld_events(text)
        self.assertEqual(events[0]["name"], "Test Fest")

    def test_point_in_polygon(self):
        polygon = [[[-91, 29], [-89, 29], [-89, 31], [-91, 31], [-91, 29]]]
        self.assertTrue(mod.point_in_polygon(-90, 30, polygon))
        self.assertFalse(mod.point_in_polygon(-92, 30, polygon))

    def test_outdoor_relevance(self):
        event = {"name":"Riverfront Music Festival","description":"Outdoor festival with live music","venue":"City Park"}
        mod.classify_event(event)
        self.assertEqual(event["category"], "festival")
        self.assertEqual(event["outdoor_status"], "outdoor")
        self.assertTrue(mod.is_idss_relevant(event))

    def test_indoor_low_value_excluded(self):
        event = {"name":"Painting Workshop","description":"Indoor class at the museum","venue":"Museum Gallery"}
        mod.classify_event(event)
        self.assertFalse(mod.is_idss_relevant(event))

    def test_duplicate_requires_overlap_and_proximity(self):
        a = {"name":"BlackAmericana Fest", "dates":["2026-09-26"], "latitude":29.9693, "longitude":-90.0853}
        b = {"name":"BlackAmericana Fest Day 2", "dates":["2026-09-26"], "latitude":29.9694, "longitude":-90.0854}
        self.assertTrue(mod.is_duplicate(a, b))
        b["dates"] = ["2026-09-27"]
        self.assertFalse(mod.is_duplicate(a, b))

if __name__ == "__main__":
    unittest.main()
