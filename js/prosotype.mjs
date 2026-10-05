// ProsoType packed-stream decoder, written from SPEC.md sections 3.1-3.10
// alone (not from the Python prototype) as a check that the spec is complete.
// Works in browsers and Node. MIT licence.
//
//   import { decode } from "./prosotype.mjs";
//   const doc = decode(new Uint8Array(bytes));

// 3.3 Phone table en-1, codes 8..62 in order.
const EN1 = [
  "p", "b", "t", "d", "k", "ɡ", "ʔ", "ɾ", "f", "v", "θ", "ð", "s", "z", "ʃ", "ʒ", "h", "tʃ", "dʒ",
  "m", "n", "ŋ", "l", "ɹ", "w", "j",
  "n̩", "l̩", "m̩",
  "i", "ɪ", "e", "ɛ", "æ", "a", "ɑ", "ɒ", "ɔ", "o", "ʊ", "u", "ʌ", "ə", "ɚ", "ɜ", "ɐ",
  "eɪ", "aɪ", "ɔɪ", "aʊ", "oʊ", "əʊ", "ɪə", "ɛə", "ʊə",
];
const VOICELESS = new Set(["p", "t", "k", "ʔ", "f", "θ", "s", "ʃ", "h", "tʃ"]);
const TABLES = { "en-1": EN1 };
const FIRST_PHONE = 8;
const [PAD, WORD, PAUSE, TURN, ESC] = [0, 1, 2, 3, 4];

// 3.4 Profiles: field widths.
const PROFILES = {
  "16a": { width: 16, b: false, flag: 0, pitch: 4, dur: 3, loud: 3 },
  "16b": { width: 16, b: true, flag: 1, pitch: 4, dur: 3, loud: 2 },
  "12a": { width: 12, b: false, flag: 0, pitch: 3, dur: 2, loud: 1 },
  "12b": { width: 12, b: true, flag: 1, pitch: 3, dur: 2, loud: 0 },
  "8a": { width: 8, b: false, flag: 0, pitch: 2, dur: 0, loud: 0 },
  "8b": { width: 8, b: true, flag: 1, pitch: 1, dur: 0, loud: 0 },
};
const PITCH = { 4: [1.5, 8], 3: [3, 4], 2: [4, 2] }; // step (st), centre level
const LOUD = { 3: [3, 4], 2: [6, 2] }; // step (dB), centre level
const DUR = { 3: [30, 45, 65, 95, 140, 200, 300, 450], 2: [45, 95, 200, 450] };
const DEFAULT_DUR_MS = 80;

function pauseCentre(level, payloadBits) {
  if (level === 0) return 0;
  const L = 2 ** payloadBits - 1;
  return 100 * 32 ** ((level - 1) / (L - 1));
}

function delivery(prof, payload) {
  let v = payload;
  const take = (bits) => {
    const x = v & ((1 << bits) - 1);
    v >>>= bits;
    return x;
  };
  const loud = take(prof.loud), dur = take(prof.dur), pitch = take(prof.pitch), flag = take(prof.flag);
  return { flag, pitch, dur, loud };
}

