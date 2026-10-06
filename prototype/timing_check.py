#!/usr/bin/env python3
"""Check the transcriber's phone timing against reference boundaries.

    timing_check.py synth                    speech we synthesised, so its timing is known
    timing_check.py buckeye DIR [--per-speaker 10] [--unpack]

The transcriber's phone recogniser (transcribe.py: wav2vec2 CTC spikes,
phone = spike to next spike unless a pause intervenes) runs on each clip.
Its phones are aligned to the reference phones by identity (edit distance,
vowel-for-vowel and consonant-for-consonant substitutions allowed), and
every aligned pair is compared:

  onset error      hypothesis start - reference start (ms, signed)
  duration ratio   hypothesis duration / reference duration

Reported: median and spread of the onset error, the share of onsets within
20 ms (the usual tolerance for automatic alignment), how well durations
correlate, and the same split by vowels, stops and other consonants.

References:
  synth    FastSpeech 2 (synthesize.py) speaking samples/party_three_ways.json
           and samples/smoke/say_natural.json; each phone's span is exactly the
           frames we gave it. A proxy: the model's own boundary placement is
           learned, not hand-checked.
  buckeye  The Buckeye Corpus of Conversational Speech (Pitt et al. 2007):
           hand-corrected phone labels. Register and download it yourself from
           https://buckeyecorpus.osu.edu (free for non-commercial research);
           point DIR at the folder of its zips (--unpack extracts them) or at
           the extracted s*.wav / s*.phones files. Clips are runs of 2-15 s of
           the speaker's own phones between pauses; interviewer speech and
           noise are skipped.

Writes a summary (aggregate numbers only) to samples/timing/<source>.json and
per-phone detail to ../.timing-local/ (gitignored: Buckeye content may not be
redistributed).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import tempfile
import zipfile
from pathlib import Path

import numpy as np

import pack
import transcribe as T

HERE = Path(__file__).parent
SUMMARY_DIR = HERE / "samples" / "timing"
LOCAL_DIR = HERE.parent / ".timing-local"
TOLERANCE_MS = 20.0

# Buckeye phone labels -> en-1 IPA. Nasalised vowels ("aan", "ihn") fold to the
# plain vowel; "nx" (nasal flap) to n; "tq" is a glottal stop.
BUCKEYE = {
    "aa": "ɑ", "ae": "æ", "ah": "ʌ", "ao": "ɔ", "aw": "aʊ", "ay": "aɪ", "eh": "ɛ", "er": "ɚ",
    "ey": "eɪ", "ih": "ɪ", "iy": "i", "ow": "oʊ", "oy": "ɔɪ", "uh": "ʊ", "uw": "u",
    "b": "b", "ch": "tʃ", "d": "d", "dh": "ð", "dx": "ɾ", "el": "l̩", "em": "m̩", "en": "n̩",
    "eng": "ŋ", "f": "f", "g": "ɡ", "h": "h", "hh": "h", "jh": "dʒ", "k": "k", "l": "l", "m": "m",
    "n": "n", "ng": "ŋ", "nx": "n", "p": "p", "r": "ɹ", "s": "s", "sh": "ʃ", "t": "t", "th": "θ",
    "tq": "ʔ", "v": "v", "w": "w", "y": "j", "z": "z", "zh": "ʒ",
}
for _v in ("aa", "ae", "ah", "ao", "aw", "ay", "eh", "er", "ey", "ih", "iy", "ow", "oy", "uh", "uw"):
    BUCKEYE[_v + "n"] = BUCKEYE[_v]


# --- hypothesis -----------------------------------------------------------------


def recognise(audio: np.ndarray) -> list[dict]:
    """The transcriber's phones for one clip: [{ipa, start, end}] in seconds."""
    logp, tokens, _ = T.ctc(audio)
    if not tokens:
        return []
    ac = T.Acoustics(audio)
    T.spans(tokens, logp, ac.silent_frames(len(logp)))
    return [{"ipa": p["ipa"], "start": p["start"], "end": p["end"]} for p in T.expand(tokens)]


# --- alignment and scoring ------------------------------------------------------


def align(ref: list[dict], hyp: list[dict]) -> list[tuple[dict, dict]]:
    """Pairs of (reference, hypothesis) phones on the minimum-cost path."""
    n, m = len(ref), len(hyp)
    D = np.zeros((n + 1, m + 1))
    D[:, 0] = np.arange(n + 1)
    D[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = min(D[i - 1, j - 1] + T.sub_cost(ref[i - 1]["ipa"], hyp[j - 1]["ipa"]),
                          D[i - 1, j] + 1, D[i, j - 1] + 1)
    pairs, i, j = [], n, m
    while i > 0 and j > 0:
        c = T.sub_cost(ref[i - 1]["ipa"], hyp[j - 1]["ipa"])
        if D[i, j] == D[i - 1, j - 1] + c and c < 1.0:
            pairs.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j] + 1:
            i -= 1
        elif D[i, j] == D[i, j - 1] + 1:
            j -= 1
        else:
            i, j = i - 1, j - 1
    return pairs[::-1]


