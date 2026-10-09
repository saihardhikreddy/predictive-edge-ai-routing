import { createWorld } from "./world.js";
import { createDemoEngine } from "./demo.js";

const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ─── engine bridge: the real Bluetooth engine inside the app, a demo in a browser ─── */
let engine;
if (window.Android && typeof window.Android.call === "function") {
  engine = { call: (name, args = []) => window.Android.call(name, JSON.stringify(args)) };
} else {
  engine = createDemoEngine((s) => onState(s));
}
window.meshUpdate = (payload) => onState(typeof payload === "string" ? JSON.parse(payload) : payload);

/* ─── world ─── */
const boot = () => document.body.classList.add("ready");
const world = createWorld($("world"), { onSelect: select, onFirstFrame: boot, reducedMotion: reduced });
if (!world) { document.body.classList.add("no-webgl"); boot(); }
if (new URLSearchParams(location.search).has("debug")) window.__world = world;
setTimeout(boot, 4000);

/* ─── chapters ─── */
let chapter = "mesh";
let selected = null;
function goTo(name) {
  chapter = name;
  document.body.dataset.chapter = name;
  document.querySelectorAll(".nav button").forEach((b) => b.toggleAttribute("aria-current", b.dataset.goto === name));
  document.querySelectorAll(".nav button[aria-current]").forEach((b) => b.setAttribute("aria-current", "page"));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.dataset.panel !== name));
  if (name !== "mesh") selected = null;
  world?.setChapter(name, name === "mesh" ? selected : null);
  $("sheet-body").scrollTop = 0;
  render(true);
}
document.querySelectorAll(".nav button").forEach((b) => b.addEventListener("click", () => goTo(b.dataset.goto)));

function select(id) {
  if (chapter !== "mesh") { if (!id) return; goTo("mesh"); }
  selected = id && id !== selected ? id : null;
  world?.setChapter("mesh", selected);
  render(true);
}

/* ─── bottom sheet: drag the grip between a peek and a tall view ─── */
const sheet = $("sheet");
const NAV = 64;
let sheetFrac = 0.42;
function applySheet() {
  const landscape = matchMedia("(orientation: landscape) and (min-width: 700px)").matches;
  const px = landscape ? 0 : Math.round(innerHeight * sheetFrac);
  sheet.style.setProperty("--sheet-h", `${px}px`);
  world?.setViewInset(landscape ? 0 : px + NAV);
}
let drag = null;
$("grip").addEventListener("pointerdown", (e) => { drag = { y: e.clientY, f: sheetFrac, moved: false }; sheet.classList.add("dragging"); $("grip").setPointerCapture(e.pointerId); });
$("grip").addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dy = drag.y - e.clientY;
  if (Math.abs(dy) > 4) drag.moved = true;
  sheetFrac = Math.min(0.8, Math.max(0.2, drag.f + dy / innerHeight));
  applySheet();
});
$("grip").addEventListener("pointerup", () => {
  if (!drag) return;
  sheet.classList.remove("dragging");
  if (!drag.moved) sheetFrac = sheetFrac < 0.55 ? 0.74 : 0.42;
  else sheetFrac = sheetFrac > 0.58 ? 0.74 : sheetFrac < 0.3 ? 0.24 : 0.42;
  drag = null;
  applySheet();
});
addEventListener("resize", applySheet);
applySheet();

/* ─── controls ─── */
const call = (name, ...args) => engine.call(name, args);
$("power").addEventListener("click", () => call(S?.running ? "stop" : "start"));
$("pill").addEventListener("click", () => {
  const n = prompt("Name this phone", S?.nick || "");
  if (n != null) call("setNick", n);
});
document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => call("setMode", b.dataset.mode)));
$("triage").addEventListener("change", (e) => call("setTriage", e.target.checked));
$("sinkhole").addEventListener("change", (e) => call("setSinkhole", e.target.checked));
$("range").addEventListener("input", (e) => { $("range-out").textContent = rangeLabel(+e.target.value); });
$("range").addEventListener("change", (e) => call("setRange", +e.target.value));
$("reset-trust").addEventListener("click", () => call("clearTrust"));

let dest = null;
$("dest").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) { dest = b.dataset.id; render(true); } });
$("send").addEventListener("click", () => {
  if (!dest) return toast("Pick a phone to send to");
  const t = $("text").value.trim();
  if (!t) return toast("Write a message first");
  call("send", dest, t);
  $("text").value = "";
});
$("sos").addEventListener("click", () => {
  if (!dest) return toast("Pick a phone to send to");
  const t = $("text").value.trim() || "SOS: I need help here, people are injured and trapped.";
  call("send", dest, t);
  $("text").value = "";
});

