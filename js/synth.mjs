// ProsoType reference synthesiser: a small Klatt-style formant synthesiser
// that speaks a decoded stream exactly as written (SPEC 11). Robotic by design:
// every phone gets the stream's duration, pitch and loudness, with nothing
// predicted. A voice profile (SPEC 10) sets its pitch level and range,
// formants (from vocal-tract length and measured vowels), spectral tilt,
// breathiness, jitter and shimmer. Runs in browsers and Node. MIT licence.
//
//   import { synthesize } from "./synth.mjs";
//   const { samples, sampleRate, phones } = synthesize(doc, { voice, speaker });
//
// doc is a decoded stream or a JSON-form document; phones lists each phone's
// start and end time in the output, in stream order, for highlighting.

const SR = 22050;
const FRAME = 0.005; // parameter frame, seconds

// --- phone inventory ---------------------------------------------------------
// Vowel formants F1-F3 (Hz): adult male means, Hillenbrand et al. (1995),
// with a few unlisted vowels interpolated.
const V = {
  i: [342, 2322, 3000], "ɪ": [427, 2034, 2684], e: [476, 2089, 2691], "ɛ": [580, 1799, 2605],
  "æ": [588, 1952, 2601], a: [720, 1350, 2500], "ɑ": [768, 1333, 2522], "ɒ": [650, 950, 2500],
  "ɔ": [652, 997, 2538], o: [497, 910, 2459], "ʊ": [469, 1122, 2434], u: [378, 997, 2343],
  "ʌ": [623, 1200, 2550], "ə": [500, 1400, 2450], "ɚ": [474, 1379, 1710], "ɜ": [474, 1379, 1710],
  "ɐ": [600, 1250, 2500],
};
const DIPH = {
  "eɪ": ["e", "ɪ"], "aɪ": ["a", "ɪ"], "ɔɪ": ["ɔ", "ɪ"], "aʊ": ["a", "ʊ"], "oʊ": ["o", "ʊ"],
  "əʊ": ["ə", "ʊ"], "ɪə": ["ɪ", "ə"], "ɛə": ["ɛ", "ə"], "ʊə": ["ʊ", "ə"],
};
// Consonants: kind, voicing, formant loci (null = take them from the neighbours),
// and noise spectrum for frication or bursts: peaks [freq, bandwidth, amp] + flat bypass.
const LAB = [300, 900, 2200], ALV = [300, 1700, 2600], VEL = [300, 1900, 2300], PAL = [300, 1900, 2400];
const NOISE = {
  lab: { peaks: [[1200, 900, 0.25]], bypass: 0.35 },
  den: { peaks: [[6000, 2500, 0.15]], bypass: 0.25 },
  alv: { peaks: [[5500, 1300, 1.0], [8000, 1800, 0.45]], bypass: 0.05 },
  pal: { peaks: [[2700, 500, 0.9], [4300, 900, 0.5]], bypass: 0.03 },
  burstAlv: { peaks: [[4000, 1500, 1.0], [6500, 2000, 0.5]], bypass: 0.1 },
  burstVel: { peaks: [[2200, 800, 1.0]], bypass: 0.1 },
  burstLab: { peaks: [[1000, 900, 0.4]], bypass: 0.45 },
};
const C = {
  p: { kind: "stop", voiced: false, F: LAB, burst: "burstLab" }, b: { kind: "stop", voiced: true, F: LAB, burst: "burstLab" },
  t: { kind: "stop", voiced: false, F: ALV, burst: "burstAlv" }, d: { kind: "stop", voiced: true, F: ALV, burst: "burstAlv" },
  k: { kind: "stop", voiced: false, F: VEL, burst: "burstVel" }, "ɡ": { kind: "stop", voiced: true, F: VEL, burst: "burstVel" },
  "ʔ": { kind: "glottal", voiced: true, F: null },
  "ɾ": { kind: "flap", voiced: true, F: [300, 1700, 2600] },
  f: { kind: "fric", voiced: false, F: [300, 1100, 2300], noise: "lab", level: 0.35 },
  v: { kind: "fric", voiced: true, F: [300, 1100, 2300], noise: "lab", level: 0.2 },
  "θ": { kind: "fric", voiced: false, F: [300, 1500, 2500], noise: "den", level: 0.3 },
  "ð": { kind: "fric", voiced: true, F: [300, 1500, 2500], noise: "den", level: 0.15 },
  s: { kind: "fric", voiced: false, F: ALV, noise: "alv", level: 1.0 },
  z: { kind: "fric", voiced: true, F: ALV, noise: "alv", level: 0.6 },
  "ʃ": { kind: "fric", voiced: false, F: PAL, noise: "pal", level: 1.0 },
  "ʒ": { kind: "fric", voiced: true, F: PAL, noise: "pal", level: 0.6 },
  h: { kind: "asp", voiced: false, F: null },
  "tʃ": { kind: "affr", voiced: false, F: PAL, noise: "pal", level: 1.0 },
  "dʒ": { kind: "affr", voiced: true, F: PAL, noise: "pal", level: 0.6 },
  m: { kind: "nasal", voiced: true, F: [280, 1100, 2200], zero: 900 },
  n: { kind: "nasal", voiced: true, F: [280, 1700, 2600], zero: 1600 },
  "ŋ": { kind: "nasal", voiced: true, F: [280, 2100, 2700], zero: 3000 },
  "m̩": { kind: "nasal", voiced: true, F: [280, 1100, 2200], zero: 900 },
  "n̩": { kind: "nasal", voiced: true, F: [280, 1700, 2600], zero: 1600 },
  l: { kind: "approx", voiced: true, F: [360, 1050, 2650] }, "l̩": { kind: "approx", voiced: true, F: [360, 1050, 2650] },
  "ɹ": { kind: "approx", voiced: true, F: [310, 1060, 1380] },
  w: { kind: "approx", voiced: true, F: [300, 610, 2200] }, j: { kind: "approx", voiced: true, F: [270, 2200, 3000] },
};
const F45 = [3500, 4500];
const BW = [70, 90, 150, 200, 250];

