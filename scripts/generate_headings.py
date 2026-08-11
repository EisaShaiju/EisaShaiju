#!/usr/bin/env python3
"""
generate_headings.py

The only way to put your own typeface on a heading in a GitHub README:
draw it as an SVG. Lowercase mono label + a hairline rule to the right edge.
These don't get anchor links (GitHub can't outline an image), so the alt
text carries the word for screen readers.

Usage: python3 generate_headings.py
"""
import base64
import subprocess
import tempfile
from pathlib import Path

FONT = Path(__file__).parent.parent / "fonts" / "JetBrainsMono-Regular.ttf"
OUT_DIR = Path(__file__).parent.parent
BG = "#0d1117"
FG = "#8b949e"
RULE = "#21262d"

HEADINGS = ["portrait", "activity", "languages", "about"]


def font_data_uri(chars: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".woff2", delete=False) as tmp:
        out_path = tmp.name
    subprocess.run(
        ["pyftsubset", str(FONT), f"--text={chars}", "--flavor=woff2",
         "--layout-features=", "--no-hinting", f"--output-file={out_path}"],
        check=True, capture_output=True,
    )
    data = base64.b64encode(Path(out_path).read_bytes()).decode()
    Path(out_path).unlink(missing_ok=True)
    return f"data:font/woff2;base64,{data}"


def build(word: str, width: int = 460, height: int = 28) -> str:
    font_uri = font_data_uri(word)
    text_w = len(word) * 7.74 + 8
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
     width="{width}" height="{height}" role="img" aria-label="{word}">
  <style>
    @font-face {{
      font-family: 'HeadingMono';
      src: url('{font_uri}') format('woff2');
    }}
    text {{ font-family: 'HeadingMono', monospace; }}
  </style>
  <rect width="100%" height="100%" fill="{BG}"/>
  <text x="0" y="19" font-size="13" fill="{FG}">{word}</text>
  <line x1="{text_w:.1f}" y1="14" x2="{width - 4}" y2="14" stroke="{RULE}" stroke-width="1"/>
</svg>'''


def main():
    for word in HEADINGS:
        svg = build(word)
        (OUT_DIR / f"hd-{word}.svg").write_text(svg)
        print(f"wrote hd-{word}.svg")


if __name__ == "__main__":
    main()