phone_class = T.phone_class


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {"pairs": 0}
    on = np.array([r["onset_ms"] for r in rows])
    rd = np.array([r["ref_ms"] for r in rows])
    hd = np.array([r["hyp_ms"] for r in rows])
    return {
        "pairs": len(rows),
        "onset_error_ms": {"median_signed": round(float(np.median(on)), 1),
                           "median_abs": round(float(np.median(np.abs(on))), 1),
                           "p90_abs": round(float(np.percentile(np.abs(on), 90)), 1)},
        "onsets_within_20ms": round(float(np.mean(np.abs(on) <= TOLERANCE_MS)), 3),
        "duration_ms": {"ref_median": round(float(np.median(rd)), 1), "hyp_median": round(float(np.median(hd)), 1)},
        "duration_ratio_median": round(float(np.median(hd / rd)), 2),
        "duration_log_correlation": round(float(np.corrcoef(np.log(rd), np.log(hd))[0, 1]), 3) if len(rows) > 2 else None,
        "same_level_16a": round(float(np.mean([pack.q_dur(a, 3) == pack.q_dur(b, 3) for a, b in zip(rd, hd)])), 3),
        "within_one_level_16a": round(float(np.mean([abs(pack.q_dur(a, 3) - pack.q_dur(b, 3)) <= 1 for a, b in zip(rd, hd)])), 3),
    }


def score(clips: list[tuple[str, np.ndarray, list[dict]]]) -> tuple[dict, list[dict]]:
    rows, n_ref, n_hyp = [], 0, 0
    for name, audio, ref in clips:
        hyp = recognise(audio)
        n_ref += len(ref)
        n_hyp += len(hyp)
        for r, h in align(ref, hyp):
            rows.append({"clip": name, "ref": r["ipa"], "hyp": h["ipa"], "class": phone_class(r["ipa"]),
                         "onset_ms": (h["start"] - r["start"]) * 1000,
                         "ref_ms": max(1.0, (r["end"] - r["start"]) * 1000),
                         "hyp_ms": max(1.0, (h["end"] - h["start"]) * 1000)})
    out = {"clips": len(clips), "reference_phones": n_ref, "recognised_phones": n_hyp,
           "aligned_share": round(len(rows) / max(1, n_ref), 3), "all": summarise(rows)}
    for c in ("vowel", "stop", "other consonant"):
        out[c] = summarise([r for r in rows if r["class"] == c])
    return out, rows


# --- references -------------------------------------------------------------------


def synth_clips() -> list[tuple[str, np.ndarray, list[dict]]]:
    import synthesize as S

    s = S.Synth()
    cal = json.loads(S.CAL_FILE.read_text())
    clips = []
    for path in ("samples/party_three_ways.json", "samples/smoke/say_natural.json"):
        doc = json.loads((HERE / path).read_text())
        for k, utt in enumerate(doc["utterances"]):
            wav, spans = S.speak(s, utt, cal)
            audio = resample(wav, S.SR, T.SR)
            ref = [{"ipa": pack.normalise_ipa(ph["ipa"]), "start": float(a), "end": float(b)} for ph, a, b in spans]
            clips.append((f"{Path(path).stem}#{k}", audio, ref))
    return clips


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "f32le", "-ar", str(sr_in), "-ac", "1", "-i", "-",
                          "-ar", str(sr_out), "-f", "f32le", "-"], input=x.astype(np.float32).tobytes(),
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def unpack(root: Path) -> None:
    """Extract Buckeye's nested zips in place (speaker zips contain track zips)."""
    done = set()
    while True:
        todo = [z for z in root.rglob("*.zip") if z not in done]
        if not todo:
            return
        for z in todo:
            with zipfile.ZipFile(z) as f:
                f.extractall(z.parent)
            done.add(z)


def read_buckeye(path: Path) -> list[tuple[float, float, str]]:
    """(start, end, label) from a .phones file; labels lower-case, extras stripped."""
    out, prev, body = [], 0.0, False
    for line in path.read_text(errors="replace").splitlines():
        if not body:
            body = line.strip() == "#"
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        end = float(parts[0])
        label = parts[2].split(";")[0].split()[0].strip().lower() if parts[2].strip() else ""
        out.append((prev, end, label))
        prev = end
    return out