for (const [id, fmt] of [["n", (v) => `${v}`], ["iv", (v) => `${v} s`], ["sosf", (v) => `${v}%`]]) {
  const upd = () => ($(`${id}-out`).textContent = fmt($(id).value));
  $(id).addEventListener("input", upd);
  upd();
}
$("run").addEventListener("click", () => call("startExperiment", +$("n").value, +$("iv").value * 1000, +$("sosf").value / 100));
$("stop-run").addEventListener("click", () => call("stopExperiment"));
$("save").addEventListener("click", () => toast(call("exportLog") || "Saved"));
$("share").addEventListener("click", () => { const r = call("shareLog"); if (r) toast(r); });
$("reset").addEventListener("click", () => call("resetStats"));

let toastT = 0;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => (el.hidden = true), 2600);
}

/* ─── state → screen ─── */
let S = null;
let lastSeq = -1;
function onState(s) {
  S = s;
  world?.setState(s);
  world?.handleEvents(s.events);
  for (const e of s.events || []) {
    if (e.seq <= lastSeq) continue;
    lastSeq = e.seq;
    if (e.ev === "DELACK_RX") {
      const m = (s.messages || []).find((x) => x.id === e.msg);
      if (m) toast(`Delivered to ${m.peerName} in ${m.hops} ${m.hops === 1 ? "hop" : "hops"}, ${(m.rttMs / 1000).toFixed(1)} s round trip`);
    } else if (e.ev === "QUARANTINE") {
      const n = (s.neighbors || []).find((x) => x.id === e.peer);
      toast(`${n?.nick || e.peer} kept dropping messages and was cut out of your routes`);
    } else if (e.ev === "ERROR") toast(e.value);
  }
  render(false);
}

const memo = new Map();
function put(id, html) {
  if (memo.get(id) === html) return;
  memo.set(id, html);
  $(id).innerHTML = html;
}
/* Keyed list update: rows are reused by key and only their contents change, so the
   element under a finger survives the 2-4 state pushes per second (a tap whose
   pointerdown and pointerup land on different elements is otherwise lost). */
function keyed(id, items, empty, wrap) {
  const el = $(id);
  if (!items.length) { put(id, empty); return; }
  if (memo.has(id)) { memo.delete(id); el.innerHTML = ""; }
  const old = new Map([...el.children].map((c) => [c.dataset.key, c]));
  items.forEach((it, i) => {
    let c = old.get(it.key);
    if (c) old.delete(it.key);
    else {
      c = document.createElement(it.tag || "li");
      c.dataset.key = it.key;
      if (wrap) c.innerHTML = wrap;
    }
    for (const [k, v] of Object.entries(it.attrs || {})) if (c.getAttribute(k) !== v) c.setAttribute(k, v);
    const target = wrap ? c.firstElementChild : c;
    for (const [k, v] of Object.entries(it.innerAttrs || {})) if (target.getAttribute(k) !== v) target.setAttribute(k, v);
    if (c._html !== it.html) { c._html = it.html; target.innerHTML = it.html; }
    if (el.children[i] !== c) el.insertBefore(c, el.children[i] || null);
  });
  old.forEach((c) => c.remove());
}
/* "SOS[TRAPPED,COLLAPSE]p3" (the compact on-air form) -> readable text */
const SOS_WORDS = { SOS: "SOS", TRAPPED: "people trapped", INJURED: "injuries", BLEEDING: "bleeding", UNCONSCIOUS: "someone unconscious",
  FIRE: "fire", COLLAPSE: "building collapse", FLOOD: "flooding", QUAKE: "earthquake damage", MEDICAL: "needs medical help", VIOLENCE: "violence" };
function readable(text) {
  const m = /^SOS\[([A-Z,]*)\](?:p(\d+))?$/.exec(text || "");
  if (!m) return text;
  const parts = m[1].split(",").filter(Boolean).map((t) => SOS_WORDS[t] || t.toLowerCase()).filter((t) => t !== "SOS");
  return `Emergency: ${parts.join(", ") || "help needed"}${m[2] ? `, ${m[2]} people` : ""}`;
}
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const rangeLabel = (v) => (v <= -99 ? "Off" : `Stronger than ${v} dBm`);
const modeName = (m) => (m === "F" ? "flooding" : "learned route");

