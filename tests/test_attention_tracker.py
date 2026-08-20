import sys
import unittest
from pathlib import Path


ANALYZER_DIR = Path(__file__).resolve().parents[1] / "pc-analyzer"
sys.path.insert(0, str(ANALYZER_DIR))

from attention_tracker import AttentionTracker  # noqa: E402


class AttentionTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tracker = AttentionTracker(
            threshold_seconds=2.0,
            zone=(0.25, 0.25, 0.75, 0.75),
            missing_grace_seconds=0.5,
        )

    def update(self, anonymous_id, x, y, now):
        return self.tracker.update(anonymous_id, x, y, 320, 240, now=now)

    def test_counts_after_two_seconds_inside(self):
        self.assertFalse(self.update("person_001", 160, 120, 0.0)["stopped"])
        self.assertFalse(self.update("person_001", 160, 120, 1.9)["stopped"])
        result = self.update("person_001", 160, 120, 2.0)
        self.assertTrue(result["new_stop"])
        self.assertEqual(self.tracker.snapshot()["stops"], 1)

    def test_exit_before_threshold_resets_timer(self):
        self.update("person_001", 160, 120, 0.0)
        self.update("person_001", 20, 120, 1.5)
        result = self.update("person_001", 160, 120, 2.0)
        self.assertAlmostEqual(result["seconds"], 0.0)
        self.assertEqual(self.tracker.snapshot()["stops"], 0)

    def test_short_detection_gap_is_tolerated(self):
        self.update("person_001", 160, 120, 0.0)
        self.update("person_001", 160, 120, 1.0)
        self.tracker.finish_frame([], now=1.3)
        result = self.update("person_001", 160, 120, 2.0)
        self.assertTrue(result["stopped"])

    def test_long_detection_gap_resets_timer(self):
        self.update("person_001", 160, 120, 0.0)
        self.update("person_001", 160, 120, 1.0)
        self.tracker.finish_frame([], now=1.6)
        result = self.update("person_001", 160, 120, 2.0)
        self.assertAlmostEqual(result["seconds"], 0.0)
        self.assertFalse(result["stopped"])

    def test_same_id_is_counted_only_once(self):
        self.update("person_001", 160, 120, 0.0)
        self.update("person_001", 160, 120, 2.0)
        self.update("person_001", 20, 120, 2.2)
        self.update("person_001", 160, 120, 3.0)
        result = self.update("person_001", 160, 120, 5.0)
        self.assertFalse(result["new_stop"])
        self.assertEqual(self.tracker.snapshot()["stops"], 1)


if __name__ == "__main__":
    unittest.main()
