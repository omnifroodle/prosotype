#!/usr/bin/env python3
"""Round-trip tests for pack.py: the hand-written sample plus random documents
with long pauses, out-of-table phones, several speakers and missing pitch.

    python test_pack.py
"""

import json
import random
import sys
from pathlib import Path

import pack

HERE = Path(__file__).parent


def random_doc(rng: random.Random) -> dict:
    phones = [ipa for ipa, _ in pack.EN1_PHONES] + ["x", "ʍ", "iː", "ˈæ", "ɫ", "ɝ", "ç"]
    spk = {f"S{i}": {"f0_median_hz": rng.uniform(80, 250), "loudness_mean_db": rng.uniform(50, 75)}
           for i in range(rng.randint(1, 3))}
    doc = {"phone_table": "en-1", "speakers": spk, "utterances": []}
    t = rng.uniform(0, 5)
    for _ in range(rng.randint(1, 4)):
        words = []
        for _ in range(rng.randint(1, 8)):
            ws, ph = t, []
            for _ in range(rng.randint(1, 6)):
                d = rng.uniform(15, 700)
                v = rng.random() < 0.8
                ph.append({"ipa": rng.choice(phones), "start_s": t, "dur_ms": d, "voiced": v,
                           "pitch_st": rng.uniform(-15, 15) if v and rng.random() < 0.9 else None,
                           "loud_db": rng.uniform(-20, 15)})
                t += d / 1000
            words.append({"text": "w", "start_s": ws, "end_s": t, "phones": ph})
            t += rng.choice([0, 0, 0, rng.uniform(0, 0.2), rng.uniform(0, 12)])
        doc["utterances"].append({"speaker": rng.choice(list(spk)), "words": words})
        t += rng.uniform(0, 9)
    return doc


def main() -> int:
    failures = 0
    docs = [("sample", json.loads((HERE / "samples/party_three_ways.json").read_text()))]
    rng = random.Random(1)
    docs += [(f"random{i}", random_doc(rng)) for i in range(400)]
    for name, doc in docs:
        for p in pack.PROFILES.values():
            ok, msg, *_ = pack.round_trip(doc, p)
            if not ok:
                failures += 1
                print(f"FAIL {name} {p.name}: {msg}")
    # Hand calculation for the sample: per delivery 1 TURN + 20 phones (+ 5 WORD
    # in 'a'); 2 PAUSE between deliveries; 1 extra PAUSE in 'b' for the 150 ms gap.
    expected = {"16a": 80, "16b": 66, "12a": 80, "12b": 66, "8a": 80, "8b": 66}
    sample = docs[0][1]
    for name, n in expected.items():
        got = len(pack.encode(sample, pack.PROFILES[name]).symbols)
        if got != n:
            failures += 1
            print(f"FAIL sample {name}: {got} symbols, expected {n}")
    print(f"{len(docs)} documents x {len(pack.PROFILES)} profiles, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
