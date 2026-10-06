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



# --- profile 0.2: conditions, articulation, speaking habits, pronunciation (VOICE-PROFILE.md) ---

STOPS_VL, STOPS_VD = ("p", "t", "k"), ("b", "d", "ɡ")
FRICATIVES = ("s", "z", "ʃ", "ʒ", "f", "θ")
DIPHTHONGS = ("eɪ", "aɪ", "oʊ", "aʊ", "ɔɪ")


def _med(xs, nd=1):
    xs = [x for x in xs if x is not None and x == x]
    return round(float(np.median(xs)), nd) if xs else None


def conditions(files: list[str], doc: dict, audio: np.ndarray, sr: int, device: str | None, environment: str | None) -> dict:
    """How the audio was captured, so measurements can be interpreted (and thin
    or noisy profiles flagged)."""
    import subprocess

    out = []
    for f in files:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=codec_name,sample_rate,bit_rate,channels", "-of", "json", f],
                               capture_output=True, text=True, check=True)
            st = json.loads(r.stdout)["streams"][0]
            out.append({"file": Path(f).name, "codec": st.get("codec_name"), "sample_rate": int(st.get("sample_rate", 0)),
                        "bit_rate": int(st["bit_rate"]) if st.get("bit_rate") else None, "channels": st.get("channels")})
        except Exception:
            out.append({"file": Path(f).name})
    # speech level over phone spans; noise floor from the quietest 10% of 50 ms frames outside them
    phones = phones_of(doc)
    mask = np.zeros(len(audio), bool)
    for ph in phones:
        a, b = int(ph["start_s"] * sr), int((ph["start_s"] + ph["dur_ms"] / 1000) * sr)
        mask[max(0, a):min(len(audio), b)] = True
    def db(x):
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))
    hop = int(0.05 * sr)
    quiet = [db(audio[i:i + hop]) for i in range(0, len(audio) - hop, hop) if not mask[i:i + hop].any()]
    allf = [db(audio[i:i + hop]) for i in range(0, len(audio) - hop, hop)]
    noise = float(np.percentile(quiet if len(quiet) >= 5 else allf, 10))
    speech = db(audio[mask]) if mask.any() else None
    return {"files": out, "device": device, "environment": environment,
            "speech_level_dbfs": round(speech, 1) if speech is not None else None,
            "noise_floor_dbfs": round(noise, 1),
            "snr_db": round(speech - noise, 1) if speech is not None else None,
            "transcription": doc["source"].get("aligner") or doc["source"].get("phone_model")}


