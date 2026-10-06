"""Montreal Forced Aligner: phone boundaries for known words.

MFA 3.4.2 runs from its own conda environment in ../.mfa/env, with models in
../.mfa/root (english_us_arpa acoustic model and dictionary). Set it up with:

    MAMBA_ROOT_PREFIX=../.mfa/mamba CONDA_PKGS_DIRS=../.mfa/pkgs \\
        micromamba create -y -p ../.mfa/env -c conda-forge montreal-forced-aligner=3.4.2
    MFA_ROOT_DIR=../.mfa/root ../.mfa/env/bin/mfa model download acoustic english_us_arpa
    MFA_ROOT_DIR=../.mfa/root ../.mfa/env/bin/mfa model download dictionary english_us_arpa

Against Buckeye hand labels, its boundaries are much closer than the phone
recogniser's (SPEC 9.5). Its phones are the dictionary pronunciation of each
word, not a free decoding of what was said.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
MFA_DIR = HERE.parent / ".mfa"
MODEL = "english_us_arpa"
VERSION = "3.4.2"

ARPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s",
    "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def available() -> bool:
    return (MFA_DIR / "env" / "bin" / "mfa").exists()


def env() -> dict:
    # MFA calls its helper programs (OpenFst, Kaldi) from PATH, so put its env first
    return dict(os.environ, MFA_ROOT_DIR=str(MFA_DIR / "root"),
                PATH=f"{MFA_DIR / 'env' / 'bin'}:{os.environ.get('PATH', '')}")


def read_textgrid(path: Path, tier: str) -> list[tuple[float, float, str]]:
    """Intervals of one tier from a long-format TextGrid."""
    out, in_tier, cur = [], False, {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("name ="):
            in_tier = line.split("=", 1)[1].strip().strip('"') == tier
        elif in_tier and line.startswith(("xmin =", "xmax =", "text =")):
            k, v = (x.strip() for x in line.split("=", 1))
            cur[k] = v.strip('"') if k == "text" else float(v)
            if k == "text":
                out.append((cur["xmin"], cur["xmax"], cur["text"]))
                cur = {}
    return out


def align(items: list[tuple[str, str, np.ndarray, int, str]]) -> dict[str, dict]:
    """items: (key, speaker, audio, sample rate, transcript). Returns, per key,
    {"words": [(start, end, word)], "phones": [{ipa, start, end, label}]}.
    Items of one speaker are adapted together."""
    import soundfile as sf

    if not available():
        raise SystemExit(f"MFA is not installed in {MFA_DIR / 'env'} (see mfa.py)")
    with tempfile.TemporaryDirectory(dir=MFA_DIR) as td:
        corpus, out = Path(td) / "corpus", Path(td) / "out"
        keys = {}
        for i, (key, spk, audio, sr, text) in enumerate(items):
            d = corpus / spk
            d.mkdir(parents=True, exist_ok=True)
            sf.write(d / f"u{i:05d}.wav", audio, sr)
            (d / f"u{i:05d}.lab").write_text(text + "\n")
            keys[f"u{i:05d}"] = key
        r = subprocess.run([str(MFA_DIR / "env" / "bin" / "mfa"), "align", "--clean", "-j", "4", str(corpus),
                            MODEL, MODEL, str(out)], capture_output=True, text=True, env=env())
        if r.returncode:
            raise SystemExit(f"mfa align failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        res = {}
        for tg in out.rglob("*.TextGrid"):
            phones = []
            for a, b, lab in read_textgrid(tg, "phones"):
                base = lab.rstrip("012").upper()
                if base in ARPA:
                    ipa = "ə" if lab.upper() == "AH0" else ARPA[base]  # unstressed AH is schwa
                    phones.append({"ipa": ipa, "start": a, "end": b, "label": lab})
            words = [(a, b, w) for a, b, w in read_textgrid(tg, "words") if w.strip()]
            res[keys[tg.stem]] = {"words": words, "phones": phones}
    return res


# --- aligning the heard phones (no dictionary) ---------------------------------------
# Each heard phone needs a stand-in from the acoustic model's phone set for alignment
# only; the transcript keeps the heard label. Full vowels take stress 1, reduced ones 0.
HEARD_TO_ARPA = {
    "p": "P", "b": "B", "t": "T", "d": "D", "k": "K", "ɡ": "G", "ʔ": "T", "ɾ": "D",
    "f": "F", "v": "V", "θ": "TH", "ð": "DH", "s": "S", "z": "Z", "ʃ": "SH", "ʒ": "ZH", "h": "HH",
    "tʃ": "CH", "dʒ": "JH", "m": "M", "n": "N", "ŋ": "NG", "l": "L", "ɹ": "R", "w": "W", "j": "Y",
    "n̩": "N", "l̩": "L", "m̩": "M",
    "i": "IY1", "ɪ": "IH1", "e": "EY1", "ɛ": "EH1", "æ": "AE1", "a": "AA1", "ɑ": "AA1", "ɒ": "AA1",
    "ɔ": "AO1", "o": "OW1", "ʊ": "UH1", "u": "UW1", "ʌ": "AH1", "ə": "AH0", "ɚ": "ER0", "ɜ": "ER1", "ɐ": "AH0",
    "eɪ": "EY1", "aɪ": "AY1", "ɔɪ": "OY1", "aʊ": "AW1", "oʊ": "OW1", "əʊ": "OW1",
    "ɪə": "IH1", "ɛə": "EH1", "ʊə": "UH1",
    "x": "HH", "ç": "HH", "ʍ": "W", "β": "B", "ɣ": "G", "y": "UW1", "ø": "ER1", "ɨ": "IH0",
}


def align_heard(items: list[tuple[str, str, np.ndarray, int, list[list[str]]]]) -> dict[str, list[tuple[float, float] | None]]:
    """Forced-align phones as heard, with no pronouncing dictionary (SPEC 1, 7.1).

    items: (key, speaker, audio, sample rate, groups), where groups are runs of
    heard IPA phones (for example, phones between pauses). Each group becomes a
    pseudo-word whose only pronunciation is exactly its heard phones, so the
    aligner can place boundaries but cannot change, add or remove a phone.
    Returns, per key, one (start, end) per phone in order, or None for a phone
    whose group the aligner could not fit (callers keep their own timing there)."""
    import soundfile as sf

    if not available():
        raise SystemExit(f"MFA is not installed in {MFA_DIR / 'env'} (see mfa.py)")
    with tempfile.TemporaryDirectory(dir=MFA_DIR) as td:
        corpus, out = Path(td) / "corpus", Path(td) / "out"
        lexicon = Path(td) / "heard.dict"
        entries, keys, layout = [], {}, {}
        for i, (key, spk, audio, sr, groups) in enumerate(items):
            d = corpus / spk
            d.mkdir(parents=True, exist_ok=True)
            names = []
            for j, g in enumerate(groups):
                name = f"u{i:05d}g{j:04d}"
                entries.append(f"{name}\t{' '.join(HEARD_TO_ARPA.get(ph, 'AH0') for ph in g)}")
                names.append(name)
            sf.write(d / f"u{i:05d}.wav", audio, sr)
            (d / f"u{i:05d}.lab").write_text(" ".join(names) + "\n")
            keys[f"u{i:05d}"] = key
            layout[key] = [(n, len(g)) for n, g in zip(names, groups)]
        lexicon.write_text("\n".join(entries) + "\n")
        r = subprocess.run([str(MFA_DIR / "env" / "bin" / "mfa"), "align", "--clean", "-j", "4", str(corpus),
                            str(lexicon), MODEL, str(out)], capture_output=True, text=True, env=env())
        if r.returncode:
            raise SystemExit(f"mfa align failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        res = {key: [None] * sum(n for _, n in layout[key]) for key in layout}
        for tg in out.rglob("*.TextGrid"):
            key = keys[tg.stem]
            words = {w: (a, b) for a, b, w in read_textgrid(tg, "words") if w.strip()}
            phones = [(a, b) for a, b, lab in read_textgrid(tg, "phones") if lab.strip() and lab not in ("sil", "sp", "spn")]
            k = 0
            pos = 0
            for name, n in layout[key]:
                if name in words:
                    wa, wb = words[name]
                    inside = [(a, b) for a, b in phones if a >= wa - 1e-6 and b <= wb + 1e-6]
                    if len(inside) == n:
                        res[key][pos:pos + n] = inside
                pos += n
        return res
