# ProsoType

Speech written in the International Phonetic Alphabet, with how it was said (pitch, length and loudness) set into the type itself.

**Site:** https://omnifroodle.github.io/prosotype/

ProsoType has three parts:

1. **A data model.** Utterances, words and IPA phones, where each phone carries pitch (semitones from the speaker's median), duration and loudness (dB from the speaker's mean).
2. **A packed stream.** One fixed-width symbol per phone: 6 bits name the phone and the remaining 2, 6 or 10 bits carry delivery. The 8- and 12-bit variants with a word-start flag come out smaller than plain text.
3. **A standard visual mapping.** Pitch is shown as glyph height, duration as width and loudness as weight, in one variable font.

This repository holds the output of the viability phase:

| Path | What |
|---|---|
| [SPEC.md](SPEC.md) | The specification (draft 0.2), including measured findings and a go / adjust / stop call |
| [PLAN.md](PLAN.md) | The plan and the decisions this phase worked from |
| [prototype/](prototype) | Python prototype: `pack.py`, `render.py`, `transcribe.py`, `bitrate.py`, `site.py` |
| [docs/](docs) | The GitHub Pages site, built by `prototype/site.py` |

Status: technical viability looks good, with adjustments (SPEC.md §9.4). Fluent reading of IPA is a known limitation that is deliberately deferred.

The evidence comes from one speaker. Their source recordings are not published; their transcriptions (`prototype/samples/*.json`) are. The project was developed under the working name Shadowcat.
