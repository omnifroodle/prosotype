#!/usr/bin/env python3
"""Size report: packed ProsoType profiles vs text vs audio.

    bitrate.py IN.json [IN2.json ...] [--json OUT.json]

For each sample:
  - every packed profile: body bytes, bytes/word, bit/s, raw and compressed
    (zlib level 9, xz preset 9e); container header reported separately
  - the transcript as UTF-8 and UTF-16, raw and compressed
  - the source audio file, 16 kHz 16-bit mono PCM, Opus at 6 kbit/s,
    Codec 2 at 700C, its lowest released mode (when ffmpeg / c2enc are available)

Bit rates use the clip duration (the source audio's, or the end of the last
phone when there is no audio). The transcript is the orthographic words of
each utterance joined by spaces, one utterance per line.
"""

from __future__ import annotations

import argparse
import json
import lzma
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

import pack


def zl(b: bytes) -> int:
    return len(zlib.compress(b, 9))


def xz(b: bytes) -> int:
    return len(lzma.compress(b, preset=9 | lzma.PRESET_EXTREME))


def transcript(doc: dict) -> str:
    return "\n".join(" ".join(w["text"] for w in u["words"] if w.get("text")) for u in doc["utterances"])


def duration_s(doc: dict, base: Path) -> float:
    src = doc.get("source", {})
    if src.get("duration_s"):
        return float(src["duration_s"])
    ends = [p["start_s"] + p["dur_ms"] / 1000 for u in doc["utterances"] for w in u["words"] for p in w["phones"]]
    return max(ends)


def file_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def audio_sizes(path: Path, dur: float) -> dict[str, int]:
    out = {"source file": path.stat().st_size, "PCM 16 kHz 16-bit mono": round(dur * 16000) * 2}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if shutil.which("ffmpeg"):
            opus = td / "a.ogg"
            r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "16000",
                                "-c:a", "libopus", "-b:a", "6k", "-application", "voip", str(opus)], capture_output=True)
            if r.returncode == 0:
                out["Opus 6 kbit/s (Ogg)"] = opus.stat().st_size
            if shutil.which("c2enc"):
                raw = td / "a.raw"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "8000",
                                "-f", "s16le", str(raw)], check=True)
                for mode in ["700C"]:  # lowest mode in the Codec 2 1.2 release
                    bit = td / f"a{mode}.bit"
                    r = subprocess.run(["c2enc", mode, str(raw), str(bit)], capture_output=True)
                    if r.returncode == 0:
                        out[f"Codec 2 {mode}"] = bit.stat().st_size
    return out


def report(path: str) -> dict:
    doc = json.loads(Path(path).read_text())
    words = sum(len(u["words"]) for u in doc["utterances"])
    phones = sum(len(w["phones"]) for u in doc["utterances"] for w in u["words"])
    dur = duration_s(doc, Path(path).parent)
    text = transcript(doc)
    rows = []

    def row(kind: str, name: str, raw: int, z: int | None, x: int | None, symbols: int | None = None):
        rows.append({"kind": kind, "name": name, "bytes": raw, "zlib": z, "xz": x, "symbols": symbols,
                     "bytes_per_word": raw / words, "bit_s": raw * 8 / dur,
                     "zlib_bytes_per_word": z / words if z else None, "xz_bytes_per_word": x / words if x else None})

    header = None
    for p in pack.PROFILES.values():
        enc = pack.encode(doc, p)
        body = pack.pack_body(enc)
        header = len(pack.pack_header(enc))
        row("packed", p.name, len(body), zl(body), xz(body), len(enc.symbols))
    for enc_name, codec in [("UTF-8", "utf-8"), ("UTF-16", "utf-16-le")]:
        b = text.encode(codec)
        row("text", enc_name, len(b), zl(b), xz(b))
    audio = doc.get("source", {}).get("audio")
    files = [audio] if isinstance(audio, str) else (audio or [])
    if files and all(Path(f).exists() for f in files):
        totals: dict[str, int] = {}
        for f in files:  # several files: sizes add up; PCM uses each file's own duration
            for name, size in audio_sizes(Path(f), file_duration(f)).items():
                totals[name] = totals.get(name, 0) + size
        for name, size in totals.items():
            row("audio", name, size, None, None)
    return {"sample": path, "words": words, "phones": phones, "duration_s": dur,
            "phones_per_word": phones / words, "chars_per_word": len(text) / words,
            "phones_per_s": phones / dur, "header_bytes": header, "transcript": text, "rows": rows}


def fmt(r: dict) -> str:
    lines = [f"## {r['sample']}",
             f"{r['words']} words, {r['phones']} phones, {r['duration_s']:.2f} s; "
             f"{r['phones_per_word']:.2f} phones/word, {r['chars_per_word']:.2f} chars/word (incl. space), "
             f"{r['phones_per_s']:.1f} phones/s; container header {r['header_bytes']} bytes (not included below)",
             "",
             "| Form | Symbols | Bytes | Bytes/word | bit/s | zlib B/word | xz B/word |",
             "|---|---|---|---|---|---|---|"]
    for x in r["rows"]:
        z = f"{x['zlib_bytes_per_word']:.2f}" if x["zlib"] else "–"
        xx = f"{x['xz_bytes_per_word']:.2f}" if x["xz"] else "–"
        lines.append(f"| {x['kind']} {x['name']} | {x['symbols'] or '–'} | {x['bytes']} | "
                     f"{x['bytes_per_word']:.2f} | {x['bit_s']:.0f} | {z} | {xx} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--json", help="also write results as JSON")
    a = ap.parse_args()
    results = [report(p) for p in a.inputs]
    print("\n\n".join(fmt(r) for r in results))
    if a.json:
        Path(a.json).write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
