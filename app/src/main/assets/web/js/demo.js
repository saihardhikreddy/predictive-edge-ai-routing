/* Browser stand-in for the Android engine: five made-up phones drifting around, with the same
   state shape and event stream MeshEngine.kt publishes. Used when the page runs outside the app
   (previews, screenshots); on a phone the real Bluetooth engine replaces it. */

const NAMES = [["A1C4E2F0", "Gagan"], ["B7D2C9A1", "Saatvikh"], ["C3E8F1B2", "Library desk"], ["D9A0B4C7", "Hostel B"], ["E5F6A7B8", "Canteen"]];
const ROUTINE = ["Reached the hostel, network is down here.", "Meet me near the main gate in 10 minutes.", "Is the mess open tonight?"];
const SOS = ["Help! Block B collapsed, 3 people trapped.", "SOS fire on the second floor of the hostel."];

export function createDemoEngine(emit) {
  let seq = 0;
  let t0 = Date.now();
  const s = {
    myId: "F0E1D2C3", nick: "Hardhik", running: false, status: "Stopped", mode: "M", sinkhole: false, triageOn: true,
    rangeDbm: -100, battery: 82, neighbors: [], known: [], messages: [],
    stats: { M: { originated: 0, confirmed: 0, rttSum: 0, hopSum: 0, sosOriginated: 0, sosConfirmed: 0 }, F: { originated: 0, confirmed: 0, rttSum: 0, hopSum: 0, sosOriginated: 0, sosConfirmed: 0 } },
    txFrames: 0, txFails: 0, txBytes: 0, stored: 0, queue: 0,
    weights: [0, 7, 0.5, 1, -1.5, 10, -0.3], samples: 0, flRounds: 0, predictability: [],
    expRemaining: 0, expTotal: 0, logTail: [], events: [],
  };
  const phones = NAMES.slice(0, 4).map(([id, nick], i) => ({ id, nick, base: -58 - i * 9, phase: i * 1.7 }));
  let exp = null;

  const ev = (e, extra = {}) => {
    s.events.push({ seq: ++seq, ev: e, ...extra });
    if (s.events.length > 60) s.events.shift();
    const line = `${new Date().toTimeString().slice(0, 8)}  ${e}${extra.msg ? " " + extra.msg : ""}${extra.peer ? " peer=" + extra.peer : ""}${extra.value ? " " + extra.value : ""}`;
    s.logTail.unshift(line);
    if (s.logTail.length > 150) s.logTail.pop();
  };

  function tick() {
    const t = (Date.now() - t0) / 1000;
    if (s.running) {
      s.neighbors = phones.map((p) => {
        const rssi = Math.round(p.base + Math.sin(t * 0.3 + p.phase) * 6);
        const present = rssi >= s.rangeDbm && !(s.blocked || []).includes(p.id);
        const n = s.neighbors.find((x) => x.id === p.id);
        return {
          id: p.id, nick: p.nick, rssi, battery: 60 + ((p.phase * 13) | 0) % 40, present, seenAgoS: 0,
          linkQ: 1 / (1 + Math.exp(-(rssi + 85) / 2.5)),
          reputation: n?.reputation ?? 0.5, anomaly: n?.anomaly ?? 0, quarantined: n?.quarantined ?? false,
          blocked: (s.blocked || []).includes(p.id),
        };
      });
      s.known = NAMES.map(([id, nick]) => [id, nick]);
      s.predictability = s.neighbors.slice(0, 4).map((n, i) => [n.nick, +(0.8 - i * 0.17).toFixed(2)]);
      if (Math.random() < 0.08) { const p = phones[(Math.random() * phones.length) | 0]; ev("TX_OK", { peer: p.id, value: "Hello" }); }
      if (exp && exp.left > 0 && Date.now() >= exp.next) { exp.left--; exp.next = Date.now() + exp.iv; send(NAMES[(Math.random() * NAMES.length) | 0][0], Math.random() < exp.sos ? SOS[0] : ROUTINE[(Math.random() * 3) | 0]); }
      s.expRemaining = exp?.left ?? 0;
      // a demo sinkhole: the third phone starts swallowing after a while
      const bad = s.neighbors[2];
      if (bad && t > 14 && !bad.quarantined) { bad.anomaly = Math.min(1, bad.anomaly + 0.05); bad.reputation = Math.max(0.1, bad.reputation - 0.01); if (bad.anomaly >= 1) { bad.quarantined = true; ev("QUARANTINE", { peer: bad.id }); } }
    }
    emit(JSON.parse(JSON.stringify(s)));
  }

  function send(dst, text) {
    const sos = /help|sos|fire|trapped/i.test(text);
    const id = `F0E1-${(++seq).toString(36)}`;
    const mode = s.mode;
    s.stats[mode].originated++;
    s.messages.push({ id, peer: dst, peerName: NAMES.find((n) => n[0] === dst)?.[1] || dst, text, outgoing: true, intent: sos ? "EMERGENCY_SOS" : "ROUTINE", status: "sent", time: Date.now(), rttMs: 0, hops: 0, mode, note: sos ? "113→30 B" : "" });
    ev("ORIG", { mode, msg: id });
    const near = s.neighbors.filter((n) => n.present && !n.quarantined);
    const relays = mode === "F" ? near : near.slice(0, sos ? 2 : 1);
    relays.forEach((n, i) => setTimeout(() => { s.txFrames++; ev("TX_OK", { mode, msg: id, peer: n.id, value: "Data" }); }, 120 + i * 180));
    const hops = 1 + ((Math.random() * 3) | 0);
    setTimeout(() => {
      const m = s.messages.find((x) => x.id === id);
      if (!m || !relays.length) return;
      m.status = "delivered"; m.rttMs = 900 + hops * 700; m.hops = hops;
      s.stats[mode].confirmed++; s.stats[mode].rttSum += m.rttMs; s.stats[mode].hopSum += hops;
      ev("RX", { mode, msg: id, peer: relays[0].id, value: "Data" });
      ev("DELACK_RX", { mode, msg: id, value: String(m.rttMs) });
    }, 1400 + hops * 600);
    s.samples += 1;
    s.weights = s.weights.map((w) => w + (Math.random() - 0.5) * 0.05);
  }

  setInterval(tick, 500);
  setInterval(() => {
    if (!s.running) return;
    const n = s.neighbors.find((x) => x.present && Math.random() < 0.4);
    if (n) { ev("RX", { mode: "M", msg: "relay", peer: n.id, value: "Data" }); setTimeout(() => ev("TX_OK", { mode: "M", msg: "relay", peer: s.neighbors[(Math.random() * s.neighbors.length) | 0]?.id, value: "Data" }), 900); }
  }, 2600);
  setTimeout(tick, 50);

  return {
    call(name, args = []) {
      switch (name) {
        case "start": s.running = true; s.status = "Running"; t0 = Date.now(); ev("START"); break;
        case "stop": s.running = false; s.status = "Stopped"; s.neighbors = []; break;
        case "setMode": s.mode = args[0]; break;
        case "setSinkhole": s.sinkhole = !!args[0]; break;
        case "setTriage": s.triageOn = !!args[0]; break;
        case "setRange": s.rangeDbm = +args[0]; break;
        case "setNick": s.nick = String(args[0] || "").slice(0, 16) || s.nick; break;
        case "toggleBlock": { s.blocked = s.blocked || []; const i = s.blocked.indexOf(args[0]); if (i >= 0) s.blocked.splice(i, 1); else s.blocked.push(args[0]); break; }
        case "send": send(args[0], args[1]); break;
        case "startExperiment": exp = { left: +args[0], iv: +args[1], sos: +args[2], next: Date.now() }; s.expTotal = +args[0]; break;
        case "stopExperiment": if (exp) exp.left = 0; break;
        case "resetStats": for (const k of ["M", "F"]) s.stats[k] = { originated: 0, confirmed: 0, rttSum: 0, hopSum: 0, sosOriginated: 0, sosConfirmed: 0 }; s.messages = []; break;
        case "clearTrust": s.neighbors.forEach((n) => { n.quarantined = false; n.anomaly = 0; }); t0 = Date.now(); break;
        case "exportLog": return "Demo mode: nothing to save";
        case "shareLog": return "Demo mode: nothing to share";
        default: break;
      }
      tick();
      return "";
    },
  };
}
