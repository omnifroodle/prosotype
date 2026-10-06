#!/usr/bin/env python3
"""Speak a ProsoType stream: phones + pitch + duration + loudness -> audio.

    synthesize.py IN.json [--profile 16a] [-o samples/resynth] [--calibrate]

The input JSON is first packed at the profile and decoded again, so the
audio uses only what the stream holds (the centre value of every level and
the reconstructed timing). Use --profile measured to skip that and speak
the unquantised values.

Synthesiser: ESPnet FastSpeech 2 (Conformer, LJSpeech) with its HiFi-GAN
vocoder, Apache-2.0. Its encoder, variance embeddings, length regulator and
decoder are run directly so that our per-phone values replace its own
predictions:

  phones    en-1 IPA -> its ARPAbet symbols (full vowels stressed, schwas not)
  duration  milliseconds -> 11.6 ms frames (cumulative rounding)
  pitch     semitones from the speaker median -> its normalised log-F0,
            base + KP * st, calibrated so 1 st in = 1 st out (--calibrate)
  loudness  dB from the speaker's vowel mean -> its normalised energy,
            base + KE * dB, calibrated the same way
  pauses    a "," token lasting the pause

The voice is the model's (one female US reader); ProsoType does not encode
voice identity, so this tests content and delivery only.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import fetch
import pack

fetch.use_project_hf_cache()

HERE = Path(__file__).parent
SR = 22050
HOP = 256
FRAME_MS = HOP / SR * 1000  # 11.61 ms
VOICE_FILE = HERE.parent / "profiles" / "fastspeech2-ljspeech.json"  # this model's voice profile and calibration

ARPA = {
    "p": "P", "b": "B", "t": "T", "d": "D", "k": "K", "ɡ": "G", "ʔ": "T", "ɾ": "D",
    "f": "F", "v": "V", "θ": "TH", "ð": "DH", "s": "S", "z": "Z", "ʃ": "SH", "ʒ": "ZH",
    "h": "HH", "tʃ": "CH", "dʒ": "JH", "m": "M", "n": "N", "ŋ": "NG", "l": "L", "ɹ": "R",
    "w": "W", "j": "Y",
    "n̩": "AH0 N", "l̩": "AH0 L", "m̩": "AH0 M",
    "i": "IY1", "ɪ": "IH1", "e": "EY1", "ɛ": "EH1", "æ": "AE1", "a": "AA1", "ɑ": "AA1",
    "ɒ": "AA1", "ɔ": "AO1", "o": "OW1", "ʊ": "UH1", "u": "UW1", "ʌ": "AH1", "ə": "AH0",
    "ɚ": "ER0", "ɜ": "ER1", "ɐ": "AH0",
    "eɪ": "EY1", "aɪ": "AY1", "ɔɪ": "OY1", "aʊ": "AW1", "oʊ": "OW1", "əʊ": "OW1",
    "ɪə": "IH1 AH0", "ɛə": "EH1 AH0", "ʊə": "UH1 AH0",
    # common out-of-table phones from the recogniser
    "x": "HH", "ç": "HH", "ʍ": "W", "β": "B", "ɣ": "G", "y": "UW1", "ø": "ER1", "ɨ": "IH0",
}
PAUSE_MIN_MS = 70


def arpa(ipa: str) -> list[str]:
    return ARPA.get(pack.normalise_ipa(ipa), "AH0").split()


class Synth:
    def __init__(self) -> None:
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import FastSpeech2ConformerHifiGan, FastSpeech2ConformerModel

        self.torch = torch
        self.model = FastSpeech2ConformerModel.from_pretrained(fetch.TTS_MODEL, revision=fetch.TTS_MODEL_REV).eval()
        self.vocoder = FastSpeech2ConformerHifiGan.from_pretrained(fetch.VOCODER, revision=fetch.VOCODER_REV).eval()
        self.vocab = json.loads(Path(hf_hub_download(fetch.TTS_MODEL, "vocab.json", revision=fetch.TTS_MODEL_REV)).read_text())

    def run(self, tokens: list[str], frames: list[int], pitch: list[float | None], energy: list[float | None]):
        """Synthesise tokens with given frame counts; None pitch/energy keeps the model's prediction.
        Returns (waveform, predicted pitch, predicted energy) as numpy arrays."""
        from transformers.models.fastspeech2_conformer.modeling_fastspeech2_conformer import length_regulator

        torch, m = self.torch, self.model
        ids = torch.tensor([[self.vocab[t] for t in tokens] + [self.vocab["<sos/eos>"]]])
        frames = list(frames) + [0]
        pitch, energy = list(pitch) + [None], list(energy) + [None]
        mask = torch.ones_like(ids)
        with torch.no_grad():
            h = m.encoder(ids, mask.unsqueeze(-2), return_dict=True)[0]
            dmask = ~mask.bool()
            p_hat = m.pitch_predictor(h, dmask.unsqueeze(-1))
            e_hat = m.energy_predictor(h, dmask.unsqueeze(-1))
            p, e = p_hat.clone(), e_hat.clone()
            for i, v in enumerate(pitch):
                if v is not None:
                    p[0, i, 0] = float(v)
            for i, v in enumerate(energy):
                if v is not None:
                    e[0, i, 0] = float(v)
            h = h + m.energy_embed(e) + m.pitch_embed(p)
            h = length_regulator(h, torch.tensor([frames]))
            dec = m.decoder(h, None, return_dict=True)[0]
            _, mel = m.speech_decoder_postnet(dec)
            wav = self.vocoder(mel)
        return wav.squeeze().numpy().astype(np.float64), p_hat[0, :, 0].numpy(), e_hat[0, :, 0].numpy()


def plan(utt: dict):
    """Tokens, frame counts and per-token targets (st, dB) for one utterance.
    Also returns, for each phone, its token span for measurement."""
    tokens, ms, st, db, phone_tokens = [], [], [], [], []
    prev_end = None
    for w in utt["words"]:
        if not w["phones"]:
            continue
        gap = 0.0 if prev_end is None else (w["start_s"] - prev_end) * 1000
        if gap >= PAUSE_MIN_MS:
            tokens.append(","); ms.append(gap); st.append(None); db.append(None)
        for ph in w["phones"]:
            parts = arpa(ph["ipa"])
            first = len(tokens)
            share = [0.4, 0.6] if len(parts) == 2 else [1.0]
            for part, frac in zip(parts, share):
                tokens.append(part)
                ms.append(ph["dur_ms"] * frac)
                st.append(ph["pitch_st"] if ph.get("voiced") and ph.get("pitch_st") is not None else None)
                db.append(ph.get("loud_db"))
            phone_tokens.append((ph, first, len(tokens)))
        last = w["phones"][-1]
        prev_end = last["start_s"] + last["dur_ms"] / 1000
    # cumulative rounding keeps the total length right
    frames, acc, done = [], 0.0, 0
    for x in ms:
        acc += x / FRAME_MS
        n = max(1, int(round(acc)) - done)
        frames.append(n)
        done += n
    return tokens, frames, st, db, phone_tokens


def fill_unvoiced(values: list[float | None], tokens: list[str]) -> list[float | None]:
    """Interpolate pitch across unvoiced tokens (the model was trained on continuous F0)."""
    idx = [i for i, v in enumerate(values) if v is not None]
    if not idx:
        return values
    xs, ys = np.array(idx, float), np.array([values[i] for i in idx])
    out = list(values)
    for i, t in enumerate(tokens):
        if out[i] is None and t not in (",",):
            out[i] = float(np.interp(i, xs, ys))
    return out


def speak(s: Synth, utt: dict, cal: dict, shift_st: float = 0.0, range_scale: float = 1.0) -> tuple[np.ndarray, list]:
    """shift_st moves the whole voice up or down; range_scale widens or narrows
    the stream's pitch movements (see voice_mapping)."""
    tokens, frames, st, db, phone_tokens = plan(utt)
    st = [None if v is None else shift_st + range_scale * v for v in fill_unvoiced(st, tokens)]
    lo, hi = cal["pitch_limits"]
    pitch = [None if v is None else float(np.clip(cal["base_pitch"] + cal["kp"] * v, lo, hi)) for v in st]
    energy = [None if v is None else cal["base_energy"] + cal["ke"] * v for v in db]
    wav, *_ = s.run(tokens, frames, pitch, energy)
    # phone spans in the output, in seconds
    starts = np.concatenate([[0], np.cumsum(frames)]) * HOP / SR
    spans = [(ph, starts[a], starts[b]) for ph, a, b in phone_tokens]
    return wav, spans


