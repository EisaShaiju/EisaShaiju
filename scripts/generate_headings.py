#!/usr/bin/env python3
"""
generate_headings.py

The only way to put your own typeface on a heading in a GitHub README:
draw it as an SVG. Lowercase mono label + a hairline rule to the right edge.
These don't get anchor links (GitHub can't outline an image), so the alt
text carries the word for screen readers.

Usage: python3 generate_headings.py
"""
from pathlib import Path

from svgkit import CARD_W, MUTED, RULE, char_w, svg_shell

OUT_DIR = Path(__file__).parent.parent
FONT_SIZE = 13

HEADINGS = ["portrait", "about", "skills", "work", "activity", "languages"]


def build(word: str, width: int = CARD_W, height: int = 28) -> str:
    text_w = len(word) * char_w(FONT_SIZE) + 8
    body = (f'<text x="0" y="19" font-size="{FONT_SIZE}" fill="{MUTED}">{word}</text>\n'
            f'  <line x1="{text_w:.1f}" y1="14" x2="{width - 4}" y2="14" '
            f'stroke="{RULE}" stroke-width="1"/>')
    return svg_shell(width, height, body, word, chars=word, rx=0)


def main():
    for word in HEADINGS:
        (OUT_DIR / f"hd-{word}.svg").write_text(build(word))
        print(f"wrote hd-{word}.svg")


if __name__ == "__main__":
    main()