// Apparent vocal-tract length of the reference table, by the same method as
// voiceprofile.py (formant dispersion over F1-F4), so profiles scale it consistently.
const REF_VTL = (() => {
  const vs = Object.values(V);
  const mean = [0, 1, 2].map((i) => vs.reduce((s, v) => s + v[i], 0) / vs.length).concat([F45[0]]);
  const k = [0.5, 1.5, 2.5, 3.5];
  const df = k.reduce((s, x, i) => s + x * mean[i], 0) / k.reduce((s, x) => s + x * x, 0);
  return 35000 / (2 * df);
})();

// --- voice --------------------------------------------------------------------

function voiceSettings(doc, voice, speaker) {
  const spk = Object.values(doc.speakers || {})[0] || {};
  const median = voice?.pitch?.median_hz ?? spk.f0_median_hz ?? 120;
  let range = 1;
  if (voice?.pitch?.range_st && speaker?.pitch?.range_st) range = voice.pitch.range_st / speaker.pitch.range_st;
  const t = voice?.timbre || {};
  const k = t.vocal_tract_cm ? Math.min(1.5, Math.max(0.7, REF_VTL / t.vocal_tract_cm)) : 1;
  const measured = {};
  for (const [v, f] of Object.entries(t.formants_hz || {})) {
    if ((t.formant_tokens?.[v] ?? 0) >= 3) measured[v] = f;
  }
  const tilt = t.spectral_tilt_db_per_octave ?? -8;
  return {
    median, range, k, measured,
    tilt: Math.min(0.85, Math.max(0, (-tilt - 6) / 8)), // one-pole low-pass coefficient on the source
    breath: t.hnr_db != null ? Math.min(0.5, Math.max(0.02, (18 - t.hnr_db) / 30)) : 0.08,
    jitter: Math.min(0.02, (t.jitter_local ?? 0.01) * 0.5),
    shimmer: Math.min(0.08, (t.shimmer_local ?? 0.04) * 0.5),
  };
}

