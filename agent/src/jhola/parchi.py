"""Render a synthetic handwritten-style parchi image with PIL (for demos and tests)."""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc",
    "/System/Library/Fonts/Noteworthy.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

DIDI_LIST = [
    "doodh - 2 packet",
    "pyaaz 1 kg",
    "tamatar 1 kg",
    "aloo 2 kg",
    "dhaniya",
    "hari mirch",
    "adrak",
    "namak",
    "toor dal 1/2 kg",
]


def _font(size: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_parchi(lines: list[str] = DIDI_LIST, seed: int = 7) -> bytes:
    rnd = random.Random(seed)
    w, h = 720, 110 + 70 * len(lines)
    img = Image.new("RGB", (w, h), (246, 240, 222))
    d = ImageDraw.Draw(img)
    for y in range(90, h, 70):  # ruled lines
        d.line([(30, y + 50), (w - 30, y + 50)], fill=(170, 190, 215), width=2)
    d.line([(80, 0), (80, h)], fill=(220, 120, 120), width=2)
    font = _font(40)
    d.text((100, 20), "Saaman ki list", font=_font(46), fill=(40, 40, 110))
    for i, line in enumerate(lines):
        x = 100 + rnd.randint(-6, 10)
        y = 95 + 70 * i + rnd.randint(-4, 4)
        d.text((x, y), f"{i + 1}. {line}", font=font, fill=(25, 35, 95))
    img = img.rotate(rnd.uniform(-1.5, 1.5), expand=False, fillcolor=(246, 240, 222))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def transcription(lines: list[str] = DIDI_LIST) -> dict:
    return {"items": [{"text": l, "quantity": ""} for l in lines]}


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "parchi.jpg")
    out.write_bytes(render_parchi())
    print(f"wrote {out}")
