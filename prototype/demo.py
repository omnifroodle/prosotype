#!/usr/bin/env python3
"""Demo: one reader, many voices (A Christmas Carol, Stave 1, LibriVox).

    demo.py prepare RAW.json            label voices -> samples/carol_stave1_humbug.json
    (site.py calls build() to write docs/carol.html)

prepare takes a transcription of the scene (transcribe.py --aligner heard) and the
hand-written voice attribution in samples/carol_stave1_humbug.voices.txt. It
matches the transcription's words to the attribution in order, assigns each
word a voice, and splits utterances wherever the voice changes. Each voice
becomes a speaker in the header, all sharing the reader's baseline, so the
register of each voice stays visible (a v1 form of SPEC 12 item 10, personas).
The attribution only says who speaks; every phone is as heard (SPEC 1).

The original audio is not in the repository: the page plays the excerpt from
archive.org, where LibriVox hosts it, with credit.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
from pathlib import Path

import numpy as np

import pack
import render
import textmap

HERE = Path(__file__).parent
SAMPLE = HERE / "samples" / "carol_stave1_humbug.json"
VOICES_TXT = HERE / "samples" / "carol_stave1_humbug.voices.txt"
VOICE_ORDER = ["narrator", "Scrooge", "Fred"]

CREDIT = {
    "work": "A Christmas Carol, Stave 1 (Charles Dickens, 1843)",
    "reader": "Jeff Robinson",
    "librivox": "https://librivox.org/a-christmas-carol-by-charles-dickens-3/",
    "audio": "https://archive.org/download/christmascarol_1012_librivox/christmascarol_01_dickens_64kb.mp3",
    "start_s": 397.0, "end_s": 479.2,
    "licence": "LibriVox recordings are in the public domain.",
}


def norm(w: str) -> str:
    return re.sub(r"[^a-z']", "", w.lower().replace("’", "'")).strip("'")


def attribution() -> list[tuple[str, str]]:
    """(voice, token) for every word of the attribution file, in order."""
    out = []
    for line in VOICES_TXT.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        voice, text = line.split(":", 1)
        out += [(voice.strip(), norm(t)) for t in text.split() if norm(t)]
    return out


def tidy(t: str) -> str:
    """Whisper writes nested quotes as "' ... '; show them as plain curly quotes."""
    t = re.sub(r'^"?\'', "“", t)
    t = re.sub(r"([,.?!;])'$", r"\1”", t)
    return t


def prepare(raw: dict) -> dict:
    words = [w for u in raw["utterances"] for w in u["words"]]
    att = attribution()
    sm = difflib.SequenceMatcher(a=[norm(w["text"]) for w in words], b=[t for _, t in att], autojunk=False)
    voice_of: dict[int, str] = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            voice_of[blk.a + k] = att[blk.b + k][0]
    # unmatched words take the voice of the nearest matched word before them (or after, at the start)
    last = next((voice_of[i] for i in range(len(words)) if i in voice_of), "narrator")
    for i in range(len(words)):
        last = voice_of.get(i, last)
        voice_of[i] = last
    spk = raw["speakers"]["S1"]
    doc = {k: v for k, v in raw.items() if k not in ("utterances", "speakers", "text")}
    doc["source"] = {**raw["source"], "audio": "(not in the repository; see original)", "original": CREDIT,
                     "voices": "speakers are voices of one reader, labelled by hand from the text "
                               "(samples/carol_stave1_humbug.voices.txt); all share the reader's baseline"}
    doc["speakers"] = {v: dict(spk) for v in VOICE_ORDER}
    utts: list[dict] = []
    for i, w in enumerate(words):
        v = voice_of[i]
        if not utts or utts[-1]["speaker"] != v:
            utts.append({"speaker": v, "label": v, "words": []})
        utts[-1]["words"].append({**{k: x for k, x in w.items() if k != "chars"}, "text": tidy(w["text"])})
    doc["utterances"] = utts
    return textmap.add_chars(doc)


