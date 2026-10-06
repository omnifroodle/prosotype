"""Build the browser player (docs/play.html) for the GitHub Pages site.

Called by site.py. For each sample and stream profile it writes the packed
stream (.prs), and puts its text map (textmap.py) and a mapping B rendering
with highlight indices (render.py) into docs/play/manifest.json. The page
decodes the stream in the browser (js/prosotype.mjs), speaks it with the
reference synthesiser (js/synth.mjs) in a chosen voice profile, and highlights
each glyph and word as it is spoken. Only public (synthetic) voice profiles
are published; a viewer can load their own profile from disk, and it stays
in their browser.
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

SAMPLES = [
    ("hand", "Hand-written: one sentence, three deliveries", "samples/party_three_ways.json"),
    ("recorded", "Recorded: the owner's three takes (transcription only)", "samples/recorded_three_ways.json"),
    ("story", "Synthetic speech: a 26-second story (macOS say)", "samples/smoke/say_natural.json"),
]
STREAM_PROFILES = ["16a", "12b", "8b"]
VOICES = [  # (id, label); None = the stream speaker's own pitch with the reference vocal tract
    (None, "Speaker's own pitch, reference voice"),
    ("reference-low", "Reference low voice (hand-defined)"),
    ("reference-high", "Reference high voice (hand-defined)"),
    ("fastspeech2-ljspeech", "FastSpeech 2 voice, measured profile"),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProsoType player</title>
<meta name="description" content="Play ProsoType streams with the reference synthesiser, highlighting each phone and word as it is spoken.">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<style>
{fontface}
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#1b1b1f;--muted:#5f5f68;--unvoiced:#6c6c74;--rule:#e4e4df;--guide:#c9c9c2;
--link:oklch(0.48 0.13 250);--hl:oklch(0.9 0.08 85);--hl-ink:#1b1b1f;--spk-l:0.5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131316;--surface:#1b1b20;--ink:#ececf0;--muted:#a3a3ad;--unvoiced:#9a9aa3;
--rule:#2c2c33;--guide:#4a4a53;--link:oklch(0.78 0.11 250);--hl:oklch(0.45 0.09 85);--hl-ink:#fff;--spk-l:0.8;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 72px}}
a{{color:var(--link)}}
header{{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;margin-bottom:8px}}
header img{{height:44px;width:auto}}
h1{{font-size:24px;margin:0}}
p{{max-width:68ch;margin:0 0 12px}}
.note{{font-size:14px;color:var(--muted)}}
.controls{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0}}
label{{display:grid;gap:4px;font-size:13px;color:var(--muted);min-width:0}}
select,input[type=file]{{width:100%;min-width:0}}
select,input[type=file],button{{font:inherit;font-size:15px;color:var(--ink);background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:8px 10px}}
button{{cursor:pointer;font-weight:600}}
button.primary{{background:var(--ink);color:var(--bg);border-color:var(--ink);min-width:110px}}
.bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px 20px;margin-top:16px}}
.card h2{{font-size:13px;font-weight:600;color:var(--muted);margin:0 0 6px;text-transform:uppercase;letter-spacing:.04em}}
.ipa{{font-family:'ProsoType IPA',sans-serif;font-size:clamp(24px,4vw,34px);line-height:2.3;overflow-wrap:anywhere}}
.utt{{margin:0 0 4px}}
.w{{white-space:nowrap;border-radius:4px}}
.p{{display:inline-block;font-family:'ProsoType IPA',sans-serif;border-radius:3px;transition:background .06s}}
.pause{{display:inline-block;height:.9em;vertical-align:middle;border-left:2px solid var(--rule);border-right:2px solid var(--rule)}}
.p.now{{background:var(--hl);color:var(--hl-ink)}}
.text{{font-size:20px;line-height:1.7;white-space:pre-wrap}}
.text span{{border-radius:4px;padding:0 1px}}
.text span.now{{background:var(--hl);color:var(--hl-ink)}}
#status{{font-size:14px;color:var(--muted)}}
{levelcss}
.mapB .w{{background:linear-gradient(to bottom,transparent calc(78.5% - 1px),var(--guide) calc(78.5% - 1px),var(--guide) 78.5%,transparent 78.5%)}}
</style></head>
<body><main>
<header><a href="./"><img src="img/logo.svg" alt="ProsoType" width="200" height="44"></a><h1>Player</h1></header>
<p>Plays a packed ProsoType stream with the <strong>reference synthesiser</strong>: a small formant synthesiser that speaks every phone with exactly the duration, pitch and loudness in the stream. It sounds robotic on purpose. A <strong>voice profile</strong> sets its pitch level and vocal-tract length, and voice qualities such as breathiness. The stream is decoded and spoken in your browser; nothing is sent anywhere.</p>
<div class="controls">
<label>Sample<select id="sample"></select></label>
<label>Stream profile<select id="profile"></select></label>
<label>Voice<select id="voice"></select></label>
<label>Your own voice profile (stays on this device)<input type="file" id="ownvoice" accept="application/json,.json"></label>
</div>
<div class="bar"><button class="primary" id="play">Play</button><span id="status"></span></div>
<section class="card"><h2>Text</h2><div class="text" id="text"></div></section>
<section class="card"><h2>ProsoType, mapping B</h2><div class="ipa mapB" id="ipa" lang="und-fonipa"></div></section>
<p class="note" style="margin-top:18px">Highlighting follows the audio clock: each glyph lights while its phone sounds, each word while any of its phones does. Profiles: <a href="{repo}/blob/main/SPEC.md">SPEC §10–11</a>. Source: <a href="{repo}/tree/main/js">js/</a>.</p>
</main>
<script type="module">
import {{ decode }} from "./js/prosotype.mjs";
import {{ synthesize }} from "./js/synth.mjs";

const $ = (id) => document.getElementById(id);
const manifest = await (await fetch("play/manifest.json")).json();
const voices = Object.fromEntries(await Promise.all(manifest.voices.filter((v) => v.file)
  .map(async (v) => [v.id, await (await fetch(v.file)).json()])));
let ownVoice = null, ctx = null, source = null, timer = 0;

for (const s of manifest.samples) $("sample").add(new Option(s.title, s.id));
for (const p of manifest.profiles) $("profile").add(new Option(p, p));
for (const v of manifest.voices) $("voice").add(new Option(v.label, v.id ?? ""));

const current = () => manifest.samples.find((s) => s.id === $("sample").value).streams[$("profile").value];

function show() {{
  stop();
  const st = current();
  $("ipa").innerHTML = st.ipa_html;
  const tm = st.text, frag = [];
  let last = 0, w = 0;
  tm.utterances.forEach((u) => u.forEach(([a, b]) => {{
    frag.push(esc(tm.text.slice(last, a)), `<span data-w="${{w++}}">${{esc(tm.text.slice(a, b))}}</span>`);
    last = b;
  }}));
  frag.push(esc(tm.text.slice(last)));
  $("text").innerHTML = frag.join("");
  $("status").textContent = `${{st.bytes}} bytes, ${{st.symbols}} symbols`;
}}
const esc = (s) => s.replace(/[&<>]/g, (c) => ({{"&": "&amp;", "<": "&lt;", ">": "&gt;"}})[c]);

function stop() {{
  clearTimeout(timer);
  if (source) {{ try {{ source.stop(); }} catch {{}} source = null; }}
  document.querySelectorAll(".now").forEach((e) => e.classList.remove("now"));
  $("play").textContent = "Play";
}}

async function play() {{
  if (source) return stop();
  const st = current();
  const bytes = new Uint8Array(await (await fetch(st.prs)).arrayBuffer());
  const doc = decode(bytes);
  const vid = $("voice").value;
  const voice = vid === "own" ? ownVoice : (vid ? voices[vid] : null);
  const res = synthesize(doc, {{ voice }});
  ctx ??= new AudioContext();
  const buf = ctx.createBuffer(1, res.samples.length, res.sampleRate);
  buf.copyToChannel(res.samples, 0);
  source = ctx.createBufferSource();
  source.buffer = buf;
  source.connect(ctx.destination);
  const t0 = ctx.currentTime + 0.05;
  source.start(t0);
  source.onended = stop;
  $("play").textContent = "Stop";
  // global word index per (utterance, word): words are counted in stream order
  const base = []; let n = 0;
  doc.utterances.forEach((u, i) => {{ base[i] = n; n += u.words.length; }});
  const glyphs = [...$("ipa").querySelectorAll("[data-i]")];
  const words = [...$("text").querySelectorAll("[data-w]")];
  const ipaWords = [...$("ipa").querySelectorAll("[data-w]")];
  // Each update is scheduled for the next phone boundary on the audio clock,
  // so highlighting does not depend on the display's frame rate.
  let k = 0, lit = null;
  const tick = () => {{
    const t = ctx.currentTime - t0;
    while (k < res.phones.length && res.phones[k].end <= t) k++;
    const p = res.phones[k];
    const on = p && t >= p.start ? p : null;
    if (on !== lit) {{
      document.querySelectorAll(".now").forEach((e) => e.classList.remove("now"));
      if (on) {{
        glyphs[on.index]?.classList.add("now");
        words[base[on.utt] + on.word]?.classList.add("now");
      }}
      lit = on;
    }}
    if (!source || !p) return;
    const next = on ? p.end : p.start;
    timer = setTimeout(tick, Math.max(1, (next - (ctx.currentTime - t0)) * 1000));
  }};
  tick();
}}

$("ownvoice").addEventListener("change", async (e) => {{
  const f = e.target.files[0];
  if (!f) return;
  try {{
    ownVoice = JSON.parse(await f.text());
    let opt = [...$("voice").options].find((o) => o.value === "own");
    if (!opt) {{ opt = new Option("", "own"); $("voice").add(opt); }}
    opt.text = `Your profile: ${{ownVoice.id ?? f.name}}`;
    $("voice").value = "own";
  }} catch {{ $("status").textContent = "That file is not a voice profile (JSON)."; }}
}});
$("sample").onchange = show; $("profile").onchange = show; $("voice").onchange = stop;
$("play").onclick = play;
show();
</script>
</body></html>
"""


