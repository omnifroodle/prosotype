# ProsoType voice profile specification

Version 0.2, draft, 2026-10-06. © 2026 Matt Overstreet, licensed under [CC BY 4.0](LICENSE-CC-BY-4.0.txt). Companion to [SPEC.md](SPEC.md); machine-readable schema in [`profiles/schema/`](profiles/schema).

## 1. What a voice profile is

A ProsoType stream records **what was said this time**: phones, and each phone's duration, pitch and loudness relative to the speaker (SPEC §2–3). A **voice profile** records **how a voice tends to sound and to say things**. Its uses:

- **Analysis.** A known speaker's profile fixes the pitch baseline, so stream levels mean the same thing across sessions (SPEC §10).
- **Synthesis.** A synthesiser takes from the profile whatever the stream leaves out: timbre, the timing inside a phone (how a stop divides into closure, burst and aspiration), fricative spectra, r-colouring.
- **Swapping.** Speaking a stream with a different profile changes the voice and keeps the delivery. This is also how privacy works: one profile is swapped for another, rather than leaving information out of profiles.

A profile should eventually carry as much vocal information as good resynthesis needs. The aim is reconstruction that feels right, not a perfect copy.

Accent is split between the two: phones as heard (a tap for "t", a dropped "r") travel in the stream, and finer habits (how much breath follows a "p") live in the profile.

## 2. Versioning

- The `prosotype_profile` field holds the version as `major.minor`. Tools write the version they implement.
- **Minor versions** only add: new optional blocks or fields, or new allowed values. They never change the meaning or unit of an existing field. A reader written for 0.2 must accept a 0.3 profile by ignoring what it does not know.
- **Major versions** may change or remove fields. While the major version is 0, a minor version may also do this, and the changelog (§8) must say so.
- **Unknown fields** must be ignored by readers and preserved by tools that rewrite a profile. Experimental fields from other producers use an `x_` prefix.
- **Every version has a JSON Schema,** `profiles/schema/voice-profile-MAJOR.MINOR.schema.json`. Check a profile with `cd prototype && uv run voiceprofile.py validate FILE.json`.
- **Each field has a stability level** (§3): *stable* (its meaning will not change before 1.0), *provisional* (it may be refined, with changelog notice), or *experimental* (it may be removed).

## 3. Structure

| Block | Field | Unit | Stability | Since | Notes |
|---|---|---|---|---|---|
| (top) | `prosotype_profile` | version | stable | 0.1 | |
| | `id` | string | stable | 0.1 | lower-case, `[a-z0-9._-]` |
| | `kind` | `person` or `synthetic` | stable | 0.1 | |
| | `private` | boolean | stable | 0.1 | default `true` for `person` |
| | `created`, `source` | date, object | provisional | 0.1 | `source`: amount of speech, phones, tool |
| `pitch` | `median_hz`, `p10_hz`, `p90_hz` | Hz | stable | 0.1 | over voiced phones |
| | `range_st` | semitones | stable | 0.1 | p90 − p10 |
| `loudness` | `vowel_mean_db`, `sd_db` | dB | provisional | 0.1 | session-relative; depends on gain |
| `timing` | `phones_per_s`, `median_phone_ms` | /s, ms | provisional | 0.1 | per class: vowel, stop, other consonant |
| `timbre` | `formants_hz`, `formant_tokens` | Hz, count | provisional | 0.1 | per vowel, median F1–F4 at vowel midpoints |
| | `formant_mean_hz`, `formant_dispersion_hz`, `vocal_tract_cm` | Hz, cm | provisional | 0.1 | apparent vocal-tract length, Fi ≈ (2i−1)/2 · ΔF, L = c/2ΔF |
| | `hnr_db`, `jitter_local`, `shimmer_local` | dB, ratio | provisional | 0.1 | Praat, on the continuous recording |
| | `spectral_tilt_db_per_octave` | dB/octave | provisional | 0.1 | long-term spectrum of voiced speech, 100–5000 Hz |
| `conditions` | `files[]` | codec, sample rate, bit rate, channels | provisional | 0.2 | from the audio files |
| | `device`, `environment` | text | provisional | 0.2 | supplied by the person recording |
| | `speech_level_dbfs`, `noise_floor_dbfs`, `snr_db` | dB | provisional | 0.2 | noise floor: quietest 10% of 50 ms frames outside phones |
| | `transcription` | text | provisional | 0.2 | which phone source the profile was built on |
| `articulation.stops` | `voiceless`, `voiced` → `vot_ms`, `closure_ms`, `tokens` | ms | provisional | 0.2 | stops before vowels; burst = sharpest rise in high-frequency energy in the later 70% of the stop; VOT = burst to the first of three regular glottal pulses |
| `articulation.fricatives` | `band_hz`; per fricative `cog_hz`, `tokens` | Hz | provisional | 0.2 | spectral centre of gravity above 1 kHz, middle 60% of each token |
| `articulation.rhotic` | `f3_hz`, `f3_drop_hz`, `tokens` | Hz | provisional | 0.2 | F3 in ɹ ɚ ɜ, and how far below other vowels' F3 it sits |
| `articulation.diphthongs` | per diphthong `delta_f1_hz`, `delta_f2_hz`, `tokens` | Hz | experimental | 0.2 | formant change from 25% to 75% of the vowel |
| `speaking.rhythm` | `percent_v`, `delta_c_ms`, `npvi_v` | %, ms, index | provisional | 0.2 | %V, ΔC and vocalic nPVI over each utterance |
| `speaking.pitch` | `declination_st_per_s`, `median_step_st` | st/s, st | provisional | 0.2 | slope of pitch over an utterance; pitch change between voiced phones |
| `speaking.phrase_final` | `lengthening_ratio`, `unpitched_share` | ratio | experimental | 0.2 | last vowel vs median vowel; share of final vowels with no pitch (creak, fade) |
| `pronunciation` | `phones_compared`, `match_share`, `substitutions{c→r: rate, count, of}` | | experimental | 0.2 | recognised vs dictionary phones; `null` for forced-aligned transcriptions |
| `embeddings` | | | experimental | 0.1 | reserved for learned speaker embeddings |
| `synth` | per synthesiser | | experimental | 0.1 | controls for one synthesiser, e.g. FastSpeech 2 calibration |

