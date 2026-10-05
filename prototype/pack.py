#!/usr/bin/env python3
"""ProsoType packed symbol stream: JSON <-> fixed-width packed symbols.

Profiles (see SPEC.md section 3):

    16a 16b 12a 12b 8a 8b

The number is the symbol width in bits. 'a' marks word boundaries with a
WORD symbol whose payload carries the pause length; 'b' sets a word-start
flag bit on the first phone of each word and emits PAUSE symbols only where
there is an audible pause.

Usage:
    pack.py encode IN.json --profile 16a -o OUT.prs
    pack.py decode IN.prs -o OUT.json
    pack.py check IN.json [IN2.json ...]     round-trip every profile

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Phone table "en-1"

PAD, WORD, PAUSE, TURN, ESC = 0, 1, 2, 3, 4
RESERVED_NAMES = {PAD: "PAD", WORD: "WORD", PAUSE: "PAUSE", TURN: "TURN", ESC: "ESC"}
FIRST_PHONE = 8

# (ipa, inherently voiced)
EN1_PHONES: list[tuple[str, bool]] = [
    # consonants, codes 8-33
    ("p", False), ("b", True), ("t", False), ("d", True), ("k", False), ("ɡ", True),
    ("ʔ", False), ("ɾ", True), ("f", False), ("v", True), ("θ", False), ("ð", True),
    ("s", False), ("z", True), ("ʃ", False), ("ʒ", True), ("h", False), ("tʃ", False),
    ("dʒ", True), ("m", True), ("n", True), ("ŋ", True), ("l", True), ("ɹ", True),
    ("w", True), ("j", True),
    # syllabic consonants, codes 34-36
    ("n̩", True), ("l̩", True), ("m̩", True),
    # monophthongs, codes 37-53
    ("i", True), ("ɪ", True), ("e", True), ("ɛ", True), ("æ", True), ("a", True),
    ("ɑ", True), ("ɒ", True), ("ɔ", True), ("o", True), ("ʊ", True), ("u", True),
    ("ʌ", True), ("ə", True), ("ɚ", True), ("ɜ", True), ("ɐ", True),
    # diphthongs, codes 54-62
    ("eɪ", True), ("aɪ", True), ("ɔɪ", True), ("aʊ", True), ("oʊ", True), ("əʊ", True),
    ("ɪə", True), ("ɛə", True), ("ʊə", True),
]
assert FIRST_PHONE + len(EN1_PHONES) <= 64

PHONE_TABLES = {"en-1": EN1_PHONES}

# Spellings that are folded onto a table entry before lookup. Length and
# stress marks are dropped because duration and delivery carry them.
ALIASES = {
    "g": "ɡ", "r": "ɹ", "ɫ": "l", "ɝ": "ɚ", "ᵻ": "ɪ", "ɹ̩": "ɚ",
    "ʧ": "tʃ", "ʤ": "dʒ", "t͡ʃ": "tʃ", "d͡ʒ": "dʒ",
}
STRIP = "ːˑˈˌ"


def normalise_ipa(ipa: str) -> str:
    s = "".join(c for c in ipa if c not in STRIP)
    return ALIASES.get(s, s)


# ---------------------------------------------------------------------------
# Quantisers. Each maps a measurement to an integer level and back to the
# level's centre value. quantise(dequantise(i)) == i for every level.

DUR_CENTRES = {3: [30, 45, 65, 95, 140, 200, 300, 450], 2: [45, 95, 200, 450]}
PITCH_STEP = {4: 1.5, 3: 3.0, 2: 4.0}  # semitones per level
LOUD_STEP = {3: 3.0, 2: 6.0}  # dB per level
LOUD_CENTRE_LEVEL = {3: 4, 2: 2}  # level that means 0 dB
PAUSE_MIN_MS, PAUSE_MAX_MS = 100.0, 3200.0


def rnd(x: float) -> int:
    """Round half away from zero (SPEC 3.10). Python's round() rounds half
    to even, which other languages do not, so it is never used for levels."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def _nearest_log(value: float, centres: list[float]) -> int:
    """Nearest level on a log scale (SPEC 3.10): the number of boundaries
    sqrt(c[k] * c[k+1]) that the value is strictly above."""
    return sum(1 for a, b in zip(centres, centres[1:]) if value > math.sqrt(a * b))


