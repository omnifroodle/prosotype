"""Build the browser reader for the GitHub Pages site (called by site.py).

Writes, under docs/:
  js/        the <prosotype-player> web component (js/prosotype-player.mjs), the
             decoder and reference synthesiser it uses, and its IPA font
  play/data  every sample packed at 16a, 12b and 8b (.prs), each with its text map
  play/voices  the published (synthetic) voice profiles
  play.html  all samples as <prosotype-player> elements, with page-level
             format and voice menus and a local "your own profile" loader

The homepage hero uses the same component (site.py).
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pack
import render
import textmap

HERE = Path(__file__).parent
ROOT = HERE.parent

SAMPLES = [  # (id, title, note, path)
    ("recorded", "Recorded: three takes", "The owner's recordings, transcribed automatically (the audio is not published).",
     "samples/recorded_three_ways.json"),
    ("hand", "Hand-written: three deliveries", "One sentence with delivery values chosen by hand.", "samples/party_three_ways.json"),
    ("story", "Synthetic speech: a short story", "26 seconds of macOS speech synthesis, transcribed automatically.",
     "samples/smoke/say_natural.json"),
    ("statement", "Synthetic: statement", "macOS speech synthesis.", "samples/smoke/say_statement.json"),
    ("question", "Synthetic: question", "macOS speech synthesis.", "samples/smoke/say_question.json"),
    ("emphatic", "Synthetic: emphatic", "macOS speech synthesis.", "samples/smoke/say_emphatic.json"),
]
STREAM_PROFILES = ["16a", "12b", "8b"]
VOICES = [("reference-low", "Reference low"), ("reference-high", "Reference high"),
          ("fastspeech2-ljspeech", "FastSpeech 2 (measured)")]
JS_FILES = ["prosotype.mjs", "synth.mjs", "prosotype-player.mjs", "prosotype-ipa.woff2", "prosotype-ipa.OFL.txt"]

# Every IPA character the component may need to draw: the en-1 table and common extension phones.
FONT_CHARS = "".join(sorted({c for ph, _ in pack.PHONE_TABLES["en-1"] for c in ph}
                            | set("xçɣβʍyøɨɫʁʀɬɮʝʎɲɳɖʈɻʐʂχħʕɦɥɯɤɵœɶʉɞʏʜʡɕʑɟcqɢɴɰ") | {"̩"}))

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProsoType reader</title>
<meta name="description" content="Every ProsoType sample, drawn in mapping B and playable with the reference synthesiser, highlighting each phone and word.">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<script type="module" src="js/prosotype-player.mjs"></script>
<style>
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#1b1b1f;--muted:#5f5f68;--rule:#e4e4df;--link:oklch(0.48 0.13 250);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131316;--surface:#1b1b20;--ink:#ececf0;--muted:#a3a3ad;--rule:#2c2c33;--link:oklch(0.78 0.11 250);color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 72px}}
a{{color:var(--link)}}
header{{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;margin-bottom:8px}}
header img{{height:44px;width:auto}}
h1{{font-size:24px;margin:0}}
h2{{font-size:18px;margin:0}}
p{{max-width:68ch;margin:0 0 12px}}
.note{{font-size:14px;color:var(--muted)}}
.controls{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0 8px;background:var(--bg);padding:10px 0}}
@media (min-width:760px){{.controls{{position:sticky;top:0;z-index:1}}}}
.fallback{{font-size:20px;color:var(--muted)}}
label{{display:grid;gap:4px;font-size:13px;color:var(--muted);min-width:0}}
select,input[type=file]{{font:inherit;font-size:15px;color:var(--ink);background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:8px 10px;width:100%;min-width:0}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px 20px;margin-top:16px}}
.card .note{{margin:2px 0 8px}}
pre{{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:12px 14px;overflow-x:auto;font-size:13px}}
</style></head>
<body><main>
<header><a href="./"><img src="img/logo.svg" alt="ProsoType" width="200" height="44"></a><h1>Reader</h1><a href="compare.html" style="margin-left:auto;font-size:15px">Compare synthesiser versions</a></header>
<p>Every sample on this site, decoded and drawn in your browser from its packed stream, and spoken by the <strong>reference synthesiser</strong>: a small formant synthesiser that gives every phone exactly the stream's duration, pitch and loudness. It sounds robotic on purpose. Each glyph and word lights while it sounds. A <strong>voice profile</strong> sets the voice's pitch level, vocal-tract length and voice quality. Nothing is sent anywhere.</p>
<div class="controls">
<label>Stream profile (all samples)<select id="profile">{profiles}</select></label>
<label>Voice (all samples)<select id="voice"><option value="">Speaker's own pitch, reference voice</option>{voices}</select></label>
<label>Your own voice profile (stays on this device)<input type="file" id="own" accept="application/json,.json"></label>
</div>
{cards}
<section class="card"><h2>Embed it in your own page</h2>
<p class="note">One script and one element. The stream can be a file or inline base64; the text map and voice are optional.</p>
<pre>&lt;script type="module" src="https://omnifroodle.github.io/prosotype/js/prosotype-player.mjs"&gt;&lt;/script&gt;
&lt;prosotype-player src="hand.16a.prs" text="hand.16a.text.json" voice="reference-high.json"&gt;&lt;/prosotype-player&gt;

&lt;prosotype-player stream="{inline}"&gt;&lt;/prosotype-player&gt;</pre>
<p class="note">Attributes, events and theming: <a href="{repo}/blob/main/js/prosotype-player.mjs">js/prosotype-player.mjs</a> and <a href="{repo}/blob/main/SPEC.md">SPEC §11</a>.</p>
</section>
</main>
<script type="module">
const players = [...document.querySelectorAll("prosotype-player")];
const setAll = () => {{
  const prof = document.getElementById("profile").value, voice = document.getElementById("voice").value;
  for (const p of players) {{
    const id = p.dataset.sample;
    p.setAttribute("text", `play/data/${{id}}.${{prof}}.text.json`);
    p.setAttribute("src", `play/data/${{id}}.${{prof}}.prs`);
    if (voice && voice !== "own") p.setAttribute("voice", voice); else p.removeAttribute("voice");
  }}
}};
document.getElementById("profile").onchange = setAll;
document.getElementById("voice").onchange = () => {{
  const own = document.getElementById("voice").value === "own";
  if (!own) for (const p of players) p.voiceProfile = null;
  setAll();
}};
document.getElementById("own").onchange = async (e) => {{
  const f = e.target.files[0];
  if (!f) return;
  try {{
    const profile = JSON.parse(await f.text());
    for (const p of players) p.voiceProfile = profile;
    const sel = document.getElementById("voice");
    let opt = [...sel.options].find((o) => o.value === "own");
    if (!opt) {{ opt = new Option("", "own"); sel.add(opt); }}
    opt.text = `Your profile: ${{profile.id ?? f.name}}`;
    sel.value = "own";
  }} catch {{ alert("That file is not a voice profile (JSON)."); }}
}};
</script>
</body></html>
"""


