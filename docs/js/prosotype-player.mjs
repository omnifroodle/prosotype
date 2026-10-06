// <prosotype-player>: embed a ProsoType stream in a web page, drawn in the
// standard visual mapping (SPEC 5, mapping B) and playable with the reference
// synthesiser (SPEC 11), highlighting each glyph and word as it sounds. MIT licence.
//
//   <script type="module" src="prosotype-player.mjs"></script>
//   <prosotype-player src="hand.16a.prs" text="hand.16a.text.json"
//                     voice="reference-high.json"></prosotype-player>
//
// Attributes
//   src       URL of a packed stream (.prs) or a JSON-form document (.json)
//   stream    the packed stream inline, base64 (instead of src)
//   text      URL of a text map (SPEC 4.1); or put the map in a child
//             <script type="application/json"> element
//   voice     URL of a voice profile (SPEC 10) to speak with
//   voices    space-separated voice profile URLs; shows a voice menu
//   compact   smaller type, no footer
//   synth     JSON options for the reference synthesiser, e.g. {"pitchSmooth": 60}
//   label     text for the play button (default "Play")
//   view      "controls": only the play controls and footer, for pages that
//             draw the stream themselves and follow the prosotype-phone events
// Properties: voiceProfile (a profile object; overrides voice), doc (decoded)
// Methods: play(utterance?), stop()
// Events: "prosotype-phone" {index, ipa, utterance, word}, "prosotype-end"
// Theming: --prosotype-ink, -muted, -unvoiced, -rule, -guide, -highlight,
//          -highlight-ink, -surface, -size (glyph size)
// Children are shown until the element upgrades, so a static rendering inside
// it works as the no-JavaScript fallback.

import { decode } from "./prosotype.mjs";
import { synthesize } from "./synth.mjs";

// --- mapping B, at 16a levels (same tables as prototype/render.py) -----------------
const WEIGHT = [300, 325, 350, 400, 500, 600, 750, 900];
const WIDTH = [62.5, 70, 78, 86, 94, 100, 100, 100];
const TRACK = [0, 0, 0, 0, 0, 0, 0.06, 0.14];
const RAISE = 0.075;
const DUR = [30, 45, 65, 95, 140, 200, 300, 450];
const rnd = (x) => (x >= 0 ? Math.floor(x + 0.5) : -Math.floor(-x + 0.5));
const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const nearest = (v, c) => c.slice(1).reduce((n, b, i) => n + (v > Math.sqrt(c[i] * b) ? 1 : 0), 0);
const qPitch = (p) => (!p.voiced || p.pitch_st == null ? 0 : clip(rnd(p.pitch_st / 1.5) + 8, 1, 15));
const qDur = (p) => nearest(p.dur_ms, DUR);
const qLoud = (p) => clip(rnd((p.loud_db ?? 0) / 3) + 4, 0, 7);

const FONT_URL = new URL("./prosotype-ipa.woff2", import.meta.url).href;
let fontAdded = false;
function addFont() { // @font-face must live in the document, not a shadow root
  if (fontAdded) return;
  fontAdded = true;
  const s = document.createElement("style");
  s.textContent = `@font-face{font-family:'ProsoType IPA';src:url(${FONT_URL}) format('woff2');` +
    "font-weight:100 900;font-stretch:62.5% 100%;font-display:swap}";
  document.head.append(s);
}

const levelCss = [
  ...Array.from({ length: 16 }, (_, i) => `.pb${i}{transform:translateY(${(-(i === 0 ? 0 : i - 8) * RAISE).toFixed(3)}em)}`),
  ...Array.from({ length: 8 }, (_, i) => `.l${i}{font-weight:${WEIGHT[i]}}.w${i}{font-stretch:${WIDTH[i]}%;letter-spacing:${TRACK[i]}em}`),
].join("");

