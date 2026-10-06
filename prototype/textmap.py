#!/usr/bin/env python3
"""Text maps: tie a packed stream's words back to readable text (SPEC 4.1).

    textmap.py IN.json --profile 16a [-o OUT.text.json]

A packed stream keeps word boundaries but not spelling. A text map is a small
sidecar holding the text and, for each word the stream contains, its character
range in that text, in stream order. With it a player can highlight the word
being spoken while it highlights each phone's glyph.

The JSON form carries the same information inline: a document-level "text"
and a "chars" [start, end) range on each word (add_chars).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pack


def add_chars(doc: dict) -> dict:
    """Give the document a "text" (words joined by spaces, utterances by
    newlines) and each word a "chars" range into it, unless already present."""
    if "text" in doc and all("chars" in w for u in doc["utterances"] for w in u["words"]):
        return doc
    parts, pos = [], 0
    for ui, u in enumerate(doc["utterances"]):
        if ui:
            parts.append("\n")
            pos += 1
        for wi, w in enumerate(u["words"]):
            if wi:
                parts.append(" ")
                pos += 1
            t = w.get("text") or ""
            w["chars"] = [pos, pos + len(t)]
            parts.append(t)
            pos += len(t)
    doc["text"] = "".join(parts)
    return doc


def stream_words(doc: dict, profile: pack.Profile) -> list[list[dict]]:
    """Per utterance, the source words that the packed stream contains, in
    order (SPEC 3.10: profiles b drop words without phones; profiles a drop a
    lone empty word)."""
    out = []
    for u in doc["utterances"]:
        ws = u["words"]
        if profile.boundary == "b":
            ws = [w for w in ws if w["phones"]]
        elif len(ws) == 1 and not ws[0]["phones"]:
            ws = []
        out.append(ws)
    return out


def build(doc: dict, profile: pack.Profile) -> dict:
    doc = add_chars(doc)
    words = stream_words(doc, profile)
    dec = pack.decode(pack.from_bytes(pack.to_bytes(pack.encode(doc, profile))))
    got = [len(u["words"]) for u in dec["utterances"]]
    assert got == [len(ws) for ws in words], (got, [len(ws) for ws in words])
    out = {"prosotype_text": "0.1", "profile": profile.name, "text": doc["text"],
           "utterances": [[w["chars"] for w in ws] for ws in words]}
    # optional per-utterance labels, kept only where they say more than the words
    labels = []
    for u, ws in zip(doc["utterances"], words):
        said = doc["text"][ws[0]["chars"][0]:ws[-1]["chars"][1]] if ws else ""
        lab = u.get("label")
        redundant = lab and said.strip(" .?!").startswith(lab.strip(" .?!"))  # the text itself, or a cut of it
        labels.append(lab if lab and not redundant else None)
    if any(labels):
        out["labels"] = labels
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--profile", default="16a", choices=list(pack.PROFILES))
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    tm = build(json.loads(Path(a.input).read_text()), pack.PROFILES[a.profile])
    out = a.output or str(Path(a.input).with_suffix(f".{a.profile}.text.json"))
    Path(out).write_text(json.dumps(tm, ensure_ascii=False, indent=1) + "\n")
    n = sum(len(u) for u in tm["utterances"])
    print(f"{out}: {n} words over {len(tm['text'])} characters")


if __name__ == "__main__":
    main()