function render(force) {
  if (!S) return;
  if (force) memo.clear();
  const present = (S.neighbors || []).filter((n) => n.present && !n.blocked);
  document.body.classList.toggle("running", !!S.running);
  document.body.classList.toggle("attacker", !!S.sinkhole);
  $("pill-name").textContent = S.nick || "This phone";
  $("pill-sub").textContent = !S.running ? (S.status === "Stopped" ? "Mesh off" : S.status)
    : S.sinkhole ? "Attacker mode is on"
    : present.length ? `${present.length} ${present.length === 1 ? "phone" : "phones"} in reach, ${modeName(S.mode)}` : "Looking for phones";
  $("power").textContent = S.running ? "Stop" : "Start";

  // Mesh
  $("mesh-lede").textContent = !S.running
    ? "Every phone running this app relays for the others over Bluetooth. Tap Start, then open the app on another phone."
    : present.length
      ? "Tap a phone to fly to it. Distance on the map is signal strength: closer means a stronger link."
      : "Listening. Open the app on another phone nearby and press Start there too.";
  const ns = S.neighbors || [];
  keyed("neighbors", ns.map((n) => {
    const cls = n.quarantined ? "bad" : n.present && !n.blocked ? "" : "away";
    const sub = n.quarantined ? "Cut off: kept dropping messages" : n.blocked ? "Blocked by you" : n.present ? `Link ${pct(n.linkQ)}, battery ${n.battery}%` : `Last heard ${n.seenAgoS} s ago`;
    return {
      key: n.id,
      innerAttrs: { "data-id": n.id, "aria-pressed": String(n.id === selected) },
      html: `<span class="dot ${cls}"></span><span><span class="name">${esc(n.nick || n.id)}</span><span class="sub">${esc(sub)}</span></span><span class="num">${n.rssi} dBm</span>`,
    };
  }), `<li class="empty">${S.running ? "No phones heard yet." : "Start the mesh to look for phones."}</li>`, `<button type="button"></button>`);
  const sel = ns.find((n) => n.id === selected);
  const insp = $("inspector");
  insp.hidden = !sel;
  if (sel) {
    put("inspector", `<h3>${esc(sel.nick || sel.id)}</h3><p class="hint">${sel.present ? "In direct reach" : "Out of direct reach"}${sel.quarantined ? ", cut out of routes" : ""}</p>
      <dl class="facts"><div><dt>Signal</dt><dd>${sel.rssi} dBm</dd></div><div><dt>Link quality</dt><dd>${pct(sel.linkQ)}</dd></div><div><dt>Battery</dt><dd>${sel.battery}%</dd></div>
      <div><dt>Reputation</dt><dd>${pct(sel.reputation)}</dd></div><div><dt>Suspicion</dt><dd>${pct(sel.anomaly)}</dd></div><div><dt>Id</dt><dd>${esc(sel.id.slice(0, 4))}</dd></div></dl>
      <div class="row-actions"><button class="btn" type="button" data-block="${esc(sel.id)}">${sel.blocked ? "Unblock" : "Block this phone"}</button><button class="btn" type="button" data-message="${esc(sel.id)}">Message</button></div>`);
  }

  // Send
  const known = S.known || [];
  if (!dest && known.length) dest = known[0][0];
  keyed("dest", known.map(([id, name]) => {
    const n = ns.find((x) => x.id === id);
    const tag = n?.present ? "" : "<small>via mesh</small>";
    return { key: id, tag: "button", attrs: { class: "chip", type: "button", "data-id": id, "aria-pressed": String(id === dest) }, html: `${esc(name)}${tag}` };
  }), `<p class="empty">No phones known yet. They appear here once they have been heard.</p>`);
  const msgs = (S.messages || []).slice().reverse();
  keyed("thread", msgs.map((m) => {
    const sos = m.intent === "EMERGENCY_SOS";
    const meta = m.outgoing
      ? (m.status === "delivered" ? `<span class="meta ok">Delivered in ${m.hops} ${m.hops === 1 ? "hop" : "hops"}, ${(m.rttMs / 1000).toFixed(1)} s round trip</span>` : `<span class="meta">On its way by ${modeName(m.mode)}</span>`)
      : `<span class="meta">Arrived over ${m.hops} ${m.hops === 1 ? "hop" : "hops"}</span>`;
    return { key: m.id + (m.outgoing ? ">" : "<"), attrs: { class: `msg ${m.outgoing ? "out" : "in"} ${sos ? "sos" : ""}` },
      html: `<span class="who">${m.outgoing ? "To" : "From"} ${esc(m.peerName)}${sos ? ", SOS" : ""}${m.note ? `, sent as ${esc(m.note)}` : ""}</span><p>${esc(readable(m.text))}</p>${!m.outgoing && m.text !== readable(m.text) ? `<span class="meta">Received as ${esc(m.text)}</span>` : ""}${meta}` };
  }), "");

  // Route
  document.querySelectorAll(".segmented button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === S.mode)));
  $("mode-hint").textContent = S.mode === "F"
    ? "Every phone repeats every message to everyone it hears. Reliable in small groups, but it costs every phone battery and the copies collide."
    : "Each phone hands a message to the one neighbour most likely to meet the destination, or holds it until a better one comes along. It learns from every hop.";
  $("triage").checked = !!S.triageOn;
  if (document.activeElement !== $("range")) { $("range").value = S.rangeDbm; $("range-out").textContent = rangeLabel(S.rangeDbm); }
  const names = ["Base", "Meets dest", "Link", "Battery", "Busy", "Is dest", "Hold"];
  const w = S.weights || [];
  const maxW = Math.max(1, ...w.map((x) => Math.abs(x)));
  put("weights", w.map((x, i) => `<div><i class="${x < 0 ? "neg" : ""}" style="height:${Math.max(2, Math.abs(x) / maxW * 64).toFixed(0)}px" title="${x.toFixed(2)}"></i><span>${names[i] || i}</span></div>`).join(""));
  $("learn-sub").textContent = `${S.samples || 0} lessons from real hops, ${S.flRounds || 0} times averaged with phones it met. Taller bars matter more when choosing a relay; red ones count against it.`;
  const pr = S.predictability || [];
  put("predict", pr.length ? pr.map(([name, p]) => `<li><span>${esc(name)}</span><span class="val">${pct(p)}</span><span class="track"><span class="fill" style="width:${pct(p)}"></span></span></li>`).join("") : `<li class="empty">Nothing yet. Phones show up here after you have met them.</li>`);

  // Defend
  $("sinkhole").checked = !!S.sinkhole;
  const byRisk = ns.slice().sort((a, b) => (b.quarantined - a.quarantined) || (b.anomaly - a.anomaly));
  keyed("trust", byRisk.map((n) => {
    const cls = n.quarantined || n.anomaly > 0.7 ? "bad" : n.anomaly > 0.3 ? "warn" : "";
    const val = n.quarantined ? "cut off" : `${pct(n.anomaly)} suspicious`;
    return { key: n.id, html: `<span>${esc(n.nick || n.id)}</span><span class="val">${val}</span><span class="track"><span class="fill ${cls}" style="width:${Math.max(3, n.anomaly * 100)}%"></span></span>` };
  }), `<li class="empty">No phones to judge yet.</li>`);

  // Lab
  const busy = (S.expRemaining || 0) > 0;
  $("run").disabled = !S.running || busy;
  $("stop-run").disabled = !busy;
  $("exp-progress").textContent = busy ? `Sending ${S.expTotal - S.expRemaining + 1} of ${S.expTotal}` : "";
  const row = (k, label) => {
    const st = S.stats?.[k] || {};
    const pdr = st.originated ? pct(st.confirmed / st.originated) : "–";
    const rtt = st.confirmed ? `${(st.rttSum / st.confirmed / 1000).toFixed(1)} s` : "–";
    const hops = st.confirmed ? (st.hopSum / st.confirmed).toFixed(1) : "–";
    return `<tr class="${k === "M" ? "m" : "f"}"><td>${label}</td><td>${st.originated || 0}</td><td>${pdr}</td><td>${rtt}</td><td>${hops}</td></tr>`;
  };
  put("results", `<tr><th></th><th>Sent</th><th>Arrived</th><th>Round trip</th><th>Hops</th></tr>${row("M", "Learned")}${row("F", "Flooding")}`);
  $("frames").textContent = `This phone sent ${S.txFrames || 0} frames (${S.txFails || 0} failed, ${Math.round((S.txBytes || 0) / 1024)} KB) and is holding ${S.stored || 0} for later. Only your own messages are counted here; merge every phone's CSV for the full picture.`;
  put("log", esc((S.logTail || []).join("\n")));
}

$("neighbors").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) select(b.dataset.id); });
$("inspector").addEventListener("click", (e) => {
  const blk = e.target.closest("[data-block]");
  if (blk) call("toggleBlock", blk.dataset.block);
  const msg = e.target.closest("[data-message]");
  if (msg) { dest = msg.dataset.message; goTo("send"); }
});

goTo("mesh");
