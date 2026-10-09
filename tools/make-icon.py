"""Draw the program's icon: the brand mark, filled in, at every size Windows asks for.

The header draws 「和」 inside a hairline circle (`.mark` in src/library.css). At 16 pixels that
hairline turns to mush, so the icon is the solid version of the same mark — a filled circle in
the brand's deep green with the glyph in its paper white. Colours are read from the stylesheet
rather than invented here, so the icon cannot drift away from the interface.

One file serves both jobs: `public/favicon.ico` is what the page declares for the browser tab and
the window, and what PyInstaller embeds in the executable (and therefore what a desktop shortcut
shows). Regenerating is safe to repeat.

    python tools/make-icon.py

Pillow is needed to run this and nothing else needs it — the icon is committed, so a build does
not depend on it.
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
STYLESHEET = ROOT / "src" / "styles" / "library.css"
OUTPUT = ROOT / "public" / "favicon.ico"
GLYPH = "和"
SIZES = [16, 24, 32, 48, 64, 128, 256]
#: Drawn large and scaled down, which is what keeps the strokes smooth at 16 pixels.
SUPERSAMPLE = 1024
#: Shipped with Windows; the interface already asks for this family.
FONTS = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]


def brand_colours():
    """The two colours the icon is made of, taken from the stylesheet."""
    css = STYLESHEET.read_text(encoding="utf-8")

    def value(name, fallback):
        match = re.search(rf"--{name}:\s*([0-9a-fA-F]{{6}})", css)
        return "#" + match.group(1) if match else fallback

    return value("green", "#376c53"), value("paper", "#f7f8f2")


def load_font(size):
    from PIL import ImageFont

    for name in FONTS:
        path = Path(r"C:\Windows\Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise SystemExit(
        "找不到中文字体（试过 " + "、".join(FONTS) + "）。这个图标需要一个能画「和」的字体。"
    )


def draw(size, background, foreground, font):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)
    inset = round(size * 0.02)
    pen.ellipse((inset, inset, size - inset, size - inset), fill=background)
    box = pen.textbbox((0, 0), GLYPH, font=font)
    pen.text(
        ((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
        GLYPH,
        font=font,
        fill=foreground,
    )
    return canvas


def main():
    background, foreground = brand_colours()
    font = load_font(round(SUPERSAMPLE * 0.62))
    master = draw(SUPERSAMPLE, background, foreground, font)
    frames = [
        master.resize((size, size), Image.LANCZOS)
        for size in SIZES
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes a multi-resolution .ico from the list; the largest frame becomes the
    # 256-pixel entry that Windows uses for the taskbar and large thumbnails.
    frames[-1].save(OUTPUT, format="ICO", sizes=[(size, size) for size in SIZES])
    print(
        f"已生成 {OUTPUT.relative_to(ROOT)}  {OUTPUT.stat().st_size} 字节  "
        f"{len(SIZES)} 种尺寸 {SIZES}  颜色 {background} / {foreground}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
