import sys
import unittest
from pathlib import Path


ANALYZER_DIR = Path(__file__).resolve().parents[1] / "pc-analyzer"
sys.path.insert(0, str(ANALYZER_DIR))

from line_counter import LineCounter  # noqa: E402


class LineCounterTest(unittest.TestCase):
    def setUp(self):
        self.counter = LineCounter(
            line_ratio=0.5,
            deadband_ratio=0.05,
            cooldown_seconds=0.75,
            stability_frames=3,
        )

    def stabilize(self, anonymous_id, x, start):
        result = None
        for offset in (0.0, 0.1, 0.2):
            result = self.counter.update(
                anonymous_id, x, 320, now=start + offset
            )
        return result

    def test_counts_one_left_to_right_crossing(self):
        self.assertIsNone(self.stabilize("person_001", 100, 0.0))
        self.assertIsNone(self.counter.update("person_001", 158, 320, now=0.5))
        self.assertEqual(
            self.stabilize("person_001", 220, 0.8),
            "left_to_right",
        )
        self.assertEqual(self.counter.snapshot()["passages"], 1)

    def test_counts_return_crossing_after_cooldown(self):
        self.stabilize("person_001", 80, 0.0)
        self.stabilize("person_001", 240, 0.8)
        self.assertEqual(
            self.stabilize("person_001", 80, 1.8),
            "right_to_left",
        )
        snapshot = self.counter.snapshot()
        self.assertEqual(snapshot["passages"], 2)
        self.assertEqual(snapshot["left_to_right"], 1)
        self.assertEqual(snapshot["right_to_left"], 1)

    def test_suppresses_immediate_boundary_bounce(self):
        self.stabilize("person_001", 80, 0.0)
        self.stabilize("person_001", 240, 0.8)
        self.assertIsNone(self.stabilize("person_001", 80, 1.1))
        self.assertEqual(self.counter.snapshot()["passages"], 1)

    def test_new_track_on_other_side_is_not_a_crossing(self):
        self.stabilize("person_001", 80, 0.0)
        self.stabilize("person_002", 240, 1.0)
        self.assertEqual(self.counter.snapshot()["passages"], 0)

    def test_reset_clears_counts_and_track_history(self):
        self.stabilize("person_001", 80, 0.0)
        self.stabilize("person_001", 240, 0.8)
        self.counter.reset()
        self.stabilize("person_001", 80, 2.0)
        self.assertEqual(self.counter.snapshot()["passages"], 0)


if __name__ == "__main__":
    unittest.main()
