#!/usr/bin/env python3
"""Voice profiles: measure a voice, for analysis baselines and for playback.

    voiceprofile.py build AUDIO... --id NAME [-o OUT.json] [--aligner mfa] [--synthetic]
    voiceprofile.py build TRANSCRIPT.json --id NAME [-o OUT.json]
    voiceprofile.py show PROFILE.json

A profile describes how a voice sounds (SPEC 10):

  pitch     median, 10th/90th percentile, range in semitones
  loudness  mean vowel level and its spread
  timing    speaking rate and median phone duration per class
  timbre    mean F1-F4 per vowel and overall, formant dispersion and the
            apparent vocal-tract length it implies, harmonics-to-noise ratio,
            jitter, shimmer, long-term spectral tilt
  embeddings  reserved for learned speaker embeddings (none yet)
  synth     optional controls for a particular synthesiser

Transcription uses the profile's pitch median and vowel loudness as the
speaker baseline (transcribe.py --profile). Playback maps a stream onto a
target profile (synthesize.py and js/synth.mjs).

A profile of a real person describes their voice in detail and is personal:
treat it like a private key. Profiles of people default to private and are
written under ../profiles/private/ (gitignored).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
PROFILES = HERE.parent / "profiles"
SPEED_OF_SOUND_CM_S = 35000.0
FORMANT_VOWELS = ("i", "ɪ", "eɪ", "ɛ", "æ", "ɑ", "ɔ", "oʊ", "ʊ", "u", "ʌ", "ə", "ɚ", "aɪ", "aʊ")


def load_timeline(doc: dict, sr: int) -> np.ndarray:
    """The transcript's audio as one array, files back to back (transcribe.py's timeline)."""
    import transcribe as T

    audio = doc["source"]["audio"]
    files = [audio] if isinstance(audio, str) else audio
    parts = [T.load_audio(str(HERE / f) if not Path(f).is_absolute() else f) for f in files]
    if sr != T.SR:
        raise ValueError("timeline is built at the transcriber's rate")
    return np.concatenate(parts)


def phones_of(doc: dict) -> list[dict]:
    return [p for u in doc["utterances"] for w in u["words"] for p in w["phones"]]


def measure(doc: dict, audio: np.ndarray, sr: int) -> dict:
    import parselmouth
    from parselmouth.praat import call

    import transcribe as T

    phones = phones_of(doc)
    spk = doc["speakers"][next(iter(doc["speakers"]))]
    f0_med, db_mean = spk["f0_median_hz"], spk["loudness_mean_db"]
    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=sr)

    # pitch, over voiced phones (st relative to the median, back to Hz)
    st = np.array([p["pitch_st"] for p in phones if p.get("voiced") and p.get("pitch_st") is not None])
    hz = f0_med * 2 ** (st / 12) if len(st) else np.array([f0_med])
    pitch = {"median_hz": round(float(f0_med), 1), "p10_hz": round(float(np.percentile(hz, 10)), 1),
             "p90_hz": round(float(np.percentile(hz, 90)), 1),
             "range_st": round(float(np.percentile(st, 90) - np.percentile(st, 10)), 2) if len(st) else 0.0}

    vowel_db = [p["loud_db"] for p in phones if p["ipa"] in T.VOWELS and p.get("loud_db") is not None]
    loudness = {"vowel_mean_db": round(float(db_mean), 1),
                "sd_db": round(float(np.std(vowel_db)), 2) if vowel_db else 0.0}

    speech_s = sum(p["dur_ms"] for p in phones) / 1000
    timing = {"phones_per_s": round(len(phones) / speech_s, 2) if speech_s else 0.0,
              "median_phone_ms": {c: round(float(np.median([p["dur_ms"] for p in phones if T.phone_class(p["ipa"]) == c])), 1)
                                  for c in ("vowel", "stop", "other consonant")
                                  if any(T.phone_class(p["ipa"]) == c for p in phones)}}

    # formants at vowel midpoints; the ceiling follows the voice (5000 Hz for low voices, 5500 otherwise)
    ceiling = 5000.0 if f0_med < 160 else 5500.0
    fm = snd.to_formant_burg(time_step=0.005, max_number_of_formants=5, maximum_formant=ceiling)
    per_vowel: dict[str, list[list[float]]] = {}
    for p in phones:
        if p["ipa"] not in FORMANT_VOWELS or p["dur_ms"] < 40:
            continue
        t = p["start_s"] + p["dur_ms"] / 2000
        vals = [fm.get_value_at_time(i, t) for i in (1, 2, 3, 4)]
        if all(v == v and v > 0 for v in vals):
            per_vowel.setdefault(p["ipa"], []).append(vals)
    formants = {v: [round(float(x)) for x in np.median(np.array(rows), axis=0)] for v, rows in sorted(per_vowel.items())}
    all_rows = np.array([r for rows in per_vowel.values() for r in rows]) if per_vowel else np.zeros((0, 4))
    timbre: dict = {"formant_ceiling_hz": ceiling, "formants_hz": formants,
                    "formant_tokens": {v: len(rows) for v, rows in sorted(per_vowel.items())},
                    "vowel_tokens": int(len(all_rows))}
    if len(all_rows):
        mean_f = all_rows.mean(axis=0)
        # Fi = (2i-1)/2 * dF for a uniform tube; least squares over F1-F4 (Reby & McComb 2003)
        k = np.array([0.5, 1.5, 2.5, 3.5])
        df = float((k @ mean_f) / (k @ k))
        timbre.update({"formant_mean_hz": [round(float(x)) for x in mean_f],
                       "formant_dispersion_hz": round(df, 1),
                       "vocal_tract_cm": round(SPEED_OF_SOUND_CM_S / (2 * df), 2)})

    # voice quality over the voiced phones only
    voiced = [p for p in phones if p.get("voiced") and p["dur_ms"] >= 30]
    if voiced:
        pieces = [snd.extract_part(p["start_s"], p["start_s"] + p["dur_ms"] / 1000, preserve_times=False) for p in voiced]
        vs = parselmouth.Sound(np.concatenate([q.values[0] for q in pieces]), sampling_frequency=sr)
        # HNR, jitter and shimmer on the continuous recording: Praat skips unvoiced
        # stretches itself, and joining phones end to end would add false period breaks
        hnr = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=60)
        hv = hnr.values[0]
        pp = call(snd, "To PointProcess (periodic, cc)", 60, 600)
        jitter = call(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        shimmer = call([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
        ltas = call(vs, "To Ltas", 50)
        fr = np.array([call(ltas, "Get frequency from bin number", b) for b in range(1, call(ltas, "Get number of bins") + 1)])
        lv = np.array([call(ltas, "Get value in bin", b) for b in range(1, len(fr) + 1)])
        m = (fr >= 100) & (fr <= 5000) & np.isfinite(lv)
        tilt = float(np.polyfit(np.log2(fr[m]), lv[m], 1)[0]) if m.sum() > 2 else float("nan")
        timbre.update({"hnr_db": round(float(np.mean(hv[hv > -100])), 2),
                       "jitter_local": round(float(jitter), 4) if jitter == jitter else None,
                       "shimmer_local": round(float(shimmer), 4) if shimmer == shimmer else None,
                       "spectral_tilt_db_per_octave": round(tilt, 2) if tilt == tilt else None})
    return {"pitch": pitch, "loudness": loudness, "timing": timing, "timbre": timbre,
            "source": {"speech_s": round(speech_s, 2), "phones": len(phones), "voiced_phones": len(voiced)}}


def build(inputs: list[str], pid: str, synthetic: bool, aligner: str) -> dict:
    import transcribe as T

    if len(inputs) == 1 and inputs[0].endswith(".json"):
        doc = json.loads(Path(inputs[0]).read_text())
        audio = load_timeline(doc, T.SR)
    else:
        doc = T.transcribe(inputs, aligner=aligner)
        audio = np.concatenate([T.load_audio(p) for p in inputs])
    m = measure(doc, audio, T.SR)
    src = m.pop("source")
    return {
        "prosotype_profile": "0.1",
        "id": pid,
        "kind": "synthetic" if synthetic else "person",
        "private": not synthetic,
        "created": dt.date.today().isoformat(),
        "source": {**src, "tool": "prototype/voiceprofile.py",
                   "transcription": doc["source"].get("aligner") or doc["source"].get("phone_model")},
        **m,
        "embeddings": {},
    }


def default_path(p: dict) -> Path:
    return PROFILES / ("private" if p["private"] else "") / f"{p['id']}.json"


def save(p: dict, out: Path | None = None) -> Path:
    out = out or default_path(p)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(p, ensure_ascii=False, indent=1) + "\n")
    return out


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def show(p: dict) -> str:
    t = p["timbre"]
    lines = [f"{p['id']} ({p['kind']}{', private' if p.get('private') else ''}): {p['source']['speech_s']} s of speech, "
             f"{p['source']['phones']} phones",
             f"  pitch    median {p['pitch']['median_hz']} Hz, p10-p90 {p['pitch']['p10_hz']}-{p['pitch']['p90_hz']} Hz "
             f"({p['pitch']['range_st']} st)",
             f"  timing   {p['timing']['phones_per_s']} phones/s, median ms {p['timing']['median_phone_ms']}"]
    if "vocal_tract_cm" in t:
        lines.append(f"  timbre   vocal tract {t['vocal_tract_cm']} cm (dF {t['formant_dispersion_hz']} Hz), "
                     f"F1-F4 mean {t['formant_mean_hz']}, {t['vowel_tokens']} vowel tokens")
    lines.append(f"  quality  HNR {t.get('hnr_db')} dB, jitter {t.get('jitter_local')}, shimmer {t.get('shimmer_local')}, "
                 f"tilt {t.get('spectral_tilt_db_per_octave')} dB/oct")
    if "synth" in p:
        lines.append(f"  synth    controls for {', '.join(p['synth'])}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("inputs", nargs="+")
    b.add_argument("--id", required=True)
    b.add_argument("-o", "--output", type=Path)
    b.add_argument("--synthetic", action="store_true", help="a synthetic voice (public by default)")
    b.add_argument("--aligner", choices=["recogniser", "mfa"], default="recogniser")
    s = sub.add_parser("show")
    s.add_argument("profile")
    a = ap.parse_args()
    if a.cmd == "build":
        p = build(a.inputs, a.id, a.synthetic, a.aligner)
        print(show(p))
        print(f"-> {save(p, a.output)}")
    else:
        print(show(load(a.profile)))


if __name__ == "__main__":
    main()