def measure(wav: np.ndarray, spans) -> tuple[list[float], list[float]]:
    """Median F0 (Hz) and mean intensity (dB) per phone span of a synthesised utterance."""
    import parselmouth

    snd = parselmouth.Sound(wav, sampling_frequency=SR)
    pitch = snd.to_pitch_ac(time_step=0.005, pitch_floor=90, pitch_ceiling=700)  # the model's female voice
    inten = snd.to_intensity(minimum_pitch=60, time_step=0.005)
    pt, f0 = pitch.xs(), pitch.selected_array["frequency"]
    it, dbv = inten.xs(), inten.values[0]
    hz, db = [], []
    for _, a, b in spans:
        m = (pt >= a) & (pt < b) & (f0 > 0)
        hz.append(float(np.median(f0[m])) if m.any() else float("nan"))
        mi = (it >= a) & (it < b)
        db.append(float(10 * np.log10(np.mean(10 ** (dbv[mi] / 10)))) if mi.any() else float("nan"))
    return hz, db


def calibrate(s: Synth, utt: dict) -> dict:
    """Fit KP (units per semitone) and KE (units per dB) from sweeps inside the
    model's clean range: its pitch control is monotonic for about +-1 unit
    around its mean and saturates or breaks beyond that."""
    tokens, frames, *_ = plan(utt)
    _, p_hat, e_hat = s.run(tokens, frames, [None] * len(tokens), [None] * len(tokens))
    vowel = [i for i, t in enumerate(tokens) if t[-1].isdigit()]
    base_p, base_e = float(np.mean(p_hat[vowel])), float(np.mean(e_hat[vowel]))
    starts = np.concatenate([[0], np.cumsum(frames)]) * HOP / SR
    spans = [(None, starts[i], starts[i + 1]) for i in vowel]

    def level(pitch_off: float, energy_off: float) -> tuple[float, float]:
        n = len(tokens)
        wav, *_ = s.run(tokens, frames, [base_p + pitch_off] * n, [base_e + energy_off] * n)
        hz, db = measure(wav, spans)
        return float(np.nanmedian(hz)), float(np.nanmedian(db))

    offs = [-0.5, 0.0, 0.5]
    pitch_pts = [level(o, 0)[0] for o in offs]
    st_per_unit = float(np.polyfit(offs, [12 * np.log2(h / pitch_pts[1]) for h in pitch_pts], 1)[0])
    eoffs = [-1.0, 0.0, 1.0]
    energy_pts = [level(0, o)[1] for o in eoffs]
    db_per_unit = float(np.polyfit(eoffs, energy_pts, 1)[0])
    return {"base_pitch": base_p, "base_energy": base_e,
            "kp": 1 / st_per_unit, "ke": 1 / db_per_unit,
            "pitch_limits": [base_p - 1.0, base_p + 1.3],  # beyond this the voice saturates or breaks
            "probe": {"st_per_unit": st_per_unit, "db_per_unit": db_per_unit,
                      "pitch_hz": pitch_pts, "energy_db": energy_pts},
            "model": f"{fetch.TTS_MODEL}@{fetch.TTS_MODEL_REV}", "vocoder": f"{fetch.VOCODER}@{fetch.VOCODER_REV}"}


