import unittest
from datetime import datetime, timedelta, timezone

from usr.plugins.a0_hindsight.helpers import hindsight_dreaming as d


class HindsightDreamingTests(unittest.TestCase):
    def test_stats_unchanged_requires_no_pending_consolidation(self):
        previous = {
            "total_documents": 10,
            "total_nodes": 20,
            "total_observations": 30,
        }

        self.assertTrue(d.stats_unchanged(previous, {
            "total_documents": 10,
            "total_nodes": 20,
            "total_observations": 30,
            "pending_consolidation": 0,
        }))
        self.assertFalse(d.stats_unchanged(previous, {
            "total_documents": 10,
            "total_nodes": 20,
            "total_observations": 30,
            "pending_consolidation": 1,
        }))

    def test_due_for_run_honors_interval(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        config = {"hindsight_dreaming_interval_hours": 24}

        self.assertFalse(d.due_for_run(config, {"last_run": recent.isoformat()}))
        self.assertTrue(d.due_for_run(config, {"last_run": old.isoformat()}))
        self.assertTrue(d.due_for_run(config, {"last_run": recent.isoformat()}, force=True))

    def test_api_base_normalizes_plain_server_url(self):
        self.assertEqual(
            d._api_base("http://hindsight.local:8888"),
            "http://hindsight.local:8888/v1/default",
        )
        self.assertEqual(
            d._api_base("http://hindsight.local:8888/v1/default"),
            "http://hindsight.local:8888/v1/default",
        )

    def test_dream_query_excludes_prior_dream_entries(self):
        query = d._dream_query()
        self.assertIn("source:dreaming", query)
        self.assertIn("type:dream-journal", query)
        self.assertIn("not source facts", query)


if __name__ == "__main__":
    unittest.main()
