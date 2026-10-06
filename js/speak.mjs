// Speak a ProsoType stream with the reference synthesiser and write a WAV.
//
//   node js/speak.mjs IN.prs|IN.json [-o OUT.wav] [--voice PROFILE.json] [--speaker PROFILE.json] [--rate 1]
//
// IN.prs is decoded with prosotype.mjs; IN.json is a JSON-form document.
// Prints each phone's time span (the highlighting schedule) with --spans.

import { readFileSync, writeFileSync } from "node:fs";
import { decode } from "./prosotype.mjs";
import { synthesize, wav } from "./synth.mjs";

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : def; };
const flag = (name) => { const i = args.indexOf(name); if (i >= 0) args.splice(i, 1); return i >= 0; };
const out = opt("-o", null), voicePath = opt("--voice", null), speakerPath = opt("--speaker", null);
const rate = parseFloat(opt("--rate", "1")), spans = flag("--spans");
const input = args[0];
if (!input) { console.error("usage: node js/speak.mjs IN.prs|IN.json [-o OUT.wav] [--voice P.json] [--speaker P.json]"); process.exit(2); }

const doc = input.endsWith(".json") ? JSON.parse(readFileSync(input, "utf8")) : decode(new Uint8Array(readFileSync(input)));
const json = (p) => (p ? JSON.parse(readFileSync(p, "utf8")) : null);
const t0 = performance.now();
const res = synthesize(doc, { voice: json(voicePath), speaker: json(speakerPath), rate });
const ms = performance.now() - t0;
const dest = out || input.replace(/\.(prs|json)$/, ".ref.wav");
writeFileSync(dest, wav(res.samples, res.sampleRate));
const secs = res.samples.length / res.sampleRate;
console.log(`${dest}: ${secs.toFixed(2)} s, ${res.phones.length} phones, synthesised in ${ms.toFixed(0)} ms ` +
  `(f0 ${res.voice.median.toFixed(0)} Hz, formants x${res.voice.k.toFixed(2)})`);
if (spans) for (const p of res.phones) console.log(`${p.start.toFixed(3)}\t${p.end.toFixed(3)}\t${p.ipa}\tutt ${p.utt} word ${p.word}`);
