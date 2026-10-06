#!/usr/bin/env python3
"""Audio file -> ProsoType JSON.

    transcribe.py IN.(wav|m4a|aiff|mp3) [IN2 ...] [-o OUT.json] [--label TEXT ...]

Several files are treated as consecutive recordings of one speaker: they
share one set of speaker baselines, and each becomes one or more utterances
labelled with the file name.

Pipeline (SPEC.md section 7):
  1. Words: Whisper large-v3-turbo via mlx-whisper (text and rough times).
  2. Phones as spoken: facebook/wav2vec2-lv-60-espeak-cv-ft, greedy CTC on
     20 ms frames. Each recognised phone is a spike of one or more frames.
  3. Phone spans: the recogniser's spikes sit at phone onsets, so a phone
     runs from its spike to the next one. Quiet stretches of 120 ms or more
     (Praat intensity 25 dB below the loud end of the recording) are pauses
     and belong to no phone; a stop keeps up to 60 ms of its closure.
  4. Words: recognised phones are aligned (edit distance) to CMUdict
     pronunciations of Whisper's words; each phone takes the word it aligns
     to. The alignment also counts where as-spoken phones differ from the
     dictionary.
  5. Pitch and intensity from Praat via parselmouth. Per phone: median F0
     over voiced frames, mean intensity (power domain). Normalised to the
     speaker: semitones from the median F0 of voiced phones, dB from the mean
     of all phones.

Single speaker ("S1"). Utterances are Whisper segments (labelled by file).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

import pack

HERE = Path(__file__).parent
# Models live on the project drive, not in ~/.cache (the internal disk is small).
os.environ.setdefault("HF_HOME", str(HERE.parent / ".hf-cache"))
os.environ.setdefault("HF_HUB_CACHE", str(HERE.parent / ".hf-cache" / "hub"))
SR = 16000
HOP = 320  # wav2vec2 conv stride in samples
FRAME_S = HOP / SR  # 20 ms
from fetch import PHONE_MODEL, PHONE_MODEL_REV, WORD_MODEL, WORD_MODEL_REV  # pinned revisions
CMUDICT = HERE / "data" / "cmudict.dict"

PAUSE_FRAMES = 6  # 120 ms of quiet counts as a pause
SILENCE_DB_BELOW = 25.0
STOPS = {"p", "t", "k", "b", "d", "ɡ", "tʃ", "dʒ"}
VOWELS = set("iɪeɛæaɑɒɔoʊuʌəɚɜɐ") | {"eɪ", "aɪ", "ɔɪ", "aʊ", "oʊ", "əʊ", "ɪə", "ɛə", "ʊə"}

# Recogniser labels that are two table phones; their span is split evenly.
SPLIT = {
    "ɑːɹ": ["ɑ", "ɹ"], "ɔːɹ": ["ɔ", "ɹ"], "oːɹ": ["o", "ɹ"], "ɛɹ": ["ɛ", "ɹ"],
    "ɪɹ": ["ɪ", "ɹ"], "ʊɹ": ["ʊ", "ɹ"], "əl": ["ə", "l"], "aɪɚ": ["aɪ", "ɚ"],
    "aɪə": ["aɪ", "ə"], "ts": ["t", "s"], "ju": ["j", "u"],
}
FOLD = {"iə": "ɪə"}

ARPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s",
    "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def load_audio(path: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# --- 1. words ------------------------------------------------------------------


def whisper_words(path: str) -> list[dict]:
    import mlx_whisper
    from huggingface_hub import snapshot_download

    model_dir = snapshot_download(WORD_MODEL, revision=WORD_MODEL_REV)
    res = mlx_whisper.transcribe(path, path_or_hf_repo=model_dir, word_timestamps=True,
                                 language="en", condition_on_previous_text=False)
    segs = []
    for seg in res["segments"]:
        words = [{"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                 for w in seg.get("words", []) if w["word"].strip()]
        if words:
            segs.append({"text": seg["text"].strip(), "words": words})
    return segs


# --- 2. phones -----------------------------------------------------------------


def ctc(audio: np.ndarray) -> tuple[np.ndarray, list[dict], int]:
    """Frame log-posteriors and greedy CTC tokens [{tok, id, f0, f1, conf}]
    (f0..f1 inclusive frames of the spike)."""
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

    fe = Wav2Vec2FeatureExtractor.from_pretrained(PHONE_MODEL, revision=PHONE_MODEL_REV)
    model = Wav2Vec2ForCTC.from_pretrained(PHONE_MODEL, revision=PHONE_MODEL_REV).eval()
    vocab = json.loads(Path(hf_hub_download(PHONE_MODEL, "vocab.json", revision=PHONE_MODEL_REV)).read_text())
    id2tok = {i: t for t, i in vocab.items()}
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)

    # 30 s chunks with 1 s of context either side keep memory bounded.
    chunk, ctx = 30 * SR, 1 * SR
    parts = []
    for s in range(0, len(audio), chunk):
        a0, a1 = max(0, s - ctx), min(len(audio), s + chunk + ctx)
        x = fe(audio[a0:a1], sampling_rate=SR, return_tensors="pt").input_values.to(device)
        with torch.no_grad():
            lp = torch.log_softmax(model(x).logits[0].float(), dim=-1).cpu().numpy()
        f0 = (s - a0) // HOP
        parts.append(lp[f0: f0 + (min(len(audio), s + chunk) - s) // HOP])
    logp = np.concatenate(parts)
    blank = vocab["<pad>"]

    tokens = []
    best = logp.argmax(-1)
    f = 0
    while f < len(best):
        k = best[f]
        g = f
        while g + 1 < len(best) and best[g + 1] == k:
            g += 1
        if k != blank and not id2tok[k].startswith("<"):
            conf = float(np.exp(logp[f:g + 1, k].mean()))
            tokens.append({"tok": id2tok[k], "id": int(k), "f0": f, "f1": g, "conf": conf})
        f = g + 1
    return logp, tokens, blank


def spans(tokens: list[dict], logp: np.ndarray, silent: np.ndarray) -> None:
    """Set 'a' and 'b' (frame start, exclusive end) on each token."""
    n = len(logp)

    def silent_run(lo: int, hi: int) -> tuple[int, int] | None:
        """Longest run of silent frames in [lo, hi), if at least PAUSE_FRAMES."""
        best, f = None, lo
        while f < hi:
            if silent[f]:
                g = f
                while g < hi and silent[g]:
                    g += 1
                if g - f >= PAUSE_FRAMES and (best is None or g - f > best[1] - best[0]):
                    best = (f, g)
                f = g
            else:
                f += 1
        return best

    def closure(tok: dict) -> int:
        return 3 if tok["tok"] in STOPS else 0  # let a stop keep up to 60 ms of closure

    # The model's spikes sit at phone onsets (checked against Praat pitch and
    # intensity on test clips), so a phone runs from its spike to the next
    # spike, unless a pause intervenes.
    for i, t in enumerate(tokens):
        if i == 0:
            run = silent_run(0, t["f0"])
            t["a"] = min(t["f0"], max(run[0], run[1] - closure(t))) if run else t["f0"]
        if i + 1 < len(tokens):
            u = tokens[i + 1]
            run = silent_run(t["f1"] + 1, u["f0"])
            if run:
                t["b"] = run[0]
                u["a"] = min(u["f0"], max(run[0], run[1] - closure(u)))
            else:
                t["b"] = u["a"] = u["f0"]
        else:
            run = silent_run(t["f1"] + 1, n)
            t["b"] = run[0] if run else min(n, t["f1"] + 3)


def expand(tokens: list[dict]) -> list[dict]:
    """Recogniser labels -> table phones, with spans in seconds."""
    out = []
    for t in tokens:
        parts = SPLIT.get(t["tok"], [FOLD.get(t["tok"], t["tok"])])
        a, b = t["a"] * FRAME_S, max(t["b"], t["a"] + 1) * FRAME_S
        step = (b - a) / len(parts)
        for j, ipa in enumerate(parts):
            ipa = pack.normalise_ipa(ipa)
            prev = out[-1] if out else None
            if prev and prev["ipa"] == ipa and (len(parts) > 1 or prev["raw"] in SPLIT):
                # "ɑːɹ ɹ": a split label followed by the phone it already contains
                prev["end"] = a + (j + 1) * step
                continue
            out.append({"ipa": ipa, "start": a + j * step, "end": a + (j + 1) * step,
                        "conf": t["conf"], "raw": t["tok"]})
    return out


# --- 4. word alignment ---------------------------------------------------------


_cmu: dict[str, list[str]] | None = None


def canonical(word: str) -> list[str] | None:
    global _cmu
    if _cmu is None:
        _cmu = {}
        for line in CMUDICT.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("#")[0].split()
            if parts and parts[0] not in _cmu:  # first pronunciation only
                _cmu[parts[0]] = [
                    "ə" if p == "AH0" else ARPA[re.sub(r"\d", "", p)] for p in parts[1:]
                ]
    key = re.sub(r"[^a-z']", "", word.lower().replace("’", "'"))
    return _cmu.get(key)


def sub_cost(r: str, c: str) -> float:
    if c == "?":
        return 0.3
    if r == c:
        return 0.0
    if (r in VOWELS) == (c in VOWELS):
        return 0.6
    return 1.0


def align(phones: list[dict], words: list[dict]) -> dict:
    """Assign each phone a word index by edit-distance alignment against the
    words' dictionary pronunciations. Returns alignment statistics."""
    canon, owner = [], []
    oov = 0
    for wi, w in enumerate(words):
        c = canonical(w["text"])
        if c is None:
            oov += 1
            letters = len(re.sub(r"[^A-Za-z]", "", w["text"])) or 1
            c = ["?"] * max(1, round(letters * 0.8))
        w["canon"] = c
        canon += c
        owner += [wi] * len(c)
    R, C = [p["ipa"] for p in phones], canon
    n, m = len(R), len(C)
    D = np.zeros((n + 1, m + 1))
    D[:, 0] = np.arange(n + 1)
    D[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = min(D[i - 1, j - 1] + sub_cost(R[i - 1], C[j - 1]), D[i - 1, j] + 1, D[i, j - 1] + 1)
    # trace back
    i, j = n, m
    assign: list[int | None] = [None] * n
    stats = Counter()
    subs = Counter()
    while i > 0 or j > 0:
        if i > 0 and j > 0 and D[i, j] == D[i - 1, j - 1] + sub_cost(R[i - 1], C[j - 1]):
            assign[i - 1] = owner[j - 1]
            if C[j - 1] == "?":
                stats["oov_phone"] += 1
            elif R[i - 1] == C[j - 1]:
                stats["match"] += 1
            else:
                stats["sub"] += 1
                subs[f"{C[j - 1]}→{R[i - 1]}"] += 1
            i, j = i - 1, j - 1
        elif i > 0 and D[i, j] == D[i - 1, j] + 1:
            stats["ins"] += 1
            subs[f"+{R[i - 1]}"] += 1
            i -= 1
        else:
            stats["del"] += 1
            subs[f"-{C[j - 1]}"] += 1
            j -= 1
    # inserted phones join the neighbouring word nearest in time
    for k, wi in enumerate(assign):
        if wi is None:
            prev = next((assign[x] for x in range(k - 1, -1, -1) if assign[x] is not None), None)
            nxt = next((assign[x] for x in range(k + 1, n) if assign[x] is not None), None)
            if prev is None or nxt is None:
                assign[k] = prev if nxt is None else nxt
            else:
                t = phones[k]["start"]
                assign[k] = prev if abs(t - words[prev]["end"]) <= abs(t - words[nxt]["start"]) else nxt
    for p, wi in zip(phones, assign):
        p["word"] = wi
    return {"canonical_phones": m, "recognised_phones": n, "oov_words": oov,
            **dict(stats), "top_differences": dict(subs.most_common(15))}


# --- 5. acoustics --------------------------------------------------------------


class Acoustics:
    def __init__(self, audio: np.ndarray):
        import parselmouth

        snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SR)
        pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=60, pitch_ceiling=500)
        self.pt = pitch.xs()
        self.f0 = pitch.selected_array["frequency"]  # 0 = unvoiced
        inten = snd.to_intensity(minimum_pitch=60, time_step=0.01)
        self.it = inten.xs()
        self.db = inten.values[0]

    def silent_frames(self, n: int) -> np.ndarray:
        centres = (np.arange(n) + 0.5) * FRAME_S
        db = np.interp(centres, self.it, self.db, left=-100, right=-100)
        return db < np.percentile(self.db, 90) - SILENCE_DB_BELOW

    def span(self, a: float, b: float) -> tuple[bool, float | None, float]:
        m = (self.pt >= a) & (self.pt < b)
        f = self.f0[m]
        voiced = f[f > 0]
        is_voiced = len(f) > 0 and len(voiced) >= max(1, 0.5 * len(f))
        f0 = float(np.median(voiced)) if len(voiced) else None
        mi = (self.it >= a) & (self.it < b)
        if not mi.any():
            d = np.abs(self.it - (a + b) / 2)
            mi = d == d.min()
        db = float(10 * np.log10(np.mean(10 ** (self.db[mi] / 10))))
        return is_voiced, f0, db