def voice_mapping(model: dict, target: dict | None, speaker: dict | None) -> tuple[float, float]:
    """(shift_st, range_scale) to play a stream in the target voice's pitch:
    its median relative to the model's, and its range relative to the speaker's
    (SPEC 10.3). The model's own timbre is unchanged: FastSpeech 2 has one voice."""
    if target is None:
        return 0.0, 1.0
    shift = 12 * math.log2(target["pitch"]["median_hz"] / model["pitch"]["median_hz"])
    scale = 1.0
    if speaker and speaker["pitch"].get("range_st") and target["pitch"].get("range_st"):
        scale = target["pitch"]["range_st"] / speaker["pitch"]["range_st"]
    return shift, scale


def stream_view(doc: dict, profile: str) -> dict:
    """What a stream at this profile holds: pack, then decode (texts and labels kept for naming)."""
    if profile == "measured":
        return doc
    p = pack.PROFILES[profile]
    dec = pack.decode(pack.from_bytes(pack.to_bytes(pack.encode(doc, p))))
    for u, src in zip(dec["utterances"], doc["utterances"]):
        u["label"] = src.get("label")
        if p.pitch == 1:  # 1-bit pitch: "not high" is spoken at the median
            for w in u["words"]:
                for ph in w["phones"]:
                    if ph["voiced"] and ph["pitch_st"] is None:
                        ph["pitch_st"] = 0.0
    return dec