def q_pitch(st: float | None, voiced: bool, bits: int) -> int:
    if bits == 1:  # 1 = high (more than 2 st above median), 0 = anything else
        return 1 if (voiced and st is not None and st > 2.0) else 0
    if not voiced or st is None:
        return 0
    top = (1 << bits) - 1
    centre = (top + 1) // 2
    return min(top, max(1, rnd(st / PITCH_STEP[bits]) + centre))


def dq_pitch(level: int, bits: int) -> float | None:
    if bits == 1:
        return 4.0 if level else None
    if level == 0:
        return None
    centre = ((1 << bits) - 1 + 1) // 2
    return (level - centre) * PITCH_STEP[bits]


def q_dur(ms: float, bits: int) -> int:
    return _nearest_log(ms, DUR_CENTRES[bits])


def dq_dur(level: int, bits: int) -> float:
    return float(DUR_CENTRES[bits][level])


def q_loud(db: float | None, bits: int) -> int:
    db = 0.0 if db is None else db
    if bits == 1:  # 1 = loud (more than 3 dB above mean)
        return 1 if db > 3.0 else 0
    top = (1 << bits) - 1
    return min(top, max(0, rnd(db / LOUD_STEP[bits]) + LOUD_CENTRE_LEVEL[bits]))


def dq_loud(level: int, bits: int) -> float:
    if bits == 1:
        return 6.0 if level else 0.0
    return (level - LOUD_CENTRE_LEVEL[bits]) * LOUD_STEP[bits]


def pause_centres(payload_bits: int) -> list[float]:
    """Pause lengths for payload levels 1..L, geometric from 100 to 3200 ms."""
    n = (1 << payload_bits) - 1
    if n == 1:
        return [PAUSE_MIN_MS]
    r = PAUSE_MAX_MS / PAUSE_MIN_MS
    return [PAUSE_MIN_MS * r ** (i / (n - 1)) for i in range(n)]


def q_pause(ms: float, payload_bits: int) -> list[int]:
    """Pause length -> list of payload levels (0 = no pause). A pause longer
    than the largest level is split across several symbols."""
    cs = pause_centres(payload_bits)
    threshold = cs[0] / math.sqrt(2)  # about 71 ms
    if ms < threshold:
        return [0]
    out = []
    while ms >= cs[-1] + threshold:
        out.append(len(cs))
        ms -= cs[-1]
    if ms >= threshold:
        out.append(_nearest_log(ms, cs) + 1)
    return out


def dq_pause(level: int, payload_bits: int) -> float:
    return 0.0 if level == 0 else pause_centres(payload_bits)[level - 1]


# ---------------------------------------------------------------------------
# Profiles


@dataclass(frozen=True)
class Profile:
    name: str
    width: int
    boundary: str  # "a" or "b"
    flag: int  # bits for word-start flag (0 or 1)
    pitch: int
    dur: int
    loud: int

    @property
    def payload_bits(self) -> int:
        return self.width - 6

    @property
    def id_byte(self) -> int:
        return self.width | (0x80 if self.boundary == "b" else 0)


PROFILES = {
    p.name: p
    for p in [
        Profile("16a", 16, "a", 0, 4, 3, 3),
        Profile("16b", 16, "b", 1, 4, 3, 2),
        Profile("12a", 12, "a", 0, 3, 2, 1),
        Profile("12b", 12, "b", 1, 3, 2, 0),
        Profile("8a", 8, "a", 0, 2, 0, 0),
        Profile("8b", 8, "b", 1, 1, 0, 0),
    ]
}
for _p in PROFILES.values():
    assert 6 + _p.flag + _p.pitch + _p.dur + _p.loud == _p.width, _p


