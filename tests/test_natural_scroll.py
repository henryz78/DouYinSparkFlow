import random
import unittest

from core.tasks import _build_natural_scroll_plan, natural_scroll_element


class _FakeScrollable:
    def __init__(self, scroll_top=0, max_scroll=5000):
        self.scroll_top = scroll_top
        self.max_scroll = max_scroll
        self.deltas = []

    def evaluate(self, expression, arg=None):
        if "scrollTop += delta" in expression:
            self.deltas.append(arg)
            self.scroll_top = min(self.max_scroll, self.scroll_top + arg)
        return self.scroll_top


class NaturalScrollTests(unittest.TestCase):
    def test_scroll_plan_keeps_old_search_distance_with_multiple_steps(self):
        steps, pauses = _build_natural_scroll_plan(random.Random(1234))
        self.assertGreaterEqual(len(steps), 6)
        self.assertLessEqual(len(steps), 9)
        self.assertEqual(len(pauses), len(steps) - 1)
        self.assertGreaterEqual(sum(steps), 650)
        self.assertLessEqual(sum(steps), 850)
        self.assertTrue(all(step > 0 for step in steps))
        self.assertTrue(all(0.03 <= pause <= 0.15 for pause in pauses))
        # The middle of the gesture should generally be stronger than an edge.
        middle = steps[len(steps) // 2]
        self.assertGreater(middle, min(steps[0], steps[-1]))

    def test_natural_scroll_moves_in_several_steps(self):
        element = _FakeScrollable(scroll_top=100, max_scroll=5000)
        sleeps = []
        before, after = natural_scroll_element(
            element,
            rng=random.Random(42),
            sleep_fn=sleeps.append,
        )
        self.assertEqual(before, 100)
        self.assertGreater(after, before)
        self.assertGreaterEqual(len(element.deltas), 6)
        self.assertEqual(after - before, sum(element.deltas))
        self.assertGreaterEqual(len(sleeps), len(element.deltas))

    def test_natural_scroll_stops_when_container_is_at_bottom(self):
        element = _FakeScrollable(scroll_top=900, max_scroll=900)
        sleeps = []
        before, after = natural_scroll_element(
            element,
            rng=random.Random(7),
            sleep_fn=sleeps.append,
        )
        self.assertEqual((before, after), (900, 900))
        self.assertEqual(len(element.deltas), 1)
        # Even at the boundary, keep the small settle delay for lazy-load state.
        self.assertEqual(len(sleeps), 1)


if __name__ == "__main__":
    unittest.main()
