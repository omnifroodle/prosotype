#!/usr/bin/env python3
"""Draw the ProsoType logo as SVG outlines (no font needed to display it).

    logo.py [--out DIR] [--variants]

The logo is the name set the way ProsoType sets speech (mapping B): height
above a median guide line is pitch, width is length, weight is loudness.
"Pro" is the stressed syllable (high, long, heavy), "so" drops (low, short,
light) and "Type" comes back up. Outlines are taken from Noto Sans at each
letter's weight and width, so the SVGs are self-contained.

Writes logo.svg (wordmark, follows the reader's light/dark setting),
logo-light.svg and logo-dark.svg (fixed colours, for READMEs), logo-ipa.svg
(the same contour on the IPA /ˈpɹoʊsoʊˌtaɪp/) and favicon.svg into DIR
(default ../docs/img).
"""

from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).parent
FONT = HERE / "fonts" / "NotoSans-VF.ttf"
OUT = HERE.parent / "docs" / "img"
UPM = 1000

LIGHT = ".v{fill:#1b1b1f}.u{fill:#7a7a82}.g{stroke:#b9b9b2}"
DARK = ".v{fill:#ececf0}.u{fill:#9a9aa3}.g{stroke:#55555e}"
STYLES = {
    "auto": f"<style>{LIGHT}@media (prefers-color-scheme:dark){{{DARK}}}</style>",
    "light": f"<style>{LIGHT}</style>",
    "dark": f"<style>{DARK}</style>",
}

# (text, pitch in em above the median line, weight, width, muted)
WORDMARK = {
    "rise-fall": [("P", .10, 760, 100, 0), ("r", .17, 760, 100, 0), ("o", .22, 800, 100, 0),
                  ("s", .02, 380, 86, 0), ("o", -.06, 330, 80, 0),
                  ("T", .04, 560, 96, 0), ("y", .11, 600, 100, 0), ("p", .12, 600, 100, 0), ("e", .07, 560, 96, 0)],
    "question": [("P", .10, 760, 100, 0), ("r", .16, 760, 100, 0), ("o", .20, 800, 100, 0),
                 ("s", .02, 380, 86, 0), ("o", -.06, 330, 80, 0),
                 ("T", -.02, 540, 94, 0), ("y", .06, 580, 100, 0), ("p", .15, 620, 100, 0), ("e", .26, 660, 100, 0)],
    "gentle": [("P", .06, 720, 100, 0), ("r", .10, 720, 100, 0), ("o", .13, 760, 100, 0),
               ("s", .02, 400, 88, 0), ("o", -.03, 360, 82, 0),
               ("T", .02, 560, 96, 0), ("y", .06, 580, 100, 0), ("p", .07, 580, 100, 0), ("e", .04, 560, 96, 0)],
}
# /ˈpɹoʊsoʊˌtaɪp/ with the same contour; unvoiced phones muted
IPA = [("p", .10, 560, 90, 1), ("ɹ", .16, 700, 100, 0), ("o", .21, 800, 100, 0), ("ʊ", .22, 800, 100, 0),
       ("s", .02, 380, 86, 1), ("o", -.05, 330, 80, 0), ("ʊ", -.06, 330, 80, 0),
       ("t", .04, 520, 90, 1), ("a", .10, 620, 100, 0), ("ɪ", .11, 600, 100, 0), ("p", .07, 520, 90, 1)]
FAVICON = [("P", .14, 820, 100, 0), ("s", -.08, 380, 84, 0)]


@lru_cache(maxsize=None)
def instance(wght: float, wdth: float) -> TTFont:
    return instancer.instantiateVariableFont(TTFont(FONT), {"wght": wght, "wdth": wdth})


def draw(spec, track: float = 0.0):
    """Paths for a modulated line, baseline (median) at y=0, in font units.
    Returns (svg elements, bounds)."""
    x = 0.0
    els = []
    x0 = y0 = 1e9
    x1 = y1 = -1e9
    for ch, dy, wght, wdth, muted in spec:
        f = instance(wght, wdth)
        gs = f.getGlyphSet()
        g = gs[f.getBestCmap()[ord(ch)]]
        pen = SVGPathPen(gs)
        g.draw(TransformPen(pen, (1, 0, 0, -1, x, -dy * UPM)))
        bp = BoundsPen(gs)
        g.draw(TransformPen(bp, (1, 0, 0, 1, x, dy * UPM)))
        if bp.bounds:
            x0, y0, x1, y1 = min(x0, bp.bounds[0]), min(y0, bp.bounds[1]), max(x1, bp.bounds[2]), max(y1, bp.bounds[3])
        els.append(f'<path class="{"u" if muted else "v"}" d="{pen.getCommands()}"/>')
        x += g.width + track * UPM
    return els, (x0, y0, x1, y1)


def svg(spec, pad=70, guide=True, square=False, track=0.0, stroke=16, theme="auto") -> str:
    els, (x0, y0, x1, y1) = draw(spec, track)
    # the guide line spans the glyphs and sits on the median (y = 0)
    top, bottom = y1, min(y0, -stroke)
    w, h = x1 - x0, top - bottom
    if square:
        side = max(w, h)
        ox, oy = x0 - (side - w) / 2, -top - (side - h) / 2
        w = h = side
    else:
        ox, oy = x0, -top
    vb = f"{ox - pad:.0f} {oy - pad:.0f} {w + 2 * pad:.0f} {h + 2 * pad:.0f}"
    line = (f'<line class="g" x1="{x0:.0f}" x2="{x1:.0f}" y1="0" y2="0" stroke-width="{stroke}" stroke-linecap="round"/>'
            if guide else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="ProsoType">'
            f"<title>ProsoType</title>{STYLES[theme]}{line}{''.join(els)}</svg>")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--variants", action="store_true", help="also write each wordmark contour")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    files = {
        "logo.svg": svg(WORDMARK["rise-fall"]),
        "logo-light.svg": svg(WORDMARK["rise-fall"], theme="light"),  # fixed colours, for GitHub <picture>
        "logo-dark.svg": svg(WORDMARK["rise-fall"], theme="dark"),
        "logo-ipa.svg": svg(IPA),
        "favicon.svg": svg(FAVICON, pad=40, square=True, stroke=40),
    }
    if a.variants:
        files |= {f"logo-{k}.svg": svg(v) for k, v in WORDMARK.items()}
        files["logo-noguide.svg"] = svg(WORDMARK["rise-fall"], guide=False)
    for name, text in files.items():
        (a.out / name).write_text(text)
        print(f"{name}: {len(text) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