def profile_from_id(b: int) -> Profile:
    for p in PROFILES.values():
        if p.id_byte == b:
            return p
    raise ValueError(f"unknown profile id {b:#x}")


# ---------------------------------------------------------------------------
# Symbols. A symbol is (code, payload) where payload is the width-6 low bits.
# For phones the payload is flag|pitch|dur|loud, most significant first.


def phone_payload(p: Profile, flag: int, pitch: int, dur: int, loud: int) -> int:
    v = flag
    v = (v << p.pitch) | pitch
    v = (v << p.dur) | dur
    v = (v << p.loud) | loud
    return v


def split_payload(p: Profile, v: int) -> tuple[int, int, int, int]:
    loud = v & ((1 << p.loud) - 1); v >>= p.loud
    dur = v & ((1 << p.dur) - 1); v >>= p.dur
    pitch = v & ((1 << p.pitch) - 1); v >>= p.pitch
    flag = v & ((1 << p.flag) - 1)
    return flag, pitch, dur, loud


@dataclass
class Encoded:
    profile: Profile
    table_id: str
    speakers: list[tuple[str, float, float]]  # name, f0 median Hz, loudness mean dB
    extension: list[str]  # phones outside the table, indexed by ESC
    symbols: list[tuple[int, int]] = field(default_factory=list)


def encode(doc: dict, p: Profile) -> Encoded:
    table_id = doc.get("phone_table", "en-1")
    table = PHONE_TABLES[table_id]
    index = {ipa: FIRST_PHONE + i for i, (ipa, _) in enumerate(table)}
    spk_names = list(doc["speakers"])
    speakers = [
        (n, doc["speakers"][n]["f0_median_hz"], doc["speakers"][n]["loudness_mean_db"])
        for n in spk_names
    ]
    enc = Encoded(p, table_id, speakers, [])
    sym = enc.symbols

    def pauses(ms: float) -> list[int]:
        return [lvl for lvl in q_pause(ms, p.payload_bits) if lvl]

    cursor = 0.0  # time in seconds of the end of the last encoded thing
    for utt in doc["utterances"]:
        words = utt["words"]
        if p.boundary == "b":
            # SPEC 3.10: profiles b have no slot for a word without phones
            words = [w for w in words if w["phones"]]
        elif len(words) == 1 and not words[0]["phones"]:
            # a lone empty word is indistinguishable from no words (a bare TURN)
            words = []
        u_start = words[0]["start_s"] if words else cursor
        for lvl in pauses((u_start - cursor) * 1000):
            sym.append((PAUSE, lvl))
        cursor = u_start
        sym.append((TURN, spk_names.index(utt["speaker"])))
        for wi, w in enumerate(words):
            gap_ms = max(0.0, (w["start_s"] - cursor) * 1000)
            if wi > 0:
                if p.boundary == "a":
                    lvls = q_pause(gap_ms, p.payload_bits)
                    # one WORD symbol carries the pause; any overflow goes first as PAUSE
                    for lvl in lvls[:-1]:
                        sym.append((PAUSE, lvl))
                    sym.append((WORD, lvls[-1]))
                else:
                    for lvl in pauses(gap_ms):
                        sym.append((PAUSE, lvl))
            for pi, ph in enumerate(w["phones"]):
                ipa = normalise_ipa(ph["ipa"])
                flag = 1 if (p.flag and pi == 0) else 0
                pitch = q_pitch(ph.get("pitch_st"), ph.get("voiced", True), p.pitch) if p.pitch else 0
                dur = q_dur(ph["dur_ms"], p.dur) if p.dur else 0
                loud = q_loud(ph.get("loud_db"), p.loud) if p.loud else 0
                payload = phone_payload(p, flag, pitch, dur, loud)
                if ipa in index:
                    sym.append((index[ipa], payload))
                else:
                    if ipa not in enc.extension:
                        enc.extension.append(ipa)
                    sym.append((ESC, 0))
                    sym.append((enc.extension.index(ipa), payload))
            if w["phones"]:
                last = w["phones"][-1]
                cursor = max(w.get("end_s", 0.0), last["start_s"] + last["dur_ms"] / 1000)
            else:
                cursor = w.get("end_s", w["start_s"])  # SPEC 3.10: gap runs from the previous word's end
    if len(enc.extension) > 64:
        raise ValueError("more than 64 out-of-table phones")
    return enc


