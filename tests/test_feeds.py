import unittest
import xml.etree.ElementTree as ET

from genealogy.feeds import FeedEntry, atom_feed, timestamp

NS = {"a": "http://www.w3.org/2005/Atom"}


class FeedTests(unittest.TestCase):
    def test_partial_dates_become_timestamps(self):
        self.assertEqual(timestamp("1851"), "1851-01-01T00:00:00Z")
        self.assertEqual(timestamp("1851-04"), "1851-04-01T00:00:00Z")
        self.assertEqual(timestamp("1851-04-06"), "1851-04-06T00:00:00Z")
        self.assertEqual(timestamp("2026-10-20T09:30:00+01:00"), "2026-10-20T09:30:00+01:00")
        for bad in ("", "about 1851", "1851-4-6", "2026-10-20 09:30"):
            with self.assertRaises(ValueError):
                timestamp(bad)

    def test_feed_is_well_formed_escaped_and_deterministic(self):
        entries = [FeedEntry(id="https://example.org/f/1", title='Ada & "Rowan" <Fable>', link="https://example.org/f.html#1",
                             updated="2026-10-01", published="2026-10-01", summary="It's <b>not</b> markup.",
                             category=("relationship", "Family & relationships")),
                   FeedEntry(id="https://example.org/f/2", title="Baptism", link="https://example.org/f.html#2", updated="2026-03")]
        arguments = dict(title="Invented & Co", feed_id="https://example.org/", alternate="https://example.org/f.html",
                         self_url="https://example.org/feed.xml", author="Invented", updated="2026-10-01",
                         subtitle="Newest first", entries=entries)
        text = atom_feed(**arguments)
        self.assertEqual(text, atom_feed(**arguments))
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="utf-8"?>\n'))
        feed = ET.fromstring(text.encode("utf-8"))
        self.assertEqual(feed.find("a:title", NS).text, "Invented & Co")
        self.assertEqual(feed.find("a:link[@rel='self']", NS).get("href"), "https://example.org/feed.xml")
        first, second = feed.findall("a:entry", NS)
        self.assertEqual(first.find("a:title", NS).text, 'Ada & "Rowan" <Fable>')
        self.assertEqual(first.find("a:summary", NS).text, "It's <b>not</b> markup.")
        self.assertEqual(first.find("a:category", NS).get("label"), "Family & relationships")
        self.assertEqual(second.find("a:updated", NS).text, "2026-03-01T00:00:00Z")
        self.assertIsNone(second.find("a:summary", NS))
        self.assertIsNone(second.find("a:published", NS))


if __name__ == "__main__":
    unittest.main()