const STYLE = `
:host{display:block;--ink:var(--prosotype-ink,#1b1b1f);--muted:var(--prosotype-muted,#5f5f68);
--unvoiced:var(--prosotype-unvoiced,#6c6c74);--rule:var(--prosotype-rule,#e4e4df);--guide:var(--prosotype-guide,#c9c9c2);
--hl:var(--prosotype-highlight,oklch(0.9 0.08 85));--hl-ink:var(--prosotype-highlight-ink,#1b1b1f);
--surface:var(--prosotype-surface,transparent);color:var(--ink)}
@media (prefers-color-scheme:dark){:host{--ink:var(--prosotype-ink,#ececf0);--muted:var(--prosotype-muted,#a3a3ad);
--unvoiced:var(--prosotype-unvoiced,#9a9aa3);--rule:var(--prosotype-rule,#2c2c33);--guide:var(--prosotype-guide,#4a4a53);
--hl:var(--prosotype-highlight,oklch(0.45 0.09 85));--hl-ink:var(--prosotype-highlight-ink,#fff)}}
.box{background:var(--surface);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:4px}
button,select{font:inherit;font-size:14px;color:var(--ink);background:transparent;border:1px solid var(--rule);border-radius:8px;padding:5px 10px}
button{cursor:pointer;font-weight:600}
button.row{padding:0 7px;font-size:12px;line-height:20px;border-radius:999px}
.utt{padding:6px 0 2px;border-top:1px solid var(--rule)}
.top + .utt{border-top:0}
.cap{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline;font-size:13px;color:var(--muted)}
.cap b{color:var(--ink);font-weight:600;text-transform:capitalize}
.cap .t span{border-radius:3px}
.ipa{font-family:'ProsoType IPA',sans-serif;font-size:var(--prosotype-size,clamp(24px,4.2vw,34px));line-height:2.3;overflow-wrap:anywhere}
:host([compact]) .ipa{font-size:var(--prosotype-size,24px);line-height:2.1}
.w{white-space:nowrap;background:linear-gradient(to bottom,transparent calc(78.5% - 1px),var(--guide) calc(78.5% - 1px),var(--guide) 78.5%,transparent 78.5%)}
.p{display:inline-block;border-radius:3px}
.unv{color:var(--unvoiced)}
.pause{display:inline-block;height:.9em;vertical-align:middle;border-left:2px solid var(--rule);border-right:2px solid var(--rule)}
.now{background:var(--hl);color:var(--hl-ink)}
.foot{font-size:12px;color:var(--muted);margin-top:4px}
.foot a{color:inherit}
:host([compact]) .foot{display:none}
.err{color:var(--muted);font-size:13px}
${levelCss}`;

let ctx = null, playing = null; // one shared AudioContext; one player sounds at a time

