#!/usr/bin/env python3
"""
generate_portrait.py

Photo -> ASCII portrait -> self-typing animated SVG, using only the repo's
own assets (no third-party image services at render time).

Pipeline:
  1. cutout            -> isolates the subject and yields a binary subject mask
  2. CLAHE             -> lifts the dark hair mass off the darker eye sockets
  3. edges, FULL RES   -> bilateral filter + auto-threshold Canny + the mask
                          silhouette, so features are found at a scale where
                          they still exist
  4. area downsample   -> each grid cell becomes an edge *coverage fraction*,
                          which is what makes the ramp's anti-aliasing mean
                          something
  5. tone channel      -> inverted luminance, also area-downsampled, so hair and
                          shadow read as mass rather than outline
  6. map to ramp       -> blank outside the subject, denser characters for more ink
  7. SVG               -> staggered clipPath animation for the typing effect

Detecting edges *before* the downsample is the whole trick. Running Canny on the
90-column grid (as this script used to) means looking for a face that is 50 px
wide -- the eyes, nose and mouth are below the detector's scale and come back as
disconnected specks.

Usage:
    python3 generate_portrait.py <input_photo> <output_svg> [--cols 100]
                                 [--style hybrid|line|tone] [--no-cutout]
"""
import sys
import argparse
import base64
import io
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

# Ink ramp: index 0 is blank, then thin -> dense. A single leading space (the
# old ramp had three) because the input is now a smooth coverage fraction, not a
# binary speck map -- padding the low end here just erases the mid-tones.
RAMP = " .:-=+*#%@"
INK_FLOOR = 0.06                  # below this a cell stays blank
EDGE_KNEE = 0.45                  # hybrid: edge coverage below this adds nothing
SIL_WEIGHT = 0.55                 # hybrid: ink floor along the cutout boundary
CHAR_W = 7.74                     # px advance at font-size 12.9 (0.600em, JetBrains Mono)
FONT_SIZE = 12.9
LINE_HEIGHT = CHAR_W / 0.48       # derived so rows = cols * (h/w) * 0.48 holds visually
DISPLAY_WIDTH = 460               # px, final <img> width in the README


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Keep the largest blob and fill its interior.

    Specular highlights on a forehead or a white shirt panel threshold out as
    background; left alone they punch holes straight through the face.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    biggest = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, [biggest], -1, 255, thickness=cv2.FILLED)
    return filled


def remove_background(img: Image.Image) -> tuple[Image.Image, np.ndarray]:
    from rembg import remove
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = remove(buf.getvalue())
    cut = Image.open(io.BytesIO(out)).convert("RGBA")
    alpha = np.array(cut.getchannel("A"))

    # Composite onto solid white -- makes the outer boundary easy to detect
    bg = Image.new("RGBA", cut.size, (255, 255, 255, 255))
    bg.paste(cut, (0, 0), cut)
    mask = _fill_holes((alpha > 128).astype(np.uint8) * 255)
    return bg.convert("RGB"), mask


def mask_from_white(img: Image.Image) -> np.ndarray:
    """Subject mask for a photo that already sits on a white background."""
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    mask = (gray < 246).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return _fill_holes(mask)


