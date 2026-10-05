#!/usr/bin/env python3
"""Render ProsoType JSON as one self-contained HTML page, mappings A and B
side by side, IPA glyphs only. Delivery is shown at the 16-bit (16a) levels,
i.e. what the packed stream actually holds.

    render.py IN.json [IN2.json ...] -o OUT.html

Mapping A (owner's proposal): pitch = colour, duration = size, loudness = weight.
Mapping B: pitch = vertical offset, duration = width (+ tracking), loudness = weight,
           colour = speaker.

Needs fontTools + brotli and fonts/NotoSans-VF.ttf (see README.md).
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

import pack

HERE = Path(__file__).parent
FONT = HERE / "fonts" / "NotoSans-VF.ttf"
P = pack.PROFILES["16a"]

# --- visual tables, indexed by 16a level -----------------------------------

SIZE_EM = [0.72, 0.80, 0.90, 1.00, 1.12, 1.26, 1.41, 1.60]  # duration level 0-7
WEIGHT = [300, 325, 350, 400, 500, 600, 750, 900]  # loudness level 0-7 (4 = 0 dB)
WIDTH = [62.5, 70, 78, 86, 94, 100, 100, 100]  # duration level 0-7, wdth axis
TRACK_EM = [0, 0, 0, 0, 0, 0, 0.06, 0.14]  # extra spacing for the longest bins
RAISE_EM = 0.075  # vertical offset per pitch level (B)
SPEAKER_HUES = [None, 160, 300, 80]  # first speaker uses ink


def pitch_colour(level: int, dark: bool) -> str:
    """Mapping A. Constant lightness so every level has the same contrast;
    hue and chroma carry the pitch: blue below median, orange above."""
    if level == 0:
        return "var(--unvoiced)"
    k = level - 8
    if k == 0:
        return "var(--ink)"
    lightness = 0.80 if dark else 0.50
    hue = 250 if k < 0 else 45
    chroma = 0.03 + 0.022 * abs(k)
    return f"oklch({lightness} {chroma:.3f} {hue})"


# --- font --------------------------------------------------------------------


def font_face(text: str) -> str:
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = TTFont(FONT, recalcTimestamp=False)  # keep output stable between builds
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        "@font-face{font-family:'ProsoType IPA';"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
        "font-weight:100 900;font-stretch:62.5% 100%;font-display:block}"
    )


# --- rendering ---------------------------------------------------------------


def levels(ph: dict) -> tuple[int, int, int]:
    pitch = pack.q_pitch(ph.get("pitch_st"), ph.get("voiced", True), P.pitch)
    dur = pack.q_dur(ph["dur_ms"], P.dur)
    loud = pack.q_loud(ph.get("loud_db"), P.loud)
    return pitch, dur, loud


def tip(ph: dict, lv: tuple[int, int, int]) -> str:
    st = ph.get("pitch_st")
    pq = pack.dq_pitch(lv[0], P.pitch)
    return (
        f"/{pack.normalise_ipa(ph['ipa'])}/  "
        f"pitch {'unvoiced' if pq is None else f'{pq:+.1f} st'}"
        f"{'' if st is None else f' (measured {st:+.1f})'}  "
        f"dur {pack.dq_dur(lv[1], P.dur):.0f} ms (measured {ph['dur_ms']:.0f})  "
        f"loud {pack.dq_loud(lv[2], P.loud):+.0f} dB"
        f"{'' if ph.get('loud_db') is None else ' (measured %+.1f)' % ph['loud_db']}"
    )


def phone_span(ph: dict, mapping: str, spk: int, height: int = 8) -> str:
    """height: for mapping B, the pitch level an unvoiced glyph is drawn at."""
    lv = levels(ph)
    pitch, dur, loud = lv
    glyph = html.escape(pack.normalise_ipa(ph["ipa"]))
    t = html.escape(tip(ph, lv), quote=True)
    if mapping == "A":
        cls = f"p pa{pitch} d{dur} l{loud}"
    elif pitch == 0:
        cls = f"p pb{height} unv w{dur} l{loud} s{spk}"
    else:
        cls = f"p pb{pitch} w{dur} l{loud} s{spk}"
    return f'<span class="{cls}" title="{t}">{glyph}</span>'


def pause_span(ms: float) -> str:
    if ms <= 0:
        return " "
    # log scale: 100 ms -> 0.6em, 3200 ms -> 3.1em
    w = 0.6 + 0.5 * math.log2(ms / 100)
    return f' <span class="pause" style="width:{w:.2f}em" title="pause {ms:.0f} ms"></span> '


def unvoiced_heights(utt: dict) -> dict[int, int]:
    """Mapping B draws an unvoiced glyph at the height of the preceding voiced
    phone (or the following one at the start of an utterance), so height only
    moves where pitch does."""
    phones = [ph for w in utt["words"] for ph in w["phones"]]
    lv = [levels(ph)[0] for ph in phones]
    out, last = {}, None
    for ph, l in zip(phones, lv):
        if l:
            last = l
        out[id(ph)] = last
    nxt = None
    for ph, l in zip(reversed(phones), reversed(lv)):
        if l:
            nxt = l
        if out[id(ph)] is None:
            out[id(ph)] = nxt or 8
    return out


def utterance_html(utt: dict, mapping: str, spk: int) -> str:
    heights = unvoiced_heights(utt)
    parts = []
    prev_end = None
    for w in utt["words"]:
        if prev_end is not None:
            gap = max(0.0, (w["start_s"] - prev_end) * 1000)
            lvls = pack.q_pause(gap, P.payload_bits)
            parts.append(pause_span(sum(pack.dq_pause(l, P.payload_bits) for l in lvls)))
        spans_ = []
        for k, ph in enumerate(w["phones"]):
            h = heights[id(ph)] if mapping == "B" else 8
            spans_.append(phone_span(ph, mapping, spk, h))
        parts.append('<span class="w">' + "".join(spans_) + "</span>")
        if w["phones"]:
            last = w["phones"][-1]
            prev_end = max(w.get("end_s", 0), last["start_s"] + last["dur_ms"] / 1000)
        else:
            prev_end = w.get("end_s", w["start_s"])
    return "".join(parts)


def legend() -> str:
    def row(label: str, cells: list[str]) -> str:
        return f'<div class="lg-row"><span class="lg-label">{label}</span>{"".join(cells)}</div>'

    pa = [f'<span class="cell"><span class="p pa{i} d3 l4">a</span><small>{"unv" if i == 0 else f"{(i - 8) * 1.5:+g}"}</small></span>' for i in range(16)]
    sz = [f'<span class="cell"><span class="p pa8 d{i} l4">a</span><small>{c}</small></span>' for i, c in enumerate(pack.DUR_CENTRES[3])]
    wt = [f'<span class="cell"><span class="p pa8 d3 l{i}">a</span><small>{(i - 4) * 3:+d}</small></span>' for i in range(8)]
    pb = [f'<span class="cell"><span class="p pb{i} w3 l4 s0">a</span><small>{"unv" if i == 0 else f"{(i - 8) * 1.5:+g}"}</small></span>' for i in range(16)]
    wd = [f'<span class="cell"><span class="p pb8 w{i} l4 s0">aa</span><small>{c}</small></span>' for i, c in enumerate(pack.DUR_CENTRES[3])]
    return (
        '<section class="legend"><div><h3>Mapping A</h3>'
        + row("pitch (st) → colour", pa) + row("duration (ms) → size", sz) + row("loudness (dB) → weight", wt)
        + '</div><div><h3>Mapping B</h3>'
        + row("pitch (st) → height", pb).replace('class="lg-row"', 'class="lg-row tall"') + row("duration (ms) → width", wd)
        + row("loudness (dB) → weight", [c.replace("pa8 d3", "pb8 w3 s0") for c in wt])
        + "<p class=\"note\">Colour is free for speaker or voice quality.</p></div></section>"
    )


def css() -> str:
    out = []
    for i in range(16):
        out.append(f".pa{i}{{color:{pitch_colour(i, False)}}}")
        out.append(f".pb{i}{{transform:translateY({-(0 if i == 0 else i - 8) * RAISE_EM:.3f}em)}}")
    out.append(".pb0,.unv{color:var(--unvoiced)}")
    dark = "".join(f"{{sel}} .pa{i}{{color:{pitch_colour(i, True)}}}" for i in range(16))
    for i in range(8):
        out.append(f".d{i}{{font-size:{SIZE_EM[i]}em}}")
        out.append(f".l{i}{{font-weight:{WEIGHT[i]}}}")
        out.append(f".w{i}{{font-stretch:{WIDTH[i]}%;letter-spacing:{TRACK_EM[i]}em}}")
    for s, hue in enumerate(SPEAKER_HUES):
        if hue is not None:
            out.append(f".s{s}:not(.pb0):not(.unv){{color:oklch(var(--spk-l) 0.13 {hue})}}")
    return "\n".join(out), dark


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProsoType render</title>
<style>
{fontface}
:root{{--bg:#fbfbf9;--ink:#1b1b1f;--muted:#6b6b73;--unvoiced:#6c6c74;--rule:#e2e2dd;--guide:#c9c9c2;--panel:#ffffff;--spk-l:0.5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#141417;--ink:#ececf0;--muted:#a0a0aa;--unvoiced:#9a9aa3;--rule:#2c2c33;--guide:#4a4a53;--panel:#1b1b20;--spk-l:0.8;color-scheme:dark}}
{darkauto}}}
:root[data-theme=dark]{{--bg:#141417;--ink:#ececf0;--muted:#a0a0aa;--unvoiced:#9a9aa3;--rule:#2c2c33;--guide:#4a4a53;--panel:#1b1b20;--spk-l:0.8;color-scheme:dark}}
{darkforced}
html.grey body{{filter:grayscale(1)}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:1200px;margin:0 auto;padding:24px 16px 64px}}
header{{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:32px 0 8px}} h3{{font-size:14px;margin:0 0 8px}}
.sub{{color:var(--muted);margin:4px 0 0}}
.controls{{display:flex;gap:8px;flex-wrap:wrap}}
button{{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);cursor:pointer}}
button[aria-pressed=true]{{border-color:var(--ink)}}
.legend{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-top:20px}}
.legend>div,.utt{{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}}
.lg-row{{display:flex;flex-wrap:wrap;align-items:flex-end;gap:2px 4px;margin:6px 0}}
.lg-label{{width:100%;font-size:12px;color:var(--muted)}}
.cell{{display:inline-flex;flex-direction:column;align-items:center;min-width:30px;line-height:1.1;font-size:22px}}
.cell .p{{height:40px;display:flex;align-items:flex-end}}
.cell small{{font-size:10px;color:var(--muted)}}
.tall .cell .p{{height:52px;padding-bottom:12px}}
.note{{font-size:12px;color:var(--muted);margin:8px 0 0}}
.utt{{margin:10px 0}}
.utt-head{{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--muted);margin-bottom:6px}}
.utt-head .label{{color:var(--ink);font-weight:600}}
.pair{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.map{{font-family:'ProsoType IPA',sans-serif;font-size:30px;line-height:2.3;overflow-wrap:anywhere;padding:0 4px}}
.map-tag{{font:600 11px/1 system-ui,sans-serif;color:var(--muted);letter-spacing:.06em}}
.w{{white-space:nowrap}}
.p{{display:inline-block;font-family:'ProsoType IPA',sans-serif}}
.mapB .w{{background:linear-gradient(to bottom,transparent calc(78.5% - 1px),var(--guide) calc(78.5% - 1px),var(--guide) 78.5%,transparent 78.5%)}}
.pause{{display:inline-block;height:.9em;vertical-align:middle;border-left:2px solid var(--rule);border-right:2px solid var(--rule)}}
{levelcss}
</style></head>
<body><main>
<header><div><h1>ProsoType render</h1>
<p class="sub">IPA only. Delivery shown at the 16-bit profile's levels. Hover a glyph for its values.</p></div>
<div class="controls">
<button id="theme" type="button">Theme: auto</button>
<button id="grey" type="button" aria-pressed="false">Greyscale</button>
</div></header>
{legend}
{body}
</main>
<script>
(function(){{
  var root=document.documentElement, modes=['auto','light','dark'], i=0;
  try{{var s=localStorage.getItem('pt-theme'); if(s) i=Math.max(0,modes.indexOf(s));}}catch(e){{}}
  function apply(){{ if(modes[i]==='auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme',modes[i]);
    document.getElementById('theme').textContent='Theme: '+modes[i]; }}
  apply();
  document.getElementById('theme').onclick=function(){{ i=(i+1)%3; apply(); try{{localStorage.setItem('pt-theme',modes[i]);}}catch(e){{}} }};
  var g=document.getElementById('grey');
  g.onclick=function(){{ var on=root.classList.toggle('grey'); g.setAttribute('aria-pressed',on); }};
}})();
</script>
</body></html>
"""


