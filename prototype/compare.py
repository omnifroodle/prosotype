"""Build docs/compare.html: a listening comparison of reference-synthesiser versions.

Each sentence plays in variants that add one change at a time:

  A  today: the original stop timing (stops: "legacy")
  B  aspirated stops: profile stop timing, defaulting to about 60 ms of breath
     after p t k, spilling into the following vowel when the stop is short
  C  B with a smoother pitch track (60 ms moving average)
  D  C with the refined transcription (transcribe.py --refine: vowel+r labels
     give the vowel 65% of the span; short unpitched vowels take neighbours' pitch);
     recorded sentences only
  E  D spoken with the listener's own voice profile, loaded from disk

Called by site.py; uses the files player.py writes (component, voices).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pack
import render
import textmap

HERE = Path(__file__).parent

ROWS = [  # (row id, title, current transcription, refined transcription or None, utterance index)
    ("rec-flat", "Recorded, flat (says “movie”)", "samples/recorded_three_ways.json", "samples/recorded_three_ways.refined.json", 0),
    ("rec-question", "Recorded, question", "samples/recorded_three_ways.json", "samples/recorded_three_ways.refined.json", 1),
    ("rec-sarcastic", "Recorded, sarcastic", "samples/recorded_three_ways.json", "samples/recorded_three_ways.refined.json", 2),
    ("hand-question", "Hand-written, question", "samples/party_three_ways.json", None, 1),
    ("hand-emphatic", "Hand-written, emphatic", "samples/party_three_ways.json", None, 2),
    ("say-statement", "Synthetic speech, statement", "samples/smoke/say_statement.json", None, 0),
    ("say-question", "Synthetic speech, question", "samples/smoke/say_question.json", None, 0),
]
VARIANTS = [  # (key, label, stream, synth options)
    ("A", "A · today", "current", {"stops": "legacy"}),
    ("B", "B · aspirated stops", "current", {"stops": "profile"}),
    ("C", "C · + smoother pitch", "current", {"stops": "profile", "pitchSmooth": 60}),
    ("D", "D · + refined transcription", "refined", {"stops": "profile", "pitchSmooth": 60}),
    ("E", "E · D in your profile", "refined", {"stops": "profile", "pitchSmooth": 60}),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProsoType comparison</title>
<meta name="description" content="Listening comparison of reference synthesiser versions, one change at a time.">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<script type="module" src="js/prosotype-player.mjs"></script>
<style>
{fontface}
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#1b1b1f;--muted:#5f5f68;--unvoiced:#6c6c74;--rule:#e4e4df;--guide:#c9c9c2;--link:oklch(0.48 0.13 250);--spk-l:0.5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131316;--surface:#1b1b20;--ink:#ececf0;--muted:#a3a3ad;--unvoiced:#9a9aa3;--rule:#2c2c33;--guide:#4a4a53;--link:oklch(0.78 0.11 250);--spk-l:0.8;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 72px}}
a{{color:var(--link)}}
header{{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;margin-bottom:8px}}
header img{{height:44px;width:auto}}
h1{{font-size:24px;margin:0}} h2{{font-size:17px;margin:0}}
p{{max-width:70ch;margin:0 0 12px}}
.note{{font-size:14px;color:var(--muted)}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:15px;margin:12px 0 20px}}
dt{{font-weight:700}} dd{{margin:0;color:var(--muted)}}
label{{display:grid;gap:4px;font-size:13px;color:var(--muted);max-width:420px}}
input[type=file]{{font:inherit;font-size:15px;color:var(--ink);background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:8px 10px;width:100%}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:14px 18px;margin-top:14px}}
.text{{font-size:14px;color:var(--muted);margin:2px 0 0}}
.ipa{{font-family:'ProsoType IPA',sans-serif;font-size:clamp(22px,3.6vw,30px);line-height:2.2;overflow-wrap:anywhere}}
.w{{white-space:nowrap}}
.p{{display:inline-block;font-family:'ProsoType IPA',sans-serif}}
.pause{{display:inline-block;height:.9em;vertical-align:middle;border-left:2px solid var(--rule);border-right:2px solid var(--rule)}}
.tag{{font:600 11px/1 system-ui,sans-serif;color:var(--muted);letter-spacing:.05em;text-transform:uppercase}}
.variants{{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}}
.variants prosotype-player{{flex:0 0 auto}}
.na{{font-size:13px;color:var(--muted);align-self:center;border:1px dashed var(--rule);border-radius:8px;padding:5px 10px}}
{levelcss}
.mapB .w{{background:linear-gradient(to bottom,transparent calc(78.5% - 1px),var(--guide) calc(78.5% - 1px),var(--guide) 78.5%,transparent 78.5%)}}
</style></head>
<body><main>
<header><a href="./"><img src="img/logo.svg" alt="ProsoType" width="200" height="44"></a><h1>Comparison</h1></header>
<p>The same sentences spoken by the reference synthesiser, adding one change at a time. Listen for clearer “p”, “t” and “k”, a less choppy melody, and whether “party” becomes easier to understand.</p>
<dl>
<dt>A</dt><dd>Today’s synthesiser: stops are mostly silence, with a short burst and little breath.</dd>
<dt>B</dt><dd>Aspirated stops: about 60 ms of breath after p, t, k (or the voice profile’s own timing), running into the next vowel when the stop is short.</dd>
<dt>C</dt><dd>B with a smoother pitch track: pitch averaged over 60 ms instead of straight lines between phones.</dd>
<dt>D</dt><dd>C with the refined transcription: in “ar”-type sounds the vowel gets 65% of the time instead of half, and very short vowels with no measured pitch borrow it from their neighbours. Recorded sentences only.</dd>
<dt>E</dt><dd>D spoken with your own voice profile (pitch, vocal-tract length, voice quality, stop timing and fricatives where it has enough examples). Load it below; it stays on this device.</dd>
</dl>
<label>Your voice profile for E<input type="file" id="own" accept="application/json,.json"></label>
{rows}
<p class="note" style="margin-top:20px">Rows show the current transcription in mapping B. Profiles: <a href="{repo}/blob/main/VOICE-PROFILE.md">VOICE-PROFILE.md</a>. Synthesiser options: <a href="{repo}/blob/main/js/synth.mjs">js/synth.mjs</a>.</p>
</main>
<script type="module">
const eCells = [...document.querySelectorAll('prosotype-player[data-variant="E"]')];
for (const p of eCells) p.style.opacity = 0.45;
document.getElementById("own").onchange = async (e) => {{
  const f = e.target.files[0];
  if (!f) return;
  try {{
    const profile = JSON.parse(await f.text());
    for (const p of eCells) {{ p.voiceProfile = profile; p.style.opacity = 1; p.setAttribute("label", `E · ${{profile.id ?? "your profile"}}`); }}
  }} catch {{ alert("That file is not a voice profile (JSON)."); }}
}};
</script>
</body></html>
"""