def decode(enc: Encoded) -> dict:
    p = enc.profile
    table = PHONE_TABLES[enc.table_id]
    doc: dict = {
        "prosotype": "0.1",
        "phone_table": enc.table_id,
        "profile": p.name,
        "speakers": {
            n: {"f0_median_hz": f0, "loudness_mean_db": ld} for n, f0, ld in enc.speakers
        },
        "utterances": [],
    }
    t = 0.0
    utt = word = None
    after_word = False  # profiles a: last WORD not yet followed by a phone
    slot_t = 0.0  # when the current word slot opened (after TURN or a WORD's pause)

    def empty_word(at: float) -> None:
        utt["words"].append({"text": None, "start_s": round(at, 6), "phones": [], "end_s": round(at, 6)})

    i = 0
    syms = enc.symbols
    while i < len(syms):
        code, payload = syms[i]
        i += 1
        if code == PAD:
            continue
        if code == PAUSE:
            t += dq_pause(payload, p.payload_bits) / 1000
            continue
        if code == TURN:
            if after_word:  # utterance ended with WORD: a trailing empty word
                empty_word(slot_t)
            after_word, slot_t = False, t
            utt = {"speaker": enc.speakers[payload][0], "words": []}
            doc["utterances"].append(utt)
            word = None
            continue
        if code == WORD:
            if utt is None:
                raise ValueError("WORD before TURN")
            if word is None:  # no phone since TURN or the last WORD: an empty word
                empty_word(slot_t)
            t += dq_pause(payload, p.payload_bits) / 1000
            word = None
            after_word, slot_t = True, t
            continue
        if code == ESC:
            code, payload = syms[i]
            i += 1
            ipa, inherent = enc.extension[code], True
        elif FIRST_PHONE <= code < FIRST_PHONE + len(table):
            ipa, inherent = table[code - FIRST_PHONE]
        else:
            raise ValueError(f"reserved code {code}")
        flag, pitch, dur, loud = split_payload(p, payload)
        if utt is None:
            raise ValueError("phone before TURN")
        after_word = False
        if word is None or (p.flag and flag):
            word = {"text": None, "start_s": round(t, 6), "phones": []}
            utt["words"].append(word)
        dur_ms = dq_dur(dur, p.dur) if p.dur else 80.0
        pst = dq_pitch(pitch, p.pitch) if p.pitch else None
        # with 2+ pitch bits level 0 means unvoiced; with 1 bit only "high" implies voicing
        voiced = (pitch != 0) if p.pitch >= 2 else (bool(pitch) or inherent)
        ph = {"ipa": ipa, "start_s": round(t, 6), "dur_ms": dur_ms, "voiced": voiced,
              "pitch_st": pst, "loud_db": dq_loud(loud, p.loud) if p.loud else None}
        word["phones"].append(ph)
        t += dur_ms / 1000
        word["end_s"] = round(t, 6)
    if after_word:
        empty_word(slot_t)
    return doc


# ---------------------------------------------------------------------------
# Binary container


def _pstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return bytes([len(b)]) + b


def pack_body(enc: Encoded) -> bytes:
    w = enc.profile.width
    acc = nbits = 0
    out = bytearray()
    for code, payload in enc.symbols:
        acc = (acc << w) | (code << (w - 6)) | payload
        nbits += w
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
        acc &= (1 << nbits) - 1
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)  # zero bits; never a whole symbol
    return bytes(out)


def pack_header(enc: Encoded) -> bytes:
    h = bytearray(b"PRS\x01")
    h.append(enc.profile.id_byte)
    h += _pstr(enc.table_id)
    h.append(len(enc.speakers))
    for name, f0, ld in enc.speakers:
        h += _pstr(name)
        h += struct.pack(">Hh", rnd(f0 * 10), rnd(ld * 10))
    h.append(len(enc.extension))
    for ipa in enc.extension:
        h += _pstr(ipa)
    h += struct.pack(">I", len(enc.symbols))
    return bytes(h)