def write_wav(path: Path, y: np.ndarray) -> None:
    import parselmouth

    peak = np.max(np.abs(y)) or 1.0
    parselmouth.Sound(y * min(1.0, 0.95 / peak), sampling_frequency=SR).save(str(path), "WAV")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--profile", nargs="+", default=["16a"])
    ap.add_argument("-o", "--out", default="samples/resynth")
    ap.add_argument("--calibrate", action="store_true", help="refit KP/KE on the hand-written sample")
    ap.add_argument("--voice", help="target voice profile: play at its pitch level (and range, with --speaker)")
    ap.add_argument("--speaker", help="the stream speaker's voice profile, for range mapping")
    a = ap.parse_args()
    s = Synth()
    model = json.loads(VOICE_FILE.read_text())
    if a.calibrate:
        hand = json.loads((HERE / "samples/party_three_ways.json").read_text())
        model.setdefault("synth", {})["fastspeech2"] = calibrate(s, hand["utterances"][0])
        VOICE_FILE.write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n")
    cal = model["synth"]["fastspeech2"]
    target = json.loads(Path(a.voice).read_text()) if a.voice else None
    speaker = json.loads(Path(a.speaker).read_text()) if a.speaker else None
    shift, scale = voice_mapping(model, target, speaker)
    if target:
        print(f"voice: {target['id']} pitch level {shift:+.1f} st from the model, range x{scale:.2f}")
    doc = json.loads(Path(a.input).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for prof in a.profile:
        view = stream_view(doc, prof)
        f0_med = view["speakers"][next(iter(view["speakers"]))]["f0_median_hz"]
        for i, utt in enumerate(view["utterances"]):
            name = (utt.get("label") or f"utt{i + 1}").split()[0].lower().strip(".?!,")
            wav, spans = speak(s, utt, cal, shift, scale)
            fname = f"{name}.tts-{prof}{'-' + target['id'] if target else ''}.wav"
            write_wav(out / fname, wav)
            hz, db = measure(wav, spans)
            # closed-loop check: does the output follow the targets? (relative to the output's own median)
            tgt = [(sp[0]["pitch_st"], h) for sp, h in zip(spans, hz) if sp[0].get("voiced") and sp[0]["pitch_st"] is not None and h == h]
            if not tgt:
                print(f"{fname}  {len(wav) / SR:.2f} s; no pitch targets to check")
                continue
            med = np.median([h for _, h in tgt])
            err = [12 * np.log2(h / med) - (t - np.median([t for t, _ in tgt])) for t, h in tgt]
            print(f"{fname}  {len(wav) / SR:.2f} s; pitch tracking error {np.median(np.abs(err)):.2f} st median, "
                  f"{np.max(np.abs(err)):.2f} max (n={len(err)})")


if __name__ == "__main__":
    main()
