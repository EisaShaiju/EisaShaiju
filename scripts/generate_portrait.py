#!/usr/bin/env python3
"""
generate_portrait.py

Photo -> ASCII boundary portrait -> self-typing animated SVG, using only the repo's
own assets (no third-party image services at render time).

Pipeline:
  1. rembg cutout         -> isolates subject on a pure white background
  2. resize to grid       -> downscales to ASCII resolution first
  3. Canny edge detection -> finds boundaries (hair, features, shirt)
  4. Gaussian blur        -> softens the edges to create an anti-aliasing gradient
  5. map to ramp          -> spaces for empty areas, text characters for lines
  6. SVG                  -> staggered clipPath animation for the typing effect

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

# Boundary Ramp: Starts with spaces so non-edges remain completely transparent/blank.
# Characters progress from thin/light to dense to anti-alias the edge lines.
RAMP = "   .:-=+*#@"
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
    
    # Composite onto solid white -- makes the outer boundary easy to detect for Canny
    bg = Image.new("RGBA", cut.size, (255, 255, 255, 255))
    bg.paste(cut, (0, 0), cut)
    return bg.convert("RGB")


def to_ascii_grid(img: Image.Image, cols: int) -> list[str]:
    # Convert directly to grayscale
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    rows = max(1, round(cols * (h / w) * 0.48))
    
    # 1. Resize to target ASCII grid FIRST
    # Doing edge detection at this resolution ensures the lines scale perfectly to 1 character wide
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)
    
    # 2. Extract Boundaries
    edges = cv2.Canny(small, 40, 100)
    
    # 3. Soften the edges to create a gradient for anti-aliasing
    edges = cv2.GaussianBlur(edges, (3, 3), 0)
    
    ramp_len = len(RAMP)
    lines = []
    for r in range(rows):
        line = []
        for c in range(cols):
            v = edges[r, c]
            # v is 0 (empty background) to 255 (hard edge)
            idx = int(v / 255 * (ramp_len - 1))
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
        
        # RESTORED: This calculates the staggered delay for the line-by-line typing animation
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
    
    # Skip enhancement block and pass directly to boundary edge mapping
    lines = to_ascii_grid(cut, args.cols)

    used_chars = "".join(sorted(set("".join(lines))))
    font_uri = embed_font(Path(args.font), used_chars)

    svg = build_svg(lines, font_uri)
    Path(args.output).write_text(svg)

    # Dump the plain-text grid so quality can be checked without a browser
    Path(args.output).with_suffix(".txt").write_text("\n".join(lines))
    print(f"wrote {args.output}  ({args.cols} cols x {len(lines)} rows)")


if __name__ == "__main__":
    main()