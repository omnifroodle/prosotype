# ProsoType specification

Draft 0.3, 2026-10-05. © 2026 Matt Overstreet, licensed under [CC BY 4.0](LICENSE-CC-BY-4.0.txt). All sections drafted. Section 9 records what the prototype measured on the owner's recordings and a synthetic clip. The packed stream (section 3, container version 1) is stable: section 3.10 gives its exact rules and `vectors/` holds conformance test vectors. Facts taken from outside the project are listed with their sources in Appendix A; anything not listed there is a design decision of this document.

## 1. Goals, non-goals, consumers

### Goals

1. Write speech as a sequence of IPA phones, each carrying a small, fixed amount of delivery information (pitch, duration, loudness), in a standard way.
2. Define a compact fixed-width binary form (one symbol per phone) and measure honestly whether phone plus delivery fits in less space than the same speech written as text.
3. Define a standard visual mapping from delivery to glyph appearance, so the same stream always looks the same.
4. Show that a local transcription pipeline can produce the format from ordinary recordings with useful accuracy.

### Positioning

Each part of ProsoType has precedent: Bolinger's height-based intonation notation, caption typography that maps loudness to weight, phonetic vocoders that send one symbol per speech unit with its pitch, duration and power, and intonation alphabets like INTSINT. What ProsoType adds is the combination, as a single open standard: phone-level IPA with delivery on every phone, a normative fixed-width stream, a standard rendering and automatic transcription. See Appendix B.

### Non-goals for this phase

- Fluent human reading of IPA (see section 8).
- Resynthesising audio from the format.
- Languages other than English, tone languages, overlapping speakers.
- A hosted service.

### Intended consumers

| Consumer | Uses |
|---|---|
| Readers who are deaf or hard of hearing | The rendered form: what was said and how it was said. |
| Readers with limited access to audio (noisy, silent or bandwidth-poor settings) | The rendered form, or the packed stream decoded locally. |
| Researchers and annotators | The JSON form, which keeps unquantised measurements. |
| Machines (search, analysis, later resynthesis) | The packed stream or JSON. Phones with pitch, duration and energy are the inputs a FastSpeech 2 style synthesiser conditions on (Appendix A), so the format is a plausible resynthesis input later. |

## 2. Data model

```
Stream
 ├─ header: language, phone table id, symbol profile, speakers[]
 │           speaker: id, median pitch (Hz), mean loudness (dB)
 └─ utterances[]            one speaker turn
     ├─ speaker id
     └─ words[]
         ├─ orthographic form   (JSON only, for debugging; not in the packed stream)
         ├─ start, end
         └─ phones[]
             ├─ IPA symbol
             ├─ start time, duration (ms)
             ├─ voiced (bool)
             ├─ pitch: semitones relative to the speaker's median pitch; absent if unvoiced or untracked
             └─ loudness: dB relative to the speaker's mean loudness
```

Rules:

- Pitch in semitones is `12 * log2(f0 / speaker_median_f0)`. A phone's pitch is the median over the voiced pitch frames inside the phone's span.
- Loudness is the phone's mean intensity in dB minus the speaker's mean vowel intensity (so a typical vowel is 0 dB).
- Times inside a word are contiguous: a phone starts where the previous one ended. Silence is represented only between words (pauses), never inside a word.
- Stress and length are not separate fields. They are carried by delivery (duration, pitch, loudness). IPA stress and length marks are stripped when phones are looked up in the phone table.

## 3. Packed symbol stream

### 3.1 Symbol layout

Every symbol has the same width *W* (8, 12 or 16 bits). The top 6 bits are the **code**. The remaining *W*−6 bits are the **payload**.

```
 MSB                                         LSB
 [ code: 6 ][ payload: W-6                     ]
```

- For a phone code, the payload holds delivery fields in the order `flag | pitch | duration | loudness`, most significant first. Any field may have zero width.
- For a reserved code, the whole payload is that code's argument.
- Symbols are concatenated into a big-endian bit stream with no padding between them. If the stream does not end on a byte boundary, it is padded with zero bits. The header records the symbol count, so padding is never read as a symbol.

### 3.2 Reserved codes

| Code | Name | Payload |
|---|---|---|
| 0 | PAD | ignored |
| 1 | WORD | pause before the next word (profiles *a* only), see 3.5 |
| 2 | PAUSE | pause length, see 3.5 |
| 3 | TURN | speaker index into the header's speaker list. Starts every utterance. |
| 4 | ESC | 0 (unused). The next symbol is a phone from the header's extension table: its code field is an index into that table and its payload is the phone's delivery. |
| 5–7 | | reserved |
| 63 | | reserved (keeps the 16-bit space mappable onto one Unicode private-use plane, see 3.8) |

### 3.3 Phone table `en-1`

Codes 8 to 62, in the order listed (p = 8, b = 9, … ʊə = 62). 55 phones, enough for General American and Southern British English in the broad-to-moderately-narrow detail that a phone recogniser produces. Anything else goes through ESC.

**Voiceless phones:** p t k ʔ f θ s ʃ h tʃ. Every other phone in the table, and every extension phone, counts as voiced. Voicing is only used when decoding profiles whose pitch field cannot say "unvoiced" (3.10).

| Codes | Phones |
|---|---|
| 8–33 consonants | p b t d k ɡ ʔ ɾ f v θ ð s z ʃ ʒ h tʃ dʒ m n ŋ l ɹ w j |
| 34–36 syllabic | n̩ l̩ m̩ |
| 37–53 monophthongs | i ɪ e ɛ æ a ɑ ɒ ɔ o ʊ u ʌ ə ɚ ɜ ɐ |
| 54–62 diphthongs | eɪ aɪ ɔɪ aʊ oʊ əʊ ɪə ɛə ʊə |

Folded before lookup: length and stress marks (ː ˑ ˈ ˌ) are removed; `g→ɡ`, `r→ɹ`, `ɫ→l`, `ɝ→ɚ`, `ᵻ→ɪ`, `ɹ̩→ɚ`, `ʧ/t͡ʃ→tʃ`, `ʤ/d͡ʒ→dʒ`. This table is a starting point. It will be revised after seeing which phones the recogniser actually emits (section 9).

### 3.4 Profiles and quantisation

A **profile** fixes the symbol width and the word-boundary option. Six profiles are defined. `16a` is the reference profile, and the standard visual mapping (section 5) shows its levels.

| Profile | Width | Boundary | Flag | Pitch | Duration | Loudness |
|---|---|---|---|---|---|---|
| 16a | 16 | WORD symbol | – | 4 | 3 | 3 |
| 16b | 16 | start flag | 1 | 4 | 3 | 2 |
| 12a | 12 | WORD symbol | – | 3 | 2 | 1 |
| 12b | 12 | start flag | 1 | 3 | 2 | – |
| 8a | 8 | WORD symbol | – | 2 | – | – |
| 8b | 8 | start flag | 1 | 1 | – | – |

In the *b* profiles, the flag bit comes out of the least valuable field. For loudness, which is partly redundant with pitch and the weakest perceptual cue of the three, that is loudness first and then duration. Pitch keeps its bits because intonation (statement versus question) is the delivery feature most often lost in text.

**Pitch**, in semitones from the speaker's median:

| Bits | Levels | Meaning |
|---|---|---|
| 4 | 0 = unvoiced or untracked; 1–15 = (level−8) × 1.5 st, so −10.5 to +10.5, 8 = median | |
| 3 | 0 = unvoiced; 1–7 = (level−4) × 3 st, so −9 to +9 | |
| 2 | 0 = unvoiced; 1–3 = −4, 0, +4 st (boundaries at ±2) | low / mid / high |
| 1 | 1 = more than 2 st above median, 0 = anything else | prominence only; voicing then comes from the phone table |

Values outside the range are clipped to the end levels.

**Duration**, nearest level on a log scale:

| Bits | Level centres (ms) |
|---|---|
| 3 | 30, 45, 65, 95, 140, 200, 300, 450 |
| 2 | 45, 95, 200, 450 |

**Loudness**, in dB from the speaker's mean:

| Bits | Levels |
|---|---|
| 3 | −12 to +9 in 3 dB steps (level 4 = 0 dB) |
| 2 | −12, −6, 0, +6 |
| 1 | 1 = more than 3 dB above mean ("loud"), 0 = otherwise |