function vowelFormants(v, vs) {
  if (vs.measured[v]) return vs.measured[v].slice(0, 4).concat([F45[1] * vs.k]);
  const f = V[v] || V["ə"];
  return f.map((x) => x * vs.k).concat(F45.map((x) => x * vs.k));
}

function consonantFormants(f, vs) {
  return f ? f.map((x) => x * vs.k).concat(F45.map((x) => x * vs.k)) : null;
}

// --- plan: per-phone formant keys and source segments ----------------------------

function plan(doc, vs, rate) {
  const phones = [];
  doc.utterances.forEach((u, ui) => u.words.forEach((w, wi) => w.phones.forEach((p) => {
    phones.push({ ...p, utt: ui, word: wi, t0: p.start_s / rate, t1: (p.start_s + p.dur_ms / 1000) / rate });
  })));
  const fkeys = []; // [t, [F1..F5], [B1..B5]]
  const segs = []; // {t0, t1, AV, AH, AF, noise, nz}
  const pkeys = []; // [t, semitones]
  const gkeys = []; // [t, dB]
  for (const p of phones) {
    const ipa = p.ipa;
    const d = p.t1 - p.t0;
    const w = Math.min(0.025, d / 3);
    const c = C[ipa];
    const bw = c?.kind === "nasal" ? [100, 120, 180, 250, 300] : BW;
    if (V[ipa] || DIPH[ipa] || !c) {
      const [a, b] = DIPH[ipa] || [ipa, ipa];
      fkeys.push([p.t0 + w, vowelFormants(a, vs), bw], [p.t1 - w, vowelFormants(b, vs), bw]);
      segs.push({ t0: p.t0, t1: p.t1, AV: 1 });
    } else {
      const F = consonantFormants(c.F, vs);
      if (F) fkeys.push([p.t0 + w, F, bw], [p.t1 - w, F, bw]);
      const nz = c.zero ? c.zero * vs.k : 0;
      const noise = c.noise ? NOISE[c.noise] : null;
      if (c.kind === "stop") {
        const tc = p.t0 + d * 0.6, tb = Math.min(p.t1, tc + Math.min(0.01, d * 0.2));
        segs.push({ t0: p.t0, t1: tc, AV: c.voiced ? 0.12 : 0 });
        segs.push({ t0: tc, t1: tb, AF: 0.9, noise: NOISE[c.burst] });
        segs.push({ t0: tb, t1: p.t1, AV: c.voiced ? 0.6 : 0, AH: c.voiced ? 0 : 0.5 });
      } else if (c.kind === "affr") {
        const tc = p.t0 + d * 0.35;
        segs.push({ t0: p.t0, t1: tc, AV: c.voiced ? 0.12 : 0 });
        segs.push({ t0: tc, t1: p.t1, AF: c.level, noise, AV: c.voiced ? 0.45 : 0 });
      } else if (c.kind === "fric") {
        segs.push({ t0: p.t0, t1: p.t1, AF: c.level, noise, AV: c.voiced ? 0.5 : 0 });
      } else if (c.kind === "asp") {
        segs.push({ t0: p.t0, t1: p.t1, AH: 0.6 });
      } else if (c.kind === "glottal") {
        segs.push({ t0: p.t0, t1: p.t0 + d * 0.2, AV: 0.5 }, { t0: p.t0 + d * 0.8, t1: p.t1, AV: 0.5 });
      } else if (c.kind === "flap") {
        segs.push({ t0: p.t0, t1: p.t1, AV: 0.45 });
      } else if (c.kind === "nasal") {
        segs.push({ t0: p.t0, t1: p.t1, AV: 0.7, nz });
      } else {
        segs.push({ t0: p.t0, t1: p.t1, AV: 0.8 });
      }
    }
    const mid = (p.t0 + p.t1) / 2;
    if (p.pitch_st != null) pkeys.push([mid, p.pitch_st]);
    gkeys.push([mid, Math.max(-20, Math.min(12, p.loud_db ?? 0))]);
  }
  return { phones, fkeys, segs, pkeys, gkeys };
}