# --- assemble ------------------------------------------------------------------


def analyse(path: str) -> dict:
    """One audio file -> segments, words with phones (absolute F0 and dB)."""
    audio = load_audio(path)
    segs = whisper_words(path)
    logp, tokens, _ = ctc(audio)
    ac = Acoustics(audio)
    spans(tokens, logp, ac.silent_frames(len(logp)))
    phones = expand(tokens)
    words = [dict(w, seg=si) for si, s in enumerate(segs) for w in s["words"]]
    stats = align(phones, words) if words and phones else {}
    for w in words:
        w["phones"] = [p for p in phones if p.get("word") is not None and words[p["word"]] is w]
        # no silence inside a word: close gaps by extending the earlier phone
        for p, q in zip(w["phones"], w["phones"][1:]):
            p["end"] = q["start"]
        for p in w["phones"]:
            p["voiced"], p["f0"], p["db"] = ac.span(p["start"], p["end"])
    return {"path": str(path), "duration_s": len(audio) / SR, "segs": segs, "words": words,
            "phones": phones, "tokens": tokens, "stats": stats}


def transcribe(paths: list[str], labels: list[str] | None = None) -> dict:
    """Audio files of one speaker -> one document. Files follow each other in
    time; speaker baselines are computed over all of them."""
    runs = [analyse(p) for p in paths]
    phones = [p for r in runs for p in r["phones"] if "db" in p]
    f0s = [p["f0"] for p in phones if p["voiced"] and p["f0"]]
    # Loudness baseline: mean over vowels, so that a typical vowel is 0 dB and
    # consonants' intrinsically lower energy does not push every vowel "loud".
    dbs = [p["db"] for p in phones if p["ipa"] in VOWELS] or [p["db"] for p in phones]
    f0_med = float(np.median(f0s)) if f0s else 0.0
    db_mean = float(np.mean(dbs)) if dbs else 0.0

    stats = Counter()
    diffs = Counter()
    for r in runs:
        for k, v in r["stats"].items():
            if k == "top_differences":
                diffs.update(v)
            else:
                stats[k] += v
    single = len(runs) == 1
    doc = {
        "prosotype": "0.1", "language": "en", "phone_table": "en-1",
        "source": {"audio": runs[0]["path"] if single else [r["path"] for r in runs],
                   "duration_s": round(sum(r["duration_s"] for r in runs), 3),
                   "word_model": f"{WORD_MODEL}@{WORD_MODEL_REV}", "phone_model": f"{PHONE_MODEL}@{PHONE_MODEL_REV}",
                   "transcript": "\n".join(" ".join(s["text"] for s in r["segs"]) for r in runs),
                   "raw_phones": "\n".join(" ".join(t["tok"] for t in r["tokens"]) for r in runs),
                   "alignment": {**dict(stats), "top_differences": dict(diffs.most_common(15))}},
        "speakers": {"S1": {"f0_median_hz": round(f0_med, 1), "loudness_mean_db": round(db_mean, 1)}},
        "utterances": [],
    }
    offset = 0.0
    for ri, r in enumerate(runs):
        label = labels[ri] if labels and ri < len(labels) else (None if single else Path(r["path"]).stem)
        for si, seg in enumerate(r["segs"]):
            ulabel = seg["text"][:60] if label is None else (label if len(r["segs"]) == 1 else f"{label} {si + 1}")
            utt = {"speaker": "S1", "label": ulabel, "words": []}
            for w in r["words"]:
                if w["seg"] != si:
                    continue
                word = {"text": w["text"], "canon": " ".join(w.get("canon", [])), "phones": []}
                for p in w["phones"]:
                    v = bool(p["voiced"] and p["f0"])
                    word["phones"].append({
                        "ipa": p["ipa"], "start_s": round(offset + p["start"], 3),
                        "dur_ms": round((p["end"] - p["start"]) * 1000, 1), "voiced": v,
                        "pitch_st": round(12 * math.log2(p["f0"] / f0_med), 2) if (v and f0_med) else None,
                        "loud_db": round(p["db"] - db_mean, 2), "conf": round(p["conf"], 3),
                    })
                if word["phones"]:
                    word["start_s"] = word["phones"][0]["start_s"]
                    last = word["phones"][-1]
                    word["end_s"] = round(last["start_s"] + last["dur_ms"] / 1000, 3)
                else:
                    word["start_s"], word["end_s"] = round(offset + w["start"], 3), round(offset + w["end"], 3)
                utt["words"].append(word)
            if utt["words"]:
                doc["utterances"].append(utt)
        offset += r["duration_s"]
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="one or more audio files of the same speaker, in order")
    ap.add_argument("-o", "--output")
    ap.add_argument("--label", action="append", help="utterance label per input file (repeatable)")
    a = ap.parse_args()
    doc = transcribe(a.inputs, a.label)
    out = a.output or str(Path(a.inputs[0]).with_suffix(".json"))
    Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    n = sum(len(w["phones"]) for u in doc["utterances"] for w in u["words"])
    nw = sum(len(u["words"]) for u in doc["utterances"])
    st = doc["source"]["alignment"]
    print(f"{out}: {len(doc['utterances'])} utterances, {nw} words, {n} phones; "
          f"vs dictionary: {st.get('match', 0)} match, {st.get('sub', 0)} sub, "
          f"{st.get('ins', 0)} ins, {st.get('del', 0)} del, {st.get('oov_words', 0)} OOV words",
          file=sys.stderr)


if __name__ == "__main__":
    main()
