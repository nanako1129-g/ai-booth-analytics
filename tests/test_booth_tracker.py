import sys
import unittest
from pathlib import Path


ANALYZER_DIR = Path(__file__).resolve().parents[1] / "pc-analyzer"
sys.path.insert(0, str(ANALYZER_DIR))

from booth_tracker import BoothTracker  # noqa: E402


class BoothTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tracker = BoothTracker(
            zone=(0.70, 0.0, 1.0, 1.0),
            missing_grace_seconds=0.5,
        )

    def update(self, anonymous_id, x, now):
        return self.tracker.update(anonymous_id, x, 120, 320, 240, now=now)

    def test_initial_detection_inside_is_not_a_visit(self):
        result = self.update("person_001", 280, 0.0)
        self.assertFalse(result["visitor"])
        self.assertEqual(self.tracker.snapshot()["visitors"], 0)

    def test_outside_to_inside_counts_one_visit(self):
        self.update("person_001", 100, 0.0)
        result = self.update("person_001", 280, 1.0)
        self.assertTrue(result["new_visit"])
        self.assertTrue(result["visitor"])
        self.assertEqual(self.tracker.snapshot()["visitors"], 1)

    def test_exit_records_completed_dwell_and_average(self):
        self.update("person_001", 100, 0.0)
        self.update("person_001", 280, 1.0)
        active = self.update("person_001", 280, 4.5)
        self.assertAlmostEqual(active["seconds"], 3.5)
        self.update("person_001", 100, 5.0)
        snapshot = self.tracker.snapshot()
        self.assertEqual(snapshot["completed_visits"], 1)
        self.assertAlmostEqual(snapshot["average_dwell_seconds"], 4.0)

    def test_same_anonymous_id_is_not_counted_twice(self):
        self.update("person_001", 100, 0.0)
        self.update("person_001", 280, 1.0)
        self.update("person_001", 100, 2.0)
        result = self.update("person_001", 280, 3.0)
        self.assertFalse(result["new_visit"])
        self.assertEqual(self.tracker.snapshot()["visitors"], 1)

    def test_short_missing_gap_keeps_visit_active(self):
        self.update("person_001", 100, 0.0)
        self.update("person_001", 280, 1.0)
        self.update("person_001", 280, 2.0)
        self.tracker.finish_frame([], now=2.3)
        result = self.update("person_001", 280, 2.4)
        self.assertAlmostEqual(result["seconds"], 1.4)
        self.assertEqual(self.tracker.snapshot()["completed_visits"], 0)

    def test_long_missing_gap_completes_at_last_seen_time(self):
        self.update("person_001", 100, 0.0)
        self.update("person_001", 280, 1.0)
        self.update("person_001", 280, 3.0)
        self.tracker.finish_frame([], now=3.6)
        snapshot = self.tracker.snapshot()
        self.assertEqual(snapshot["active_visits"], 0)
        self.assertEqual(snapshot["completed_visits"], 1)
        self.assertAlmostEqual(snapshot["average_dwell_seconds"], 2.0)

    def test_reset_clears_visits_and_durations(self):
        self.update("person_001", 100, 0.0)
        self.update("person_001", 280, 1.0)
        self.update("person_001", 100, 3.0)
        self.tracker.reset()
        snapshot = self.tracker.snapshot()
        self.assertEqual(snapshot["visitors"], 0)
        self.assertEqual(snapshot["completed_visits"], 0)
        self.assertEqual(snapshot["average_dwell_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
