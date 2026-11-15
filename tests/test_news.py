import unittest
from datetime import datetime, timedelta, timezone

from radar.news import _dedupe, _matches_company, _normalise_item
from radar.scoring import apply_news_overlay


class NewsPipelineTests(unittest.TestCase):
    def test_normalise_tracks_source_and_negative_evidence(self):
        now = datetime.now(timezone.utc)
        published = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
        item = _normalise_item(
            "SEBI penalty after accounting fraud investigation",
            "https://example.test/item/1",
            published,
            "SEBI",
            "regulator",
            "The company was penalised.",
            "SEBI",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["source_type"], "regulator")
        self.assertLess(item["sentiment"], 0)
        self.assertGreater(item["sentiment_confidence"], 0)
        self.assertIn("regulatory", item["impact_tags"])

    def test_old_news_is_filtered_out(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        item = _normalise_item("Company wins large order", "https://example.test/old", old, "Google", "company_news")
        self.assertIsNone(item)

    def test_company_matching_uses_ticker_or_distinct_name_terms(self):
        item = {"title": "Apollo Micro Systems wins defence order", "summary": ""}
        self.assertTrue(_matches_company(item, "Apollo Micro Systems Limited", "APOLLO"))
        unrelated = {"title": "Microfinance sector outlook", "summary": ""}
        self.assertFalse(_matches_company(unrelated, "Apollo Micro Systems Limited", "APOLLO"))

    def test_duplicate_links_are_removed(self):
        a = {"link": "https://example.test/item?utm_source=x", "title": "Story"}
        b = {"link": "https://example.test/item", "title": "Story duplicate"}
        self.assertEqual(len(_dedupe([a, b])), 1)

    def test_official_negative_headline_is_flagged(self):
        headline = {
            "sentiment": -1.0,
            "sentiment_confidence": 1.0,
            "source_weight": 1.0,
            "age_hours": 1,
            "source_type": "exchange",
            "source": "NSE",
        }
        _, _, adjustment, flags = apply_news_overlay(75, [headline])
        self.assertLess(adjustment, 0)
        self.assertTrue(flags)
        self.assertIn("NSE", flags[0])


if __name__ == "__main__":
    unittest.main()
