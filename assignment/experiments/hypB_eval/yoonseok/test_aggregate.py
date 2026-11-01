"""Small regressions for pairing, pending Judge work and marker boundaries."""
import unittest
from aggregate import MARKERS, paired


class AggregateTest(unittest.TestCase):
    def test_gain_loss_direction_and_pending(self):
        left = {"a": {"final_correct": False}, "b": {"final_correct": True}}
        right = {"a": {"final_correct": True}, "b": {"final_correct": True}}
        self.assertEqual(paired(left, right, ["a", "b"])["net_gain"], 1)
        self.assertEqual(paired(right, left, ["a", "b"])["net_gain"], -1)
        right["b"]["final_correct"] = None
        self.assertIsNone(paired(left, right, ["a", "b"])["net_gain"])

    def test_marker_boundaries(self):
        text = "WAIT waiters waited perhaps re-examine re-examined re-evaluate alternatively actually however reconsider"
        self.assertEqual(len(MARKERS.findall(text)), 8)


if __name__ == "__main__":
    unittest.main()