class ProsoTypePlayer extends HTMLElement {
  static observedAttributes = ["src", "stream", "text", "voice", "voices"];

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.voiceProfile = null;
    this._voices = {};
    this._timer = 0;
  }

  connectedCallback() { addFont(); this._load(); }
  attributeChangedCallback() { if (this.isConnected) this._load(); }
  disconnectedCallback() { this.stop(); }

  async _load() {
    const token = (this._token = {});
    this.stop();
    try {
      const [bytes, json] = await this._fetchStream();
      const text = await this._fetchText();
      const voiceUrls = (this.getAttribute("voices") || "").split(/\s+/).filter(Boolean);
      const vurl = this.getAttribute("voice");
      for (const u of new Set([...voiceUrls, ...(vurl ? [vurl] : [])])) {
        this._voices[u] ??= await (await fetch(u)).json();
      }
      if (token !== this._token) return;
      this.doc = json ?? decode(bytes);
      this._bytes = bytes;
      this._text = text;
      this._render(voiceUrls, vurl);
    } catch (e) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><p class="err">Could not load this ProsoType stream (${e.message}).</p>`;
    }
  }

  async _fetchStream() {
    const inline = this.getAttribute("stream");
    if (inline) return [Uint8Array.from(atob(inline.trim()), (c) => c.charCodeAt(0)), null];
    const src = this.getAttribute("src");
    if (!src) throw new Error("no src or stream attribute");
    const r = await fetch(src);
    if (!r.ok) throw new Error(`${src}: ${r.status}`);
    if (src.endsWith(".json")) return [null, await r.json()];
    return [new Uint8Array(await r.arrayBuffer()), null];
  }

  async _fetchText() {
    const url = this.getAttribute("text");
    if (url) return (await fetch(url)).json();
    const child = this.querySelector('script[type="application/json"]');
    return child ? JSON.parse(child.textContent) : null;
  }

  _render(voiceUrls, vurl) {
    const doc = this.doc, tm = this._text;
    const multi = doc.utterances.length > 1;
    let pi = 0, wi = 0;
    const rows = doc.utterances.map((u, ui) => {
      const phones = u.words.flatMap((w) => w.phones);
      // unvoiced glyphs sit at the height of the previous voiced phone (or the next one)
      const lv = phones.map(qPitch), h = [];
      let last = null;
      lv.forEach((l, i) => { if (l) last = l; h[i] = last; });
      let next = null;
      for (let i = lv.length - 1; i >= 0; i--) { if (lv[i]) next = lv[i]; h[i] ??= next ?? 8; }
      let k = 0, prevEnd = null;
      const glyphs = u.words.map((w) => {
        let gap = "";
        if (prevEnd != null) {
          const ms = Math.max(0, (w.start_s - prevEnd) * 1000);
          gap = ms >= 71 ? ` <span class="pause" style="width:${(0.6 + 0.5 * Math.log2(ms / 100)).toFixed(2)}em" title="pause ${Math.round(ms)} ms"></span> ` : " ";
        }
        const spans = w.phones.map((p) => {
          const pl = qPitch(p), dl = qDur(p), ll = qLoud(p);
          const cls = pl ? `p pb${pl} w${dl} l${ll}` : `p pb${h[k]} unv w${dl} l${ll}`;
          const tip = `/${p.ipa}/ ${pl ? `${p.pitch_st >= 0 ? "+" : ""}${p.pitch_st.toFixed(1)} st` : "unvoiced"}, ${Math.round(p.dur_ms)} ms`;
          k++;
          return `<span class="${cls}" data-i="${pi++}" title="${tip}">${esc(p.ipa)}</span>`;
        }).join("");
        if (w.phones.length) { const l = w.phones[w.phones.length - 1]; prevEnd = l.start_s + l.dur_ms / 1000; }
        return `${gap}<span class="w" data-w="${wi++}">${spans}</span>`;
      }).join("");
      let cap = "";
      const label = tm?.labels?.[ui];
      const ranges = tm?.utterances?.[ui];
      if (label || ranges) {
        let words = "";
        if (ranges?.length) {
          const base = wi - u.words.length;
          let pos = ranges[0][0];
          words = ranges.map(([a, b], j) => { const pre = esc(tm.text.slice(pos, a)); pos = b; return `${pre}<span data-tw="${base + j}">${esc(tm.text.slice(a, b))}</span>`; }).join("");
        }
        cap = `<div class="cap">${multi ? `<button class="row" data-u="${ui}" aria-label="Play this line">▶</button>` : ""}` +
          `${label ? `<b>${esc(label)}</b>` : ""}<span class="t">${words}</span></div>`;
      }
      return `<div class="utt">${cap}<div class="ipa" lang="und-fonipa">${glyphs}</div></div>`;
    }).join("");
    const opts = voiceUrls.length ? `<option value="">speaker's pitch</option>` + voiceUrls.map((u) =>
      `<option value="${esc(u)}"${u === vurl ? " selected" : ""}>${esc(this._voices[u]?.id ?? u)}</option>`).join("") : "";
    const size = this._bytes ? `${this._bytes.length} bytes` : "JSON form";
    const dl = this._bytes ? `<a href="${URL.createObjectURL(new Blob([this._bytes], { type: "application/octet-stream" }))}" download="stream.prs">download stream</a>` : "";
    const controlsOnly = this.getAttribute("view") === "controls";
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><div class="box" part="box">
<div class="top"><button class="main" aria-label="Play">${esc(this.getAttribute("label") || "Play")}</button>${opts ? `<select aria-label="Voice">${opts}</select>` : ""}</div>
${controlsOnly ? "" : rows}
<div class="foot">ProsoType ${esc(doc.profile ?? "")} · ${size} · ${doc.utterances.length} utterance${multi ? "s" : ""} ${dl ? "· " + dl : ""}</div></div>`;
    this.shadowRoot.querySelector(".main").onclick = () => (this._source ? this.stop() : this.play());
    this.shadowRoot.querySelectorAll("button.row").forEach((b) => (b.onclick = () => this.play(+b.dataset.u)));
    const sel = this.shadowRoot.querySelector("select");
    if (sel) sel.onchange = () => { this.stop(); if (sel.value) this.setAttribute("voice", sel.value); else this.removeAttribute("voice"); };
  }

  _voice() {
    if (this.voiceProfile) return this.voiceProfile;
    const sel = this.shadowRoot.querySelector("select");
    const u = sel ? sel.value : this.getAttribute("voice");  // "" in the menu: the stream speaker's own pitch
    return u ? this._voices[u] : null;
  }

  play(utterance = null) {
    if (!this.doc) return;
    if (playing && playing !== this) playing.stop();
    this.stop();
    // one utterance: play it alone, shifted to start at zero
    let doc = this.doc, uOffset = 0, wOffset = 0, pOffset = 0, t0doc = 0;
    if (utterance != null) {
      const u = this.doc.utterances[utterance];
      const first = u.words.find((w) => w.phones.length)?.phones[0];
      t0doc = first ? first.start_s : 0;
      this.doc.utterances.slice(0, utterance).forEach((v) => { wOffset += v.words.length; pOffset += v.words.reduce((n, w) => n + w.phones.length, 0); });
      uOffset = utterance;
      const shift = (p) => ({ ...p, start_s: p.start_s - t0doc });
      doc = { ...this.doc, utterances: [{ ...u, words: u.words.map((w) => ({ ...w, start_s: w.start_s - t0doc, phones: w.phones.map(shift) })) }] };
    }
    let extra = {};
    try { extra = JSON.parse(this.getAttribute("synth") || "{}"); } catch {}
    const res = synthesize(doc, { ...extra, voice: this._voice() });
    ctx ??= new AudioContext();
    const buf = ctx.createBuffer(1, res.samples.length, res.sampleRate);
    buf.copyToChannel(res.samples, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const start = ctx.currentTime + 0.05;
    src.start(start);
    src.onended = () => { if (this._source === src) this.stop(); this.dispatchEvent(new CustomEvent("prosotype-end")); };
    this._source = src;
    playing = this;
    const main = this.shadowRoot.querySelector(".main");
    main.textContent = "Stop"; main.setAttribute("aria-label", "Stop");
    // word index across the whole stream, per (utterance, word)
    const base = []; let n = 0;
    this.doc.utterances.forEach((u, i) => { base[i] = n; n += u.words.length; });
    const sr = this.shadowRoot;
    let k = 0, lit = null;
    const tick = () => { // scheduled at phone boundaries on the audio clock
      const t = ctx.currentTime - start;
      while (k < res.phones.length && res.phones[k].end <= t) k++;
      const p = res.phones[k];
      const on = p && t >= p.start ? p : null;
      if (on !== lit) {
        sr.querySelectorAll(".now").forEach((e) => e.classList.remove("now"));
        if (on) {
          const ui = on.utt + uOffset, gw = base[ui] + on.word, gi = on.index + pOffset;
          sr.querySelector(`[data-i="${gi}"]`)?.classList.add("now");
          sr.querySelector(`[data-tw="${gw}"]`)?.classList.add("now");
          this.dispatchEvent(new CustomEvent("prosotype-phone", { detail: { index: gi, ipa: on.ipa, utterance: ui, word: gw } }));
        }
        lit = on;
      }
      if (this._source !== src || !p) return;
      this._timer = setTimeout(tick, Math.max(1, ((on ? p.end : p.start) - (ctx.currentTime - start)) * 1000));
    };
    tick();
  }

  stop() {
    clearTimeout(this._timer);
    const src = this._source;
    this._source = null;
    if (src) { try { src.stop(); } catch {} }
    if (playing === this) playing = null;
    this.shadowRoot?.querySelectorAll(".now").forEach((e) => e.classList.remove("now"));
    const main = this.shadowRoot?.querySelector(".main");
    if (main) { main.textContent = this.getAttribute("label") || "Play"; main.setAttribute("aria-label", "Play"); }
  }
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

if (!customElements.get("prosotype-player")) customElements.define("prosotype-player", ProsoTypePlayer);
export { ProsoTypePlayer };
