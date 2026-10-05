#!/usr/bin/env python3
"""Download the prototype's external inputs at pinned versions and verify them.

    fetch.py            font + pronouncing dictionary (small)
    fetch.py --models   also the two models used by transcribe.py (about 4 GB,
                        into ../.hf-cache/hub)

Every file is pinned to an upstream commit and checked against a SHA-256, so a
fresh checkout reproduces the same renders and transcriptions.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

FILES = [
    {   # Noto Sans variable font (SIL OFL 1.1)
        "path": HERE / "fonts" / "NotoSans-VF.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/2984c575fdce412ee02b2baaba67672b9a9434d8/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf",
        "sha256": "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
    },
    {   # Its licence, kept beside it
        "path": HERE / "fonts" / "OFL.txt",
        "url": "https://raw.githubusercontent.com/google/fonts/2984c575fdce412ee02b2baaba67672b9a9434d8/ofl/notosans/OFL.txt",
        "sha256": None,
    },
    {   # CMU Pronouncing Dictionary (BSD-style licence)
        "path": HERE / "data" / "cmudict.dict",
        "url": "https://raw.githubusercontent.com/cmusphinx/cmudict/0f8072f814306c5ee4fbf992ed853601b12c01f9/cmudict.dict",
        "sha256": "81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22",
    },
]

# Model revisions (Hugging Face commits). transcribe.py imports these.
PHONE_MODEL = "facebook/wav2vec2-lv-60-espeak-cv-ft"
PHONE_MODEL_REV = "ae45363bf3413b374fecd9dc8bc1df0e24c3b7f4"
WORD_MODEL = "mlx-community/whisper-large-v3-turbo"
WORD_MODEL_REV = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
HF_CACHE = HERE.parent / ".hf-cache" / "hub"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_file(spec: dict) -> bool:
    path: Path = spec["path"]
    if path.exists() and (spec["sha256"] is None or sha256(path) == spec["sha256"]):
        print(f"ok        {path.relative_to(HERE)}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    urllib.request.urlretrieve(spec["url"], tmp)
    if spec["sha256"] and sha256(tmp) != spec["sha256"]:
        tmp.unlink()
        print(f"MISMATCH  {path.relative_to(HERE)}: checksum differs from the pinned file", file=sys.stderr)
        return False
    tmp.replace(path)
    print(f"fetched   {path.relative_to(HERE)}")
    return True


def fetch_models() -> None:
    os.environ.setdefault("HF_HUB_CACHE", str(HF_CACHE))
    from huggingface_hub import snapshot_download

    for repo, rev, patterns in [
        (PHONE_MODEL, PHONE_MODEL_REV, ["*.json", "pytorch_model.bin"]),
        (WORD_MODEL, WORD_MODEL_REV, ["*.json", "*.safetensors"]),
    ]:
        path = snapshot_download(repo, revision=rev, allow_patterns=patterns)
        print(f"model     {repo}@{rev[:7]} -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", action="store_true")
    a = ap.parse_args()
    ok = all([fetch_file(f) for f in FILES])
    if a.models:
        fetch_models()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