Decoding returns each level's centre value. Quantising a centre value again gives the same level, which is what makes the round trip below exact. Section 3.10 gives the exact rules, including rounding and boundaries.

### 3.5 Word boundaries and pauses

Two options are defined and both are measured.

- **(a) WORD symbol.** Between consecutive words of an utterance there is exactly one WORD symbol. Its payload is the pause before the next word (0 = none). Costs one symbol per word boundary.
- **(b) Start flag.** The first phone of each word has its flag bit set. There are no WORD symbols. A PAUSE symbol is inserted only where there is an audible pause.

Pause payloads use *L* = 2^(W−6) − 1 levels spaced geometrically from 100 ms to 3200 ms. Gaps under about 71 ms (100/√2) count as no pause. Longer gaps are split across several symbols, each carrying the largest level, with the remainder in the last one. Pauses before an utterance (including the start of the stream) are always PAUSE symbols placed before its TURN.

This is a correction to the original planning note. Option (b) cannot drop pause information altogether, otherwise timing drifts and hesitations disappear. It therefore pays one extra symbol per audible pause instead of one per word.

Known losses of option (b): a word with no recognised phones disappears entirely, and the gaps on either side of it merge. Option (a) keeps it as an empty slot between two WORD symbols, except when it is the only word of its utterance (3.10).

### 3.6 Container

```
"PRS" 0x01                 magic + version
u8   profile id            width | 0x80 if option b
str  phone table id        u8 length + UTF-8
u8   speaker count
  per speaker: str id, u16 median f0 (0.1 Hz), i16 mean loudness (0.1 dB)
u8   extension phone count
  per phone: str IPA
u32  symbol count
...  body (packed symbols)
```

For one speaker and no extension phones, the header is 23 bytes. It is reported separately from the body in all measurements.

### 3.7 Lossless at quantised resolution

The required property, checked by `prototype/test_pack.py` for every profile:

1. `encode(json)` produces bytes *B₁*.
2. `decode(B₁)` produces JSON *J₂* (centre values, reconstructed times).
3. `encode(J₂)` produces exactly *B₁* again, and decoding that gives exactly *J₂*.

Reconstructed times are cumulative: each phone takes its duration level's centre, and each pause takes its level's centre. Absolute times therefore drift from the original by the accumulated quantisation error. The JSON form keeps true times.

### 3.8 Size estimates

The planning figures below assumed 3.5 phones per word. Measured values are 3.1 to 3.3, so the measured sizes in section 9.1 come out slightly smaller.

| Profile | Symbols/word | Bytes/word |
|---|---|---|
| 16b | ≈3.5 + pauses | ≈7.0 |
| 16a | ≈4.5 | ≈9.0 |
| 12b | ≈3.5 + pauses | ≈5.3 |
| 12a | ≈4.5 | ≈6.8 |
| 8b | ≈3.5 + pauses | ≈3.5 |
| 8a | ≈4.5 | ≈4.5 |

Text reference: measured at 5.1 to 5.6 bytes per word in ASCII/UTF-8 (including the space and punctuation), and twice that in UTF-16.

The hand-written sample (`prototype/samples/party_three_ways.json`, three deliveries of a six-word sentence, 60 phones) gives exactly 80 symbols in the *a* profiles and 66 in the *b* profiles: per delivery, 1 TURN, 20 phones and 5 WORDs; 2 PAUSEs between deliveries; and in *b*, 1 extra PAUSE for a 150 ms gap. That is 160 / 132 / 120 / 99 / 80 / 66 body bytes for 16a / 16b / 12a / 12b / 8a / 8b.

### 3.9 Unicode private-use form (discussion)

Purpose: let a stream live in ordinary text files, chat messages and databases.

- **16-bit profiles.** Supplementary Private Use Area-A (plane 15, U+F0000–U+FFFFD) holds 65,534 code points, two short of 2¹⁶ because U+FFFFE and U+FFFFF are noncharacters. Reserving phone code 63 (3.2) makes every used symbol fit: symbol *s* maps to U+F0000 + *s*. Each symbol is 4 bytes in UTF-8 and 4 in UTF-16 (a surrogate pair), double the packed size.
- **12-bit profiles.** These fit in the BMP Private Use Area (U+E000–U+F8FF, 6,400 code points): 3 bytes in UTF-8, 2 in UTF-16.
- **8-bit profiles.** These could use the same BMP range at the same cost, which is worse than the packed form by 3×.

Consequences:

- The text form gives up the size claim. At about 4.5 symbols per word, a 16a stream costs about 18 UTF-8 bytes per word against about 5.6 for plain text. It is an interchange form, not a compact one.
- Display still needs a renderer that decodes symbols into styled IPA glyphs. A font that drew each 16-bit symbol directly would need about 56,000 glyphs (55 phones × 1,024 payloads). That is inside OpenType's 65,535-glyph limit, but impractical, and it would fix one visual mapping into the font.
- Private-use code points have no agreed meaning. Any system that normalises, filters or substitutes fonts may mangle them silently.

Recommendation: keep the packed binary form canonical, and treat PUA text as an optional transport encoding.

### 3.10 Exact rules (normative)

These rules fix every choice an encoder or decoder has to make, so that independent implementations produce identical bytes. The test vectors in `vectors/` are generated by `prototype/pack.py` and must be matched exactly by encoders, and within 10⁻⁶ by decoders.

**Arithmetic.**