function interp(keys, t, def) {
  if (!keys.length) return def;
  if (t <= keys[0][0]) return keys[0][1];
  if (t >= keys[keys.length - 1][0]) return keys[keys.length - 1][1];
  let lo = 0, hi = keys.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (keys[m][0] <= t) lo = m; else hi = m; }
  const [ta, a] = keys[lo], [tb, b] = keys[hi];
  const x = tb > ta ? (t - ta) / (tb - ta) : 0;
  return Array.isArray(a) ? a.map((v, i) => v + (b[i] - v) * x) : a + (b - a) * x;
}

// --- signal processing -------------------------------------------------------------

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

function coefs(f, bw) {
  const c = -Math.exp(-2 * Math.PI * bw / SR);
  const b = 2 * Math.exp(-Math.PI * bw / SR) * Math.cos(2 * Math.PI * f / SR);
  return [1 - b - c, b, c];
}

class Resonator { // Klatt (1980) two-pole resonator, unity gain at 0 Hz or at its peak
  constructor() { this.y1 = 0; this.y2 = 0; this.a = 1; this.b = 0; this.c = 0; }
  set(f, bw, peak = false) {
    [this.a, this.b, this.c] = coefs(Math.min(f, SR / 2 - 200), bw);
    if (peak) { // normalise the gain at the centre frequency
      const w = 2 * Math.PI * f / SR;
      const re = 1 - this.b * Math.cos(w) - this.c * Math.cos(2 * w), im = this.b * Math.sin(w) + this.c * Math.sin(2 * w);
      this.a = Math.hypot(re, im);
    }
  }
  run(x) { const y = this.a * x + this.b * this.y1 + this.c * this.y2; this.y2 = this.y1; this.y1 = y; return y; }
}

class AntiResonator {
  constructor() { this.x1 = 0; this.x2 = 0; this.a = 1; this.b = 0; this.c = 0; }
  set(f, bw) { const [a, b, c] = coefs(f, bw); this.a = 1 / a; this.b = -b / a; this.c = -c / a; }
  run(x) { const y = this.a * x + this.b * this.x1 + this.c * this.x2; this.x2 = this.x1; this.x1 = x; return y; }
}

// --- synthesis -------------------------------------------------------------------