def frame_to_face(img: Image.Image, mask: np.ndarray) -> tuple[Image.Image, np.ndarray]:
    """Crop to head and collar.

    Ungrated, the frame is whatever the photographer chose -- for photo.jpg that
    is a third of a patterned shirt, whose black-and-white blocks are the
    highest-contrast thing in the picture and swamp the face at 100 columns.
    Haar is plenty for finding one large frontal face; if it misses, fall back
    to the mask's bounding box, which at least drops the empty margins.
    """
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(max(60, w // 8), max(60, h // 8)))
    if len(faces):
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        top = fy - 0.45 * fh          # hair
        bottom = fy + fh + 0.18 * fh  # chin, neck, a hint of collar
        left = fx - 0.22 * fw
        right = fx + fw + 0.22 * fw
    else:
        ys, xs = np.nonzero(mask)
        if not ys.size:
            return img, mask
        top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()

    box = (max(0, int(left)), max(0, int(top)), min(w, int(right)), min(h, int(bottom)))
    return img.crop(box), mask[box[1]:box[3], box[0]:box[2]]


def _stretch(a: np.ndarray, lo_pct: float = 2, hi_pct: float = 98) -> np.ndarray:
    """Percentile contrast stretch to 0..1, ignoring the tails."""
    if not a.size:
        return a
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    if hi <= lo:
        return np.zeros_like(a, dtype=np.float32)
    return np.clip((a - lo) / (hi - lo), 0, 1).astype(np.float32)


def to_ascii_grid(
    img: Image.Image,
    mask: np.ndarray,
    cols: int,
    style: str = "hybrid",
    edge_weight: float = 0.25,
    tone_weight: float = 1.0,
    gamma: float = 1.2,
    clahe: float = 0.0,
) -> list[str]:
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    rows = max(1, round(cols * (h / w) * 0.48))

    # CLAHE is off by default: it equalises hair, skin and shirt toward each
    # other, and the global tonal ordering is exactly what makes a 100-column
    # face readable. Kept as a dial for flatter, softer-lit photos.
    eq = cv2.createCLAHE(clipLimit=clahe, tileGridSize=(8, 8)).apply(gray) if clahe > 0 else gray
    eq = np.where(mask > 0, eq, 255).astype(np.uint8)

    # --- edge channel, at full resolution ---------------------------------
    smooth = cv2.bilateralFilter(eq, 9, 75, 75)
    median = float(np.median(smooth[mask > 0])) if mask.any() else 128.0
    lo = int(max(0, 0.66 * median))
    hi = int(min(255, 1.33 * median))
    edges = cv2.Canny(smooth, lo, hi)
    edges = cv2.bitwise_and(edges, mask)
    # a 1 px line does not survive an ~11x reduction on its own
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel)
    edge_small = cv2.resize(edges.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    peak = edge_small.max() or 1.0
    edge_small = np.clip(edge_small / peak, 0, 1)

    # --- silhouette --------------------------------------------------------
    # Black hair against a #0d1117 card is near-zero ink, so the top of the head
    # dissolves into the background. The cutout boundary is a known-good outline;
    # give it a floor of its own so the head shape always closes.
    outline = cv2.dilate(cv2.Canny(mask, 50, 150), kernel)
    sil_small = cv2.resize(outline.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    sil_small = np.clip(sil_small / (sil_small.max() or 1.0), 0, 1)

    # --- tone channel ------------------------------------------------------
    # NOT inverted: the card is light text on #0d1117, so a denser character is
    # a *brighter* pixel. Inverting here renders a photographic negative --
    # a glowing hair mass around a hollow face.
    tone_full = np.where(mask > 0, eq.astype(np.float32), 0.0)
    tone_small = cv2.resize(tone_full, (cols, rows), interpolation=cv2.INTER_AREA)
    inside = tone_small[cv2.resize(mask.astype(np.float32), (cols, rows),
                                   interpolation=cv2.INTER_AREA) > 96]
    if inside.size:
        lo_t, hi_t = np.percentile(inside, [2, 98])
        tone_small = np.clip((tone_small - lo_t) / max(hi_t - lo_t, 1e-6), 0, 1)
    else:
        tone_small = _stretch(tone_small)

    # --- subject coverage per cell ----------------------------------------
    mask_small = cv2.resize(mask.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA) / 255.0

    if style == "line":
        ink = np.maximum(edge_small, sil_small)
    elif style == "tone":
        ink = tone_small
    else:
        # Tone carries the likeness; edges only sharpen it. Blending with max()
        # lets the edge channel win on any textured skin and flattens the whole
        # face to one mid-grey, so add in the *strong* edges only.
        accent = np.clip((edge_small - EDGE_KNEE) / (1 - EDGE_KNEE), 0, 1)
        ink = tone_small * tone_weight + accent * edge_weight
        ink = np.maximum(ink, sil_small * SIL_WEIGHT)
    ink = np.clip(ink, 0, 1) ** gamma
    ink[mask_small < 0.35] = 0.0

    ramp_len = len(RAMP)
    lines = []
    for r in range(rows):
        line = []
        for c in range(cols):
            v = float(ink[r, c])
            if v < INK_FLOOR:
                line.append(RAMP[0])
                continue
            idx = 1 + int(v * (ramp_len - 1))
            line.append(RAMP[min(idx, ramp_len - 1)])
        lines.append("".join(line))

    return trim(lines)


def trim(lines: list[str]) -> list[str]:
    """Drop fully blank border rows and columns so the face fills the frame."""
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return [" "]
    left = min((len(l) - len(l.lstrip())) for l in lines if l.strip())
    right = max((len(l.rstrip())) for l in lines)
    return [l[left:right] for l in lines]


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

        # staggered delay -> the line-by-line typing animation
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
    ap.add_argument("--cols", type=int, default=100)
    ap.add_argument("--style", choices=["hybrid", "line", "tone"], default="hybrid")
    ap.add_argument("--edge-weight", type=float, default=0.25)
    ap.add_argument("--tone-weight", type=float, default=1.0)
    ap.add_argument("--gamma", type=float, default=1.2,
                    help=">1 compresses highlights; the lit forehead otherwise "
                         "clips to a flat block of @")
    ap.add_argument("--clahe", type=float, default=0.0,
                    help="local contrast clip limit; 0 disables")
    ap.add_argument("--no-cutout", action="store_true",
                    help="photo is already isolated on white; skip rembg")
    ap.add_argument("--no-frame", action="store_true",
                    help="keep the photo's original framing instead of cropping to the face")
    ap.add_argument("--font", default=str(Path(__file__).parent.parent / "fonts" / "JetBrainsMono-Regular.ttf"))
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGB")
    if args.no_cutout:
        mask = mask_from_white(img)
    else:
        img, mask = remove_background(img)

    if not args.no_frame:
        img, mask = frame_to_face(img, mask)

    lines = to_ascii_grid(
        img, mask, args.cols,
        style=args.style,
        edge_weight=args.edge_weight,
        tone_weight=args.tone_weight,
        gamma=args.gamma,
        clahe=args.clahe,
    )

    used_chars = "".join(sorted(set("".join(lines))))
    font_uri = embed_font(Path(args.font), used_chars)

    svg = build_svg(lines, font_uri)
    Path(args.output).write_text(svg)

    # Dump the plain-text grid so quality can be checked without a browser
    Path(args.output).with_suffix(".txt").write_text("\n".join(lines))
    print(f"wrote {args.output}  ({args.cols} cols x {len(lines)} rows, style={args.style})")


if __name__ == "__main__":
    main()