def one_utterance(doc: dict, k: int) -> dict:
    return {**doc, "utterances": [doc["utterances"][k]]}


def build(docs_dir: Path, repo: str) -> str:
    out = docs_dir / "compare"
    out.mkdir(parents=True, exist_ok=True)
    chars: set[str] = set()
    rows = []
    for rid, title, cur_path, ref_path, k in ROWS:
        cur = textmap.add_chars(json.loads((HERE / cur_path).read_text()))
        streams = {"current": one_utterance(cur, k)}
        if ref_path:
            streams["refined"] = one_utterance(textmap.add_chars(json.loads((HERE / ref_path).read_text())), k)
        for name, d in streams.items():
            (out / f"{rid}.{name}.prs").write_bytes(pack.to_bytes(pack.encode(d, pack.PROFILES["16a"])))
        utt = streams["current"]["utterances"][0]
        chars |= {c for w in utt["words"] for ph in w["phones"] for c in pack.normalise_ipa(ph["ipa"])}
        text = " ".join(w.get("text") or "" for w in utt["words"])
        cells = []
        for key, label, stream, opts in VARIANTS:
            if stream not in streams:
                cells.append(f'<span class="na">{html.escape(label)}: n/a</span>')
                continue
            cells.append(f'<prosotype-player view="controls" compact data-variant="{key}" label="{html.escape(label)}" '
                         f'src="compare/{rid}.{stream}.prs" synth=\'{json.dumps(opts)}\'></prosotype-player>')
        rows.append(f'<section class="card"><h2>{html.escape(title)}</h2><p class="text">{html.escape(text)}</p>'
                    f'<div class="ipa mapB" lang="und-fonipa">{render.utterance_html(utt, "B", 0)}</div>'
                    f'<div class="variants">{"".join(cells)}</div></section>')
    levelcss, _ = render.css()
    page = PAGE.format(fontface=render.font_face("".join(sorted(chars))), levelcss=levelcss, rows="\n".join(rows), repo=repo)
    (docs_dir / "compare.html").write_text(page)
    return f"docs/compare.html: {len(ROWS)} sentences x {len(VARIANTS)} variants"