def articulation(doc: dict, snd, sr: int, ceiling: float) -> dict:
    """How this voice produces sounds inside a phone: stop timing, fricative
    spectra, r-colouring, diphthong glides."""
    import transcribe as T
    from parselmouth.praat import call

    phones = phones_of(doc)
    x = snd.values[0]
    # voicing onset = first of three regular glottal pulses (pitch-track frames start
    # voicing up to half an analysis window early, which hides short VOTs)
    pp = call(snd, "To PointProcess (periodic, cc)", 60, 600)
    pulses = np.array([call(pp, "Get time from index", j) for j in range(1, call(pp, "Get number of points") + 1)])

    def voicing_onset(after: float, before: float) -> float | None:
        cand = pulses[(pulses > after) & (pulses < before)]
        for j in range(len(cand) - 2):
            d1, d2 = cand[j + 1] - cand[j], cand[j + 2] - cand[j + 1]
            if 0.0016 <= d1 <= 0.016 and 0.0016 <= d2 <= 0.016 and abs(d1 - d2) < 0.3 * max(d1, d2):
                return float(cand[j])
        return None
    # high-frequency energy envelope (first difference emphasises the burst), 1 ms frames
    hf = np.diff(x, prepend=x[0])
    fr = int(0.001 * sr)
    env = np.array([np.sum(hf[i:i + fr] ** 2) for i in range(0, len(hf) - fr, fr)])
    logenv = 10 * np.log10(env + 1e-12)

    stops = {"voiceless": {"closure_ms": [], "vot_ms": []}, "voiced": {"closure_ms": [], "vot_ms": []}}
    for i, ph in enumerate(phones[:-1]):
        if ph["ipa"] not in STOPS_VL + STOPS_VD or phones[i + 1]["ipa"] not in T.VOWELS:
            continue
        s, e = ph["start_s"], ph["start_s"] + ph["dur_ms"] / 1000
        # the burst: sharpest rise in high-frequency energy within the later part of the stop
        a, b = int((s + 0.3 * (e - s)) * 1000), min(len(logenv) - 1, int((e + 0.005) * 1000))
        if b - a < 5:
            continue
        rise = np.diff(logenv[a:b + 1])
        burst = (a + int(np.argmax(rise)) + 1) / 1000
        onset = voicing_onset(burst + 0.002, e + 0.15)
        if onset is None:
            continue
        vot, clo = (onset - burst) * 1000, (burst - s) * 1000
        if 0 <= vot <= 150 and clo >= 0:
            k = "voiceless" if ph["ipa"] in STOPS_VL else "voiced"
            stops[k]["vot_ms"].append(vot)
            stops[k]["closure_ms"].append(clo)
    stop_out = {k: {"vot_ms": _med(v["vot_ms"]), "closure_ms": _med(v["closure_ms"]), "tokens": len(v["vot_ms"])}
                for k, v in stops.items()}

    cog: dict[str, list[float]] = {}
    for ph in phones:
        if ph["ipa"] in FRICATIVES and ph["dur_ms"] >= 40:
            s, e = ph["start_s"] + ph["dur_ms"] * 0.2 / 1000, ph["start_s"] + ph["dur_ms"] * 0.8 / 1000
            part = snd.extract_part(s, e, preserve_times=False)
            spec = call(part, "To Spectrum", "yes")
            # above 1 kHz only, so voicing and low-frequency noise do not pull the centre down
            call(spec, "Filter (pass Hann band)", 1000, 0, 100)
            cog.setdefault(ph["ipa"], []).append(call(spec, "Get centre of gravity", 2))
    fric_out = {"band_hz": [1000, sr // 2],
                **{f: {"cog_hz": _med(v, 0), "tokens": len(v)} for f, v in sorted(cog.items())}}

    fm = snd.to_formant_burg(time_step=0.005, max_number_of_formants=5, maximum_formant=ceiling)
    f3r = []
    for ph in phones:
        if ph["ipa"] in ("ɹ", "ɚ", "ɜ"):
            v = fm.get_value_at_time(3, ph["start_s"] + ph["dur_ms"] / 2000)
            if v == v:
                f3r.append(v)
    vow_f3 = [fm.get_value_at_time(3, ph["start_s"] + ph["dur_ms"] / 2000) for ph in phones
              if ph["ipa"] in T.VOWELS and ph["ipa"] not in ("ɚ", "ɜ") and ph["dur_ms"] >= 40]
    vow_f3 = [v for v in vow_f3 if v == v]
    rhotic = {"f3_hz": _med(f3r, 0), "f3_drop_hz": (round(float(np.median(vow_f3) - np.median(f3r))) if f3r and vow_f3 else None),
              "tokens": len(f3r)}

    glides: dict[str, list[list[float]]] = {}
    for ph in phones:
        if ph["ipa"] in DIPHTHONGS and ph["dur_ms"] >= 60:
            t25, t75 = ph["start_s"] + ph["dur_ms"] * 0.25 / 1000, ph["start_s"] + ph["dur_ms"] * 0.75 / 1000
            a = [fm.get_value_at_time(j, t25) for j in (1, 2)]
            b = [fm.get_value_at_time(j, t75) for j in (1, 2)]
            if all(v == v for v in a + b):
                glides.setdefault(ph["ipa"], []).append([b[0] - a[0], b[1] - a[1]])
    glide_out = {d: {"delta_f1_hz": _med([g[0] for g in v], 0), "delta_f2_hz": _med([g[1] for g in v], 0), "tokens": len(v)}
                 for d, v in sorted(glides.items())}
    return {"stops": stop_out, "fricatives": fric_out, "rhotic": rhotic, "diphthongs": glide_out}


def speaking(doc: dict) -> dict:
    """Rhythm, pitch habits and phrase endings, from the transcript."""
    import transcribe as T

    pvi, pct_v, delta_c, decl, steps, final_len, final_unpitched = [], [], [], [], [], [], []
    all_vowels = [p["dur_ms"] for p in phones_of(doc) if p["ipa"] in T.VOWELS]
    med_v = float(np.median(all_vowels)) if all_vowels else None
    for u in doc["utterances"]:
        ps = [p for w in u["words"] for p in w["phones"]]
        if len(ps) < 4:
            continue
        # vocalic and consonantal intervals (runs of vowels / consonants)
        runs = []
        for p in ps:
            v = p["ipa"] in T.VOWELS
            if runs and runs[-1][0] == v:
                runs[-1][1] += p["dur_ms"]
            else:
                runs.append([v, p["dur_ms"]])
        V = [d for v, d in runs if v]
        C = [d for v, d in runs if not v]
        if V and C:
            pct_v.append(100 * sum(V) / (sum(V) + sum(C)))
            delta_c.append(float(np.std(C)))
        if len(V) >= 2:
            pvi.append(100 * np.mean([abs(a - b) / ((a + b) / 2) for a, b in zip(V, V[1:])]))
        voiced = [(p["start_s"], p["pitch_st"]) for p in ps if p.get("voiced") and p.get("pitch_st") is not None]
        if len(voiced) >= 5 and voiced[-1][0] - voiced[0][0] > 0.4:
            decl.append(float(np.polyfit([t for t, _ in voiced], [s for _, s in voiced], 1)[0]))
        steps += [abs(b[1] - a[1]) for a, b in zip(voiced, voiced[1:])]
        vows = [p for p in ps if p["ipa"] in T.VOWELS]
        if vows:
            if med_v:
                final_len.append(vows[-1]["dur_ms"] / med_v)
            final_unpitched.append(vows[-1].get("pitch_st") is None)
    return {
        "rhythm": {"percent_v": _med(pct_v), "delta_c_ms": _med(delta_c), "npvi_v": _med(pvi)},
        "pitch": {"declination_st_per_s": _med(decl, 2), "median_step_st": _med(steps, 2)},
        "phrase_final": {"lengthening_ratio": _med(final_len, 2),
                         "unpitched_share": round(float(np.mean(final_unpitched)), 2) if final_unpitched else None},
        "utterances": len(doc["utterances"]),
    }


def pronunciation(doc: dict) -> dict | None:
    """How often this speaker departs from dictionary pronunciations, from the
    transcriber's comparison of what it heard with CMUdict. Only meaningful when
    phones come from the recogniser, not from forced alignment."""
    src = doc["source"]
    if src.get("aligner") or not src.get("alignment", {}).get("top_differences"):
        return None
    canon_counts: dict[str, int] = {}
    for w in (w for u in doc["utterances"] for w in u["words"]):
        for c in (w.get("canon") or "").split():
            canon_counts[c] = canon_counts.get(c, 0) + 1
    rates = {}
    for k, n in src["alignment"]["top_differences"].items():
        if "→" in k:
            c = k.split("→")[0]
            if canon_counts.get(c, 0) >= 3:
                rates[k] = {"rate": round(n / canon_counts[c], 2), "count": n, "of": canon_counts[c]}
    total = src["alignment"].get("canonical_phones") or 0
    return {"phones_compared": total,
            "match_share": round(src["alignment"].get("match", 0) / total, 2) if total else None,
            "substitutions": rates}


def build(inputs: list[str], pid: str, synthetic: bool, aligner: str,
          device: str | None = None, environment: str | None = None) -> dict:
    import transcribe as T

    import parselmouth

    if len(inputs) == 1 and inputs[0].endswith(".json"):
        doc = json.loads(Path(inputs[0]).read_text())
        audio = load_timeline(doc, T.SR)
        a = doc["source"]["audio"]
        files = [str(HERE / f) for f in ([a] if isinstance(a, str) else a)]
    else:
        doc = T.transcribe(inputs, aligner=aligner)
        audio = np.concatenate([T.load_audio(p) for p in inputs])
        files = inputs
    m = measure(doc, audio, T.SR)
    src = m.pop("source")
    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=T.SR)
    m["conditions"] = conditions(files, doc, audio, T.SR, device, environment)
    m["articulation"] = articulation(doc, snd, T.SR, m["timbre"]["formant_ceiling_hz"])
    m["speaking"] = speaking(doc)
    m["pronunciation"] = pronunciation(doc)
    return {
        "prosotype_profile": "0.2",
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
    if "conditions" in p:
        c = p["conditions"]
        f = c["files"][0] if c.get("files") else {}
        lines.append(f"  capture  {f.get('codec')} {f.get('sample_rate')} Hz, speech {c.get('speech_level_dbfs')} dBFS, "
                     f"noise {c.get('noise_floor_dbfs')} dBFS, SNR {c.get('snr_db')} dB")
    if "articulation" in p:
        a = p["articulation"]
        st = a["stops"]
        lines.append(f"  stops    voiceless VOT {st['voiceless']['vot_ms']} ms, closure {st['voiceless']['closure_ms']} ms "
                     f"(n={st['voiceless']['tokens']}); voiced VOT {st['voiced']['vot_ms']} ms (n={st['voiced']['tokens']})")
        lines.append(f"  frics    " + ", ".join(f"{k} {v['cog_hz']} Hz (n={v['tokens']})" for k, v in a["fricatives"].items() if k != "band_hz")
                     + f"; r F3 {a['rhotic']['f3_hz']} Hz (drop {a['rhotic']['f3_drop_hz']}, n={a['rhotic']['tokens']})")
    if "speaking" in p:
        sp = p["speaking"]
        lines.append(f"  rhythm   %V {sp['rhythm']['percent_v']}, deltaC {sp['rhythm']['delta_c_ms']} ms, nPVI-V {sp['rhythm']['npvi_v']}; "
                     f"declination {sp['pitch']['declination_st_per_s']} st/s, step {sp['pitch']['median_step_st']} st; "
                     f"final lengthening x{sp['phrase_final']['lengthening_ratio']}, unpitched {sp['phrase_final']['unpitched_share']}")
    if p.get("pronunciation"):
        subs = sorted(p["pronunciation"]["substitutions"].items(), key=lambda kv: -kv[1]["rate"])[:5]
        lines.append("  pronounce " + ", ".join(f"{k} {v['rate']:.0%} ({v['count']}/{v['of']})" for k, v in subs))
    if "synth" in p:
        lines.append(f"  synth    controls for {', '.join(p['synth'])}")
    return "\n".join(lines)


SCHEMAS = PROFILES / "schema"


def validate(p: dict) -> list[str]:
    """Problems with a profile against its version's schema (VOICE-PROFILE.md §2)."""
    import jsonschema

    v = p.get("prosotype_profile")
    path = SCHEMAS / f"voice-profile-{v}.schema.json"
    if not path.exists():  # a minor version only adds: check against the newest schema of the same major
        same = sorted(SCHEMAS.glob(f"voice-profile-{str(v).split('.')[0]}.*.schema.json"))
        if not same:
            return [f"no schema for version {v!r}"]
        path = same[-1]
    schema = json.loads(path.read_text())
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(p), key=lambda e: list(e.path))
    out = [f"{'/'.join(map(str, e.path)) or '(top)'}: {e.message}" for e in errs]
    if p.get("kind") == "person" and p.get("private") is False:
        out.append("kind is person but private is false: profiles of people are private by default")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("inputs", nargs="+")
    b.add_argument("--id", required=True)
    b.add_argument("-o", "--output", type=Path)
    b.add_argument("--synthetic", action="store_true", help="a synthetic voice (public by default)")
    b.add_argument("--aligner", choices=["recogniser", "mfa"], default="recogniser")
    b.add_argument("--device", help="recording device or microphone, for the conditions block")
    b.add_argument("--environment", help="room or setting, for the conditions block")
    s = sub.add_parser("show")
    s.add_argument("profile")
    v = sub.add_parser("validate")
    v.add_argument("profiles", nargs="+")
    a = ap.parse_args()
    if a.cmd == "validate":
        bad = 0
        for f in a.profiles:
            errs = validate(load(f))
            bad += bool(errs)
            print(f"{'ok     ' if not errs else 'INVALID'} {f}" + "".join(f"\n    {e}" for e in errs))
        raise SystemExit(1 if bad else 0)
    if a.cmd == "build":
        p = build(a.inputs, a.id, a.synthetic, a.aligner, a.device, a.environment)
        print(show(p))
        print(f"-> {save(p, a.output)}")
    else:
        print(show(load(a.profile)))


if __name__ == "__main__":
    main()