def write_streams(docs_dir: Path) -> None:
    out = docs_dir / "play" / "data"
    out.mkdir(parents=True, exist_ok=True)
    for sid, _, _, path in SAMPLES:
        doc = textmap.add_chars(json.loads((HERE / path).read_text()))
        for name in STREAM_PROFILES:
            prof = pack.PROFILES[name]
            (out / f"{sid}.{name}.prs").write_bytes(pack.to_bytes(pack.encode(doc, prof)))
            (out / f"{sid}.{name}.text.json").write_text(json.dumps(textmap.build(doc, prof), ensure_ascii=False) + "\n")


def write_js(docs_dir: Path) -> None:
    (ROOT / "js" / "prosotype-ipa.woff2").write_bytes(render.font_woff2(FONT_CHARS))
    shutil.copyfile(HERE / "fonts" / "OFL.txt", ROOT / "js" / "prosotype-ipa.OFL.txt")
    (docs_dir / "js").mkdir(exist_ok=True)
    for f in JS_FILES:
        shutil.copyfile(ROOT / "js" / f, docs_dir / "js" / f)


def write_voices(docs_dir: Path) -> None:
    out = docs_dir / "play" / "voices"
    out.mkdir(parents=True, exist_ok=True)
    for vid, _ in VOICES:
        src = ROOT / "profiles" / f"{vid}.json"
        assert not json.loads(src.read_text()).get("private"), f"{vid} is private and must not be published"
        shutil.copyfile(src, out / f"{vid}.json")


def fallback(sid: str) -> str:
    """Plain IPA, shown inside the element until it upgrades (and to readers
    without JavaScript)."""
    path = next(p for s, _, _, p in SAMPLES if s == sid)
    doc = json.loads((HERE / path).read_text())
    lines = (" ".join("".join(pack.normalise_ipa(ph["ipa"]) for ph in w["phones"]) for w in u["words"]) for u in doc["utterances"])
    return "".join(f'<p class="fallback" lang="und-fonipa">{html.escape(t)}</p>' for t in lines)


def build(docs_dir: Path, repo: str) -> str:
    for stale in (docs_dir / "play" / "manifest.json",):
        stale.unlink(missing_ok=True)
    write_js(docs_dir)
    write_streams(docs_dir)
    write_voices(docs_dir)
    cards = "\n".join(
        f'<section class="card"><h2>{html.escape(title)}</h2><p class="note">{html.escape(note)}</p>'
        f'<prosotype-player data-sample="{sid}" src="play/data/{sid}.16a.prs" text="play/data/{sid}.16a.text.json">{fallback(sid)}</prosotype-player></section>'
        for sid, title, note, _ in SAMPLES)
    import base64
    inline = base64.b64encode((docs_dir / "play" / "data" / "statement.8b.prs").read_bytes()).decode()
    page = PAGE.format(cards=cards, repo=repo, inline=inline,
                       profiles="".join(f'<option value="{p}">{p}</option>' for p in STREAM_PROFILES),
                       voices="".join(f'<option value="play/voices/{v}.json">{html.escape(l)}</option>' for v, l in VOICES))
    (docs_dir / "play.html").write_text(page)
    return f"docs/play.html: {len(SAMPLES)} samples x {len(STREAM_PROFILES)} profiles, component + font {len(FONT_CHARS)} glyphs"
