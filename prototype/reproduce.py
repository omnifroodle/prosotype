#!/usr/bin/env python3
"""Re-run every check behind SPEC.md and report what reproduces.

    reproduce.py

1. Pinned inputs (font, dictionary) are present and match their checksums.
2. Round-trip tests pass.
3. pack.py reproduces the conformance vectors byte for byte.
4. The independent JS decoder matches the vectors (needs Node).
5. The site, renders and logo rebuild to the committed files.
6. If the source recordings are present (they are not published) and the
   models are cached: transcription reproduces samples/recorded_three_ways.json.

Run inside the locked environment:  uv sync --extra transcribe
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
PY = sys.executable
RECORDINGS = [HERE / "samples" / f"{n}.m4a" for n in ("flat", "question", "sarcastic")]


def run(label: str, cmd: list[str], **kw) -> bool:
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, **kw)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    print(f"{'PASS' if r.returncode == 0 else 'FAIL'}  {label}  {last}")
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:], sep="\n")
    return r.returncode == 0


def docs_unchanged() -> bool:
    # rebuilt files vs the git index (what is committed or staged)
    r = subprocess.run(["git", "diff", "--name-only", "--", "docs"], cwd=ROOT, capture_output=True, text=True)
    changed = r.stdout.strip()
    print(f"{'PASS' if not changed else 'FAIL'}  site rebuild matches docs/ in git"
          + ("" if not changed else f"\n{changed}"))
    return not changed


def transcription() -> bool | None:
    if not all(p.exists() for p in RECORDINGS):
        print("SKIP  transcription (source recordings are not published)")
        return None
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "rerun.json"
        env = dict(os.environ, HF_HUB_OFFLINE=os.environ.get("HF_HUB_OFFLINE", "0"))
        rel = [str(p.relative_to(HERE)) for p in RECORDINGS]  # source.audio records these paths
        r = subprocess.run([PY, "transcribe.py", *rel, "-o", str(out)], cwd=HERE,
                           capture_output=True, text=True, env=env)
        if r.returncode:
            print("FAIL  transcription", r.stderr[-1500:], sep="\n")
            return False
        same = json.loads(out.read_text()) == json.loads((HERE / "samples/recorded_three_ways.json").read_text())
    print(f"{'PASS' if same else 'FAIL'}  transcription reproduces samples/recorded_three_ways.json")
    return same


def main() -> int:
    results = [
        run("pinned inputs", [PY, "fetch.py"]),
        run("round trip", [PY, "test_pack.py"]),
        run("vectors (Python encoder)", [PY, "make_vectors.py", "--check"]),
    ]
    if shutil.which("node"):
        results.append(run("vectors (JS decoder)", ["node", str(ROOT / "js" / "test_vectors.mjs")]))
    else:
        print("SKIP  JS decoder (Node not installed)")
    results.append(run("logo", [PY, "logo.py"]))
    results.append(run("site", [PY, "site.py"]))
    results.append(docs_unchanged())
    t = transcription()
    if t is not None:
        results.append(t)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
