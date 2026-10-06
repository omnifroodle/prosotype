#!/usr/bin/env python3
"""Re-deliver recordings with the delivery a ProsoType stream keeps.

    redeliver.py samples/recorded_three_ways.json [-o samples/resynth] [--profiles measured 16a 12b 8b]

For each source recording named in the JSON, and each profile, Praat
(overlap-add resynthesis, via parselmouth) imposes on the speaker's own audio:

  pitch     each voiced phone's pitch, at the profile's level centre
  duration  each phone's duration, at the profile's level centre
            (80 ms per phone in profiles without duration bits, SPEC 3.10)
  loudness  each phone's loudness, at the profile's level centre

"measured" uses the unquantised JSON values, so it isolates what the
analysis itself loses; the profiles add quantisation on top. Phones and
voice quality come from the original audio, so this tests delivery only.
A field a profile does not carry (loudness in 12b and 8b) is left as
recorded, and the summary says so.

Writes NAME.original.wav and NAME.VARIANT.wav at 22.05 kHz.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call

import pack

HERE = Path(__file__).parent
SR = 22050
ANALYSIS_SR = 16000  # transcribe.py's rate; phone times are offsets in that timeline


def load(path: str, sr: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def targets(ph: dict, variant: str) -> dict:
    """Delivery a variant keeps for one phone: st (or None), ms, db (None = not carried)."""
    if variant == "measured":
        return {"st": ph["pitch_st"] if ph.get("voiced") else None, "ms": ph["dur_ms"], "db": ph.get("loud_db")}
    p = pack.PROFILES[variant]
    voiced = ph.get("voiced", True)
    lp = pack.q_pitch(ph.get("pitch_st"), voiced, p.pitch) if p.pitch else 0
    st = pack.dq_pitch(lp, p.pitch) if p.pitch else None
    if p.pitch == 1 and st is None and voiced:
        st = 0.0  # 1-bit pitch: "not high" is rendered at the median
    ms = pack.dq_dur(pack.q_dur(ph["dur_ms"], p.dur), p.dur) if p.dur else 80.0
    db = pack.dq_loud(pack.q_loud(ph.get("loud_db"), p.loud), p.loud) if p.loud else None
    return {"st": st, "ms": ms, "db": db}


def phones_by_file(doc: dict) -> list[tuple[str, float, list[dict]]]:
    """(audio path, offset in s, phones) per source file, in the JSON's timeline."""
    audio = doc["source"]["audio"]
    files = [audio] if isinstance(audio, str) else audio
    out, offset = [], 0.0
    for f in files:
        dur = len(load(str(HERE / f), ANALYSIS_SR)) / ANALYSIS_SR
        phs = [p for u in doc["utterances"] for w in u["words"] for p in w["phones"]
               if offset <= p["start_s"] < offset + dur]
        out.append((f, offset, phs))
        offset += dur
    return out


def redeliver(x: np.ndarray, phones: list[dict], offset: float, f0_med: float, variant: str) -> tuple[np.ndarray, dict]:
    dur = len(x) / SR
    spans = [(p["start_s"] - offset, p["start_s"] - offset + p["dur_ms"] / 1000, p, targets(p, variant)) for p in phones]

    # 1. loudness: a per-phone gain with 10 ms ramps (0 dB in pauses)
    carried_loud = any(t["db"] is not None for *_, t in spans)
    if carried_loud:
        pts_t, pts_g = [0.0], [0.0]
        for a, b, p, t in spans:
            g = 0.0 if t["db"] is None or p.get("loud_db") is None else t["db"] - p["loud_db"]
            ramp = min(0.01, (b - a) / 4)
            pts_t += [a, a + ramp, b - ramp, b]
            pts_g += [0.0 if not pts_g else pts_g[-1], g, g, g]
        pts_t.append(dur); pts_g.append(0.0)
        order = np.argsort(pts_t, kind="stable")
        gain_db = np.interp(np.arange(len(x)) / SR, np.array(pts_t)[order], np.array(pts_g)[order])
        x = x * 10 ** (gain_db / 20)

    snd = parselmouth.Sound(x, sampling_frequency=SR)
    manip = call(snd, "To Manipulation", 0.01, 60, 500)

    # 2. pitch: one point per voiced phone at its centre
    tier = call("Create PitchTier", "pitch", 0, dur)
    for a, b, p, t in spans:
        if t["st"] is not None:
            call(tier, "Add point", (a + b) / 2, f0_med * 2 ** (t["st"] / 12))
    call([manip, tier], "Replace pitch tier")

    # 3. duration: a constant stretch factor inside each phone, 1 in the gaps
    dtier = call("Create DurationTier", "dur", 0, dur)
    call(dtier, "Add point", 0, 1.0)
    prev_end = 0.0
    eps = 0.0005
    for a, b, p, t in spans:
        if a - prev_end > 4 * eps:
            call(dtier, "Add point", prev_end + eps, 1.0)
            call(dtier, "Add point", a - eps, 1.0)
        f = t["ms"] / max(p["dur_ms"], 1.0)
        call(dtier, "Add point", a + eps, f)
        call(dtier, "Add point", b - eps, f)
        prev_end = b
    call(dtier, "Add point", dur, 1.0)
    call([manip, dtier], "Replace duration tier")

    out = call(manip, "Get resynthesis (overlap-add)")
    y = out.values[0]
    peak = np.max(np.abs(y)) or 1.0
    if peak > 0.99:
        y = y * 0.99 / peak
    return y, {"loudness": "imposed" if carried_loud else "left as recorded"}


def write_wav(path: Path, y: np.ndarray) -> None:
    parselmouth.Sound(y, sampling_frequency=SR).save(str(path), "WAV")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--out", default="samples/resynth")
    ap.add_argument("--profiles", nargs="+", default=["measured", "16a", "12b", "8b"])
    a = ap.parse_args()
    doc = json.loads(Path(a.input).read_text())
    f0_med = doc["speakers"][next(iter(doc["speakers"]))]["f0_median_hz"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f, offset, phones in phones_by_file(doc):
        stem = Path(f).stem
        x = load(str(HERE / f), SR)
        write_wav(out / f"{stem}.original.wav", x)
        for v in a.profiles:
            y, info = redeliver(x, phones, offset, f0_med, v)
            write_wav(out / f"{stem}.{v}.wav", y)
            print(f"{stem}.{v}.wav  {len(phones)} phones, {len(y) / SR:.2f} s, loudness {info['loudness']}")


if __name__ == "__main__":
    main()