def to_bytes(enc: Encoded) -> bytes:
    return pack_header(enc) + pack_body(enc)


def from_bytes(data: bytes) -> Encoded:
    if data[:4] != b"PRS\x01":
        raise ValueError("not a ProsoType v1 stream")
    pos = 4
    p = profile_from_id(data[pos]); pos += 1

    def pstr() -> str:
        nonlocal pos
        n = data[pos]
        s = data[pos + 1: pos + 1 + n].decode("utf-8")
        pos += 1 + n
        return s

    table_id = pstr()
    speakers = []
    nspk = data[pos]; pos += 1
    for _ in range(nspk):
        name = pstr()
        f0, ld = struct.unpack(">Hh", data[pos:pos + 4]); pos += 4
        speakers.append((name, f0 / 10, ld / 10))
    next_ = data[pos]; pos += 1
    extension = [pstr() for _ in range(next_)]
    (count,) = struct.unpack(">I", data[pos:pos + 4]); pos += 4
    body = data[pos:]
    w = p.width
    symbols = []
    acc = nbits = 0
    it = iter(body)
    while len(symbols) < count:
        while nbits < w:
            acc = (acc << 8) | next(it)
            nbits += 8
        nbits -= w
        s = (acc >> nbits) & ((1 << w) - 1)
        acc &= (1 << nbits) - 1
        symbols.append((s >> (w - 6), s & ((1 << (w - 6)) - 1)))
    return Encoded(p, table_id, speakers, extension, symbols)


# ---------------------------------------------------------------------------
# Round-trip check


def round_trip(doc: dict, p: Profile) -> tuple[bool, str, Encoded, bytes]:
    """JSON -> packed -> JSON -> packed must give identical bytes, and the
    second decode must equal the first (the quantised view is stable)."""
    enc1 = encode(doc, p)
    b1 = to_bytes(enc1)
    enc1b = from_bytes(b1)
    if enc1b.symbols != enc1.symbols:
        return False, "binary container did not return the same symbols", enc1, b1
    doc2 = decode(enc1b)
    b2 = to_bytes(encode(doc2, p))
    if b1 != b2:
        return False, "re-encoding the decoded JSON changed the bytes", enc1, b1
    if decode(from_bytes(b2)) != doc2:
        return False, "second decode differs from first", enc1, b1
    return True, "ok", enc1, b1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode"); e.add_argument("input"); e.add_argument("--profile", default="16a", choices=PROFILES); e.add_argument("-o", "--output")
    d = sub.add_parser("decode"); d.add_argument("input"); d.add_argument("-o", "--output")
    c = sub.add_parser("check"); c.add_argument("inputs", nargs="+")
    a = ap.parse_args(argv)

    if a.cmd == "encode":
        doc = json.loads(Path(a.input).read_text())
        data = to_bytes(encode(doc, PROFILES[a.profile]))
        out = a.output or str(Path(a.input).with_suffix(f".{a.profile}.prs"))
        Path(out).write_bytes(data)
        print(f"{out}: {len(data)} bytes")
    elif a.cmd == "decode":
        doc = decode(from_bytes(Path(a.input).read_bytes()))
        text = json.dumps(doc, ensure_ascii=False, indent=1)
        if a.output:
            Path(a.output).write_text(text + "\n")
        else:
            print(text)
    else:
        ok_all = True
        for path in a.inputs:
            doc = json.loads(Path(path).read_text())
            for p in PROFILES.values():
                ok, msg, enc, data = round_trip(doc, p)
                ok_all &= ok
                print(f"{path} {p.name:>3}: {'PASS' if ok else 'FAIL'} "
                      f"{len(enc.symbols)} symbols, {len(data)} bytes"
                      f"{'' if ok else ' - ' + msg}")
        return 0 if ok_all else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
