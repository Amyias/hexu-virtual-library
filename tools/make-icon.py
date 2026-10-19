"""Rebuild Xiaohe's transparent SVG, 1024px PNG and pixel-snapped Windows ICO.

The front silhouette uses the same 43 x 29 pixel measurements and terracotta
colour as blender/xiaohe_pet.py. Each ICO frame is drawn at its own resolution:
resizing a large raster would blur the square eyes at taskbar sizes.
Pillow is only needed to regenerate the committed assets, never at runtime.
"""
import re
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'public' / 'favicon.ico'
ASSETS = ROOT / 'public' / 'icons'
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
# x, y, width, height. Local coordinates match the model's front silhouette.
BODY = [(7, 0, 29, 21), (0, 7, 7, 7), (36, 7, 7, 7),
        (7, 21, 3, 8), (14, 21, 4, 8), (25, 21, 4, 8), (32, 21, 4, 8)]
EYES = [(10, 3, 5, 4), (28, 3, 5, 4)]


def body_colour():
    source = (ROOT / 'blender' / 'xiaohe_pet.py').read_text(encoding='utf-8')
    match = re.search(r'''^BODY_COLOR = ['"]([0-9A-Fa-f]{6})['"]''', source, re.M)
    if not match:
        raise ValueError("Cannot find Xiaohe model's BODY_COLOR")
    return '#' + match.group(1)


def rectangles(size):
    shapes = [(box, body_colour()) for box in BODY]
    # Small frames stay flat and sharp; large previews echo the model's bevel.
    if size >= 48:
        shapes += [((7, 0, 29, .65), '#EDAA8B'),
                   ((35.3, .65, .7, 20.35), '#BE6046')]
    return shapes + [(box, '#171918') for box in EYES]


def draw(size):
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)
    scale = size * .875 / 43
    left, top = (size - 43 * scale) / 2, (size - 29 * scale) / 2
    for (x, y, width, height), fill in rectangles(size):
        x0, y0 = round(left + x * scale), round(top + y * scale)
        x1, y1 = round(left + (x + width) * scale), round(top + (y + height) * scale)
        if x1 > x0 and y1 > y0:
            pen.rectangle((x0, y0, x1 - 1, y1 - 1), fill=fill)
    return canvas


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    elements = []
    for (x, y, width, height), fill in rectangles(1024):
        elements.append(f'    <rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}"/>')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="小和">\n'
           '  <title>小和 · 和序图书馆</title>\n'
           '  <g transform="translate(4 13.116279) scale(1.30232558)" shape-rendering="crispEdges">\n'
           + '\n'.join(elements) + '\n  </g>\n</svg>\n')
    (ASSETS / 'xiaohe.svg').write_text(svg, encoding='utf-8')
    draw(1024).save(ASSETS / 'xiaohe.png')
    frames = [draw(size) for size in SIZES]
    frames[-1].save(OUTPUT, format='ICO', sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    with Image.open(OUTPUT) as icon:
        assert icon.ico.sizes() == {(s, s) for s in SIZES}
        for size, frame in zip(SIZES, frames):
            assert icon.ico.getimage((size, size)).convert('RGBA').tobytes() == frame.tobytes()
    print(f'Xiaohe icon: {SIZES}; transparent SVG and 1024px PNG; {OUTPUT.stat().st_size} bytes')


if __name__ == '__main__':
    main()
