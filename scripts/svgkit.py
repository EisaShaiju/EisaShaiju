#!/usr/bin/env python3
"""
svgkit.py

The bits every card in this repo needs: the palette, a subsetted webfont as a
data URI, and the <svg> wrapper. Three scripts were carrying their own copy.

Stdlib + fonttools only, deliberately. generate_stats.py runs in CI with nothing
but `pip install fonttools brotli`, so anything imported here has to survive
that environment -- no numpy, no cv2, no PIL.
"""
import base64
import subprocess
import tempfile
from pathlib import Path

BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"   # section headings -- readable at 13px
DIM = "#6e7681"     # secondary labels inside a card
ACCENT = "#58a6ff"
RULE = "#21262d"
PANEL = "#161b22"

FONT_DIR = Path(__file__).parent.parent / "fonts"
REGULAR = FONT_DIR / "JetBrainsMono-Regular.ttf"

CHAR_ADV = 0.6   # JetBrains Mono advance width, in em
CARD_W = 460     # every asset in the README renders at this width


def char_w(font_size: float) -> float:
    """Advance width of one glyph at a given font-size."""
    return font_size * CHAR_ADV


def font_data_uri(chars: str, src: Path = REGULAR) -> str:
    """Subset the font to `chars` and return it as a base64 woff2 data URI.

    Subsetting matters: the full JetBrains Mono is 270 KB, and these SVGs are
    inlined into a README that GitHub proxies on every page load.
    """
    chars = "".join(sorted(set(chars)))
    with tempfile.NamedTemporaryFile(suffix=".woff2", delete=False) as tmp:
        out_path = tmp.name
    subprocess.run(
        ["pyftsubset", str(src), f"--text={chars}", "--flavor=woff2",
         "--layout-features=", "--no-hinting", f"--output-file={out_path}"],
        check=True, capture_output=True,
    )
    data = base64.b64encode(Path(out_path).read_bytes()).decode()
    Path(out_path).unlink(missing_ok=True)
    return f"data:font/woff2;base64,{data}"


def font_face(chars: str, family: str = "CardMono", src: Path = REGULAR) -> str:
    return f"""@font-face {{
      font-family: '{family}';
      src: url('{font_data_uri(chars, src)}') format('woff2');
    }}"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_shell(width: int, height: int, body: str, title: str, chars: str,
              family: str = "CardMono", rx: int = 6) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
     width="{width}" height="{height}" role="img" aria-label="{esc(title)}">
  <style>
    {font_face(chars, family)}
    text {{ font-family: '{family}', monospace; }}
  </style>
  <rect width="100%" height="100%" rx="{rx}" fill="{BG}"/>
  {body}
</svg>'''
