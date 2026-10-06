#!/usr/bin/env python3
"""Build the GitHub Pages site into ../docs.

    site.py

Reads samples/recorded_three_ways.json, samples/party_three_ways.json,
samples/smoke/*.json and samples/bitrate_results.json (run bitrate.py first),
writes docs/index.html and docs/renders/*.html. Screenshots in docs/img are
made separately (see README.md).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import render

HERE = Path(__file__).parent
DOCS = HERE.parent / "docs"
REPO = "https://github.com/omnifroodle/prosotype"

RENDERS = {
    "recorded_three_ways.html": ["samples/recorded_three_ways.json", "samples/party_three_ways.json"],
    "party_three_ways.html": ["samples/party_three_ways.json"],
    "synthetic.html": ["samples/smoke/say_statement.json", "samples/smoke/say_question.json",
                       "samples/smoke/say_natural.json"],
}

SIZE_ROWS = [  # (kind, name, label)
    ("packed", "8b", "Packed 8-bit, word flag"),
    ("packed", "12b", "Packed 12-bit, word flag"),
    ("packed", "16b", "Packed 16-bit, word flag"),
    ("packed", "16a", "Packed 16-bit, word symbol"),
    ("text", "UTF-8", "Plain text (UTF-8)"),
    ("text", "UTF-16", "Plain text (UTF-16)"),
    ("audio", "Codec 2 700C", "Codec 2, 700 bit/s"),
    ("audio", "Opus 6 kbit/s (Ogg)", "Opus, 6 kbit/s"),
]


def size_table(results: list[dict]) -> str:
    synth = next(r for r in results if "say_natural" in r["sample"])
    rec = next(r for r in results if "recorded" in r["sample"])
    find = lambda r, k, n: next(x for x in r["rows"] if x["kind"] == k and x["name"] == n)  # noqa: E731
    scale = 12.0  # bytes/word at full bar width
    out = []
    for kind, name, label in SIZE_ROWS:
        a, b = find(synth, kind, name), find(rec, kind, name)
        v = a["bytes_per_word"]
        bar = (f'<span class="bar {kind}" style="width:{min(v, scale) / scale * 100:.1f}%"></span>'
               + ('<span class="off">off scale</span>' if v > scale else ""))
        z = f'{a["zlib_bytes_per_word"]:.1f}' if a["zlib"] else "–"
        out.append(f"<tr><th scope=row>{html.escape(label)}</th><td class=num>{v:.1f}</td>"
                   f"<td class=num>{b['bytes_per_word']:.1f}</td><td class=num>{z}</td>"
                   f"<td class=num>{a['bit_s']:,.0f}</td><td class=barcell>{bar}</td></tr>")
    return "\n".join(out)


def hero(doc: dict) -> str:
    rows = []
    for utt in doc["utterances"]:
        text = " ".join(w["text"] for w in utt["words"])
        rows.append(
            f'<figure class="take"><figcaption><b>{html.escape(utt["label"])}</b>'
            f'<span>{html.escape(text)}</span></figcaption>'
            f'<div class="ipa mapB" lang="und-fonipa">{render.utterance_html(utt, "B", 0)}</div></figure>'
        )
    return "\n".join(rows)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProsoType</title>
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<script type="module" src="js/prosotype-player.mjs"></script>
<meta name="description" content="Speech written in IPA, with pitch, duration and loudness set into the type. Specification and prototype from the viability phase.">
<style>
{fontface}
:root{{--bg:#fbfbf9;--surface:#ffffff;--ink:#1b1b1f;--muted:#5f5f68;--unvoiced:#6c6c74;--rule:#e4e4df;--guide:#c9c9c2;
--link:oklch(0.48 0.13 250);--go:oklch(0.5 0.12 150);--adjust:oklch(0.55 0.13 70);--bar-packed:oklch(0.55 0.12 250);
--bar-text:#8a8a92;--bar-audio:oklch(0.62 0.12 45);--spk-l:0.5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131316;--surface:#1b1b20;--ink:#ececf0;--muted:#a3a3ad;--unvoiced:#9a9aa3;
--rule:#2c2c33;--guide:#4a4a53;--link:oklch(0.78 0.11 250);--go:oklch(0.78 0.13 150);--adjust:oklch(0.82 0.12 80);
--bar-packed:oklch(0.72 0.11 250);--bar-text:#8a8a92;--bar-audio:oklch(0.75 0.11 45);--spk-l:0.8;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:48px 16px 80px}}
a{{color:var(--link)}}
h1{{margin:0;line-height:0}}
h1 .logo{{height:clamp(56px,10vw,96px);width:auto;max-width:100%}}
h2{{font-size:24px;margin:64px 0 12px;letter-spacing:-0.01em}}
h3{{font-size:17px;margin:0 0 6px}}
p{{margin:0 0 14px;max-width:68ch}}
.lede{{font-size:21px;color:var(--muted);margin-top:14px;max-width:46ch}}
.status{{display:inline-block;font-size:13px;border:1px solid var(--rule);border-radius:999px;padding:2px 10px;color:var(--muted);margin-top:18px}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:20px 22px}}
.takes{{margin-top:36px;display:grid;gap:4px}}
.take{{margin:0;padding:6px 0 2px;border-top:1px solid var(--rule)}}
.take:first-child{{border-top:0}}
.take figcaption{{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--muted)}}
.take figcaption b{{color:var(--ink);font-weight:600;text-transform:capitalize}}
.ipa{{font-family:'ProsoType IPA',sans-serif;font-size:clamp(24px,4.2vw,36px);line-height:2.3;overflow-wrap:anywhere}}
.w{{white-space:nowrap}}
.p{{display:inline-block;font-family:'ProsoType IPA',sans-serif}}
.pause{{display:inline-block;height:.9em;vertical-align:middle;border-left:2px solid var(--rule);border-right:2px solid var(--rule)}}
.legend-line{{font-size:13px;color:var(--muted);margin:12px 0 0}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
.grid3 .card p{{font-size:15.5px;color:var(--muted);margin:0}}
.tablewrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:15px;min-width:640px}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:middle}}
thead th{{font-size:12.5px;color:var(--muted);font-weight:600}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.barcell{{width:30%;position:relative}}
.bar{{display:inline-block;height:10px;border-radius:3px;vertical-align:middle}}
.bar.packed{{background:var(--bar-packed)}}.bar.text{{background:var(--bar-text)}}.bar.audio{{background:var(--bar-audio)}}
.off{{font-size:12px;color:var(--muted);margin-left:6px}}
.note{{font-size:14px;color:var(--muted)}}
.shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.shots figure{{margin:0}}
.shots img{{width:100%;height:auto;border:1px solid var(--rule);border-radius:10px;display:block}}
.shots figcaption{{font-size:14px;color:var(--muted);margin-top:6px}}
.verdict td:nth-child(2){{font-weight:700;white-space:nowrap}}
.go{{color:var(--go)}}.adjust{{color:var(--adjust)}}
.links{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.links a{{display:block;text-decoration:none;color:var(--ink)}}
.links a span{{display:block;font-size:14px;color:var(--muted)}}
.links a:hover strong{{color:var(--link)}}
footer{{margin-top:72px;font-size:14px;color:var(--muted);border-top:1px solid var(--rule);padding-top:18px}}
{levelcss}
.mapB .w{{background:linear-gradient(to bottom,transparent calc(78.5% - 1px),var(--guide) calc(78.5% - 1px),var(--guide) 78.5%,transparent 78.5%)}}
</style></head>
<body><main>

<header>
<h1><img class="logo" src="img/logo.svg" alt="ProsoType" width="{logo_w}" height="{logo_h}"></h1>
<p class="lede">Speech written in the International Phonetic Alphabet, with how it was said (pitch, length and loudness) set into the type itself.</p>
<span class="status">Viability phase · specification draft 0.3 · October 2026</span>
</header>

<section class="card takes" aria-label="Three deliveries, transcribed automatically">
<prosotype-player src="play/data/recorded.16a.prs" text="play/data/recorded.16a.text.json">{hero}</prosotype-player>
<p class="legend-line">One speaker, three takes, transcribed automatically from audio. Height is pitch (the faint line is the speaker's median), width is length, weight is loudness. Unvoiced sounds are grey. Press play to hear the stream spoken by the reference synthesiser (the recordings themselves are not published).</p>
</section>

<h2>The idea</h2>
<div class="grid3">
<div class="card"><h3>Phones, not letters</h3><p>Speech is written as IPA phones: about 3.2 per English word, against about 5.3 characters of ordinary text.</p></div>
<div class="card"><h3>One fixed-width symbol per phone</h3><p>6 bits name the phone; the remaining bits carry pitch, duration and loudness relative to the speaker. 8, 12 and 16-bit variants.</p></div>
<div class="card"><h3>A standard look</h3><p>Delivery maps to glyph height, width and weight the same way every time, so a trained reader can see how a line was spoken.</p></div>
</div>

<h2>What the prototype measured</h2>
<p>Bytes per word for the same speech in each form. Body only (a 23-byte header is excluded). The synthetic clip is 26 s, 87 words; the recorded clips are 19 words.</p>
<div class="tablewrap card">
<table>
<thead><tr><th>Form</th><th class=num>Synthetic B/word</th><th class=num>Recorded B/word</th><th class=num>After zlib</th><th class=num>bit/s</th><th>Synthetic, to scale</th></tr></thead>
<tbody>
{sizes}
</tbody></table>
</div>
<p class="note" style="margin-top:10px">Packed symbols beat plain text at 8 and 12 bits, not at 16, and none beat zip-compressed text (about 3.3 B/word). Every packed form is at least 3× smaller than the lowest-rate Codec 2 audio, but that is not the real comparison: phonetic vocoders reached 100–400 bit/s in 1989–2008, and neural codecs now reach 160 bit/s while staying playable. ProsoType's size is in that same range. What it adds is that its symbols mean something to any reader or program without a model; turning them back into sound needs a synthesiser, which is out of scope.</p>

<h2>Two ways to draw it</h2>
<p>Mapping A (the original proposal) shows pitch as colour, length as size and loudness as weight. Mapping B shows pitch as height, length as width and loudness as weight, close to published work on speech-modulated captions. In greyscale, A loses pitch entirely; B keeps everything.</p>
<div class="shots">
<figure><img src="img/recorded_colour.png" width="1600" height="1000" alt="The three takes drawn in mapping A (left, coloured) and mapping B (right, raised and lowered glyphs)."><figcaption>Colour: A on the left, B on the right.</figcaption></figure>
<figure><img src="img/recorded_grey.png" width="1600" height="1000" alt="The same comparison in greyscale: mapping A's pitch disappears, mapping B is unchanged."><figcaption>Greyscale: A's intonation is gone; B's contour remains.</figcaption></figure>
</div>
<p class="note" style="margin-top:10px">Recommendation: mapping B as the standard, with A's colour allowed only as a redundant layer in five bands.</p>

<h2>Verdict on the technical questions</h2>
<div class="tablewrap card">
<table class="verdict">
<thead><tr><th>Question</th><th>Call</th><th>Why</th></tr></thead>
<tbody>
<tr><th scope=row>Encoding size</th><td class="adjust">Adjust</td><td>The size claim holds at 12 bits and below with a word-start flag. Next step: entropy coding rather than wider symbols.</td></tr>
<tr><th scope=row>Transcription</th><td class="adjust">Adjust</td><td>Words and pitch are dependable; phones degrade at quiet sentence ends, and durations still need checking against hand labels.</td></tr>
<tr><th scope=row>Rendering</th><td class="go">Go</td><td>Mapping B separates all three deliveries in light, dark and greyscale, and meets contrast and size floors.</td></tr>
</tbody></table>
</div>

<h2>Read more</h2>
<ul class="links">
<li><a href="{repo}/blob/main/SPEC.md"><strong>Specification</strong><span>Data model, packed stream, visual mapping, accessibility, findings.</span></a></li>
<li><a href="play.html"><strong>Reader</strong><span>Every sample, decoded and spoken in your browser in a choice of voice profiles, with each phone and word highlighted; and how to embed it.</span></a></li>
<li><a href="compare.html"><strong>Synthesiser comparison</strong><span>The same sentences with one synthesiser change at a time, and in your own voice profile.</span></a></li>
<li><a href="renders/recorded_three_ways.html"><strong>Interactive render</strong><span>The recorded takes in both mappings, with theme and greyscale toggles.</span></a></li>
<li><a href="renders/synthetic.html"><strong>Synthetic speech render</strong><span>A 26-second paragraph from macOS speech synthesis.</span></a></li>
<li><a href="{repo}/tree/main/prototype"><strong>Prototype</strong><span>Python: pack, render, transcribe, size report.</span></a></li>
<li><a href="renders/party_three_ways.html"><strong>Hand-written sample</strong><span>One sentence, three deliveries, values chosen by hand.</span></a></li>
<li><a href="{repo}/blob/main/SPEC.md#appendix-b-related-work-and-positioning"><strong>Related work</strong><span>Bolinger, ToBI, INTSINT, Prosogram, Jefferson notation, phonetic vocoders, neural codecs.</span></a></li>
<li><a href="{repo}/tree/main/vectors"><strong>Conformance vectors</strong><span>Exact bytes for every profile, and a decoder in JavaScript written from the spec.</span></a></li>
<li><a href="{repo}/blob/main/PLAN.md"><strong>Phase plan</strong><span>Goals and decisions for this phase.</span></a></li>
</ul>

<footer>
<p>Fluent reading of IPA is a known limitation, deliberately left to later work. Evidence so far: one speaker, three short recorded takes and synthetic speech. Built with Whisper, wav2vec2 phoneme recognition, Praat (via parselmouth) and Noto Sans.</p>
<p><a href="{repo}">github.com/omnifroodle/prosotype</a> · Specification and site © 2026 Matt Overstreet, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> · Code <a href="{repo}/blob/main/LICENSE">MIT</a> · Glyphs: Noto Sans, <a href="https://openfontlicense.org">SIL OFL 1.1</a></p>
</footer>
</main></body></html>
"""


