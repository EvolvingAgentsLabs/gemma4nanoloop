"""Render the eyeless/PAX6 alignment as an image.

    python tools/render_alignment.py docs/img/alignment.png

Monospaced text is the whole point of a sequence alignment and most places that
matter — LinkedIn, slides, X — destroy it. So this draws the real alignment
rather than asking anyone to screenshot a terminal.

Every character comes from `examples/bioinformatics-eyeless`: the sequences are
the vendored UniProt entries and the alignment is computed at render time. There
is nothing decorative in the letters.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "bioinformatics-eyeless"))

BG = (27, 36, 48)
FLY = (94, 214, 226)  # cyan, matching the other assets
HUMAN = (240, 180, 92)  # amber
MATCH = (108, 124, 140)  # muted: the bars are texture, not the message
MISMATCH = (232, 106, 106)
LABEL = (150, 165, 180)
TITLE = (225, 235, 245)

MONO = "/System/Library/Fonts/Menlo.ttc"
WIDTH = 60  # residues per row; 60 is what fits legibly at this size


def font(size: int, path: str = MONO) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def render(out: Path) -> None:
    from conserved import conserved_blocks
    from sequences import EYELESS_DROME, PAX6_HUMAN

    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    best = max(blocks, key=lambda b: b["percent_identity"])
    fly = EYELESS_DROME[best["query_start"] - 1 : best["query_end"]][:WIDTH]
    human = PAX6_HUMAN[best["subject_start"] - 1 : best["subject_end"]][:WIDTH]

    f_mono = font(26)
    f_label = font(20)
    f_title = font(30)
    f_note = font(19)

    cw = int(f_mono.getlength("M"))
    pad, gutter = 70, 150
    w = pad * 2 + gutter + cw * WIDTH
    h = 340

    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.text((pad, 42), "eyeless (fruit fly)  vs  PAX6 (human)", font=f_title, fill=TITLE)
    mismatches = sum(1 for a, b in zip(fly, human, strict=True) if a != b)
    d.text(
        (pad, 84),
        f"{WIDTH - mismatches} of {WIDTH} identical — "
        f"{best['length']} residues at {best['percent_identity']:.0f}% overall",
        font=f_note,
        fill=LABEL,
    )

    x, y = pad + gutter, 150
    d.text((pad, y), "fly", font=f_label, fill=LABEL)
    d.text((pad, y + 76), "human", font=f_label, fill=LABEL)

    for i, (a, b) in enumerate(zip(fly, human, strict=True)):
        cx = x + i * cw
        same = a == b
        d.text((cx, y), a, font=f_mono, fill=FLY if same else MISMATCH)
        d.text((cx, y + 76), b, font=f_mono, fill=HUMAN if same else MISMATCH)
        # The bar row is what makes an alignment readable at a glance.
        d.text((cx, y + 38), "|" if same else " ", font=f_mono, fill=MATCH)

    d.text(
        (pad, h - 62),
        "600 million years apart. What survived is the part that grips DNA.",
        font=f_note,
        fill=LABEL,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"  wrote {out}  {img.width}x{img.height}  ({out.stat().st_size // 1024} KB)")
    print(f"  {WIDTH - mismatches}/{WIDTH} identical, {mismatches} mismatch(es) in red")


if __name__ == "__main__":
    render(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img/alignment.png"))
