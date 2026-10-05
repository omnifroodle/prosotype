# ProsoType: handoff plan for the viability phase

ProsoType was developed under the working name Shadowcat; the local folder keeps that name.

This document is self-contained. It is written for a model (or person) picking the project up with no access to the conversation that produced it.

## 1. What ProsoType is

An old idea being revived. The way speech is written down still reflects the limits of old printing technology. ProsoType proposes:

1. Write speech in the International Phonetic Alphabet (IPA) instead of Latin orthography.
2. Use modern displays and printing to encode delivery (pitch, duration, loudness, possibly more) into each glyph through size, colour and weight, in a standard way, so a trained reader can read the text as it was spoken.
3. Build a transcription service that converts spoken audio into this format.

Original motivations: extreme compression of spoken audio, and richer information for readers who are deaf or have limited access to audio. The owner has further uses in mind and will describe them once this phase shows whether the idea is technically viable.

## 2. Decisions already made by the owner (do not reopen)

- **Spec first.** The main deliverable is a written specification, backed by a small prototype that produces evidence.
- **Readability is acknowledged and ignored for now.** The owner knows that fluent human reading of IPA is a likely dead end for the format as it stands, and has later work in mind that may fix it. Do not solve it, test it, design around it, or add an orthography view. Mention it once in the spec as a known limitation deferred to later work.
- **The compression idea is a fixed-width packed symbol.** One symbol per phone. About 6 bits identify the phone (64 codes are enough for one language), and the remaining bits in the symbol carry delivery information. The claim "smaller than text" is about this raw fixed-width encoding: speech has fewer phones than letters, so phone plus delivery can fit in the space text would use. Measuring this honestly is a goal of the phase.
- **The owner's proposed visual mapping** is pitch, duration and so on shown through glyph size, colour and weight. It must be one of the mappings prototyped (mapping A below).

## 3. State of the project

- Folder: `/Volumes/External/shadowcat`. Empty apart from this file. Not a git repository.
- Machine: macOS, fish shell.
- **Nothing has been built or run.** Installed tooling (Python version, uv, ffmpeg, espeak-ng, GPU/MPS support) has not been checked. Check it first.
- Model downloads and package installs are large; tell the owner what will be downloaded before doing it.

## 4. Claims that are unverified

Everything below came from memory during planning. Verify each before it goes into the spec as fact.

