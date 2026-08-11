#!/usr/bin/env python3
"""
generate_portrait.py

Photo -> ASCII portrait -> self-typing animated SVG, using only the repo's
own assets (no third-party image services at render time).

Pipeline:
  1. rembg cutout        -> forces background to white (blank end of ramp)
  2. bilateral filter     -> smooths skin, keeps edges
  3. CLAHE (clip ~3.0)    -> local contrast so a flatly-lit face isn't one tone
  4. darkening curve      -> (v/255)^1.7, keeps glasses/brows/lips from washing out
  5. map to ramp          -> 13-level brightness ramp, leading space = background
  6. SVG                  -> each row wipes in via clipPath + SMIL animate,
                             staggered top->bottom, fill="freeze" (types once)

Usage:
    python3 generate_portrait.py <input_photo> <output_svg> [--cols 90]
"""
import sys
import argparse
import base64
import io
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

RAMP = " .`:-=+*cs#%@"          # 13 levels, index 0 = blank/background
CHAR_W = 7.74                    # px advance at font-size 12.9 (0.600em, JetBrains Mono)
FONT_SIZE = 12.9
LINE_HEIGHT = CHAR_W / 0.48       # derived so rows = cols * (h/w) * 0.48 holds visually
DISPLAY_WIDTH = 460               # px, final <img> width in the README


def remove_background(img: Image.Image) -> Image.Image:
    from rembg import remove
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = remove(buf.getvalue())
    cut = Image.open(io.BytesIO(out)).convert("RGBA")
    # composite onto solid white -- background must be the blank end of the ramp
    bg = Image.new("RGBA", cut.size, (255, 255, 255, 255))
    bg.paste(cut, (0, 0), cut)
    return bg.convert("RGB")


def enhance(img: Image.Image) -> np.ndarray:
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    arr = cv2.bilateralFilter(arr, d=9, sigmaColor=75, sigmaSpace=75)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    arr = clahe.apply(arr)
    v = arr.astype(np.float64) / 255.0
    v = np.power(v, 1.7)          # darkening curve -- the fix
    return (v * 255.0).astype(np.uint8)


def to_ascii_grid(gray: np.ndarray, cols: int) -> list[str]:
    h, w = gray.shape
    rows = max(1, round(cols * (h / w) * 0.48))
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)
    ramp_len = len(RAMP)
    lines = []
    for r in range(rows):
        line = []
        for c in range(cols):
            v = small[r, c]
            # brighter pixel (closer to white background) -> further toward blank end
            idx = int((255 - v) / 255 * (ramp_len - 1))
            idx = max(0, min(ramp_len - 1, idx))
            line.append(RAMP[idx])
        lines.append("".join(line))
    return lines


def embed_font(ttf_path: Path, subset_chars: str) -> str:
    """Subset the font to just the characters used and return a base64 woff2 data URI."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".woff2", delete=False) as tmp:
        out_path = tmp.name
    subprocess.run(
        [
            "pyftsubset", str(ttf_path),
            f"--text={subset_chars}",
            "--flavor=woff2",
            "--layout-features=",
            "--no-hinting",
            f"--output-file={out_path}",
        ],
        check=True,
        capture_output=True,
    )
    data = Path(out_path).read_bytes()
    Path(out_path).unlink(missing_ok=True)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:font/woff2;base64,{b64}"


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_svg(lines: list[str], font_uri: str, fill: str = "#c9d1d9") -> str:
    cols = max(len(l) for l in lines)
    rows = len(lines)
    width = cols * CHAR_W
    height = rows * LINE_HEIGHT
    scale = DISPLAY_WIDTH / width

    row_elems = []
    for i, line in enumerate(lines):
        y = (i + 0.8) * LINE_HEIGHT
        begin = round(i * 0.09, 2)
        clip_id = f"clip{i}"
        row_elems.append(f'''
  <clipPath id="{clip_id}">
    <rect x="0" y="{i * LINE_HEIGHT:.2f}" width="0" height="{LINE_HEIGHT:.2f}">
      <animate attributeName="width" from="0" to="{width:.2f}"
               dur="0.5s" begin="{begin}s" fill="freeze" />
    </rect>
  </clipPath>
  <text x="0" y="{y:.2f}" font-family="PortraitRamp" font-size="{FONT_SIZE}"
        fill="{fill}" xml:space="preserve"
        clip-path="url(#{clip_id})">{esc(line)}</text>''')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.2f} {height:.2f}"
     width="{width * scale:.0f}" height="{height * scale:.0f}" role="img"
     aria-label="ASCII self-portrait, typed in on load">
  <style>
    @font-face {{
      font-family: 'PortraitRamp';
      src: url('{font_uri}') format('woff2');
    }}
  </style>
  <rect width="100%" height="100%" fill="#0d1117"/>
  {"".join(row_elems)}
</svg>'''
    return svg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--cols", type=int, default=90)
    ap.add_argument("--font", default=str(Path(__file__).parent.parent / "fonts" / "JetBrainsMono-Regular.ttf"))
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGB")
    cut = remove_background(img)
    gray = enhance(cut)
    lines = to_ascii_grid(gray, args.cols)

    used_chars = "".join(sorted(set("".join(lines))))
    font_uri = embed_font(Path(args.font), used_chars)

    svg = build_svg(lines, font_uri)
    Path(args.output).write_text(svg)

    # also dump the plain-text grid so quality can be checked without a browser
    Path(args.output).with_suffix(".txt").write_text("\n".join(lines))
    print(f"wrote {args.output}  ({args.cols} cols x {len(lines)} rows)")


if __name__ == "__main__":
    main()
