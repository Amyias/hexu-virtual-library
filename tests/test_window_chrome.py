import pathlib
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from window_chrome import DesktopChrome, resize_bounds


class ChromeTests(unittest.TestCase):
    def test_west_north_clamp_preserves_opposite_corner(self):
        self.assertEqual(resize_bounds((100, 200, 1000, 800), 'nw', 500, 500, (880, 620)), (220, 380, 880, 620))
        self.assertEqual(resize_bounds((-1500, 200, 1000, 800), 'se', 300, 100, (880, 620)), (-1500, 200, 1300, 900))
        for edge, dx, dy in [('invalid', 0, 0), ([], 0, 0), ('n', float('nan'), 0), ('e', 10001, 0), ('s', True, 0)]:
            with self.assertRaises(ValueError): resize_bounds((0, 0, 1000, 800), edge, dx, dy, (880, 620))

    def test_only_exact_local_document_can_control_its_window(self):
        api = DesktopChrome('http://localhost:8090/')
        self.assertIsNone(api.desktop_state())
        for url in ['https://example.org/', 'http://localhost:8091/', 'http://localhost:8090/settings', 'http://localhost:8090/foreign']:
            api._window = SimpleNamespace(get_current_url=lambda: url)
            self.assertFalse(api.desktop_action('close'))
            self.assertFalse(api.resize_start('se'))
        api._window = SimpleNamespace(get_current_url=lambda: 'http://localhost:8090/')
        self.assertFalse(api.desktop_action('launch'))
        self.assertFalse(api.resize_start([]))
        self.assertFalse(api.resize_move(10, 20))


if __name__ == '__main__': unittest.main()