export function synthesize(doc, { voice = null, speaker = null, rate = 1, seed = 1 } = {}) {
  const vs = voiceSettings(doc, voice, speaker);
  const { phones, fkeys, segs, pkeys, gkeys } = plan(doc, vs, rate);
  const end = phones.length ? phones[phones.length - 1].t1 + 0.15 : 0.15;
  const nFrames = Math.ceil(end / FRAME);
  const N = nFrames * Math.round(FRAME * SR);
  const out = new Float32Array(N);
  const spf = Math.round(FRAME * SR);

  // per-frame source amplitudes from segments, smoothed over 3 frames (about 15 ms ramps)
  const fr = (k) => new Float32Array(nFrames);
  const AV = fr(), AH = fr(), AF = fr(), NZ = fr();
  const noiseAt = new Array(nFrames).fill(null);
  for (const s of segs) {
    for (let i = Math.max(0, Math.floor(s.t0 / FRAME)); i < Math.min(nFrames, Math.ceil(s.t1 / FRAME)); i++) {
      const tc = (i + 0.5) * FRAME;
      if (tc < s.t0 || tc >= s.t1) continue;
      AV[i] = s.AV || 0; AH[i] = s.AH || 0; AF[i] = s.AF || 0; NZ[i] = s.nz || 0;
      if (s.noise) noiseAt[i] = s.noise;
    }
  }
  const smooth = (a) => a.map((_, i) => (a[Math.max(0, i - 1)] + a[i] + a[Math.min(a.length - 1, i + 1)]) / 3);
  const sAV = smooth(AV), sAH = smooth(AH), sAF = smooth(AF);

  const casc = [0, 1, 2, 3, 4].map(() => new Resonator());
  const anti = new AntiResonator();
  const par = [0, 1].map(() => new Resonator());
  const rand = rng(seed);
  const gauss = () => { let s = 0; for (let i = 0; i < 6; i++) s += rand(); return (s - 3) / Math.sqrt(0.5); };

  let phase = 0, periodF0 = vs.median, periodAmp = 1, tiltY = 0, hpX = 0, hpY = 0, n = 0;
  let lastNoise = null;
  const fk = fkeys.map(([tt, f, b]) => [tt, f.concat(b)]);
  const neutral = vowelFormants("ə", vs).concat(BW);
  for (let i = 0; i < nFrames; i++) {
    const t = (i + 0.5) * FRAME;
    const k = interp(fk, t, null) || neutral;
    const F = k.slice(0, 5), B = k.slice(5);
    for (let j = 0; j < 5; j++) casc[j].set(F[j], B[j]);
    const nasal = NZ[i] > 0;
    if (nasal) anti.set(NZ[i], 150);
    const noise = noiseAt[i] || lastNoise;
    if (noiseAt[i]) lastNoise = noiseAt[i];
    if (noise) noise.peaks.forEach(([f, bw], j) => par[j].set(f * Math.sqrt(vs.k), bw, true));
    const st = interp(pkeys, t, 0) * vs.range;
    const f0 = vs.median * Math.pow(2, st / 12);
    const gain = Math.pow(10, interp(gkeys, t, 0) / 20);
    for (let s = 0; s < spf; s++, n++) {
      // glottal source: KLGLOTT88 flow derivative, open quotient 0.6, with jitter and shimmer per period
      phase += periodF0 / SR;
      if (phase >= 1) {
        phase -= 1;
        periodF0 = f0 * (1 + vs.jitter * gauss());
        periodAmp = 1 + vs.shimmer * gauss();
      }
      const oq = 0.6;
      let g = 0;
      if (phase < oq) { const x = phase / oq; g = (2 * x - 3 * x * x) * 6; }
      g *= periodAmp;
      tiltY = (1 - vs.tilt) * g + vs.tilt * tiltY;
      const open = phase < oq ? 1 : 0.3;
      const voiced = sAV[i] * tiltY + sAV[i] * vs.breath * gauss() * open * 0.6;
      let x = (voiced + sAH[i] * gauss() * 0.5) * gain;
      if (nasal) x = anti.run(x);
      for (let j = 0; j < 5; j++) x = casc[j].run(x);
      let y = x;
      if (sAF[i] > 0 && noise) {
        const nz = gauss() * sAF[i] * gain;
        let fsum = noise.bypass * nz;
        noise.peaks.forEach(([, , a], j) => { fsum += a * par[j].run(nz); });
        y += fsum * 0.6;
      }
      hpY = y - hpX + 0.995 * hpY; hpX = y; // remove DC
      out[n] = hpY;
    }
  }
  let peak = 0;
  for (const v of out) peak = Math.max(peak, Math.abs(v));
  if (peak > 0) for (let i = 0; i < out.length; i++) out[i] *= 0.9 / peak;
  return {
    samples: out, sampleRate: SR,
    phones: phones.map((p, index) => ({ index, ipa: p.ipa, utt: p.utt, word: p.word, start: p.t0, end: p.t1 })),
    voice: vs,
  };
}

export function wav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 32767, true));
  return new Uint8Array(buf);
}