def render(docs: list[tuple[str, dict]]) -> str:
    chars = set("aa ") | {chr(c) for c in range(0x20, 0x7F)}
    sections = []
    for name, doc in docs:
        spk_names = list(doc["speakers"])
        rows = []
        for ui, utt in enumerate(doc["utterances"]):
            spk = spk_names.index(utt["speaker"])
            for w in utt["words"]:
                for ph in w["phones"]:
                    chars |= set(pack.normalise_ipa(ph["ipa"]))
            text = " ".join(w.get("text") or "" for w in utt["words"]).strip()
            label = utt.get("label") or f"utterance {ui + 1}"
            rows.append(
                '<div class="utt"><div class="utt-head">'
                f'<span class="label">{html.escape(label)}</span>'
                f'<span>speaker {html.escape(utt["speaker"])}</span>'
                + (f'<span>{html.escape(text)}</span>' if text != label else "") + '</div>'
                '<div class="pair">'
                f'<div><div class="map-tag">A</div><div class="map" lang="und-fonipa">{utterance_html(utt, "A", spk)}</div></div>'
                f'<div><div class="map-tag">B</div><div class="map mapB" lang="und-fonipa">{utterance_html(utt, "B", spk)}</div></div>'
                "</div></div>"
            )
        src = doc.get("source", {})
        audio = src.get("audio") or ""
        note = src.get("note") or (", ".join(audio) if isinstance(audio, list) else audio)
        sections.append(
            f"<h2>{html.escape(name)}</h2>"
            + (f'<p class="sub">{html.escape(note)}</p>' if note else "")
            + "".join(rows)
        )
    levelcss, darkpa = css()
    return PAGE.format(
        fontface=font_face("".join(sorted(chars))),
        darkauto=darkpa.replace("{sel}", ":root:not([data-theme=light])"),
        darkforced=darkpa.replace("{sel}", ":root[data-theme=dark]"),
        levelcss=levelcss,
        legend=legend(),
        body="".join(sections),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--output", default="render.html")
    a = ap.parse_args()
    docs = [(Path(p).stem, json.loads(Path(p).read_text())) for p in a.inputs]
    out = render(docs)
    Path(a.output).write_text(out)
    print(f"{a.output}: {len(out.encode()) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
