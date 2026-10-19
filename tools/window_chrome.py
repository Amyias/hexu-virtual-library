"""Small, local-only bridge for the glass titlebar; never exposes general native access."""
import math
from urllib.parse import urlsplit

EDGES = {'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'}


def resize_bounds(bounds, edge, dx, dy, minimum):
    if not isinstance(edge, str) or edge not in EDGES or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                                not math.isfinite(v) or abs(v) > 10000 for v in (dx, dy)):
        raise ValueError('Invalid resize request')
    x, y, width, height = bounds
    if 'e' in edge:
        width = max(minimum[0], width + dx)
    if 's' in edge:
        height = max(minimum[1], height + dy)
    if 'w' in edge:
        new_width = max(minimum[0], width - dx)
        x, width = x + width - new_width, new_width
    if 'n' in edge:
        new_height = max(minimum[1], height - dy)
        y, height = y + height - new_height, new_height
    return tuple(round(v) for v in (x, y, width, height))


class DesktopChrome:
    def __init__(self, url):
        self._origin = urlsplit(url)
        self._window = None
        self._resize = None

    def _allowed(self):
        if self._window is None:
            return False
        current = urlsplit(self._window.get_current_url() or '')
        return (current.scheme, current.netloc, current.path) == (
            self._origin.scheme, self._origin.netloc, self._origin.path)

    def _ui(self, function):
        from System import Action
        result = []
        self._window.native.Invoke(Action(lambda: result.append(function(self._window.native))))
        return result[0]

    def desktop_state(self):
        if not self._allowed():
            return None
        return self._ui(lambda form: {
            'maximized': str(form.WindowState) == 'Maximized',
            'nativeDrag': bool(getattr(self._window, '_hexu_native_drag', False)),
        })

    def desktop_action(self, action):
        if not self._allowed() or action not in ('minimize', 'maximize', 'close'):
            return False
        self._resize = None
        if action == 'close':
            self._window.destroy()
            return True
        if action == 'minimize':
            self._window.minimize()
        elif self.desktop_state()['maximized']:
            self._window.restore()
        else:
            self._window.maximize()
        return self.desktop_state()

    def resize_start(self, edge):
        if not self._allowed() or not isinstance(edge, str) or edge not in EDGES or self.desktop_state()['maximized']:
            return False
        def snapshot(form):
            return ((form.Left, form.Top, form.Width, form.Height),
                    (form.MinimumSize.Width, form.MinimumSize.Height), float(form._scale))
        self._resize = (edge, *self._ui(snapshot))
        return True

    def resize_move(self, dx, dy):
        if not self._allowed() or self._resize is None:
            return False
        edge, bounds, minimum, scale = self._resize
        # Validate before applying the monitor DPI multiplier.
        resize_bounds((0, 0, 1000, 1000), edge, dx, dy, (880, 620))
        result = resize_bounds(bounds, edge, dx * scale, dy * scale, minimum)
        self._ui(lambda form: form.SetBounds(*result))
        return True

    def resize_end(self):
        if not self._allowed():
            return False
        self._resize = None
        return True
