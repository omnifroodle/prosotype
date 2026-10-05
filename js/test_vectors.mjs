// Check the JS decoder against vectors/ (SPEC.md 3.10): every expected/*.prs
// must decode to expected/*.json, with numbers equal within 1e-6.
//
//   node js/test_vectors.mjs

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { decode } from "./prosotype.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "vectors");
const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8"));

function diff(a, b, path = "$") {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-6 ? null : `${path}: ${a} != ${b}`;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return a === b ? null : `${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`;
  if (Array.isArray(a) !== Array.isArray(b)) return `${path}: array mismatch`;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    if (!(k in a) || !(k in b)) return `${path}.${k}: missing on one side`;
    const d = diff(a[k], b[k], `${path}.${k}`);
    if (d) return d;
  }
  return null;
}

let failures = 0;
for (const v of manifest.vectors) {
  const bytes = readFileSync(join(root, v.prs));
  const sha = createHash("sha256").update(bytes).digest("hex");
  let problem = sha === v.sha256 ? null : "sha256 of .prs does not match manifest";
  if (!problem) {
    try {
      problem = diff(decode(new Uint8Array(bytes)), JSON.parse(readFileSync(join(root, v.decoded), "utf8")));
    } catch (e) {
      problem = `threw: ${e.message}`;
    }
  }
  if (problem) { failures++; console.log(`FAIL ${v.prs}: ${problem}`); }
}
console.log(`${manifest.vectors.length} vectors, ${failures} failures`);
process.exit(failures ? 1 : 0);
