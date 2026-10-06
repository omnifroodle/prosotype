# ProsoType prototype

Evidence for `../SPEC.md`. Python 3.12, managed with [uv](https://docs.astral.sh/uv/). Transcription needs Apple silicon (mlx-whisper); everything else runs anywhere.

## Setup

```bash
cd prototype
uv sync                       # pack, render, site, logo (exact versions from uv.lock)
uv run fetch.py               # font + pronouncing dictionary at pinned commits, checksum-verified
```

For transcription as well:

```bash
uv sync --extra transcribe
uv run fetch.py --models      # the two models at pinned revisions, about 4 GB, into ../.hf-cache/hub
brew install codec2           # optional: Codec 2 row in the size report
uv run fetch.py --synth       # optional: the speech synthesiser for synthesize.py, about 340 MB
```

`transcribe.py` sets `HF_HUB_CACHE` to `../.hf-cache/hub` itself, so the models stay on the project drive.

## Reproduce

```bash
uv run reproduce.py
```

This runs every check behind the spec:
- pinned inputs and their checksums
- the round-trip tests
- the conformance vectors, encoded with `pack.py` and decoded with the independent JS decoder in `../js/` (needs Node)
- a rebuild of the site and logo, which must match the committed `docs/`

If the source recordings are present, it also re-transcribes them and checks that the output equals `samples/recorded_three_ways.json`. The recordings are not published, so this step is skipped elsewhere.

## Run things individually

```bash
uv run pack.py check samples/party_three_ways.json
uv run pack.py encode samples/party_three_ways.json --profile 12b
uv run pack.py decode samples/party_three_ways.12b.prs
uv run render.py samples/party_three_ways.json -o samples/party_three_ways.html
uv run transcribe.py samples/flat.m4a samples/question.m4a samples/sarcastic.m4a -o samples/recorded_three_ways.json
uv run bitrate.py samples/recorded_three_ways.json samples/smoke/say_natural.json --json samples/bitrate_results.json
uv run redeliver.py samples/recorded_three_ways.json                  # recordings re-delivered per profile (needs the recordings)
uv run synthesize.py samples/recorded_three_ways.json --profile 16a 8b # speak a stream with no original audio
uv run timing_check.py synth                                         # phone timing vs known synthetic timing
uv run timing_check.py buckeye ../data/buckeye --unpack              # vs Buckeye hand labels (register at buckeyecorpus.osu.edu)
uv run timing_check.py buckeye ../data/buckeye --boundaries mfa      # the same, with forced-aligned boundaries
uv run voiceprofile.py build samples/recorded_three_ways.json --id me     # a private voice profile -> ../profiles/private/me.json
uv run transcribe.py IN.m4a --voice ../profiles/private/me.json           # transcribe with that pitch baseline
node ../js/speak.mjs ../docs/play/data/hand.16a.prs -o out.wav --voice ../profiles/reference-high.json
uv run make_vectors.py        # regenerate ../vectors after a deliberate format change
uv run site.py                # rebuild ../docs
uv run logo.py                # rebuild the logo files in ../docs/img
```

Recordings of one speaker should be transcribed together, so that they share speaker baselines.

The rendered pages are self-contained (with an embedded font subset) and have theme and greyscale toggles. Hover a glyph to see its measured and quantised values.

## Files

| File | What |
|---|---|
| `pack.py` | JSON ↔ packed stream, profiles 16a/16b/12a/12b/8a/8b (SPEC 3) |
| `test_pack.py` | Round-trip tests: the sample plus 400 random documents |
| `make_vectors.py` | Generates and checks the conformance vectors in `../vectors` |
| `render.py` | JSON → HTML, mappings A and B side by side |
| `transcribe.py` | Audio → JSON: Whisper words, wav2vec2 phones, CMUdict alignment, Praat pitch and intensity |
| `bitrate.py` | Size report: packed profiles vs text vs audio (PCM, Opus 6k, Codec 2 700C) |
| `redeliver.py` | Praat resynthesis: a stream's delivery imposed on the original recording (SPEC 9.4) |
| `synthesize.py` | FastSpeech 2 + HiFi-GAN: speak a stream with no original audio; its voice profile and calibration are in `../profiles/fastspeech2-ljspeech.json`; `--voice` and `--speaker` map pitch onto a target voice profile |
| `mfa.py` | Montreal Forced Aligner wrapper for `transcribe.py --aligner mfa` and `timing_check.py --boundaries mfa`; setup steps in its docstring |
| `timing_check.py` | Phone timing vs reference boundaries: synthesised speech now, Buckeye once downloaded; summaries in `samples/timing/` |
| `voiceprofile.py` | Builds and validates voice profiles (`../VOICE-PROFILE.md`, schema in `../profiles/schema/`) |
| `textmap.py` | Text maps: the character range of each word in the stream (SPEC 4.1) |
| `compare.py` | Builds `../docs/compare.html`, the synthesiser comparison (called by `site.py`) |
| `player.py` | Builds the reader `../docs/play.html`, the per-sample streams and text maps, and the component's font (called by `site.py`) |
| `site.py`, `logo.py` | Build the GitHub Pages site and logo in `../docs` |
| `fetch.py` | Pinned external inputs and model revisions |
| `reproduce.py` | Runs every check |
| `pyproject.toml`, `uv.lock` | Locked Python environment |
| `samples/party_three_ways.json` | Hand-written: one sentence, three deliveries |
| `samples/recorded_three_ways.json` | The owner's recordings (flat, question, sarcastic), with one shared speaker baseline |
| `samples/smoke/` | Synthetic `say` clips (smoke tests and sizes only) |
