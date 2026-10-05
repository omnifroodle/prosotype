# ProsoType prototype

Evidence for `../SPEC.md`. macOS, Python 3.12 via uv.

## Setup

```bash
cd prototype
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python fonttools brotli
curl -sSfL -o fonts/NotoSans-VF.ttf 'https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf'
```

`pack.py` needs only the standard library. `render.py` needs fontTools, brotli and the font.

## Run

```bash
.venv/bin/python pack.py check samples/party_three_ways.json
.venv/bin/python test_pack.py
.venv/bin/python pack.py encode samples/party_three_ways.json --profile 12b
.venv/bin/python pack.py decode samples/party_three_ways.12b.prs
.venv/bin/python render.py samples/party_three_ways.json -o samples/party_three_ways.html
```

The rendered page is self-contained (font subset embedded) and has theme and greyscale toggles. Hover a glyph to see its measured and quantised values.

## Files

| File | Status |
|---|---|
| `pack.py` | JSON ↔ packed stream, profiles 16a/16b/12a/12b/8a/8b |
| `test_pack.py` | Round-trip tests (sample + 400 random documents) |
| `render.py` | JSON → HTML, mappings A and B side by side |
| `transcribe.py` | Audio → JSON (Whisper words, wav2vec2 phones, CMUdict alignment, Praat pitch/intensity) |
| `bitrate.py` | Size report: packed profiles vs text vs audio (PCM, Opus 6k, Codec 2 700C) |
| `samples/party_three_ways.json` | Hand-written: one sentence, three deliveries |
| `samples/recorded_three_ways.json` | Owner's recordings (flat, question, sarcastic), one shared speaker baseline |
| `samples/smoke/` | Synthetic `say` clips (smoke tests and sizes only) |
| `data/cmudict.dict` | CMU pronouncing dictionary, for word alignment |

## Transcription

```bash
uv pip install --python .venv/bin/python praat-parselmouth torch transformers mlx-whisper soundfile
brew install codec2
curl -sSfL -o data/cmudict.dict https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict
```

The models (about 4 GB) download on first use into `../.hf-cache/hub` on the project drive, not `~/.cache`; `transcribe.py` sets `HF_HUB_CACHE` itself.

Recordings of one speaker should be transcribed together so they share speaker baselines:

```bash
.venv/bin/python transcribe.py samples/flat.m4a samples/question.m4a samples/sarcastic.m4a -o samples/recorded_three_ways.json
.venv/bin/python render.py samples/recorded_three_ways.json -o samples/recorded_three_ways.html
.venv/bin/python bitrate.py samples/recorded_three_ways.json --json samples/bitrate_results.json
```
