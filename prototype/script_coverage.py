#!/usr/bin/env python3
"""Check a recording script's phone coverage against the voice profile's needs.

    script_coverage.py [../profiles/RECORDING.md]          report coverage
    script_coverage.py --export DIR                         write partN.txt per part

The script text is the content of the ```script fenced blocks under each
"### Part" heading in RECORDING.md. Pronunciations come from CMUdict (first
pronunciation, with stress), so counts are what a careful reading should
produce; real speech will reduce some vowels and flap some t's.

Targets (VOICE-PROFILE.md §4 and §7):
  every en-1 phone that General American uses     >= 5
  voiceless stops p t k before a stressed vowel   >= 20 in total, >= 6 each
  voiceless stops before an unstressed vowel      >= 10
  s, z, ʃ, f, θ, ð (fricative spectra)            >= 8 each; ʒ >= 5
  r-coloured vowels ɚ/ɜ and ɹ                      >= 8 each
  diphthongs eɪ aɪ oʊ aʊ ɔɪ                        >= 5 each
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT = HERE.parent / "profiles" / "RECORDING.md"
CMUDICT = HERE / "data" / "cmudict.dict"

ARPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɜ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s",
    "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}
GA_PHONES = ["p", "b", "t", "d", "k", "ɡ", "f", "v", "θ", "ð", "s", "z", "ʃ", "ʒ", "h", "tʃ", "dʒ",
             "m", "n", "ŋ", "l", "ɹ", "w", "j", "i", "ɪ", "eɪ", "ɛ", "æ", "ɑ", "ɔ", "oʊ", "ʊ", "u", "ʌ",
             "ə", "ɚ", "ɜ", "aɪ", "aʊ", "ɔɪ"]
TARGETS = {**{p: 5 for p in GA_PHONES}, **{f: 8 for f in ("s", "z", "ʃ", "f", "θ", "ð")}, "ʒ": 5, "ɹ": 8}


def load_dict() -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    for line in CMUDICT.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("#")[0].split()
        if parts and parts[0] not in d:
            d[parts[0]] = parts[1:]
    return d


def parts_of(md: str) -> list[tuple[str, str]]:
    """(heading, text) for each ```script block, under its nearest ### heading."""
    out, heading = [], ""
    for m in re.finditer(r"^### ([^\n]+)|^```script\n(.*?)^```", md, re.M | re.S):
        if m.group(1):
            heading = m.group(1).strip()
        else:
            out.append((heading, m.group(2).strip()))
    return out


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z']+", text.replace("’", "'").lower()) if w.strip("'")]


def analyse(text: str, cmu: dict) -> tuple[Counter, dict, list[str]]:
    counts: Counter = Counter()
    stops = {"stressed": Counter(), "unstressed": Counter()}
    oov = []
    for w in words(text):
        pron = cmu.get(w)
        if pron is None:
            oov.append(w)
            continue
        for i, ph in enumerate(pron):
            base, stress = re.sub(r"\d", "", ph), (ph[-1] if ph[-1].isdigit() else None)
            ipa = ARPA[base]
            if base == "ER":
                ipa = "ɜ" if stress in ("1", "2") else "ɚ"
            if base == "AH" and stress == "0":
                ipa = "ə"
            counts[ipa] += 1
            # a voiceless stop right before a vowel, not after s (sp, st, sk are unaspirated)
            if ipa in ("p", "t", "k") and i + 1 < len(pron) and pron[i + 1][-1].isdigit():
                if i > 0 and pron[i - 1] == "S":
                    continue
                kind = "stressed" if pron[i + 1][-1] in "12" else "unstressed"
                stops[kind][ipa] += 1
    return counts, stops, oov


def report(md_path: Path) -> int:
    cmu = load_dict()
    parts = parts_of(md_path.read_text())
    total, stops_total, oov_all = Counter(), {"stressed": Counter(), "unstressed": Counter()}, []
    for heading, text in parts:
        c, st, oov = analyse(text, cmu)
        total += c
        for k in st:
            stops_total[k] += st[k]
        oov_all += oov
        nw = len(words(text))
        print(f"{heading}: {nw} words (about {nw / 2.6:.0f} s read aloud)")
    print()
    short = []
    for p in GA_PHONES:
        need = TARGETS.get(p, 5)
        ok = total[p] >= need
        if not ok:
            short.append(f"{p} {total[p]}/{need}")
    rc = total["ɚ"] + total["ɜ"]
    checks = [
        ("every phone at target", not short, ", ".join(short) or "all met"),
        ("stressed voiceless stops >= 20", sum(stops_total["stressed"].values()) >= 20,
         f"{sum(stops_total['stressed'].values())} ({dict(stops_total['stressed'])})"),
        ("each of p t k stressed >= 6", all(stops_total["stressed"][s] >= 6 for s in "ptk"), str(dict(stops_total["stressed"]))),
        ("unstressed voiceless stops >= 10", sum(stops_total["unstressed"].values()) >= 10,
         f"{sum(stops_total['unstressed'].values())} ({dict(stops_total['unstressed'])})"),
        ("r-coloured vowels >= 8", rc >= 8, str(rc)),
        ("words in the dictionary", not oov_all, ", ".join(sorted(set(oov_all))) or "all"),
    ]
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print("\ncounts: " + " ".join(f"{p}:{total[p]}" for p in GA_PHONES))
    return 0 if all(ok for _, ok, _ in checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--export", type=Path, help="write each part's text to DIR/partN.txt")
    a = ap.parse_args()
    if a.export:
        a.export.mkdir(parents=True, exist_ok=True)
        for i, (_, text) in enumerate(parts_of(a.script.read_text()), 1):
            (a.export / f"part{i}.txt").write_text(" ".join(text.split()) + "\n")
        print(f"wrote {len(parts_of(a.script.read_text()))} parts to {a.export}")
        return 0
    return report(a.script)


if __name__ == "__main__":
    sys.exit(main())