- Tool names and suitability: wav2vec2 phoneme models (e.g. `facebook/wav2vec2-lv-60-espeak-cv-ft`), Allosaurus, WhisperX, Montreal Forced Aligner, parselmouth (Praat), pYIN.
- Noto Sans being a variable font with weight and width axes and full IPA coverage.
- English averages: about 3.5 phones per word, about 5.6 characters per word including the space, about 12 phones per second.
- Lowest conventional speech codecs being around 700 bits/s.
- Phones + pitch + duration + energy being the input of FastSpeech 2 style synthesisers (relevant to later resynthesis, not built in this phase).
- Prior art on prosodic typography (Rosenberger's Prosodic Font, WaveFont, caption studies with deaf and hard-of-hearing viewers).

## 5. Deliverables

### 5.1 `SPEC.md`

Sections:

1. Goals, non-goals, intended consumers (human readers of several kinds, and machines).
2. Data model.
3. Packed symbol stream.
4. JSON form.
5. Standard visual mapping.
6. Accessibility constraints: colour-blind safety, minimum size and weight, a monochrome print fallback.
7. Transcription pipeline architecture and expected error sources.
8. Known limitations and open questions (readability goes here, one paragraph, deferred).
9. Findings (written last, see 5.3).

#### Data model

- Stream > utterance (one speaker turn) > word > phone.
- Per phone: IPA symbol, start time, duration, voiced or not, pitch (semitones relative to the speaker's median pitch), loudness (dB relative to the speaker's mean).
- Per word: orthographic form (kept in JSON for debugging only; not part of the packed stream).
- Per utterance: speaker id.
- Stream header: language / phone table id, symbol width, per-speaker baselines (median pitch in Hz, mean loudness).

#### Packed symbol stream (starting proposal, to be refined in the spec)

16-bit symbol:

| Field | Bits | Starting quantisation |
|---|---|---|
| Phone | 6 | Index into a per-language table. English: about 40 to 44 phones plus reserved codes. |
| Pitch | 4 | 0 = unvoiced. 1 to 15 = -10.5 to +10.5 semitones from speaker median in 1.5 semitone steps (8 = median). |
| Duration | 3 | Log scale, roughly 30, 45, 65, 95, 140, 200, 300, 450+ ms. |
| Loudness | 3 | -12 to +9 dB from speaker mean in 3 dB steps. |

Reserved phone codes: word boundary, pause, speaker change, escape (for phones outside the table).

Also define and measure:

- 12-bit variant (suggested 6 phone, 3 pitch, 2 duration, 1 loudness).
- 8-bit variant (6 phone, 2 delivery; decide what the 2 bits best carry).

**Open design question that affects the headline number: word boundaries.** Two options, measure both:

- (a) A boundary symbol between words, whose delivery bits carry pause length (0 = no pause). Costs one extra symbol per word.
- (b) A word-start flag bit taken from the delivery bits. No extra symbols, one bit less delivery.

Planning estimates of bytes per word for English (to be replaced by measurements):

| Symbol width | Option (b), about 3.5 symbols/word | Option (a), about 4.5 symbols/word |
|---|---|---|
| 16-bit | 7.0 | 9.0 |
| 12-bit | 5.25 | 6.75 |
| 8-bit | 3.5 | 4.5 |

Reference: the same word as text is about 5.6 bytes in ASCII/UTF-8 and about 11.2 in UTF-16.

Also evaluate in the spec (discussion only, no build required): mapping the 16-bit symbol space onto a Unicode private-use plane so the stream can live in ordinary text files, at 4 bytes per symbol in UTF-8.

#### JSON form

Human-readable, holds the unquantised measurements plus everything in the data model. Converting JSON to packed and back must be lossless at the quantised resolution.

#### Standard visual mapping

A table from delivery feature to visual variable, with the quantisation levels. Two candidates, IPA glyphs only:

- **A (owner's proposal):** pitch = colour, duration = glyph size, loudness = weight.
- **B:** pitch = vertical offset from the baseline, duration = glyph width or spacing, loudness = weight, colour reserved for speaker or voice quality.

The spec records both and, after the prototype, recommends one with reasons.

### 5.2 `prototype/` (Python)

| File | Purpose |
|---|---|
| `pack.py` | JSON to packed stream and back, for the 8, 12 and 16-bit variants and both word-boundary options. |
| `render.py` | JSON to one self-contained HTML page showing mappings A and B side by side in IPA. Uses a variable font with IPA coverage, embedded or subset so the page works offline. Must work in light and dark themes. |
| `transcribe.py` | Audio file to JSON. |
| `bitrate.py` | Size report (see below). |
| `samples/` | Short audio clips plus one hand-written JSON sample. |
| `README.md` | Setup and run instructions. |

`transcribe.py` pipeline, preferred route:

1. Word-level transcript with timestamps from a Whisper-family model.
2. Phones as actually spoken from a phoneme recognition model with frame timings, assigned to words using the word timestamps.
3. Pitch and intensity from parselmouth; per phone, take the median over voiced frames in the phone's span.
4. Normalise to the speaker's baselines; emit JSON.

Fallback if step 2 is too inaccurate: dictionary pronunciation plus forced alignment (gives canonical rather than as-spoken phones; record this loss in the findings).

`bitrate.py` reports, for each sample:

- bytes per word and bits per second for each packed variant and boundary option,
- the transcript as ASCII/UTF-8 and UTF-16,
- all of the above both raw and after a general-purpose compressor (zlib and one stronger, e.g. xz or zstd),
- the source audio size, and the same audio at a low-bitrate speech codec setting if one is available.

Samples needed: one sentence delivered three ways (flat statement, question, sarcastic or strongly emphatic), plus about 30 to 60 seconds of natural speech. Ask the owner for recordings. The macOS `say` command is acceptable for smoke tests only; its prosody is synthetic.

### 5.3 Findings (final section of `SPEC.md`)

- Measured sizes against text and audio, raw and compressed.
- Transcription errors observed, by type.
- Which visual mapping separates the three deliveries most clearly, with screenshots.
- A go / adjust / stop recommendation on the technical questions only: transcription quality, encoding size, rendering.

## 6. Order of work

1. Check the environment; report what needs installing.
2. Verify the claims in section 4.
3. Draft `SPEC.md` sections 1 to 5.
4. Hand-write a JSON sample; build `pack.py` and `render.py` against it.
5. Build `transcribe.py`; run it on the samples.
6. Build `bitrate.py`; record the numbers.
7. Finish `SPEC.md` sections 6 to 9.

Steps 3 and 4 need no audio tooling and no downloads.

## 7. Verification

- `pack.py`: JSON to packed to JSON round trip is identical at quantised resolution, for every variant.
- `render.py`: open the page in a browser. The three deliveries of the same sentence are visibly different under both mappings; the page is legible in light, dark and greyscale.
- `transcribe.py`: spot-check phones and timings against the audio by ear; the question clip shows rising pitch at the end.
- `bitrate.py`: output matches hand calculation on the hand-written sample.

## 8. Out of scope for this phase

- Human readability of IPA, reading tests, orthography views.
- Resynthesis of audio from the format.
- Languages other than English, tone languages, multi-speaker overlap.
- A hosted service; `transcribe.py` is a local script.
