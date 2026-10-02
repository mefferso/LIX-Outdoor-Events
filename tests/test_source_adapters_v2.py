import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import refresh_events_v2 as v2


class SourceAdaptersV2Tests(unittest.TestCase):
    def test_generic_detail_parser_without_jsonld(self):
        html = """
        <html><body>
          <h1>St. Tammany Parish Fair</h1>
          <p>September 30, 2026 - October 4, 2026</p>
          <p>Location: St. Tammany Parish Fairgrounds</p>
          <p>1301 N Columbia St, Covington, LA 70433</p>
          <p>Outdoor fair with carnival rides, rodeo, livestock and live entertainment.</p>
        </body></html>
        """
        event = v2.parse_generic_event_detail(html, "https://example.com/event/fair/")
        self.assertIsNotNone(event)
        self.assertEqual(event["name"], "St. Tammany Parish Fair")
        self.assertEqual(event["startDate"], "2026-09-30")
        self.assertEqual(event["endDate"], "2026-10-04")
        self.assertEqual(event["location"]["address"]["addressRegion"], "LA")

    def test_tangipahoa_static_page_parser(self):
        html = """
        <html><body>
          <h2>SEPTEMBER 30 - OCTOBER 4, 2026</h2>
          <h3>Tangipahoa Parish Fair</h3>
          <p>400 Reid Ave, Amite, LA 70422</p>
          <p>Annual outdoor parish fair with carnival rides and livestock.</p>
        </body></html>
        """
        rows = v2.parse_tangipahoa_fairs(html, {"url": "https://example.com/fairs"})
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "Tangipahoa Parish Fair")
        self.assertEqual(rows[0]["startDate"], "2026-09-30")
        self.assertEqual(rows[0]["endDate"], "2026-10-04")

    def test_mardi_gras_schedule_parser(self):
        html = """
        <html><body>
          <div>Saturday Jan 30 2027</div>
          <div>Covington</div>
          <div>Krewe of Olympia 6:00pm view map</div>
          <div>Slidell</div>
          <div>Krewe of Bilge 12:00pm view map</div>
        </body></html>
        """
        rows = v2.parse_mardi_gras(html, {"url": "https://example.com/parades"})
        names = {r["name"] for r in rows}
        self.assertIn("Krewe of Olympia", names)
        self.assertIn("Krewe of Bilge", names)
        self.assertEqual(len(rows), 2)

    def test_sitemap_url_extraction(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/event/a/</loc></url>
          <url><loc>https://example.com/event/b/</loc></url>
        </urlset>"""
        pages, maps = v2._sitemap_urls(xml)
        self.assertEqual(len(pages), 2)
        self.assertEqual(maps, [])


if __name__ == "__main__":
    unittest.main()