def main() -> None:
    (DOCS / "renders").mkdir(parents=True, exist_ok=True)
    (DOCS / ".nojekyll").write_text("")
    import player
    player.write_js(DOCS)
    player.write_streams(DOCS)
    player.write_voices(DOCS)
    ids = {Path(path).stem: sid for sid, _, _, path in player.SAMPLES}
    pl = {"script": "../js/prosotype-player.mjs",
          "voices": [f"../play/voices/{v}.json" for v, _ in player.VOICES],
          "streams": {stem: (f"../play/data/{sid}.16a.prs", f"../play/data/{sid}.16a.text.json") for stem, sid in ids.items()}}
    for name, inputs in RENDERS.items():
        docs = [(Path(p).stem, json.loads((HERE / p).read_text())) for p in inputs]
        (DOCS / "renders" / name).write_text(render.render(docs, pl))
    rec = json.loads((HERE / "samples/recorded_three_ways.json").read_text())
    results = json.loads((HERE / "samples/bitrate_results.json").read_text())
    chars = {c for u in rec["utterances"] for w in u["words"] for p in w["phones"] for c in render.pack.normalise_ipa(p["ipa"])}
    levelcss, _ = render.css()
    import logo
    vb = logo.svg(logo.WORDMARK["rise-fall"]).split('viewBox="')[1].split('"')[0].split()
    page = PAGE.format(logo_w=round(float(vb[2]) / 10), logo_h=round(float(vb[3]) / 10), fontface=render.font_face("".join(sorted(chars))), levelcss=levelcss,
                       hero=hero(rec), sizes=size_table(results), repo=REPO)
    (DOCS / "index.html").write_text(page)
    print(f"docs/index.html: {len(page.encode()) / 1024:.0f} KB; renders: {', '.join(RENDERS)}")
    import player
    print(player.build(DOCS, REPO))
    import compare
    print(compare.build(DOCS, REPO))


if __name__ == "__main__":
    main()
