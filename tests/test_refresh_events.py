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

    def test_parking_does_not_count_as_park(self):
        event = {
            "name":"Craftin Cajuns Craft Show & Marketplace",
            "description":"This indoor shopping event has free admission and free parking.",
            "venue":"Civic Center"
        }
        mod.classify_event(event)
        self.assertEqual(event["outdoor_status"], "unknown")
        self.assertFalse(mod.is_idss_relevant(event))

    def test_houma_html_fallback(self):
        text = """<html><body>
        <h1>Hero Fest</h1>
        <div>SEPTEMBER 18–20, 2026</div>
        <p>Outdoor and indoor venues with live music, rides, food, and a 5K run.</p>
        <h3>calendar_month DATE</h3>
        <div>September 18–20, 2026</div>
        <h3>location_on LOCATION</h3>
        <div>Barry P. Bonvillain Civic Center</div>
        <div>346 Civic Center Blvd</div>
        <div>Houma, LA</div>
        <div>70360</div>
        <h3>attach_money PRICE</h3>
        </body></html>"""
        event = mod.parse_houma_event(text, "https://explorehouma.com/events/hero-fest/")
        self.assertIsNotNone(event)
        self.assertEqual(event["name"], "Hero Fest")
        self.assertEqual(event["startDate"][:10], "2026-09-18")
        self.assertEqual(event["endDate"][:10], "2026-09-20")
        self.assertEqual(event["location"]["name"], "Barry P. Bonvillain Civic Center")

    def test_sidearm_text_home_football_parser(self):
        text = """<table>
        <tr><th>Date</th><th>Time</th><th>At</th><th>Opponent</th><th>Location</th></tr>
        <tr><td>Sep 26 (Sat)</td><td>6 p.m.</td><td>Home</td><td>Southern Miss (Hall of Fame)</td><td>NEW ORLEANS (Yulman Stadium)</td></tr>
        <tr><td>Oct 10 (Sat)</td><td>11:00 AM</td><td>Away</td><td>Army</td><td>West Point, NY</td></tr>
        </table>"""
        source = {
            "name":"Tulane Athletics",
            "url":"https://tulanegreenwave.com/sports/football/schedule/text",
            "season":2026, "team_name":"Tulane", "home_venue":"Yulman Stadium",
            "home_city":"New Orleans", "home_state":"LA"
        }
        events = mod.parse_sidearm_text_football(text, source)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Tulane Football vs. Southern Miss")
        self.assertTrue(events[0]["startDate"].startswith("2026-09-26T18:00"))

    def test_sidearm_home_football_parser(self):
        text = """<ul>
        <li class="sidearm-schedule-game sidearm-schedule-home-game">
          <span>Sep 26 (Sat)</span><span>6 p.m.</span>
          <span>vs</span><span>Southern Miss</span>
          <span>NEW ORLEANS (Yulman Stadium)</span>
        </li>
        <li class="sidearm-schedule-game sidearm-schedule-away-game">
          <span>Oct 10 (Sat)</span><span>11:00 AM</span>
          <span>at</span><span>Army</span><span>West Point, NY</span>
        </li>
        </ul>"""
        source = {
            "name":"Tulane Athletics",
            "url":"https://tulanegreenwave.com/sports/football/schedule",
            "season":2026, "team_name":"Tulane", "home_venue":"Yulman Stadium",
            "home_city":"New Orleans", "home_state":"LA"
        }
        events = mod.parse_sidearm_football(text, source)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Tulane Football vs. Southern Miss")
        self.assertTrue(events[0]["startDate"].startswith("2026-09-26T18:00"))

    def test_official_football_forces_sports_category(self):
        event = {
            "name": "Nicholls State University Vs Lamar",
            "description": "",
            "venue": "John L. Guidry Stadium",
            "_source_key": "nicholls_football",
            "_venue_outdoor_status": "outdoor",
            "_venue_importance": "major",
        }
        mod.classify_event(event)
        self.assertEqual(event["category"], "sports")
        self.assertTrue(mod.is_idss_relevant(event))

    def test_operational_context_from_city(self):
        event = {"city": "Thibodaux", "state": "LA", "latitude": 29.7958, "longitude": -90.802}
        mod.derive_operational_context(event)
        self.assertEqual(event["parish_county"], "Lafourche Parish")
        self.assertEqual(event["idss_area"], "Bayou Parishes")

    def test_evvnt_event_to_schema(self):
        source = {
            "name": "Sun Herald Events",
            "calendar_url": "https://www.sunherald.com/events/#/",
            "publisher_id": 12345,
        }
        raw = {
            "objectID": "abc123",
            "title": "Gulf Coast Outdoor Festival",
            "start_time": "2026-09-26T17:00:00-05:00",
            "end_time": "2026-09-26T21:00:00-05:00",
            "summary": "Outdoor festival with live music.",
            "venue": {
                "name": "Jones Park",
                "address_1": "2250 Jones Park Dr",
                "town": "Gulfport",
                "region": "MS",
                "postcode": "39501",
                "latitude": 30.367,
                "longitude": -89.094,
            },
            "source_broadcast_url": "https://example.com/event/abc123",
        }
        event = mod.evvnt_event_to_schema(raw, source)
        self.assertIsNotNone(event)
        self.assertEqual(event["name"], "Gulf Coast Outdoor Festival")
        self.assertEqual(event["location"]["name"], "Jones Park")
        self.assertEqual(event["location"]["address"]["addressLocality"], "Gulfport")
        self.assertEqual(event["location"]["geo"]["latitude"], 30.367)
        self.assertEqual(event["url"], "https://example.com/event/abc123")

    def test_cityspark_widget_payload_and_schema(self):
        outer = {
            "Content": (
                '<script>window.csCard("#x", '
                '{"Event":{"PId":19440135,"Name":"SL Championship Series",'
                '"Description":"Outdoor baseball championship game.",'
                '"Venue":"Keesler Federal Park","CityState":"Biloxi, MS",'
                '"DateStart":"2026-09-20T18:35:00Z","DateEnd":null,'
                '"AllDay":false,"HasTime":true,"longitude":-88.8926117,'
                '"latitude":30.3949046,"Address":"105 Caillavet St",'
                '"Zip":"39530"},"Slug":"SunHerald","allowUserSubmission":true});</script>'
            )
        }
        card = mod.parse_cityspark_widget_payload(json.dumps(outer))
        self.assertIsNotNone(card)
        event = mod.cityspark_card_to_schema(
            card,
            "2026-09-20T18",
            "https://www.sunherald.com/events/#/details/test/19440135/2026-09-20T18",
        )
        self.assertEqual(event["name"], "SL Championship Series")
        self.assertEqual(event["location"]["name"], "Keesler Federal Park")
        self.assertEqual(event["location"]["address"]["addressLocality"], "Biloxi")
        self.assertEqual(event["location"]["address"]["addressRegion"], "MS")
        self.assertAlmostEqual(event["location"]["geo"]["latitude"], 30.3949046)
        self.assertIn("18:35:00", event["startDate"])

    def test_cityspark_all_day_occurrence_uses_calendar_date(self):
        card = {
            "Event": {
                "Name": "Outdoor Festival",
                "Description": "Outdoor festival in a park.",
                "Venue": "Test Park",
                "CityState": "Biloxi, MS",
                "DateStart": "2026-09-26T00:00:00Z",
                "AllDay": True,
                "HasTime": False,
                "latitude": 30.4,
                "longitude": -88.9,
                "Address": "1 Main St",
                "Zip": "39530",
            }
        }
        event = mod.cityspark_card_to_schema(
            card,
            "2026-09-27T00",
            "https://www.sunherald.com/events/#/details/test/123/2026-09-27T00",
        )
        self.assertEqual(event["startDate"], "2026-09-27")

    def test_duplicate_requires_overlap_and_proximity(self):
        a = {"name":"BlackAmericana Fest", "dates":["2026-09-26"], "latitude":29.9693, "longitude":-90.0853}
        b = {"name":"BlackAmericana Fest Day 2", "dates":["2026-09-26"], "latitude":29.9694, "longitude":-90.0854}
        self.assertTrue(mod.is_duplicate(a, b))
        b["dates"] = ["2026-09-27"]
        self.assertFalse(mod.is_duplicate(a, b))

if __name__ == "__main__":
    unittest.main()
