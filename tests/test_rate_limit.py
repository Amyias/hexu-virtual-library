import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

spec = importlib.util.spec_from_file_location('library_server', Path(__file__).resolve().parents[1] / 'tools/asr-server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RateLimitTest(unittest.TestCase):
    def test_window_slides_and_reports_the_wait(self):
        clock = Clock()
        limit = server.RateLimit(3, clock=clock)
        self.assertEqual([limit.allow('a') for _ in range(3)], [0, 0, 0])
        clock.now += 10
        self.assertEqual(limit.allow('a'), 50)  # the first call leaves the window at +60 s
        clock.now += 50
        # All three were made at the same instant, so at +60 s they leave the window together.
        self.assertEqual([limit.allow('a') for _ in range(3)], [0, 0, 0])
        self.assertEqual(limit.allow('a'), 60)

    def test_addresses_have_separate_budgets_and_idle_ones_are_dropped(self):
        clock = Clock()
        limit = server.RateLimit(1, clock=clock)
        self.assertEqual(limit.allow('a'), 0)
        self.assertGreater(limit.allow('a'), 0)
        self.assertEqual(limit.allow('b'), 0)
        clock.now += 61
        self.assertEqual(limit.allow('c'), 0)
        self.assertEqual(set(limit._calls), {'c'})

    def test_zero_disables_the_limit(self):
        limit = server.RateLimit(0)
        self.assertEqual([limit.allow('a') for _ in range(100)], [0] * 100)


if __name__ == '__main__':
    unittest.main()