export function decode(bytes) {
  let pos = 0;
  const u8 = () => bytes[pos++];
  const u16 = () => (pos += 2, (bytes[pos - 2] << 8) | bytes[pos - 1]);
  const i16 = () => { const x = u16(); return x >= 0x8000 ? x - 0x10000 : x; };
  const u32 = () => (pos += 4, ((bytes[pos - 4] << 24) >>> 0) + (bytes[pos - 3] << 16) + (bytes[pos - 2] << 8) + bytes[pos - 1]);
  const str = () => { const n = u8(); const s = new TextDecoder().decode(bytes.subarray(pos, pos + n)); pos += n; return s; };

  // 3.6 Container
  if (bytes[0] !== 0x50 || bytes[1] !== 0x52 || bytes[2] !== 0x53 || bytes[3] !== 1) throw new Error("not a ProsoType v1 stream");
  pos = 4;
  const id = u8();
  const name = `${id & 0x7f}${id & 0x80 ? "b" : "a"}`;
  const prof = PROFILES[name];
  if (!prof) throw new Error(`unknown profile id ${id}`);
  const tableId = str();
  const table = TABLES[tableId];
  if (!table) throw new Error(`unknown phone table ${tableId}`);
  const speakers = [];
  for (let n = u8(); n > 0; n--) speakers.push({ name: str(), f0: u16() / 10, loud: i16() / 10 });
  const extension = [];
  for (let n = u8(); n > 0; n--) extension.push(str());
  const count = u32();

  // 3.1 Symbols: big-endian bit stream of `width`-bit symbols.
  const W = prof.width, P = W - 6;
  const symbols = [];
  let acc = 0, nbits = 0;
  while (symbols.length < count) {
    while (nbits < W) { acc = (acc << 8) | bytes[pos++]; nbits += 8; }
    nbits -= W;
    const s = (acc >>> nbits) & ((1 << W) - 1);
    acc &= (1 << nbits) - 1;
    symbols.push([s >>> P, s & ((1 << P) - 1)]);
  }

  // 3.10 Decoding
  const doc = {
    prosotype: "0.1", phone_table: tableId, profile: name,
    speakers: Object.fromEntries(speakers.map((s) => [s.name, { f0_median_hz: s.f0, loudness_mean_db: s.loud }])),
    utterances: [],
  };
  let t = 0, utt = null, word = null, afterWord = false, slot = 0;
  const emptyWord = (at) => utt.words.push({ text: null, start_s: at, phones: [], end_s: at });

  for (let i = 0; i < symbols.length; i++) {
    let [code, payload] = symbols[i];
    if (code === PAD) continue;
    if (code === PAUSE) { t += pauseCentre(payload, P) / 1000; continue; }
    if (code === TURN) {
      if (afterWord) emptyWord(slot);
      utt = { speaker: speakers[payload].name, words: [] };
      doc.utterances.push(utt);
      word = null; afterWord = false; slot = t;
      continue;
    }
    if (code === WORD) {
      if (!utt) throw new Error("WORD before TURN");
      if (!word) emptyWord(slot);
      t += pauseCentre(payload, P) / 1000;
      word = null; afterWord = true; slot = t;
      continue;
    }
    let ipa, voicedPhone;
    if (code === ESC) {
      [code, payload] = symbols[++i];
      ipa = extension[code]; voicedPhone = true;
    } else if (code >= FIRST_PHONE && code < FIRST_PHONE + table.length) {
      ipa = table[code - FIRST_PHONE]; voicedPhone = !VOICELESS.has(ipa);
    } else {
      throw new Error(`reserved code ${code}`);
    }
    if (!utt) throw new Error("phone before TURN");
    afterWord = false;
    const d = delivery(prof, payload);
    if (!word || (prof.flag && d.flag)) {
      word = { text: null, start_s: t, phones: [] };
      utt.words.push(word);
    }
    const dur_ms = prof.dur ? DUR[prof.dur][d.dur] : DEFAULT_DUR_MS;
    let pitch_st = null;
    if (prof.pitch >= 2 && d.pitch !== 0) pitch_st = (d.pitch - PITCH[prof.pitch][1]) * PITCH[prof.pitch][0];
    if (prof.pitch === 1 && d.pitch === 1) pitch_st = 4;
    let loud_db = null;
    if (prof.loud >= 2) loud_db = (d.loud - LOUD[prof.loud][1]) * LOUD[prof.loud][0];
    if (prof.loud === 1) loud_db = d.loud ? 6 : 0;
    const voiced = prof.pitch >= 2 ? d.pitch !== 0 : prof.pitch === 1 ? (d.pitch === 1 || voicedPhone) : voicedPhone;
    word.phones.push({ ipa, start_s: t, dur_ms, voiced, pitch_st, loud_db });
    t += dur_ms / 1000;
    word.end_s = t;
  }
  if (afterWord) emptyWord(slot);
  return doc;
}