def build(docs_dir: Path, repo: str) -> str:
    out = docs_dir / "play"
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "voices").mkdir(exist_ok=True)
    js = docs_dir / "js"
    js.mkdir(exist_ok=True)
    for f in ("prosotype.mjs", "synth.mjs"):
        shutil.copyfile(ROOT / "js" / f, js / f)

    chars: set[str] = set()
    samples = []
    for sid, title, path in SAMPLES:
        doc = textmap.add_chars(json.loads((HERE / path).read_text()))
        streams = {}
        for name in STREAM_PROFILES:
            prof = pack.PROFILES[name]
            enc = pack.encode(doc, prof)
            data = pack.to_bytes(enc)
            (out / "data" / f"{sid}.{name}.prs").write_bytes(data)
            dec = pack.decode(pack.from_bytes(data))
            counter = [0, 0]
            utts = "".join(f'<div class="utt">{render.utterance_html(u, "B", 0, counter)}</div>' for u in dec["utterances"])
            chars |= {c for u in dec["utterances"] for w in u["words"] for p in w["phones"] for c in p["ipa"]}
            streams[name] = {"prs": f"play/data/{sid}.{name}.prs", "bytes": len(data), "symbols": len(enc.symbols),
                             "text": textmap.build(doc, prof), "ipa_html": utts}
        samples.append({"id": sid, "title": title, "streams": streams})

    voices = []
    for vid, label in VOICES:
        entry = {"id": vid, "label": label}
        if vid:
            src = ROOT / "profiles" / f"{vid}.json"
            prof = json.loads(src.read_text())
            assert not prof.get("private"), f"{vid} is private and must not be published"
            shutil.copyfile(src, out / "voices" / f"{vid}.json")
            entry["file"] = f"play/voices/{vid}.json"
        voices.append(entry)

    manifest = {"samples": samples, "profiles": STREAM_PROFILES, "voices": voices}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    levelcss, _ = render.css()
    page = PAGE.format(fontface=render.font_face("".join(sorted(chars))), levelcss=levelcss, repo=repo)
    (docs_dir / "play.html").write_text(page)
    return f"docs/play.html: {len(page.encode()) / 1024:.0f} KB, {len(samples)} samples x {len(STREAM_PROFILES)} profiles"