def voice_stats(doc: dict) -> list[tuple[str, float, float, float, float, int]]:
    import transcribe as T

    f0 = doc["speakers"]["narrator"]["f0_median_hz"]
    rows, base = [], None
    for v in VOICE_ORDER:
        ps = [p for u in doc["utterances"] if u["speaker"] == v for w in u["words"] for p in w["phones"]]
        st = np.array([p["pitch_st"] for p in ps if p["pitch_st"] is not None])
        med = float(np.median(st))
        base = med if base is None else base
        vw = [p["dur_ms"] for p in ps if p["ipa"] in T.VOWELS]
        rows.append((v, f0 * 2 ** (med / 12), med - base, float(np.percentile(st, 90) - np.percentile(st, 10)),
                     float(np.median(vw)), len(ps)))
    return rows


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>One reader, many voices</title>
<meta name="description" content="A Christmas Carol, read by one LibriVox reader, transcribed into ProsoType with each character as a voice.">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<script type="module" src="js/prosotype-player.mjs"></script>
<style>
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#1b1b1f;--muted:#5f5f68;--rule:#e4e4df;--link:oklch(0.48 0.13 250);--spk-l:0.5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131316;--surface:#1b1b20;--ink:#ececf0;--muted:#a3a3ad;--rule:#2c2c33;--link:oklch(0.78 0.11 250);--spk-l:0.8;color-scheme:dark}}}}
.v300{{color:oklch(var(--spk-l) 0.13 300)}} .v80{{color:oklch(var(--spk-l) 0.13 80)}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 72px}}
a{{color:var(--link)}}
header{{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;margin-bottom:8px}}
header img{{height:44px;width:auto}}
h1{{font-size:26px;margin:0}} h2{{font-size:18px;margin:28px 0 8px}}
p{{max-width:70ch;margin:0 0 12px}}
.note{{font-size:14px;color:var(--muted)}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px 20px;margin-top:14px}}
audio{{width:100%;max-width:520px}}
.tablewrap{{overflow-x:auto}}
table{{border-collapse:collapse;font-size:15px;min-width:520px}}
th,td{{padding:6px 12px;border-bottom:1px solid var(--rule);text-align:left}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.swatch{{display:inline-block;width:.8em;height:.8em;border-radius:2px;margin-right:6px;vertical-align:-.05em}}
</style></head>
<body><main>
<header><a href="./"><img src="img/logo.svg" alt="ProsoType" width="200" height="44"></a><h1>One reader, many voices</h1></header>
<p>One person reads Scrooge, his nephew Fred and the narrator in the “Bah! Humbug!” scene from <em>A Christmas Carol</em>. The ProsoType transcription below was made automatically from the recording: phones as heard, with pitch, length and loudness measured from the audio. Only the voice labels were added by hand, from the text. Each voice is a speaker sharing the reader’s pitch baseline, so you can see the reader’s register move between characters: <span class="v300">Scrooge</span> and <span class="v80">Fred</span> are coloured, the narrator is in ink.</p>
<section class="card"><h2 style="margin-top:0">The recording</h2>
<audio controls preload="none" src="{audio}#t={start},{end}"></audio>
<p class="note" style="margin-top:8px">{work}, read by {reader} for <a href="{librivox}">LibriVox</a>. {licence} The excerpt plays from archive.org (6:37–7:59 of the stave).</p></section>
<section class="card"><h2 style="margin-top:0">The ProsoType stream</h2>
<prosotype-player src="demo/carol-humbug.16a.prs" text="demo/carol-humbug.16a.text.json" voices="play/voices/reference-low.json play/voices/reference-high.json play/voices/fastspeech2-ljspeech.json"></prosotype-player>
<p class="note" style="margin-top:8px">Play speaks the stream with the robotic reference synthesiser; each line has its own play button.</p></section>
<h2>How the reader voices them</h2>
<div class="tablewrap card"><table>
<thead><tr><th>Voice</th><th style="text-align:right">Median pitch</th><th style="text-align:right">vs narrator</th><th style="text-align:right">Pitch spread</th><th style="text-align:right">Median vowel</th><th style="text-align:right">Phones</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="note" style="margin-top:8px">Spread is the 10th to 90th percentile of phone pitch, in semitones. In this scene the reader lifts both characters above the narration: Scrooge, ranting, about 2 semitones up; Fred about 3 up, with twice the pitch movement of either. Both get shorter vowels than the narrator. Voices switch inside sentences (“…,” said Scrooge, “…”), which is why the transcription splits utterances at every change of voice.</p>
<h2>What this shows, and its limits</h2>
<p>A voice switch is visible in the transcription without any text: the height of the glyphs moves with the reader’s register. The voice labels themselves came from the book, though. Detecting who is speaking from the delivery alone is an open problem (SPEC §12, item 10). The recording is compressed MP3 at 22 kHz, and the transcription has recogniser errors.</p>
<p class="note">Transcription: <a href="{repo}/blob/main/prototype/samples/carol_stave1_humbug.json">samples/carol_stave1_humbug.json</a>, voice attribution <a href="{repo}/blob/main/prototype/samples/carol_stave1_humbug.voices.txt">.voices.txt</a>, built by <a href="{repo}/blob/main/prototype/demo.py">demo.py</a>.</p>
</main></body></html>
"""

HUES = {"Scrooge": 300, "Fred": 80}


def build(docs_dir: Path, repo: str) -> str:
    doc = json.loads(SAMPLE.read_text())
    out = docs_dir / "demo"
    out.mkdir(parents=True, exist_ok=True)
    prof = pack.PROFILES["16a"]
    (out / "carol-humbug.16a.prs").write_bytes(pack.to_bytes(pack.encode(doc, prof)))
    (out / "carol-humbug.16a.text.json").write_text(json.dumps(textmap.build(doc, prof), ensure_ascii=False) + "\n")
    rows = "".join(
        f'<tr><td>{"<span class=swatch style=\'background:oklch(var(--spk-l) 0.13 %d)\'></span>" % HUES[v] if v in HUES else "<span class=swatch style=background:var(--ink)></span>"}{html.escape(v)}</td>'
        f'<td class=num>{hz:.0f} Hz</td><td class=num>{d:+.1f} st</td><td class=num>{sp:.1f} st</td><td class=num>{vm:.0f} ms</td><td class=num>{n}</td></tr>'
        for v, hz, d, sp, vm, n in voice_stats(doc))
    c = CREDIT
    page = PAGE.format(audio=c["audio"], start=c["start_s"], end=c["end_s"], work=html.escape(c["work"]),
                       reader=html.escape(c["reader"]), librivox=c["librivox"], licence=html.escape(c["licence"]),
                       rows=rows, repo=repo)
    (docs_dir / "carol.html").write_text(page)
    return "docs/carol.html: A Christmas Carol demo, " + ", ".join(f"{v} {d:+.1f} st" for v, _, d, *_ in voice_stats(doc))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("raw")
    a = ap.parse_args()
    doc = prepare(json.loads(Path(a.raw).read_text()))
    SAMPLE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    n = {v: sum(1 for u in doc["utterances"] if u["speaker"] == v) for v in VOICE_ORDER}
    print(f"{SAMPLE.relative_to(HERE)}: {len(doc['utterances'])} utterances by voice {n}")
    for u in doc["utterances"][:8]:
        print(f"  {u['speaker']:9} {' '.join(w['text'] for w in u['words'])[:90]}")


if __name__ == "__main__":
    main()