def buckeye_clips(root: Path, per_speaker: int, seed: int) -> list[tuple[str, np.ndarray, list[dict]]]:
    tracks = sorted(root.rglob("s[0-9][0-9][0-9][0-9]*.phones"))
    if not tracks:
        raise SystemExit(f"no Buckeye .phones files under {root} (try --unpack)")
    rng = random.Random(seed)
    by_speaker: dict[str, list] = {}
    for ph in tracks:
        wav = ph.with_suffix(".wav")
        if not wav.exists():
            continue
        segs = read_buckeye(ph)
        run: list[dict] = []
        for a, b, lab in segs + [(0, 0, "<end>")]:
            ipa = BUCKEYE.get(lab)
            if ipa and b > a:
                run.append({"ipa": ipa, "start": a, "end": b})
                continue
            # anything else ends a clip: silence, interviewer, noise, laughter, unknown
            if run and 2.0 <= run[-1]["end"] - run[0]["start"] <= 15.0:
                by_speaker.setdefault(ph.name[:3], []).append((ph.stem, wav, run))
            run = []
    clips = []
    for spk in sorted(by_speaker):
        chosen = rng.sample(by_speaker[spk], min(per_speaker, len(by_speaker[spk])))
        for stem, wav, run in chosen:
            t0, t1 = run[0]["start"] - 0.15, run[-1]["end"] + 0.15  # a little context each side
            audio = load_span(wav, max(0.0, t0), t1)
            off = max(0.0, t0)
            ref = [{"ipa": p["ipa"], "start": p["start"] - off, "end": p["end"] - off} for p in run]
            clips.append((f"{stem}@{run[0]['start']:.2f}", audio, ref))
    return clips


def load_span(path: Path, a: float, b: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(path),
                          "-ac", "1", "-ar", str(T.SR), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# --- main -------------------------------------------------------------------------


def report(name: str, res: dict) -> None:
    print(f"\n{name}: {res['clips']} clips, {res['reference_phones']} reference phones, "
          f"{res['recognised_phones']} recognised, {res['aligned_share']:.0%} aligned")
    print(f"{'':16}{'pairs':>7}{'onset bias':>12}{'|onset| med':>13}{'p90':>7}{'≤20 ms':>8}"
          f"{'dur ratio':>11}{'log r':>7}{'same lvl':>10}{'±1 lvl':>8}")
    for k in ("all", "vowel", "stop", "other consonant"):
        s = res[k]
        if not s.get("pairs"):
            continue
        o = s["onset_error_ms"]
        print(f"{k:16}{s['pairs']:>7}{o['median_signed']:>+11.1f} {o['median_abs']:>12.1f}{o['p90_abs']:>7.0f}"
              f"{s['onsets_within_20ms']:>8.0%}{s['duration_ratio_median']:>11.2f}"
              f"{s['duration_log_correlation'] or 0:>7.2f}{s['same_level_16a']:>10.0%}{s['within_one_level_16a']:>8.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=["synth", "buckeye"])
    ap.add_argument("dir", nargs="?", type=Path)
    ap.add_argument("--per-speaker", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--unpack", action="store_true")
    a = ap.parse_args()
    if a.source == "buckeye":
        if not a.dir:
            ap.error("buckeye needs DIR")
        if a.unpack:
            unpack(a.dir)
        clips = buckeye_clips(a.dir, a.per_speaker, a.seed)
    else:
        clips = synth_clips()
    res, rows = score(clips)
    res["source"] = a.source
    res["phone_model"] = f"{T.PHONE_MODEL}@{T.PHONE_MODEL_REV}"
    if a.source == "buckeye":
        res["settings"] = {"per_speaker": a.per_speaker, "seed": a.seed}
        res["acknowledgement"] = ("Buckeye Corpus of Conversational Speech, Pitt, M.A., Dilley, L., Johnson, K., "
                                  "Kiesling, S., Raymond, W., Hume, E. and Fosler-Lussier, E. (2007), Ohio State University")
    report(a.source, res)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    (SUMMARY_DIR / f"{a.source}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    LOCAL_DIR.mkdir(exist_ok=True)
    (LOCAL_DIR / f"{a.source}_pairs.json").write_text(json.dumps(rows, ensure_ascii=False) + "\n")
    print(f"\nsummary -> {(SUMMARY_DIR / (a.source + '.json')).relative_to(HERE)}; detail -> {LOCAL_DIR}")


if __name__ == "__main__":
    main()
