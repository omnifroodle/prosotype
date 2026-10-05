#!/usr/bin/env python3
"""Conformance test vectors for the packed stream (SPEC.md 3.10).

    make_vectors.py           regenerate ../vectors/expected and manifest.json
    make_vectors.py --check   verify pack.py still reproduces them exactly

For every input in ../vectors/inputs and every profile, writes:
  expected/NAME.PROFILE.prs    the exact bytes an encoder must produce
  expected/NAME.PROFILE.json   what a decoder must return (numbers within 1e-6)
and a manifest with symbol counts, sizes and SHA-256 of each .prs file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pack

VECTORS = Path(__file__).parent.parent / "vectors"


def build() -> tuple[list[dict], dict[str, bytes]]:
    manifest, files = [], {}
    for inp in sorted((VECTORS / "inputs").glob("*.json")):
        doc = json.loads(inp.read_text())
        for p in pack.PROFILES.values():
            enc = pack.encode(doc, p)
            data = pack.to_bytes(enc)
            decoded = pack.decode(pack.from_bytes(data))
            stem = f"{inp.stem}.{p.name}"
            files[f"{stem}.prs"] = data
            files[f"{stem}.json"] = (json.dumps(decoded, ensure_ascii=False, indent=1) + "\n").encode()
            manifest.append({
                "input": f"inputs/{inp.name}", "profile": p.name,
                "prs": f"expected/{stem}.prs", "decoded": f"expected/{stem}.json",
                "symbols": len(enc.symbols), "header_bytes": len(pack.pack_header(enc)),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "extension_phones": enc.extension,
            })
    return manifest, files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    manifest, files = build()
    mtext = json.dumps({"spec": "SPEC.md 3.10", "container_version": 1, "vectors": manifest},
                       ensure_ascii=False, indent=1) + "\n"
    if a.check:
        bad = [name for name, data in files.items() if (VECTORS / "expected" / name).read_bytes() != data]
        if (VECTORS / "manifest.json").read_text() != mtext:
            bad.append("manifest.json")
        for name in bad:
            print(f"MISMATCH {name}")
        print(f"{len(files)} files checked, {len(bad)} mismatches")
        return 1 if bad else 0
    (VECTORS / "expected").mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (VECTORS / "expected" / name).write_bytes(data)
    (VECTORS / "manifest.json").write_text(mtext)
    print(f"{len(manifest)} vectors written to {VECTORS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
