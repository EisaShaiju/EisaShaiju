#!/usr/bin/env python3
"""
generate_skills.py

The stack, drawn as one card instead of thirty-five shields.io badges: same
typeface, same palette, same 460px column as everything else on the page, and
no external image service in the render path.

Chips are flowed and wrapped in code rather than hand-placed, so editing SKILLS
below is the only thing needed to re-lay out the card.

Usage: python3 generate_skills.py
"""
from pathlib import Path

from svgkit import CARD_W, DIM, FG, MUTED, PANEL, RULE, char_w, esc, svg_shell

OUT_DIR = Path(__file__).parent.parent

SKILLS = {
    "languages & frameworks": [
        "Python", "C++", "C", "SQL", "PyTorch", "TensorFlow", "FastAPI",
        "LangChain", "LangGraph", "Stable Diffusion", "Streamlit", "Rasa",
    ],
    "libraries": [
        "Transformers", "FAISS", "MLflow", "DVC", "ControlNet", "Llama",
        "Whisper", "scikit-learn", "pandas", "NumPy", "OpenCV", "Optuna",
        "spaCy", "Jina",
    ],
    "platforms & tools": [
        "AWS (S3, Redshift)", "Databricks", "Apache Kafka", "Docker",
        "GitHub Actions", "TensorRT", "PostgreSQL", "Git", "TensorBoard", "WSL",
    ],
}

PAD = 16
LABEL_SIZE = 11
CHIP_SIZE = 11
CHIP_H = 20
CHIP_PAD = 8      # horizontal padding inside a chip
GUTTER = 6        # between chips, and between chip rows
LABEL_GAP = 14    # label baseline -> first chip row
GROUP_GAP = 18    # last chip row -> next label baseline


def chip_width(name: str) -> float:
    return len(name) * char_w(CHIP_SIZE) + 2 * CHIP_PAD


def layout(names: list[str], avail: float) -> list[list[tuple[str, float]]]:
    """Greedy flow into rows of (name, x-offset)."""
    rows, row, x = [], [], 0.0
    for name in names:
        w = chip_width(name)
        if row and x + w > avail:
            rows.append(row)
            row, x = [], 0.0
        row.append((name, x))
        x += w + GUTTER
    if row:
        rows.append(row)
    return rows


def build() -> str:
    avail = CARD_W - 2 * PAD
    parts = []
    y = PAD + LABEL_SIZE          # first label baseline

    for label, names in SKILLS.items():
        label_w = len(label) * char_w(LABEL_SIZE) + 8
        parts.append(
            f'<text x="{PAD}" y="{y}" font-size="{LABEL_SIZE}" fill="{MUTED}">{esc(label)}</text>\n'
            f'  <line x1="{PAD + label_w:.1f}" y1="{y - 4}" x2="{CARD_W - PAD}" y2="{y - 4}" '
            f'stroke="{RULE}" stroke-width="1"/>'
        )
        top = y + LABEL_GAP
        rows = layout(names, avail)
        for r, row in enumerate(rows):
            chip_y = top + r * (CHIP_H + GUTTER)
            for name, dx in row:
                x = PAD + dx
                parts.append(
                    f'<rect x="{x:.1f}" y="{chip_y:.1f}" width="{chip_width(name):.1f}" '
                    f'height="{CHIP_H}" rx="3" fill="{PANEL}" stroke="{RULE}" stroke-width="1"/>\n'
                    f'  <text x="{x + CHIP_PAD:.1f}" y="{chip_y + 14:.1f}" '
                    f'font-size="{CHIP_SIZE}" fill="{FG}">{esc(name)}</text>'
                )
        y = top + len(rows) * (CHIP_H + GUTTER) - GUTTER + GROUP_GAP + LABEL_SIZE

    height = int(y - LABEL_SIZE - GROUP_GAP + PAD)
    chars = "".join(SKILLS.keys()) + "".join(n for v in SKILLS.values() for n in v)
    title = "skills: " + "; ".join(f"{k} -- {', '.join(v)}" for k, v in SKILLS.items())
    return svg_shell(CARD_W, height, "\n  ".join(parts), title, chars=chars)


def main():
    (OUT_DIR / "skills.svg").write_text(build())
    print("wrote skills.svg")


if __name__ == "__main__":
    main()
