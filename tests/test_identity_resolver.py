import sys
import unittest
from pathlib import Path


ANALYZER_DIR = Path(__file__).resolve().parents[1] / "pc-analyzer"
sys.path.insert(0, str(ANALYZER_DIR))

from identity_resolver import IdentityResolver  # noqa: E402


class IdentityResolverTest(unittest.TestCase):
    def setUp(self):
        self.resolver = IdentityResolver(
            handoff_seconds=1.25,
            max_distance_ratio=0.18,
        )

    def resolve(self, raw_id, box, current_ids, now):
        return self.resolver.resolve(
            raw_id,
            box,
            frame_width=320,
            frame_height=240,
            current_raw_ids=current_ids,
            now=now,
        )

    def test_same_raw_id_keeps_anonymous_id(self):
        first = self.resolve(7, (80, 40, 160, 220), {7}, 0.0)
        second = self.resolve(7, (90, 40, 170, 220), {7}, 0.5)
        self.assertEqual(first, second)

    def test_nearby_new_raw_id_reuses_recent_anonymous_id(self):
        first = self.resolve(7, (80, 40, 160, 220), {7}, 0.0)
        second = self.resolve(12, (86, 42, 166, 220), {12}, 0.6)
        self.assertEqual(first, second)

    def test_far_new_raw_id_gets_new_anonymous_id(self):
        first = self.resolve(7, (10, 40, 70, 220), {7}, 0.0)
        second = self.resolve(12, (240, 40, 310, 220), {12}, 0.6)
        self.assertNotEqual(first, second)

    def test_concurrent_raw_ids_do_not_merge(self):
        first = self.resolve(7, (80, 40, 160, 220), {7}, 0.0)
        second = self.resolve(12, (90, 40, 170, 220), {7, 12}, 0.2)
        self.assertNotEqual(first, second)

    def test_old_raw_id_is_not_reused_after_handoff_window(self):
        first = self.resolve(7, (80, 40, 160, 220), {7}, 0.0)
        second = self.resolve(12, (85, 40, 165, 220), {12}, 2.0)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