`tokens` fields count how many examples a value rests on, so consumers can decide whether to trust it.

## 4. Producing a profile

`prototype/voiceprofile.py build` takes recordings, or a transcript and its audio:

```bash
uv run voiceprofile.py build me-1.wav me-2.wav --id me --device "USB condenser" --environment "quiet room"
```

- **Amount of speech.** Many fields need it: stop timing wants about 20 or more voiceless stops before vowels, rhythm a few dozen syllables. A minute of natural speech is the practical minimum, and a reading script (§7) makes coverage predictable.
- **Heard phones only.** A profile describes the voice in the audio, so it is built from phones as heard: the recogniser, by default. Dictionary forced alignment (`--aligner mfa`, `--text`) replaces what was said with the dictionary's pronunciation, and would describe an accent-neutralised voice (SPEC §1, §7.1). `voiceprofile.py` refuses it without `--dictionary-phones`, which exists for experiments only.
- **Boundaries.** Articulation fields depend on phone boundaries. `voiceprofile.py` therefore defaults to `--aligner heard` when MFA is installed: the heard phones, re-timed by aligning exactly those phones with no dictionary. On Buckeye this puts 80% of onsets within 20 ms, against 65% for the recogniser alone (SPEC §9.5).
- **Conditions.** Several timbre fields shift with the channel: spectral tilt, HNR and fricative spectra all change with a compressed phone recording and its 8–12 kHz bandwidth. Record `device` and `environment`, and compare profiles only across similar conditions.

## 5. Using a profile to synthesise

A consumer uses what it can and falls back to its own defaults for the rest. The reference synthesiser (`js/synth.mjs`, SPEC §11) does this:

| Field | Used for | Needs | Default |
|---|---|---|---|
| `pitch.median_hz`, `range_st` | pitch level and range (with the speaker's profile) | | stream speaker's median |
| `timbre.vocal_tract_cm` | scales all formants | | 17.6 cm (its own table) |
| `timbre.formants_hz` | vowel formants directly | ≥ 3 tokens | scaled table |
| `timbre.hnr_db`, `jitter_local`, `shimmer_local`, `spectral_tilt_db_per_octave` | breathiness, roughness, source tilt | | moderate |
| `articulation.stops.*.vot_ms` | breath after a voiceless stop (spilling into the next vowel when the stop is short); voicing lag after a voiced stop. Only with the synthesiser's `stops: "profile"` option, which is under listening comparison before becoming the default | ≥ 10 tokens | 60 ms; 12 ms |
| `articulation.fricatives.s/ʃ.cog_hz` | main noise peak of s z ʃ ʒ tʃ dʒ | ≥ 3 tokens | 5500 Hz; 2700 Hz |
| `articulation.rhotic.f3_hz` | F3 of ɹ ɚ ɜ | ≥ 5 tokens | 1380 Hz; 1710 Hz |

Durations, pitch and loudness of each phone always come from the stream. The other `speaking` and `pronunciation` fields are recorded but not yet used in synthesis.

## 6. Privacy and handling

- **A profile of a real person is personal.** Treat it like a private key: keep it local and share it sparingly. Tools default `private` to `true` for `kind: person` and write such profiles under `profiles/private/` (git-ignored in this repository).
- **Never publish a profile with `private: true`.** The site build refuses to.
- **Open question:** whether a profile could be *usable for synthesis without being readable*, in the spirit of public/private keys. That would mean a "projected" voice that speaks as someone without exposing their measurements. The more a profile holds (especially embeddings), the more this matters.

### Known limits (candidates for 0.3)

- **Stop timing mixes stressed and unstressed syllables.** English aspirates p, t, k strongly only at the start of stressed syllables, so a sample full of "to" and "tonight" understates aspiration. Split `articulation.stops` by stress, using the dictionary's stress marks.
- **Conditions are recorded but not corrected for.** Normalising timbre fields for the channel (codec, bandwidth, microphone) is open.
- **Measurements depend on phone boundaries.** VOT now comes from glottal pulses rather than the pitch track, which had hidden short VOTs. It still relies on the burst falling inside the stop's span.

## 7. Recording for a profile

[`profiles/RECORDING.md`](profiles/RECORDING.md) is the recording script (version 0.1) with recording instructions. It has four parts: sound coverage sentences, deliveries (one sentence five ways, moving emphasis, phrasing pairs, trailing endings), a read passage, and free speech. The script's text only tells the speaker what to say. The profile is built from what the recording contains, transcribed from the audio. `prototype/script_coverage.py` checks the script's coverage. The current version has 81 voiceless stops before stressed vowels and 44 before unstressed ones, and every General American sound at least 5 times.

## 8. Changelog

- **0.2** (2026-10-06):
  - Added `conditions`, `articulation` (stops, fricatives, rhotic, diphthongs), `speaking` (rhythm, pitch habits, phrase endings) and `pronunciation`.
  - Added the JSON Schema and the `validate` command.
  - The reference synthesiser uses stop timing, fricative centre of gravity and rhotic F3.
- **0.1** (2026-10-06): first version: `pitch`, `loudness`, `timing`, `timbre` (formants with token counts, vocal-tract length, HNR, jitter, shimmer, tilt), with `embeddings` and `synth` reserved.