- *rnd(x)* rounds half away from zero: ⌊x + 0.5⌋ for x ≥ 0, otherwise −⌊−x + 0.5⌋. (Round-half-to-even, Python's default, is not used.)
- *clip(x, lo, hi)* limits x to the range [lo, hi].
- *nearest(v, c₀ … cₙ)* is the number of boundaries √(cₖ·cₖ₊₁) that v is strictly greater than. It gives a level from 0 to n.

**Encoding a phone's delivery** (*st* = pitch in semitones or null, *voiced*, *ms* = duration, *db* = loudness or null):

| Field | Bits | Level |
|---|---|---|
| pitch | 4, 3, 2 | 0 if not *voiced* or *st* is null; otherwise clip(rnd(*st* / step) + centre, 1, 2ᵇ−1), with step 1.5 / 3 / 4 st and centre 8 / 4 / 2 |
| pitch | 1 | 1 if *voiced* and *st* > 2, otherwise 0 |
| duration | 3, 2 | nearest(*ms*, centres of 3.4) |
| loudness | 3, 2 | clip(rnd(*db* / step) + centre, 0, 2ᵇ−1), with step 3 / 6 dB and centre 4 / 2; a null *db* counts as 0 |
| loudness | 1 | 1 if *db* > 3, otherwise 0 |
| flag | 1 | 1 on the first phone of each word (profiles *b*) |

**Phones.** The IPA string is folded (3.3) and looked up in the table. A phone not in the table is written as ESC followed by a symbol whose code is the phone's index in the header's extension table (appended in order of first use; at most 64 entries).

**Gaps and pauses.** A word's end is the later of its `end_s` and the end of its last phone. The gap before a word is its `start_s` minus the previous word's end, or 0 if negative. The gap before an utterance is its first word's start minus the previous utterance's end, measured from time 0 for the first one.

With *P* = *W* − 6 payload bits, the pause levels are *L* = 2ᴾ − 1 centres *cᵢ* = 100 · 32^((i−1)/(L−1)) ms, for i = 1 … L. Let τ = c₁/√2 (about 71 ms). A gap *g* becomes a list of payload levels:

1. If *g* < τ, the list is [0].
2. Otherwise, while *g* ≥ c_L + τ, append L and subtract c_L.
3. Then, if *g* ≥ τ, append 1 + nearest(*g*, c₁ … c_L).

**Words without phones.** Profiles *b* drop them before encoding, so gaps are measured across them. Profiles *a* keep them, except that an utterance whose only word has no phones is encoded as an utterance with no words, because a bare TURN cannot tell the two apart.

**Symbol order.** For each utterance:

1. A PAUSE symbol for each non-zero level of the gap before the utterance.
2. TURN (payload = speaker index in the header).
3. The utterance's words in order, with between consecutive words:
   - Profiles *a*: PAUSE symbols for all but the last level of the gap's list, then one WORD symbol carrying the last level (0 if there is no pause).
   - Profiles *b*: a PAUSE symbol for each non-zero level of the gap.
4. Each word's phones in order.

A word with no phones produces no symbols of its own. In profiles *a* it still produces its WORD separators.

**Decoding.** Keep a clock *t* starting at 0, a current utterance, a current word, and (for profiles *a*) the time *s* at which the current word slot opened.

| Symbol | Action |
|---|---|
| PAD | Ignored. |
| PAUSE | *t* += centre of its level (level 0 adds nothing). |
| WORD | If no phone has arrived since the slot opened, append an empty word at *s*. Then *t* += centre of its level, the current word ends, and *s* = *t*. |
| TURN | If the previous utterance's last WORD was not followed by a phone, append an empty word at *s* to that utterance. Start a new utterance for speaker[payload]; the current word ends and *s* = *t*. |
| ESC | Read the next symbol: its code indexes the extension table and its payload is the delivery. The phone counts as voiced. |
| Phone | If there is no current word, or the profile has a flag and the flag is 1, start a new word at *t*. Append the phone at *t* with the delivery below, then *t* += its duration. |
| End of stream | As for TURN: a trailing WORD with no phone after it leaves an empty word at *s*. |
| Codes 5–7 and 63 | Error. A phone or WORD before any TURN is also an error. |

The decoded delivery is:

- **Duration:** the level's centre, or **80 ms** for profiles without duration bits (about the mean phone duration of English).
- **Pitch:** (level − centre) × step. Level 0 decodes as null, and in 1-bit profiles level 1 decodes as +4 st.
- **Loudness:** (level − centre) × step. In 1-bit profiles, 0 decodes as 0 dB and 1 as +6 dB. In profiles without loudness bits it is null.
- **Voicing:** with 2 or more pitch bits, voiced means level ≠ 0. With 1 bit, voiced means level 1 or a voiced phone (3.3). With no pitch bits, it comes from the phone table.

**Header values.** The speaker's f0 is stored as rnd(f0 × 10) and loudness as rnd(dB × 10). Strings are at most 255 bytes of UTF-8. The TURN payload limits a stream to 2ᴾ speakers (4 in 8-bit profiles).

## 4. JSON form

The JSON form holds unquantised measurements and everything in the data model. It is the format `transcribe.py` writes and `render.py` reads.

```json
{
  "prosotype": "0.1",
  "language": "en",
  "phone_table": "en-1",
  "source": {"audio": "samples/clip.wav", "note": "free text"},
  "speakers": {"S1": {"f0_median_hz": 120.0, "loudness_mean_db": 62.0}},
  "utterances": [
    {
      "speaker": "S1",
      "label": "optional",
      "words": [
        {
          "text": "party",
          "start_s": 0.52, "end_s": 0.90,
          "phones": [
            {"ipa": "p", "start_s": 0.52, "dur_ms": 70, "voiced": false, "pitch_st": null, "loud_db": -6.0},
            {"ipa": "ɑ", "start_s": 0.59, "dur_ms": 120, "voiced": true, "pitch_st": 1.5, "loud_db": 3.0}
          ]
        }
      ]
    }
  ]
}
```

- `pitch_st` is `null` when the phone is unvoiced or no pitch was tracked.
- `ipa` may be any IPA string. It is folded (3.3) when packed, and phones outside the table go to the extension table.
- Decoding a packed stream produces the same shape with `text: null`, centre values, reconstructed times, and a `profile` field.
- A speaker may name a voice profile (`"voice_profile": "id"`, §10) whose pitch median was used as the baseline.

### 4.1 Text map

A packed stream keeps word boundaries but not spelling. To display or highlight readable text alongside it, the JSON form carries a document-level `"text"` string and a `"chars": [start, end)` range on each word, as offsets into that string. `transcribe.py` joins words with spaces and utterances with newlines, using Whisper's spelling and punctuation.

For a packed stream, the same information travels as a **text map** sidecar, written by `prototype/textmap.py`:

```json
{"prosotype_text": "0.1", "profile": "16a",
 "text": "You're going to the party tonight?",
 "utterances": [[[0, 6], [7, 12], [13, 15], [16, 19], [20, 25], [26, 34]]]}
```

`utterances[u][w]` is the character range of the *w*-th word that the stream contains in utterance *u*, in stream order. That means it follows 3.10's rules: profiles *b* drop words without phones, and profiles *a* drop a lone empty word. A text map is therefore specific to a profile. It may also carry `"labels"`, one optional caption per utterance (such as "question"); a label is left out where it would only repeat the utterance's words. A later container version may carry text maps as an optional block.

## 5. Standard visual mapping

Both candidates draw IPA glyphs only, in one variable font (Noto Sans, axes `wght` 100–900 and `wdth` 62.5–100; see Appendix A), at the 16a levels. Both are implemented in `prototype/render.py`.

### Mapping A (owner's proposal)

| Feature | Visual variable | Levels |
|---|---|---|
| Pitch (4 bits) | Colour. Hue blue below the median and orange above. Chroma grows with distance from the median. Lightness is held constant so every level has the same contrast. Median = text colour; unvoiced = muted grey. | 16 |
| Duration (3 bits) | Font size: 0.72, 0.80, 0.90, 1.00, 1.12, 1.26, 1.41, 1.60 em | 8 |
| Loudness (3 bits) | Weight: 300, 325, 350, 400, 500, 600, 750, 900 (400 = 0 dB; floor 300, see 6.3) | 8 |

### Mapping B

| Feature | Visual variable | Levels |
|---|---|---|
| Pitch (4 bits) | Vertical offset from the baseline, 0.075 em per level (±0.525 em). A faint guide line marks the speaker's median pitch (the baseline) under each word. Unvoiced glyphs are muted grey and drawn at the height of the preceding voiced phone, so height changes only where pitch does. | 16 |
| Duration (3 bits) | Width axis 62.5, 70, 78, 86, 94, 100, 100, 100, plus extra tracking of 0.06 em and 0.14 em on the two longest levels. Noto Sans can only narrow, not widen, so the longest levels need tracking. | 8 |
| Loudness (3 bits) | Weight, as in A | 8 |
| Colour | Free. Reserved for speaker or voice quality. | |

Pauses in both: a gap whose width grows with log(pause length), bounded by faint rules.

### Prior art

Mapping B is in effect an automated, quantised form of Bolinger's intonation notation, which prints syllables higher or lower on the page as pitch rises and falls (Appendix B). It also matches the "speech-modulated typography" of de Lacerda Pataca and Costa (2022): loudness to weight, pitch to baseline shift, duration to letter-spacing. It was later evaluated with 16 deaf and hard-of-hearing participants (de Lacerda Pataca et al., CHI 2023). WaveFont (Wölfel, Stitz, Schlippe) maps loudness to weight and speed to width. Rosenberger's Prosodic Font (MIT, 1998) mapped intensity to weight and size together. None of these used pitch as colour. Mapping A's main channel is therefore the less tested one.

### Rules learned from recorded speech

The two rules in mapping B's pitch row came from the owner's recordings (section 9.3):

- **Guide line.** Without a reference, a whole utterance spoken high (the sarcastic take) reads as a uniform shift that the eye cannot see.
- **Unvoiced height.** Unvoiced glyphs drawn at the median made voiceless consonants look like pitch jumps inside low or high phrases.

## 6. Accessibility constraints

Measured on `prototype/render.py`'s output. Contrast is WCAG 2 relative luminance. Colour differences are ΔE in OKLab (×100, where about 2 is a just-noticeable difference), with colour-vision deficiency simulated by the Machado et al. (2009) matrices at full severity.

### 6.1 Colour is never the only channel

The standard mapping must survive greyscale print, colour-blind readers and monochrome displays. In mapping A, pitch is carried only by colour. In greyscale it disappears completely: the question's rise and the flat take's fall become indistinguishable (`docs/img/recorded_grey.png`). Mapping B carries every feature without colour. Consequently:

- **Rule:** a delivery feature in the standard mapping must be shown by size, position, width or weight. Colour may only repeat a feature already shown another way, or carry non-delivery information (speaker).

### 6.2 Contrast

| Glyph colour | Light theme | Dark theme |
|---|---|---|
| Pitch colours (A), 15 levels | 5.9 to 17.2 : 1 | 7.7 to 14.6 : 1 |
| Unvoiced grey (A and B) | 5.2 : 1 (raised from 4.5) | 6.2 : 1 |

- **Rule:** every glyph colour must be at least 4.5 : 1 against its background in every theme. Lightness is held constant across the pitch scale (A) so that no level becomes harder to read than another.

### 6.3 Size and weight floors

- Duration shrinks glyphs to 0.72 em at the shortest level. **Rule:** the base size must be at least 22 px on screen (10.5 pt in print), so that the smallest glyph is at least 16 px.
- Quiet speech thins glyphs. **Rule:** the minimum weight is 300. The prototype originally used 250, which breaks up at small sizes.
- B's vertical step is 0.075 em per level, which is 1.7 px at a 22 px base. Adjacent pitch levels are not separable by eye at that size, but contours and range (±11.5 px) are. **Rule:** line height of at least 2.3 so raised and lowered glyphs never collide with adjacent lines.

### 6.4 Colour-blind safety (when colour is used for pitch)

| Vision | Adjacent levels, ΔE min / median | −4.5 st vs +4.5 st | Ends of scale |
|---|---|---|---|
| Typical | 1.9 / 2.2 | 18.7 | 32.6 |
| Protan | 1.1 / 2.0 | 15.6 | 27.3 |
| Deutan | 0.3 / 1.9 | 16.9 | 28.1 |
| Tritan | 0.8 / 2.4 | 20.4 | 30.1 |

Light theme shown; the dark theme is similar (minimum adjacent ΔE 0.1 to 1.3). The blue/orange scale keeps "below median" and "above median" clearly apart for every type of colour vision. But adjacent levels are at or below the threshold of perception even for typical vision. Colour reliably carries 3 to 5 pitch bands, not 15.

- **Rule:** if colour is used as a redundant pitch layer, quantise it to 5 bands: well below, below, median, above, well above.

### 6.5 Monochrome print fallback

| Element | Mapping B in monochrome |
|---|---|
| Pitch, duration, loudness | Unchanged (height, width, weight). |
| Median guide line | Printed as a light grey hairline. |
| Unvoiced glyphs | Printed as mid grey. |
| Speaker colour | Replaced by a speaker label at the start of each utterance. |
| Pauses | Unchanged (gap width with rules). |

## 7. Transcription pipeline architecture

As built in `prototype/transcribe.py`, which runs locally on an Apple M4 (16 GB). A 26 s clip takes about 20 s once the models are cached. The models take about 4 GB on disk and are kept in `.hf-cache/` on the project drive.

```
audio ──ffmpeg──► 16 kHz mono
   │
   ├─► Whisper large-v3-turbo (mlx-whisper) ──► words + segments (utterances)
   │
   ├─► wav2vec2-lv-60-espeak-cv-ft (CTC, 20 ms frames, MPS) ──► phone spikes
   │        spikes mark phone ONSETS (checked against Praat on test clips);
   │        a phone runs from its spike to the next, cut at pauses
   │        (≥120 ms more than 25 dB below the recording's loud end;
   │        a stop keeps ≤60 ms of closure)
   │
   ├─► label clean-up: split "ɑːɹ"→ɑ ɹ etc., fold length marks, merge "ɑːɹ ɹ"
   │
   ├─► CMUdict pronunciations of Whisper's words ──► edit-distance alignment
   │        recognised phones → words (also yields as-spoken vs dictionary
   │        differences)
   │
   └─► Praat via parselmouth: F0 (autocorrelation, 60–500 Hz, 10 ms), intensity
            per phone: median F0 of voiced frames; mean intensity (power domain)
            speaker baselines over all input files: median F0 of voiced phones,
            mean intensity of vowels
```

Several files of one speaker can be passed together. They share one set of baselines, which is required for comparing deliveries: normalising each file separately hides a register shift.

### Expected error sources

| Source | Effect | Seen in |
|---|---|---|
| Quiet, creaky utterance ends (vocal fry) | Phones misrecognised or dropped. Pitch tracking unreliable at 80–90 Hz. | All three "tonight"s in the owner's recordings. |
| Unreleased final stops | Final /t/ dropped or replaced. | question, sarcastic |
| Phone recogniser substitutions | Wrong phone with the right timing: /w/→/h/, /v/→/b/, /n/→/m/, /aɪ/→/æ/, /aɪ/→/ɑɹ/. | flat, question, synthetic |
| Real connected-speech variants | Not errors, but they show as dictionary differences: flapped /t/, "goin'" /n/, reduced "to" /tə/, full /æ/ in "and". | all |
| Onset-to-onset durations | The phone before a pause absorbs any trailing frames. Durations have not been checked against hand labels (8.2). | – |
| Recording gain and distance | Loudness across separately recorded files is not comparable. The three takes have noise floors of 37, 51 and 42 dB. | owner's recordings |
| Per-phone median pitch | A pitch movement inside one long vowel is reduced to its middle value. | question /aɪ/ in synthetic clip |
| Whisper word errors | Wrong words give wrong dictionary pronunciations. This only affects word assignment, not the phones themselves. | none observed (one OOV: "9") |

**Fallback (not needed so far).** Dictionary pronunciation plus HMM forced alignment (Montreal Forced Aligner) would give better boundaries but canonical rather than as-spoken phones. It also needs a conda install. The CMUdict alignment already in the pipeline provides the canonical phones if this is ever wanted.

## 8. Known limitations and open questions

**Readability (deferred).** Fluent human reading of IPA is unlikely for most readers, and this format as it stands does not address that. It is acknowledged and deliberately left to later work. This phase neither tests it nor designs around it.

1. **Evidence base is small.** It consists of three short recorded utterances from one speaker, plus synthetic speech. The planned 30–60 s of natural recorded speech is still outstanding. All error rates below are indicative, not estimates.
2. **Durations are too coarse for 3-bit levels.** Phone boundaries come from CTC onset spikes on a 20 ms grid. Against hand labels (9.5), only 32% of durations land on the correct 3-bit level, though 58% land on the correct 2-bit level. Onsets lag by a consistent 14–38 ms depending on the phone class.
3. **Pitch inside a phone.** One value per phone flattens rises and falls within long vowels. Open question: is a 1–2 bit pitch-slope field worth more than a loudness bit? Prosogram's perceptual stylisation, which keeps a pitch movement only where a listener would hear it as one, is a candidate model (Appendix B).
4. **Delivery per phone or per syllable.** Pitch and loudness mostly matter on syllable nuclei, and Hirata and Nakagawa's 1989 vocoder coded delivery once per syllable (Appendix B). Carrying delivery only on vowels would roughly halve the delivery bits, but it breaks the one-symbol-one-width rule. It is worth measuring before the format is frozen beyond container version 1.
5. **Loudness is session-relative.** It is only meaningful within one recording setup. A stream should either declare its recording conditions or use per-session baselines.
6. **One speaker, no diarisation.** TURN symbols and speaker baselines exist, but nothing assigns speakers yet.
7. **English only.** The phone table, CMUdict and the label clean-up are all English-specific. No out-of-table (ESC) phones occurred in any sample, but the table has seen fewer than 400 phones.
8. **Option (b) drops words with no recognised phones,** and packed timestamps drift by accumulated quantisation error (3.7).
9. **Rendering is only judged by the authors.** No reader has seen it. Prior work with deaf and hard-of-hearing readers suggests B-style captions are understood (Appendix A), but the IPA form is untested by design (see the readability note above).
10. **Streaming is not specified.** The container header gives the symbol count and the speaker's median pitch and loudness up front, so a live stream cannot start before the speech ends. A streaming framing would need an open-ended count and a running or replaced baseline. Each symbol is complete once its phone ends, so the format itself adds about one phone of delay (median 70 ms in Buckeye). Measured on an Apple-silicon Mac for a 2.6 s utterance, after warm-up: phone recogniser 59 ms, pitch and loudness 2 ms, synthesis 185 ms (for 1.2 s of output), Whisper words 1.6 s, MFA alignment 34 s (mostly process start-up). The recogniser path can stream; Whisper and MFA need whole utterances. For an anonymity use, the header's absolute pitch and loudness reveal the speaker's voice and must not be sent.

## 9. Findings

Samples: the owner's recordings (`samples/flat.m4a`, `question.m4a`, `sarcastic.m4a`; one speaker; 19 words; transcribed together as `recorded_three_ways.json`), a 26 s synthetic paragraph (`samples/smoke/say_natural.wav`, macOS `say`; useful for sizes, not prosody), and the hand-written sample. The flat take uses a different sentence ("We are going to the movie tonight") from the other two.

### 9.1 Encoding size

Bytes per word, body only (the 23-byte header is excluded):

| Form | Recorded (19 words) | Synthetic (87 words) | bit/s, synthetic |
|---|---|---|---|
| packed 16a | 8.53 | 8.74 | 237 |
| packed 16b | 6.84 | 6.99 | 189 |
| packed 12a | 6.42 | 6.55 | 177 |
| packed 12b | 5.16 | 5.24 | 142 |
| packed 8a | 4.26 | 4.37 | 118 |
| packed 8b | 3.42 | 3.49 | 95 |
| text, UTF-8 | 5.47 | 5.14 | 139 |
| text, UTF-16 | 10.95 | 10.28 | 278 |
| text UTF-8 + zlib | 3.05 | 3.30 | – |
| packed 12b + zlib | 5.74 | 5.37 | – |
| packed 8b + zlib | 3.63 | 3.29 | – |
| Codec 2 700C | 44.0 | 29.5 | 799 |
| Opus 6 kbit/s (Ogg) | 389 | 245 | 6,644 |

Measured: 3.1 to 3.3 phones per word, 5.1 to 5.5 characters per word, 11 phones/s in continuous (synthetic) speech. The recorded clips have about 1 s of silence each, which inflates the audio figures per word.

- **Against text, raw.** 8b is about 35% smaller than ASCII text and 12b is about the same size. 16b is 1.3× text and 16a is 1.6×. All profiles beat UTF-16 text. The claim "phone plus delivery fits in the space of text" holds at 12 bits or below with the word-start flag.
- **Against text, compressed.** The claim does not survive: zlib brings text to about 3.0–3.3 bytes per word, while the packed streams barely compress (their bits are already dense and not byte-aligned). xz figures are dominated by container overhead at these sizes and are in `samples/bitrate_results.json`.
- **Option (b) beats (a).** It is 18–20% smaller at every width, because audible pauses are much rarer than word boundaries.
- **Against audio.** 16a at about 240 bit/s is 3.4× smaller than Codec 2 700C, the lowest mode in the current Codec 2 release, and 28× smaller than Opus at 6 kbit/s. 8b at about 95 bit/s is 8× smaller than Codec 2. These are not the right competitors, though. Neural codecs now resynthesise speech at comparable rates (FocalCodec: 160–650 bit/s, NeurIPS 2025), and phonetic vocoders reached 100–400 bit/s decades ago (Appendix B). ProsoType's size is in the same range as these, not below them. Its difference is that the stream is symbolic: readable, searchable and renderable without a model. It cannot be played back without a synthesiser (out of scope).

### 9.2 Transcription quality

| Clip set | Phones match dictionary | Substitutions | Insertions | Deletions |
|---|---|---|---|---|
| Owner's recordings (64 dictionary phones) | 40 (63%) | 18 | 1 | 5 |
| Synthetic paragraph (284) | 249 (88%) | 27 | 6 | 7 |

A difference from the dictionary is not always an error (section 7 table). On the recordings, about a third of the differences are genuine as-spoken variants (flaps, "goin'", reduced vowels). The rest are recogniser errors, concentrated at utterance ends: all three takes of "tonight" are damaged. Whisper's words were correct in every clip. Pitch extraction recovered what the takes were meant to show, with one shared baseline (122 Hz):

| Take | Pitch | Duration and loudness |
|---|---|---|
| Flat | Low and falling, −1 to −6.5 st | Vowels 3–10 dB below the speaker mean (partly recording gain) |
| Question | Level, then rising through "tonight" from +7 to +13 st | – |
| Sarcastic | Raised throughout, +2 to +5 st | Lengthened "you're" (360 ms against 180 ms in the question); loud stressed "par-" (+8 dB) |

### 9.3 Visual mappings

Screenshots: `docs/img/recorded_colour.png`, `docs/img/recorded_grey.png`, `docs/img/recorded_dark.png`.

| | Mapping A (colour, size, weight) | Mapping B (height, width, weight) |
|---|---|---|
| Question rise | Visible as a blue→orange ramp. The direction must be decoded from hue. | Immediately visible as a rising contour. |
| Sarcastic register shift | Very clear: the whole line turns orange. | Visible only with the median guide line (added after this test). |
| Lengthened "you're" | Clear (size). | Present but subtle (width can only narrow, so long phones gain tracking). |
| Loudness | Weight; clear in both mappings. | Same. |
| Greyscale | **Loses pitch entirely.** | Unchanged. |
| Colour-blind | Coarse bands only (6.4). | Unaffected. |
| Prior art | None for pitch-as-colour. | Matches published speech-modulated typography. |

**Recommendation:** adopt **mapping B** as the standard, with the guide line and unvoiced-height rule. Allow A's pitch colour only as an optional redundant layer, reduced to 5 bands (6.4), for single-speaker screen use where colour is not needed for speakers.

### 9.4 Resynthesis (back to audio)

Two tools turn ProsoType back into sound, so that a listener can judge what a stream keeps. Both run on the owner's three recorded takes, at the unquantised values ("measured") and at profiles 16a, 12b and 8b.

- **Re-delivery** (`prototype/redeliver.py`). Praat overlap-add resynthesis imposes the stream's pitch, durations and loudness on the original recording. The phones and voice stay real, so only the delivery is tested. At the measured values, the imposed pitch lands within 0.44 st of target at every voiced phone centre (median error 0.0 st). Profiles 12b and 8b carry no loudness, so the recorded loudness is left in place.
- **Re-speaking** (`prototype/synthesize.py`). This uses the stream alone, with no original audio: ESPnet FastSpeech 2 (LJSpeech, Apache-2.0) with HiFi-GAN. Our per-phone pitch, energy and durations replace the model's own predictions. Phones map from IPA to its ARPAbet symbols, and pauses become a comma token. The voice is the model's single female reader, because ProsoType does not encode voice identity.
  - **Calibration.** Measured on the model's own output, its pitch input moves the voice about 6.6 st per unit. It is monotonic only from about −6.6 to +8.6 st around its mean; beyond that it saturates or breaks, so targets are clipped to that range. Its energy input moves loudness by about 6.4 dB per unit.
  - **Closed-loop check.** Measured pitch at each phone follows the targets with a median error of 0.3–1.7 st per take.

**Round trip.** The re-spoken audio was transcribed again with `transcribe.py` and compared with the stream that produced it:

| Variant | Phone edits vs the stream | Question: end rise (in → out) | Sarcastic: end rise | Flat: end fall |
|---|---|---|---|---|
| measured | 26/59 (44%) | +8.7 → +8.3 st | +2.9 → +2.6 | −3.1 → +0.7 |
| 16a | 22/59 (37%) | +8.7 → +8.1 | +2.9 → +2.8 | −3.1 → −1.0 |
| 8b | 11/59 (19%) | +8.7 → +3.5 | +2.9 → +1.2 | −3.1 → −0.1 |

"End rise" is the mean pitch of the last third of voiced phones minus the rest, relative to the take's median.

What this shows:

1. **The question survives** at 16a and above: the final rise comes back almost unchanged. At 8b it shrinks to less than half, because one pitch bit can only say "high" or "not high".
2. **The flat take's final fall is lost** at every level. Its target goes below the range the synthesiser can follow, and its last phones are the creaky, misrecognised end of "tonight" (9.2).
3. **The durations are the weak link.** 8b stores no durations and speaks every phone for 80 ms, yet it is the most intelligible variant by a wide margin. The measured durations come from recogniser onsets (§8 item 2) and are uneven enough to garble the synthesiser: some phones are squeezed to a frame or two, while others absorb the gaps. This is the first direct evidence that phone timing, not the format, limits intelligibility. Validating durations against hand labels (Buckeye or TIMIT) is now the highest-value next check.
4. **The edit counts are relative to our own transcription, not to the truth.** They measure what the stream preserves, not whether the original transcription was right.

Human listening has not started. Every comparison above is a machine measurement.

### 9.5 Phone timing against hand labels

`prototype/timing_check.py` runs the transcriber's phone recogniser on 80 clips of conversational speech from the Buckeye Corpus (Pitt et al. 2007): 10 clips of 2–15 s from each of 8 speakers, two in each sex × age group. It aligns the recognised phones to Buckeye's hand-corrected phone labels and compares 3,018 matched pairs (95% of reference phones). The summary is in `prototype/samples/timing/buckeye.json`. The corpus itself is not redistributed.

| | Pairs | Onset lag (median) | Onsets within 20 ms | Same 3-bit duration level | Within one level | Duration correlation (log) |
|---|---|---|---|---|---|---|
| All | 3018 | +22 ms | 42% | 32% | 76% | 0.58 |
| Vowels | 1234 | +14 ms | 58% | 36% | 77% | 0.69 |
| Stops | 570 | +37 ms | 18% | 25% | 70% | 0.36 |
| Other consonants | 1214 | +25 ms | 38% | 32% | 77% | 0.53 |

What this shows:

1. **Onsets lag, consistently.** Every speaker shows an 18–26 ms lag, with no difference by age or sex. Stops lag most, because the recogniser fires near the release while Buckeye's label starts at the closure. A per-class correction, fitted on four speakers and tested on the other four, removes the lag and raises onsets within 20 ms from 44% to 67%.
2. **Durations are noisy, not biased.** Duration errors are symmetric (19% one level short, 24% one level long), and the median duration ratio is 0.99. The onset correction barely helps (31% → 36% on the right level on the held-out speakers). The cause is resolution. The recogniser places boundaries on a 20 ms grid, the shortest 3-bit duration levels are 15–20 ms apart, and 21% of real phones are under 45 ms.
3. **2-bit durations are within reach.** On the coarser levels of profiles 12a and 12b, 58% of durations land on the right level and 97% within one level.
4. **This explains 9.4.** Per-phone durations are the least reliable part of a transcription, which is why the re-spoken audio with fixed 80 ms phones (8b) was the most intelligible.

The proxy run on synthesised speech (`samples/timing/synth.json`) gave similar duration figures (43% on the right level), but its reference boundaries were themselves offset by about 40–50 ms, so it could not measure the lag.

Next steps, in order of cost:

- **Done:** `transcribe.py` now moves each onset earlier by its class's lag (vowels 14 ms, stops 37 ms, other consonants 25 ms). On all 8 speakers, onsets within 20 ms rise from 42% to 65% (median absolute error 24 → 14 ms), and durations on the right 3-bit level from 32% to 36%. The uncorrected summary is kept as `samples/timing/buckeye-uncorrected.json`. All transcribed samples were regenerated; phones and sizes are unchanged.
- **Done:** a forced aligner. `transcribe.py --aligner mfa` runs the Montreal Forced Aligner (3.4.2, `english_us_arpa` models; `prototype/mfa.py`) on Whisper's words, instead of using the recogniser's phones. Measured on the same 80 Buckeye clips, using Whisper's words rather than Buckeye's transcripts:

| | Onsets within 20 ms | Median onset error | Same 3-bit duration level | Within one level | Duration correlation (log) | Phones identical to hand label |
|---|---|---|---|---|---|---|
| Recogniser, uncorrected | 42% | 24 ms | 32% | 76% | 0.58 | 74% |
| Recogniser, corrected | 65% | 14 ms | 36% | 79% | 0.59 | 74% |
| MFA on Whisper's words | **78%** | **8 ms** | **47%** | **87%** | **0.72** | **76%** |

  MFA's phones are dictionary pronunciations, so they cannot show a pronunciation the dictionary lacks. Even so, they match the hand labels slightly more often than the recogniser's, perhaps partly because Buckeye's labels began as dictionary alignments before correction. On the owner's recordings, MFA writes "tonight" correctly in all three takes, where the recogniser misheard it each time (9.2). Two costs: MFA is English-only through its dictionary, and it needs a full utterance plus its words before it can align, which matters for streaming (§8 item 10).

- Even with MFA, fewer than half of durations land on the exact 3-bit level. Treat 3-bit durations from automatic transcription as accurate to about ±1 level; 2-bit durations are within reach.

### 9.6 Go / adjust / stop (technical questions only)

| Question | Call | Reason |
|---|---|---|
| Encoding size | **Adjust** | Size alone is not a distinguishing claim: phonetic vocoders and neural codecs reach similar rates (Appendix B). The raw fixed-width claim holds at 12 and 8 bits with the start flag, but not at 16 bits, and not against compressed text. Make 12b or 16b the reference profile and option (b) the standard boundary. If "smaller than compressed text" matters, the next step is entropy coding (pitch as deltas, phone n-grams) rather than wider symbols. |
| Transcription | **Adjust** | Words and pitch are dependable. Phones are good in clear speech but degrade at quiet utterance ends. Durations are now measured against hand labels (9.5): onsets lagged about 22 ms, a lag the transcriber now corrects, and only 32% of durations are on the right 3-bit level, against 58% at 2 bits. Next steps: the 30–60 s natural recording, forced alignment for finer boundaries (9.5), and either a stronger phone model or a dictionary-constrained decode for low-confidence spans. |
| Resynthesis | **Adjust** | A stream alone can be spoken back and keeps a question's rise at 16a. Durations from the recogniser hurt intelligibility more than quantisation does (9.4), so fix the timing before trusting duration levels. |
| Rendering | **Go** | Mapping B separates all three deliveries in light, dark and greyscale, meets the contrast and size floors, and has precedent. |

Overall: **go, with the adjustments above.** Nothing found so far makes the idea technically unviable.

---

## 10. Voice profiles

A voice profile describes how a voice sounds. It does two jobs:

- **Analysis baseline.** Transcribing a known voice with its profile (`transcribe.py --voice`) fixes the pitch baseline, so a pitch level means the same thing across sessions and a stream can start before the speaker has said enough to measure a median. Loudness stays session-relative, because microphone gain changes between sessions (§8).
- **Playback.** A synthesiser maps a stream onto a target profile, and can use the speaker's own profile to adjust range. Swapping one profile for another changes the voice while keeping the delivery.

Profiles should eventually carry as much vocal information as good resynthesis needs, including timbre. A profile of a real person is therefore personal. Treat it like a private key: keep it local and share it sparingly. In this repository, profiles of people go in `profiles/private/` (git-ignored); only synthetic voices' profiles are published. How profiles should be shared, and whether a profile could be usable for synthesis without being readable (in the spirit of public/private keys), is an open question for later.

### 10.1 Format (version 0.1)

```json
{
  "prosotype_profile": "0.1", "id": "fastspeech2-ljspeech", "kind": "synthetic", "private": false,
  "source": {"speech_s": 21.0, "phones": 267, "tool": "prototype/voiceprofile.py"},
  "pitch": {"median_hz": 208.8, "p10_hz": 179.3, "p90_hz": 231.0, "range_st": 4.39},
  "loudness": {"vowel_mean_db": 71.2, "sd_db": 2.51},
  "timing": {"phones_per_s": 12.7, "median_phone_ms": {"vowel": 89, "stop": 81.5, "other consonant": 51}},
  "timbre": {
    "formants_hz": {"i": [410, 2699, 3090, 4054]}, "formant_tokens": {"i": 10},
    "formant_mean_hz": [558, 1744, 2814, 3776], "formant_dispersion_hz": 1102.2, "vocal_tract_cm": 15.88,
    "hnr_db": 13.06, "jitter_local": 0.0193, "shimmer_local": 0.0795, "spectral_tilt_db_per_octave": -6.98
  },
  "embeddings": {},
  "synth": {"fastspeech2": {"kp": 0.15, "ke": 0.16, "base_pitch": 0.13, "pitch_limits": [-0.87, 1.43]}}
}
```

- **pitch**: the median and spread of the voiced phones' F0.
- **timbre**:
  - Per-vowel median formants F1–F4, measured at vowel midpoints, with token counts.
  - The apparent vocal-tract length, from formant dispersion over F1–F4 (Fi ≈ (2i−1)/2 · ΔF; L = c / 2ΔF).
  - Harmonics-to-noise ratio, and local jitter and shimmer, measured by Praat on the continuous recording.
  - The long-term spectral tilt of the voiced speech.
- **embeddings**: reserved for learned speaker embeddings, for synthesisers that clone timbre. None yet.
- **synth**: optional controls for one synthesiser, for example FastSpeech 2's pitch and energy calibration.

`prototype/voiceprofile.py` builds a profile from recordings or from a transcript and its audio. Checks so far, measured on 60 s of speech per speaker:

| Voice | Median F0 | Vocal tract |
|---|---|---|
| Buckeye s01 (woman under 40) | 201 Hz | 14.4 cm |
| Buckeye s03 (man over 40) | 129 Hz | 18.3 cm |
| Owner (4 s only) | 121 Hz | 18.4 cm |

The owner's profile is private. Jitter and shimmer come out high for all voices (about 2% and 9–14%), as is common for running speech, so they are useful for comparing voices rather than as absolute norms.

### 10.2 Mapping a stream onto a voice

A stream's pitch is in semitones from its speaker's median (§2). Playing it in a target voice:

- f0 = target median × 2^(*s* · *r* / 12), where *s* is the stream's semitones and *r* = target range / speaker range when the speaker's profile is known, otherwise 1.
- Durations and loudness are played as written. A rate option may scale time.
- Timbre comes from whatever the synthesiser can use: the reference synthesiser (§11) scales its formants by vocal-tract length, uses measured vowel formants that have at least 3 tokens, and sets source tilt, breathiness (from HNR), jitter and shimmer. FastSpeech 2 has one fixed voice, so it takes only the pitch level and range. Its clean range is about −6.6 to +8.6 st around its own median, so a low male target (about −9.5 st) is clipped.

## 11. Reference synthesiser and player

`js/synth.mjs` is a small Klatt-style formant synthesiser in JavaScript, for browsers and Node (`node js/speak.mjs IN.prs -o OUT.wav --voice P.json`). It speaks a decoded stream exactly as written, with nothing predicted:

- Each phone gets its stream duration.
- Pitch is interpolated between voiced phones' centres.
- Loudness is applied as gain.
- Formants glide between phone targets: adult male means for vowels (Hillenbrand et al. 1995), with consonant loci and noise spectra for fricatives and bursts.
- The voice source is a KLGLOTT88 glottal pulse.

It sounds robotic by design. It is a reference for what a stream contains, not a natural voice. Its output is deterministic (seeded noise), so it can be tested.

- **Intelligibility.** Whisper transcribes the reference voice almost perfectly. All three takes of the hand-written sentence come back word for word. The 26 s synthetic story comes back with two errors ("cancelled twice" → "can sit worse", "best day" → "best life").
- **Profiles take effect.** Asked for the FastSpeech 2 voice (209 Hz, 15.9 cm), its output profiles at 208 Hz and 15.6 cm. With no profile it uses the stream's own speaker median: 174 Hz against a 175 Hz target. The vocal-tract estimate rests on few vowels (3–9) because the profiler finds all four formants in only a few of the robotic vowels.
- **Speed.** It renders 25 s of speech in about 65 ms in Node.

### 11.1 Embedding: `<prosotype-player>`

`js/prosotype-player.mjs` defines a web component that puts the three layers in one element: the binary stream, its standard formatting, and a player.

```html
<script type="module" src="https://omnifroodle.github.io/prosotype/js/prosotype-player.mjs"></script>
<prosotype-player src="hand.16a.prs" text="hand.16a.text.json" voice="reference-high.json"></prosotype-player>
<prosotype-player stream="UFJTARAEZW4tMQ…"></prosotype-player>
```

- **Stream:** `src` (a `.prs` file, or a JSON-form `.json`) or `stream` (the packed bytes inline, as base64). The footer gives the profile and size and offers the stream as a download.
- **Formatting:** the element decodes the stream and draws it in mapping B in JavaScript. It uses the same 16a levels and tables as `render.py`, and a WOFF2 subset of Noto Sans (variable weight and width) covering the en-1 table and common extension phones (`js/prosotype-ipa.woff2`, 48 KB, SIL OFL 1.1).
- **Text:** with a text map (`text`, or a child `<script type="application/json">`), each utterance shows its words and label, and words highlight alongside glyphs.
- **Player:** Play speaks the whole stream with the reference synthesiser. When there are several utterances, each line also gets its own play button. `voice` names a voice profile; `voices` adds a voice menu; the `voiceProfile` property takes a profile object, such as one a viewer loads from disk.
- **Events and methods:** `prosotype-phone` fires as each phone sounds (index, phone, utterance, word), and `prosotype-end` fires at the end. `play(utterance?)` and `stop()` control playback. Only one element sounds at a time.
- **Controls only:** `view="controls"` shows just the play controls and footer, for pages that draw the stream themselves and follow the events.
- **Styling:** it lives in a shadow root, so page CSS cannot break it. It follows light and dark mode, and pages can retheme it with `--prosotype-ink`, `-muted`, `-unvoiced`, `-rule`, `-guide`, `-highlight`, `-highlight-ink`, `-surface` and `-size`. The `compact` attribute gives a smaller version without the footer.
- **Without JavaScript:** content placed inside the element shows until it upgrades, so a static rendering can sit inside as the fallback.

On the site, the homepage hero is a `<prosotype-player>` with the static rendering inside it as the fallback. Each document on the render pages (mappings A and B side by side) has a controls-only player: its `prosotype-phone` events highlight the phone being spoken in both columns, and every line has its own play button. `render.py` adds these only when asked (`render(docs, player=…)`), so its standalone pages stay self-contained. The **reader** (`docs/play.html`, built by `prototype/player.py`) shows every sample as an element, with page-level menus that switch all of them between 16a, 12b and 8b and between voice profiles. A viewer can also load their own profile from disk; it never leaves the browser.

## Appendix A. Verified background

Section 9.5 uses the Buckeye Corpus of Conversational Speech: Pitt, M.A., Dilley, L., Johnson, K., Kiesling, S., Raymond, W., Hume, E. and Fosler-Lussier, E. (2007), Department of Psychology, Ohio State University (distributor). It was used under its licence for non-commercial research; no corpus content is included in this repository.


Status of the claims carried over from the planning notes, checked 2026-10-05.

| Claim | Status | Detail |
|---|---|---|
| `facebook/wav2vec2-lv-60-espeak-cv-ft` recognises phones | Verified | Multilingual CTC phoneme recogniser fine-tuned on Common Voice, 16 kHz input, espeak-style IPA labels (392 tokens, including English diphthongs and r-coloured vowels as single tokens), Apache-2.0. Measured accuracy: section 9.2. |
| Allosaurus | Exists | Universal phone recogniser, `pip install allosaurus`, ICASSP 2020. Timestamp output not yet checked. |
| WhisperX | Verified | Whisper transcription plus word timestamps by wav2vec2 forced alignment, with optional pyannote diarisation. |
| Montreal Forced Aligner | Verified | Installed with conda. Pretrained `english_us_arpa` acoustic model and dictionary. Canonical phones. |
| parselmouth | Verified | `pip install praat-parselmouth`. Exposes Praat's own `to_pitch` and `to_intensity`. |
| pYIN | Not checked | Only needed if parselmouth is unsuitable. |
| Noto Sans is variable with weight and width axes, full IPA | Verified by inspecting the font file | `NotoSans[wdth,wght].ttf` from google/fonts: `wght` 100–900, `wdth` 62.5–100 (narrowing only). Covers all of IPA Extensions (U+0250–02AF), Spacing Modifier Letters (U+02B0–02FF) and Combining Diacritical Marks (U+0300–036F). |
| ≈12 phones/s; ≈3.5 phones/word; ≈5.6 chars/word | Measured | 3.1–3.3 phones/word, 5.1–5.5 chars/word, about 11 phones/s on the samples (section 9.1). 10–15 phonemes/s is the usual cross-language figure. |
| Lowest conventional speech codecs ≈700 bit/s | Verified, with a caveat | Codec 2 lists 700C and an experimental 450 bit/s mode, but the current release (1.2.0, installed here) offers 700C as its lowest. Opus goes down to 6 kbit/s. |
| FastSpeech 2 conditions on phones + pitch + duration + energy | Verified | Its variance adaptor adds duration, pitch and energy to the phoneme hidden sequence. |
| Prior art | Verified | In de Lacerda Pataca & Costa's study, 117 participants matched speech-modulated captions to their source audio 65% of the time on average, whether the text was animated or static. Rosenberger-Shankar, *Prosodic Font*, MIT MAS thesis, 1998. de Lacerda Pataca & Costa, "Hidden bawls, whispers, and yelps", arXiv:2202.10631, 2022. de Lacerda Pataca, Watkins, Peiris, Lee, Huenerfauth, "Visualization of Speech Prosody and Emotion in Captions", CHI 2023, doi:10.1145/3544548.3581511. Wölfel, Stitz, Schlippe, WaveFont. |

Sources: [wav2vec2 model listing](https://www.promptlayer.com/models/wav2vec2-lv-60-espeak-cv-ft), [Allosaurus](https://github.com/xinjli/allosaurus), [WhisperX on PyPI](https://pypi.org/project/whisperx), [MFA docs](https://montreal-forced-aligner.readthedocs.io/en/v3.2.0/getting_started.html), [parselmouth](https://pypi.org/project/praat-parselmouth), [Codec 2](https://en.wikipedia.org/wiki/Codec_2), [FastSpeech 2](https://arxiv.org/abs/2006.04558), [Prosodic Font](https://dspace.mit.edu/handle/1721.1/62340), [arXiv:2202.10631](https://arxiv.org/abs/2202.10631), [CHI 2023 paper](https://digitalcommons.njit.edu/fac_pubs/1776), [WaveFont](https://nafath.mada.org.qa/nafath-article/wavefont-visualization-of-information-and-emotions-from-the-voice-in-captions/), [speaking-rate summary](https://virtualspeech.com/blog/average-speaking-rate-words-per-minute).

## Appendix B. Related work and positioning

Reviewed 2026-10-05, to place ProsoType relative to existing ways of writing down or transmitting how something was said. Each of ProsoType's parts has precedent. What this review did not find is the combination: phone-level IPA, carrying quantised pitch, duration and loudness on every phone, in a fixed-width interchange stream with normative quantisation and conformance vectors, a standard typographic rendering, and automatic transcription.

### Notations for intonation and prosody

| Work | What it is | How ProsoType differs |
|---|---|---|
| **ToBI** (Tones and Break Indices) | Phonological annotation of pitch accents, boundary tones and break indices on separate tiers, by trained labellers; versions exist for many languages. | ToBI records categories (*what* the intonation means phonologically). ProsoType records quantised measurements of all three delivery features on every phone, automatically. A ToBI layer could be derived from ProsoType data, not the other way round. |
| **INTSINT / MOMEL** (Hirst) | An 8-symbol alphabet for pitch targets (Top, Higher, Upstepped, Same, Mid, Downstepped, Lower, Bottom), coded automatically from MOMEL target points; meant as an "IPA for intonation". | The closest in spirit to ProsoType's pitch field, but pitch only, at target points rather than on every phone. |
| **Prosogram** (Mertens) | A Praat-based tool that stylises pitch per syllable nucleus according to a model of tonal perception, and plots it with phone and word tiers and syllable measurements. | Prosogram is an analysis graphic for linguists. ProsoType is a text format and a typographic rendering. Prosogram's perceptual stylisation could improve ProsoType's per-phone pitch (§8). Note the similar name. |
| **Bolinger's notation** | Ordinary text printed with syllables raised and lowered on the page to follow pitch. It was considered impractical because it needed special typesetting. | Mapping B is this idea automated, quantised and extended to width and weight. Variable fonts and the web remove the typesetting obstacle. |
| **Jefferson transcription** (conversation analysis) | Inline marks in orthographic text: ↑↓ for pitch shifts, CAPITALS for loud speech, °degree signs° for quiet speech, colons for lengthening, underlining for emphasis, timed pauses. Written by hand and widely used. | Proof that readers can work with prosody embedded in running text. ProsoType's marks are continuous rather than categorical, automatic, and on IPA rather than spelling. |
| **IPA suprasegmentals and extIPA** | Stress and length marks, Chao tone letters, global rise and fall arrows, and extIPA/VoQS marks for loudness and tempo. | ProsoType strips IPA stress and length marks (3.3) and expresses them through delivery instead. A converter could emit IPA suprasegmentals for readers who expect them. |

### Prosody in typography

| Work | Mapping | How ProsoType differs |
|---|---|---|
| Rosenberger-Shankar, *Prosodic Font* (MIT, 1998) | Intensity → weight and size, at word or syllable level | ProsoType works at phone level with standard levels, on IPA. |
| Lee, Forlizzi & Hudson, *Kinetic Typography Engine* (UIST 2002), and later kinetic-typography work | Animated text conveying emotion | ProsoType is static by design, so that it works in print. |
| WaveFont (Wölfel, Stitz, Schlippe) | Loudness → weight, speed → width, pauses; evaluated with hearing-impaired and hearing viewers | Orthographic captions, no interchange format. |
| de Lacerda Pataca & Costa (2022); de Lacerda Pataca et al. (CHI 2023) | Loudness → weight, pitch → baseline shift, duration → letter-spacing. 117 listeners matched captions to their audio 65% of the time; 16 DHH participants evaluated caption styles. | The same mapping as B, on orthography. ProsoType adds phone-level IPA, normative quantisation and a packed stream. |

### Machine formats and low-rate coding

| Work | What it is | How ProsoType differs |
|---|---|---|
| **SSML** `<prosody>` (W3C) | XML markup that tells a synthesiser what pitch, rate and volume to use, in coarse values over spans of text | Prescriptive and verbose. ProsoType is descriptive (it measures what was said) and compact. ProsoType JSON could be converted into SSML or phoneme-level synthesiser input. |
| **Phonetic vocoders.** Hirata & Nakagawa, "A 100 bit/s speech coding using a speech recognition technique" (Eurospeech 1989); Baudoin et al. (ICASSP 2003, ~400 bit/s, corpus-based synthesis); Bistritz et al. (EUSIPCO 2008, <300 bit/s, speaker adaptation) | Recognise speech units, transmit their identity plus prosody, and resynthesise | **Direct precedent for the packed symbol.** Hirata & Nakagawa coded each Japanese syllable as one 16-bit symbol holding syllable category, duration, power and pitch. That is ProsoType's 16-bit design one level up, at syllables rather than phones. The compression idea is therefore not new. ProsoType's contribution is treating the stream as a written form, with a standard rendering and an open, normative definition. |
| **Neural codecs.** FocalCodec (NeurIPS 2025, 160–650 bit/s); ContextCodec (2026, down to ~500 bit/s) | Learned token streams resynthesised by a neural decoder | Comparable or lower bit rates, and the output is playable audio. Their tokens are opaque and tied to a particular model. ProsoType's symbols mean the same thing to any reader or implementation. |

### Name

There was no existing project, package (PyPI, npm), product or trademark using "ProsoType" in a web, GitHub and registry check on 2026-10-05, and `prosotype.com`, `.org` and `.io` were unregistered. Prosogram, a well-known tool in the same field, has a similar name. This is not legal clearance; a formal trademark search would be needed before commercial use.

Sources: [Prosogram](https://sites.google.com/site/prosogram/), [ToBI (MIT OCW)](https://ocw.mit.edu/courses/6-911-transcribing-prosodic-structure-of-spoken-utterances-with-tobi-january-iap-2006/), [INTSINT](https://en.wikipedia.org/wiki/INTSINT), [Momel](https://en.wikipedia.org/wiki/Momel), [Bolinger's notation (course notes)](https://studfile.net/preview/12728042/), [Jefferson symbols](https://ugc.futurelearn.com/uploads/files/47/8b/478b50f3-890e-4f15-9f6b-b30563b1229d/Jefferson_transcription_symbols.pdf), [IPA suprasegmentals and tone letters](https://en.wikipedia.org/wiki/Sinological_phonetic_notation), [SSML prosody](https://learn.microsoft.com/en-us/previous-versions/office/developer/speech-technologies/hh361578(v=office.14)), [Hirata & Nakagawa 1989](https://www.isca-archive.org/eurospeech_1989/hirata89_eurospeech.html), [Baudoin et al. 2003](https://perso.esiee.fr/~baudoing/pdf/baudoin2003-icassp.pdf), [Bistritz et al. 2008](https://www.eng.tau.ac.il/~bistritz/2008%20EUSIPCO.pdf), [FocalCodec](https://arxiv.org/abs/2502.04465), [ContextCodec](https://www.alphaxiv.org/abs/2606.10591), [Kinetic Typography Engine](https://uist.acm.org/archive/html/keywords/kwautomating.html), [Visualization of Speech Prosody and Emotion in Captions](https://digitalcommons.njit.edu/fac_pubs/1776).
