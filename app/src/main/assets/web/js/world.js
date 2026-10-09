/* The mesh world: a blacked-out city seen at night. Your phone is the lantern at the centre;
   every phone it can hear stands where its signal strength puts it, and every real frame the
   engine sends or receives flies along the link as light.

   Camera language (after SentinelSpread's world.js): each chapter is a shot with its own endpoint;
   moves between shots travel a quadratic Bezier bent through the destination's control point, the
   camera banks into lateral motion, the lens breathes on fast moves, and once a shot has landed it
   drifts in a slow orbit you can grab and spin with inertia. */

import * as THREE from "three";
import { createPost } from "./post.js";

const COL = {
  lantern: new THREE.Color("#ffb547"),
  route: new THREE.Color("#5ee6c8"),
  storm: new THREE.Color("#7c8cff"),
  hazard: new THREE.Color("#ff5a4e"),
  pale: new THREE.Color("#dfe7f2"),
  dim: new THREE.Color("#4a5468"),
};

/* Shot ledger. cam/tgt: endpoint. ctl: control point the move into this shot bends through.
   drift: idle orbit speed (rad/s). fx: post-process look. */
export const SHOTS = {
  mesh:   { cam: [0, 15, 24],    tgt: [0, 1.0, 0],   ctl: [17, 25, 18],  fov: 46, drift: 0.05,  fx: { bloom: 0.95, exposure: 1.05, warm: 0.45 } },
  send:   { cam: [-8, 4.5, 11],  tgt: [3, 1.5, -2],  ctl: [-19, 12, 4],  fov: 52, drift: 0.02,  fx: { bloom: 1.05, exposure: 1.1, warm: 0.55 } },
  route:  { cam: [15, 6, 11],    tgt: [-4, 1.4, -4], ctl: [24, 9, -8],   fov: 48, drift: 0.025, fx: { bloom: 1.0, exposure: 1.05, warm: 0.3 } },
  defend: { cam: [7, 7.5, 12],   tgt: [0, 1.3, 0],   ctl: [-12, 17, 13], fov: 44, drift: 0.03,  fx: { bloom: 1.1, exposure: 0.95, warm: 0.12 } },
  lab:    { cam: [0.01, 70, 0.6], tgt: [0, 0, 0],     ctl: [-30, 40, 30], fov: 34, drift: 0.015, fx: { bloom: 0.75, exposure: 0.8, warm: 0.3 } },
};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const lerp = (a, b, t) => a + (b - a) * t;
const easeIO = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const smooth = (t) => t * t * (3 - 2 * t);
const damp = (cur, target, lambda, dt) => cur + (target - cur) * (1 - Math.exp(-lambda * dt));
const Y = new THREE.Vector3(0, 1, 0);

function hash01(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 100000) / 100000;
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.25, "rgba(255,255,255,0.55)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function createWorld(canvas, { onSelect, onFirstFrame, reducedMotion = false } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
  } catch { return null; }
  if (!renderer.capabilities.isWebGL2) return null;
  const coarse = matchMedia("(pointer: coarse)").matches;
  renderer.setClearColor(0x070a10, 1);
  renderer.toneMapping = THREE.NoToneMapping;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x070a10, 0.021);
  const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 400);
  const post = createPost(renderer, { lite: coarse });
  post.params.uAberr.value = 0.35;
  post.params.uGrain.value = 0.035;
  post.params.uScan.value = 0;
  post.params.uVignette.value = 0.9;

  const uTime = { value: 0 };
  const glow = glowTexture();

  /* ─── lights: moonlight, a cold sky, and your phone lighting the street around you ─── */
  scene.add(new THREE.HemisphereLight(0x3a4c72, 0x05070a, 0.8));
  const moon = new THREE.DirectionalLight(0x9fb4e0, 0.9);
  moon.position.set(-30, 40, -20);
  scene.add(moon);
  const lamp = new THREE.PointLight(0xffb547, 30, 20, 1.8);
  lamp.position.set(0, 2.2, 0);
  scene.add(lamp);

  /* ─── ground: street grid, intersections, your coverage, the range limit ─── */
  const groundMat = new THREE.ShaderMaterial({
    transparent: false,
    uniforms: {
      uTime, uRange: { value: 0 }, uPulse: { value: 0 }, uPulseA: { value: 0 },
      uSelf: { value: COL.lantern.clone() }, uRoute: { value: COL.route.clone() },
    },
    vertexShader: /* glsl */`
      varying vec3 vW;
      void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: /* glsl */`
      uniform float uTime, uRange, uPulse, uPulseA;
      uniform vec3 uSelf, uRoute;
      varying vec3 vW;
      float line(float x, float w) { float d = abs(fract(x) - 0.5); return smoothstep(w, 0.0, 0.5 - d); }
      void main() {
        vec2 p = vW.xz;
        float r = length(p);
        vec3 col = vec3(0.022, 0.03, 0.045);
        // streets every 4 units, lanes every 1
        float street = max(line(p.x / 4.0 + 0.5, 0.035), line(p.y / 4.0 + 0.5, 0.035));
        float lane = max(line(p.x + 0.5, 0.02), line(p.y + 0.5, 0.02)) * 0.25;
        col += vec3(0.05, 0.07, 0.1) * (street + lane);
        // intersections glint
        vec2 g = abs(fract(p / 4.0 + 0.5) - 0.5);
        col += vec3(0.25, 0.3, 0.4) * smoothstep(0.03, 0.0, length(g)) * 0.6;
        // your phone lights the street
        col += uSelf * 0.22 * exp(-r * 0.42);
        // range limit ring
        if (uRange > 0.0) col += uRoute * 0.9 * smoothstep(0.12, 0.0, abs(r - uRange));
        // beacon pulse
        col += uSelf * uPulseA * smoothstep(0.25, 0.0, abs(r - uPulse)) * 0.55;
        float fogF = 1.0 - exp(-pow(r * 0.026, 1.6));
        col = mix(col, vec3(0.027, 0.039, 0.063), clamp(fogF, 0.0, 1.0));
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(420, 420), groundMat);
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  /* ─── city: dark blocks, low near the plaza so the phones stay visible ─── */
  const blocks = [];
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let gx = -64; gx <= 64; gx += 4) {
    for (let gz = -64; gz <= 64; gz += 4) {
      const r = Math.hypot(gx, gz);
      if (r < 5) continue;
      if (rnd() < 0.18) continue;                       // empty lots and squares
      const near = clamp((r - 5) / 22, 0, 1);
      const h = 0.25 + Math.pow(rnd(), 2.2) * (0.8 + near * 7.5);
      const w = 2.2 + rnd() * 0.9, d = 2.2 + rnd() * 0.9;
      blocks.push({ x: gx + (rnd() - 0.5) * 0.6, z: gz + (rnd() - 0.5) * 0.6, w, d, h });
    }
  }
  const city = new THREE.InstancedMesh(
    new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshStandardMaterial({ color: 0x1b2536, roughness: 0.82, metalness: 0.12 }),
    blocks.length,
  );
  const m4 = new THREE.Matrix4();
  blocks.forEach((b, i) => {
    m4.compose(new THREE.Vector3(b.x, b.h / 2, b.z), new THREE.Quaternion(), new THREE.Vector3(b.w, b.h, b.d));
    city.setMatrixAt(i, m4);
  });
  scene.add(city);

  // lit windows: other people's lamps in the blackout, a few flickering
  const winPos = [], winSeed = [];
  blocks.forEach((b) => {
    if (b.h < 1.2) return;
    const n = Math.floor(rnd() * 3.2);
    for (let k = 0; k < n; k++) {
      const face = Math.floor(rnd() * 4);
      const y = 0.5 + rnd() * (b.h - 0.8);
      const s = (rnd() - 0.5) * 0.8;
      const x = b.x + (face === 0 ? b.w / 2 + 0.02 : face === 1 ? -b.w / 2 - 0.02 : s * b.w);
      const z = b.z + (face === 2 ? b.d / 2 + 0.02 : face === 3 ? -b.d / 2 - 0.02 : s * b.d);
      winPos.push(x, y, z);
      winSeed.push(rnd());
    }
  });
  const winGeo = new THREE.BufferGeometry();
  winGeo.setAttribute("position", new THREE.Float32BufferAttribute(winPos, 3));
  winGeo.setAttribute("aSeed", new THREE.Float32BufferAttribute(winSeed, 1));
  const windows = new THREE.Points(winGeo, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime, uScale: { value: 600 } },
    vertexShader: /* glsl */`
      attribute float aSeed; uniform float uTime, uScale; varying float vA; varying float vWarm;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float flick = aSeed > 0.92 ? 0.55 + 0.45 * step(0.3, fract(sin(floor(uTime * 3.0 + aSeed * 40.0)) * 43758.5)) : 1.0;
        vA = (0.35 + 0.65 * fract(aSeed * 7.13)) * flick;
        vWarm = step(0.35, aSeed);
        gl_PointSize = uScale * 0.09 / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */`
      varying float vA; varying float vWarm;
      void main() {
        vec2 q = abs(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.2, max(q.x, q.y * 0.8));
        vec3 c = mix(vec3(0.55, 0.65, 0.9), vec3(1.0, 0.72, 0.38), vWarm) * 1.6;
        gl_FragColor = vec4(c * a * vA, a * vA);
      }`,
  }));
  scene.add(windows);

  /* ─── beacons ─── */
  const sphereGeo = new THREE.SphereGeometry(1, 24, 16);
  const ringGeo = new THREE.RingGeometry(0.92, 1, 64);
  ringGeo.rotateX(-Math.PI / 2);
  const stalkGeo = new THREE.CylinderGeometry(0.035, 0.035, 1, 8);
  stalkGeo.translate(0, 0.5, 0);
  const cageGeo = new THREE.IcosahedronGeometry(1, 1);

  function makeBeacon(color, size) {
    const g = new THREE.Group();
    const coreMat = new THREE.MeshBasicMaterial({ color: color.clone().multiplyScalar(2.2), fog: false });
    const core = new THREE.Mesh(sphereGeo, coreMat);
    core.scale.setScalar(size);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: color.clone(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0.85 }));
    halo.scale.setScalar(size * 5.5);
    const stalk = new THREE.Mesh(stalkGeo, new THREE.MeshBasicMaterial({ color: color.clone().multiplyScalar(1.2), transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
    const foot = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: color.clone().multiplyScalar(1.4), transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    foot.position.y = 0.02;
    const cage = new THREE.Mesh(cageGeo, new THREE.MeshBasicMaterial({ color: COL.hazard.clone().multiplyScalar(2), wireframe: true, transparent: true, opacity: 0.9 }));
    cage.visible = false;
    g.add(core, halo, stalk, foot, cage);
    scene.add(g);
    return { g, core, halo, stalk, foot, cage, size };
  }

  function paintBeacon(b, color, alpha = 1) {
    b.core.material.color.copy(color).multiplyScalar(2.2 * alpha + 0.15);
    b.halo.material.color.copy(color);
    b.halo.material.opacity = 0.85 * alpha;
    b.stalk.material.color.copy(color).multiplyScalar(1.2);
    b.stalk.material.opacity = 0.55 * alpha;
    b.foot.material.color.copy(color).multiplyScalar(1.4);
    b.foot.material.opacity = 0.7 * alpha;
  }

  const HEIGHT = 1.6;
  const self = makeBeacon(COL.lantern, 0.34);
  self.stalk.scale.y = HEIGHT;
  self.core.position.y = HEIGHT;
  self.halo.position.y = HEIGHT;
  self.cage.position.y = HEIGHT;
  self.foot.scale.setScalar(1.1);
  self.halo.scale.setScalar(0.34 * 4.5);

  /* per-phone state: beacon, link, label */
  const nodes = new Map();   // id → { b, link, pos, target, alpha, data, kind }
  const tmpV = new THREE.Vector3();

  function makeLink() {
    const pts = new Float32Array(25 * 3);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
    const mat = new THREE.LineBasicMaterial({ color: COL.route.clone(), transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false });
    const line = new THREE.Line(geo, mat);
    line.frustumCulled = false;
    scene.add(line);
    return line;
  }

  const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3());
  function linkCurve(a, b) {
    curve.v0.set(a.x, HEIGHT, a.z);
    curve.v2.set(b.x, HEIGHT, b.z);
    const d = Math.hypot(a.x - b.x, a.z - b.z);
    curve.v1.set((a.x + b.x) / 2, HEIGHT + 0.6 + d * 0.22, (a.z + b.z) / 2);
    return curve;
  }

  const mixed = new THREE.Color();
  function nodeColor(n) {
    if (n.data?.quarantined) return COL.hazard;
    if (n.kind === "far") return COL.pale;
    const base = n.mode === "F" ? COL.storm : COL.route;
    const a = clamp(n.data?.anomaly || 0, 0, 1);
    return a > 0.02 ? mixed.copy(base).lerp(COL.hazard, smooth(a)) : base;
  }

  /* ─── state from the engine ─── */
  let state = null;
  let mode = "M";
  let suspect = null;

  function placeTarget(id, rssi, present, kind) {
    const a = hash01(id) * Math.PI * 2;
    let r;
    if (kind === "far") r = 25 + hash01(id + "r") * 6;
    else {
      const q = clamp((-rssi - 45) / 50, 0, 1);       // -45 dBm → close, -95 → far
      r = 4.2 + q * 14 + (present ? 0 : 5);
    }
    return { a, r };
  }

  function setState(s) {
    state = s;
    mode = s.mode || "M";
    const seen = new Set();
    for (const n of s.neighbors || []) {
      seen.add(n.id);
      let node = nodes.get(n.id);
      if (!node) {
        node = { b: makeBeacon(COL.route, 0.24), link: makeLink(), pos: new THREE.Vector3(), angle: 0, radius: 30, alpha: 0, kind: "near" };
        const t = placeTarget(n.id, n.rssi, n.present, "near");
        node.angle = t.a; node.radius = t.r + 6;
        nodes.set(n.id, node);
      }
      node.kind = "near";
      node.data = n;
      node.mode = mode;
      const t = placeTarget(n.id, n.rssi, n.present && !n.blocked, "near");
      node.targetAngle = t.a; node.targetRadius = t.r;
      node.targetAlpha = n.present && !n.blocked ? 1 : 0.28;
    }
    // phones known through the mesh but not heard directly
    for (const [id, name] of s.known || []) {
      if (seen.has(id)) continue;
      seen.add(id);
      let node = nodes.get(id);
      if (!node) {
        node = { b: makeBeacon(COL.pale, 0.16), link: makeLink(), pos: new THREE.Vector3(), angle: hash01(id) * Math.PI * 2, radius: 34, alpha: 0, kind: "far" };
        nodes.set(id, node);
      }
      node.kind = "far";
      node.data = { id, nick: name, present: false };
      const t = placeTarget(id, -100, false, "far");
      node.targetAngle = t.a; node.targetRadius = t.r;
      node.targetAlpha = 0.45;
    }
    for (const [id, node] of nodes) {
      if (!seen.has(id)) node.targetAlpha = 0;
    }
    // who looks most suspicious (for the Defend shot)
    let best = null;
    for (const n of s.neighbors || []) if (!best || (n.quarantined ? 2 : n.anomaly) > (best.quarantined ? 2 : best.anomaly)) best = n;
    suspect = best && (best.quarantined || best.anomaly > 0.05) ? best.id : null;
    // range ring
    groundMat.uniforms.uRange.value = s.rangeDbm > -99 ? 4.2 + clamp((-s.rangeDbm - 45) / 50, 0, 1) * 14 : 0;
    const attacker = !!s.sinkhole;
    paintBeacon(self, attacker ? COL.hazard : COL.lantern, s.running ? 1 : 0.35);
    lamp.color.copy(attacker ? COL.hazard : COL.lantern);
    lamp.intensity = s.running ? 30 : 8;
    groundMat.uniforms.uSelf.value.copy(attacker ? COL.hazard : COL.lantern).multiplyScalar(s.running ? 1 : 0.35);
    running = !!s.running;
  }

  function nodePos(id) {
    if (id === "self" || id === state?.myId) return new THREE.Vector3(0, HEIGHT, 0);
    const n = nodes.get(id);
    return n ? new THREE.Vector3(n.pos.x, HEIGHT, n.pos.z) : null;
  }

  /* ─── packets, rings and bursts driven by real engine events ─── */
  const sprites = [];
  function sprite(color, size) {
    let s = sprites.find((x) => !x.visible);
    if (!s) {
      s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, fog: false }));
      scene.add(s);
      sprites.push(s);
    }
    s.material.color.copy(color).multiplyScalar(2.2);
    s.material.opacity = 1;
    s.scale.setScalar(size);
    s.visible = true;
    return s;
  }

  const flights = [];   // { from, to, t, dur, color, size, fail, head, trail[] }
  function fly(fromId, toId, color, { size = 0.55, dur = 0.95, fail = false } = {}) {
    if (!nodePos(fromId) || !nodePos(toId)) return;
    const head = sprite(color, size);
    const trail = [sprite(color, size * 0.7), sprite(color, size * 0.5), sprite(color, size * 0.35)];
    flights.push({ fromId, toId, t: 0, dur: reducedMotion ? 0.01 : dur, color, size, fail, head, trail });
  }

  const ringPool = [];
  const rings = [];
  function ring(at, color, { to = 6, dur = 1.2, width = 1 } = {}) {
    let m = ringPool.find((x) => !x.visible);
    if (!m) {
      m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, fog: false }));
      scene.add(m);
      ringPool.push(m);
    }
    m.material.color.copy(color).multiplyScalar(2);
    m.position.set(at.x, 0.04, at.z);
    m.visible = true;
    rings.push({ m, t: 0, dur, to, width });
  }

  let lastSeq = -1;
  function handleEvents(events) {
    if (!events?.length) return;
    const msgs = state?.messages || [];
    const isSos = (msg) => msgs.some((m) => m.id === msg && m.intent === "EMERGENCY_SOS");
    for (const e of events) {
      if (e.seq <= lastSeq) continue;
      lastSeq = e.seq;
      const peer = e.peer;
      const dataColor = isSos(e.msg) ? COL.lantern : (e.mode === "F" ? COL.storm : COL.route);
      switch (e.ev) {
        case "TX_OK":
          if (e.value === "Data") fly("self", peer, dataColor, { size: 0.7 });
          else if (e.value === "Hello") fly("self", peer, COL.lantern, { size: 0.35, dur: 1.2 });
          else fly("self", peer, COL.pale, { size: 0.3, dur: 0.7 });
          break;
        case "TX_FAIL": fly("self", peer, COL.dim, { size: 0.45, fail: true }); break;
        case "RX": fly(peer, "self", dataColor, { size: 0.7 }); break;
        case "ORIG": if (e.mode === "F") ring(new THREE.Vector3(), COL.storm, { to: 22, dur: 1.6 }); break;
        case "DELIVER": ring(new THREE.Vector3(), COL.lantern, { to: 3.5, dur: 0.9 }); break;
        case "DELACK_RX": ring(new THREE.Vector3(), COL.lantern, { to: 5, dur: 1.1 }); break;
        case "SINK_DROP": ring(new THREE.Vector3(), COL.hazard, { to: 2.5, dur: 0.7 }); break;
        case "ENCOUNTER": { const p = nodePos(peer); if (p) ring(p, COL.route, { to: 2.2, dur: 1.0 }); break; }
        case "QUARANTINE": { const p = nodePos(peer); if (p) { ring(p, COL.hazard, { to: 4, dur: 1.4 }); ring(p, COL.hazard, { to: 7, dur: 2 }); } break; }
        default: break;
      }
    }
  }

  /* ─── camera rig ─── */
  let chapter = "mesh", focusId = null;
  const cur = { pos: new THREE.Vector3(...SHOTS.mesh.cam), tgt: new THREE.Vector3(...SHOTS.mesh.tgt), fov: SHOTS.mesh.fov };
  const move = { t: 1, dur: 1.7, from: { pos: new THREE.Vector3(), tgt: new THREE.Vector3(), fov: 46 }, ctl: new THREE.Vector3() };
  const fx = { ...SHOTS.mesh.fx };
  const orbit = { yaw: 0, pitch: 0, vYaw: 0, vPitch: 0, zoom: 1, idle: 10, dragging: false };
  let roll = 0, breathe = 0;
  const prevPos = new THREE.Vector3();
  let viewInset = 0, viewInsetS = 0;

  function endpoint() {
    const S = SHOTS[chapter];
    const id = focusId || (chapter === "defend" ? suspect : null);
    const p = id ? nodePos(id) : null;
    if (p) {
      // a shot framed on one phone: from beyond it, looking back across it toward you
      // the phone in the middle of the frame, your lantern glowing behind it
      const out = new THREE.Vector3(p.x, 0, p.z).normalize();
      if (!isFinite(out.x)) out.set(0, 0, 1);
      // look outward from the plaza (low buildings) so nothing tall stands in between
      const side = new THREE.Vector3().crossVectors(Y, out).multiplyScalar(2.8);
      const back = Math.min(8, Math.max(3, p.length() - 2));
      const pos = new THREE.Vector3(p.x, 0, p.z).addScaledVector(out, -back).add(side).setY(7);
      const tgt = new THREE.Vector3(p.x, 1.4, p.z);
      return { pos, tgt, fov: 50 };
    }
    return { pos: new THREE.Vector3(...S.cam), tgt: new THREE.Vector3(...S.tgt), fov: S.fov };
  }

  function setChapter(name, focus = null) {
    if (!SHOTS[name]) return;
    if (name === chapter && focus === focusId) return;
    chapter = name;
    focusId = focus;
    move.from.pos.copy(camera.position);
    move.from.tgt.copy(cur.tgt);
    move.from.fov = cur.fov;
    const end = endpoint();
    if (focus) {
      move.ctl.copy(move.from.pos).add(end.pos).multiplyScalar(0.5).add(new THREE.Vector3(0, 5, 0));
    } else {
      move.ctl.set(...SHOTS[name].ctl);
    }
    move.t = 0;
    move.dur = reducedMotion ? 0.01 : focus ? 1.3 : 1.8;
    orbit.yaw = 0; orbit.pitch = 0; orbit.vYaw = 0; orbit.vPitch = 0; orbit.idle = 0;
  }

  /* ─── touch: drag to orbit with inertia, pinch to zoom, tap a phone to select it ─── */
  const pointers = new Map();
  let pinch0 = 0, zoom0 = 1, downAt = null;
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) { orbit.dragging = true; downAt = { x: e.clientX, y: e.clientY, t: performance.now() }; }
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch0 = Math.hypot(a.x - b.x, a.y - b.y); zoom0 = orbit.zoom;
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    const p = pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch0 > 0) orbit.zoom = clamp(zoom0 * pinch0 / d, 0.45, 2.2);
      return;
    }
    orbit.vYaw = -dx * 0.006;
    orbit.vPitch = dy * 0.004;
    orbit.yaw += orbit.vYaw;
    orbit.pitch = clamp(orbit.pitch + orbit.vPitch, -0.5, 0.6);
    orbit.idle = 0;
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size === 0) {
      orbit.dragging = false;
      if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < 8 && performance.now() - downAt.t < 400) pick(e.clientX, e.clientY);
      downAt = null;
    }
  };
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", (e) => { orbit.zoom = clamp(orbit.zoom * (1 + e.deltaY * 0.001), 0.45, 2.2); }, { passive: true });

  const ray = new THREE.Raycaster();
  function pick(x, y) {
    const ndc = new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
    let best = null, bestD = 42;
    for (const [id, n] of nodes) {
      if (n.alpha < 0.2) continue;
      const s = tmpV.set(n.pos.x, HEIGHT, n.pos.z).project(camera);
      if (s.z > 1) continue;
      const px = (s.x + 1) / 2 * innerWidth, py = (1 - s.y) / 2 * innerHeight;
      const d = Math.hypot(px - x, py - y);
      if (d < bestD) { bestD = d; best = id; }
    }
    void ray; void ndc;
    onSelect?.(best);
  }

  /* ─── labels ─── */
  const tagLayer = document.getElementById("tags");
  const tags = new Map();
  function tagFor(id) {
    let el = tags.get(id);
    if (!el) { el = document.createElement("p"); el.className = "tag"; tagLayer.appendChild(el); tags.set(id, el); }
    return el;
  }
  const selfTag = tagFor("self");
  selfTag.classList.add("self");

  function placeTag(el, world, html, cls, hideBelow) {
    tmpV.copy(world).project(camera);
    const x = (tmpV.x + 1) / 2 * innerWidth, y = (1 - tmpV.y) / 2 * innerHeight;
    const vis = tmpV.z < 1 && x > -40 && x < innerWidth + 40 && y > 92 && y < hideBelow;
    if (el._html !== html || el._cls !== cls) { el.innerHTML = html; el._html = html; el.className = "tag " + cls; el._cls = cls; el._w = 0; }
    el.style.opacity = vis ? "" : "0";
    // keep the pill on screen: a phone near the edge pins its tag to the edge instead of clipping it
    if (!el._w) el._w = el.offsetWidth || 90;
    const half = el._w / 2 + 8;
    const cx = Math.min(Math.max(x, half), innerWidth - half);
    el.style.transform = `translate(${cx.toFixed(1)}px, ${(y - 14).toFixed(1)}px) translate(-50%, -100%)`;
  }

  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* ─── frame loop ─── */
  let running = false, time = 0, lastNow = 0, raf = 0, first = true, pulseT = 0;

  function resize() {
    if (!innerWidth || !innerHeight) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, coarse ? 1.3 : 1.6));
    renderer.setSize(innerWidth, innerHeight, false);
    const v = renderer.getDrawingBufferSize(new THREE.Vector2());
    post.resize(v.x, v.y);
    camera.aspect = innerWidth / innerHeight;
    windows.material.uniforms.uScale.value = v.y;
  }

  function updateNodes(dt) {
    // keep phones apart on their rings
    const arr = [...nodes.values()].filter((n) => n.targetAlpha > 0);
    for (const n of arr) {
      n.angle = damp(n.angle, n.targetAngle + (n.push || 0), 1.6, dt);
      n.radius = damp(n.radius, n.targetRadius, 1.4, dt);
    }
    for (let i = 0; i < arr.length; i++) {
      arr[i].push = 0;
      for (let j = 0; j < arr.length; j++) {
        if (i === j) continue;
        let da = arr[i].angle - arr[j].angle;
        da = Math.atan2(Math.sin(da), Math.cos(da));
        const close = Math.abs(da) < 0.4 && Math.abs(arr[i].radius - arr[j].radius) < 4;
        if (close) arr[i].push += Math.sign(da || 1) * (0.4 - Math.abs(da)) * 0.8;
      }
    }
    for (const [id, n] of nodes) {
      n.alpha = damp(n.alpha, n.targetAlpha ?? 0, 2.2, dt);
      n.pos.set(Math.cos(n.angle) * n.radius, 0, Math.sin(n.angle) * n.radius);
      const b = n.b;
      b.g.position.copy(n.pos);
      b.stalk.scale.y = HEIGHT;
      b.core.position.y = HEIGHT + Math.sin(time * 1.6 + hash01(id) * 6) * 0.06;
      b.halo.position.y = b.core.position.y;
      b.cage.position.y = b.core.position.y;
      const color = nodeColor(n);
      paintBeacon(b, color, n.alpha);
      b.g.visible = n.alpha > 0.02;
      const q = !!n.data?.quarantined;
      b.cage.visible = q;
      if (q) { b.cage.rotation.y += dt * 0.6; b.cage.rotation.x += dt * 0.25; b.cage.scale.setScalar(0.62 + Math.sin(time * 3) * 0.03); }
      // link from you
      const link = n.link;
      const present = n.kind === "near" && n.data?.present && !n.data?.blocked && !q;
      const lq = n.data?.linkQ ?? 0;
      link.visible = n.alpha > 0.05 && (present || n.kind === "far");
      if (link.visible) {
        const c = linkCurve(new THREE.Vector3(0, 0, 0), n.pos);
        const arrP = link.geometry.attributes.position.array;
        for (let k = 0; k <= 24; k++) { c.getPoint(k / 24, tmpV); arrP[k * 3] = tmpV.x; arrP[k * 3 + 1] = tmpV.y; arrP[k * 3 + 2] = tmpV.z; }
        link.geometry.attributes.position.needsUpdate = true;
        link.material.color.copy(n.kind === "far" ? COL.pale : color).multiplyScalar(1.4);
        link.material.opacity = n.kind === "far" ? 0.07 * n.alpha : (0.18 + 0.7 * lq) * n.alpha;
      }
    }
  }

  function updateEffects(dt) {
    for (let i = flights.length - 1; i >= 0; i--) {
      const f = flights[i];
      f.t += dt / f.dur;
      const a = nodePos(f.fromId), b = nodePos(f.toId);
      if (!a || !b || f.t >= (f.fail ? 0.55 : 1)) {
        f.head.visible = false; f.trail.forEach((s) => (s.visible = false));
        if (b && !f.fail && f.toId !== "self") { const n = nodes.get(f.toId); if (n) n.b.halo.scale.setScalar(n.b.size * 10); }
        flights.splice(i, 1);
        continue;
      }
      const c = linkCurve(a, b);
      const e = smooth(clamp(f.t, 0, 1));
      c.getPoint(e, f.head.position);
      f.trail.forEach((s, k) => { c.getPoint(clamp(e - (k + 1) * 0.045, 0, 1), s.position); s.material.opacity = 0.6 - k * 0.17; });
      if (f.fail) f.head.material.opacity = 1 - f.t / 0.55;
    }
    for (let i = rings.length - 1; i >= 0; i--) {
      const r = rings[i];
      r.t += dt / r.dur;
      if (r.t >= 1) { r.m.visible = false; rings.splice(i, 1); continue; }
      const e = 1 - Math.pow(1 - r.t, 3);
      r.m.scale.setScalar(0.3 + e * r.to);
      r.m.material.opacity = (1 - r.t) * 0.9;
    }
    // halos relax after a hit
    for (const n of nodes.values()) { const s = n.b.halo.scale.x; n.b.halo.scale.setScalar(damp(s, n.b.size * 5.5, 4, dt)); }
    // your beacon pulse: one ping per second while the mesh is on
    if (running && !reducedMotion) {
      pulseT += dt;
      const ph = (pulseT % 1.6) / 1.6;
      groundMat.uniforms.uPulse.value = ph * 9;
      groundMat.uniforms.uPulseA.value = (1 - ph) * 0.8;
    } else groundMat.uniforms.uPulseA.value = 0;
    self.core.position.y = HEIGHT + Math.sin(time * 1.3) * 0.05;
    self.halo.position.y = self.core.position.y;
    self.cage.visible = !!state?.sinkhole;
    if (self.cage.visible) { self.cage.rotation.y -= dt * 0.8; self.cage.scale.setScalar(0.85); }
  }

  function updateCamera(dt, realDt) {
    const end = endpoint();
    const S = SHOTS[chapter];
    // idle drift and released spin
    if (!orbit.dragging) {
      orbit.yaw += orbit.vYaw * 16 * dt;
      orbit.pitch = clamp(orbit.pitch + orbit.vPitch * 16 * dt, -0.5, 0.6);
      orbit.vYaw *= Math.exp(-3 * dt); orbit.vPitch *= Math.exp(-3 * dt);
      orbit.idle += dt;
      if (!reducedMotion && orbit.idle > 2.5 && move.t >= 1) orbit.yaw += dt * S.drift * Math.min(1, (orbit.idle - 2.5) / 3);
    }
    // apply orbit + zoom to the endpoint
    const off = end.pos.clone().sub(end.tgt).multiplyScalar(orbit.zoom).applyAxisAngle(Y, orbit.yaw);
    const right = new THREE.Vector3().crossVectors(Y, off).normalize();
    off.applyAxisAngle(right, -orbit.pitch);
    if (off.y < 0.6) off.y = 0.6;
    const endPos = end.tgt.clone().add(off);

    let fovNow;
    if (move.t < 1) {
      move.t = Math.min(1, move.t + realDt / move.dur);   // wall-clock, so slow phones don't drag the move out
      const t = easeIO(move.t);
      const u = 1 - t;
      camera.position.set(
        u * u * move.from.pos.x + 2 * u * t * move.ctl.x + t * t * endPos.x,
        u * u * move.from.pos.y + 2 * u * t * move.ctl.y + t * t * endPos.y,
        u * u * move.from.pos.z + 2 * u * t * move.ctl.z + t * t * endPos.z,
      );
      cur.tgt.lerpVectors(move.from.tgt, end.tgt, smooth(move.t));
      fovNow = lerp(move.from.fov, end.fov, t);
    } else {
      camera.position.x = damp(camera.position.x, endPos.x, 6, dt);
      camera.position.y = damp(camera.position.y, endPos.y, 6, dt);
      camera.position.z = damp(camera.position.z, endPos.z, 6, dt);
      cur.tgt.x = damp(cur.tgt.x, end.tgt.x, 4, dt);
      cur.tgt.y = damp(cur.tgt.y, end.tgt.y, 4, dt);
      cur.tgt.z = damp(cur.tgt.z, end.tgt.z, 4, dt);
      fovNow = end.fov;
    }
    camera.lookAt(cur.tgt);
    // thin the fog as the camera climbs, so the overhead shot still shows the city
    scene.fog.density = lerp(0.021, 0.0075, smooth(clamp((camera.position.y - 12) / 45, 0, 1)));
    // bank into lateral motion, breathe on fast moves
    const rightAxis = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
    const vel = camera.position.clone().sub(prevPos);
    const lateral = dt > 0 ? vel.dot(rightAxis) / dt : 0;
    const speed = dt > 0 ? vel.length() / dt : 0;
    prevPos.copy(camera.position);
    roll = damp(roll, reducedMotion ? 0 : clamp(-lateral * 0.01, -0.14, 0.14), 3, dt);
    camera.rotateZ(roll);
    breathe = damp(breathe, reducedMotion ? 0 : Math.min(speed * 0.35, 8), 2.5, dt);
    cur.fov = fovNow;
    const fov = fovNow + breathe + (innerWidth < innerHeight ? 6 : 0);
    if (Math.abs(camera.fov - fov) > 1e-3) camera.fov = fov;
    // keep the subject centred in the part of the screen the sheet does not cover
    viewInsetS = damp(viewInsetS, viewInset / 2, 5, dt);
    camera.setViewOffset(innerWidth, innerHeight, 0, viewInsetS, innerWidth, innerHeight);
    camera.updateProjectionMatrix();
    // look
    for (const k of Object.keys(fx)) fx[k] = damp(fx[k], S.fx[k], 2.2, dt);
  }

  function updateTags() {
    const hideBelow = innerHeight - viewInset - 10;
    const name = state?.nick || "You";
    placeTag(selfTag, new THREE.Vector3(0, HEIGHT + 0.55, 0), `<b>${esc(name)}</b><small>you</small>`, state?.sinkhole ? "self bad" : "self", hideBelow);
    for (const [id, n] of nodes) {
      const el = tagFor(id);
      if (n.alpha < 0.08) { el.style.opacity = "0"; continue; }
      const d = n.data || {};
      const sub = n.kind === "far" ? "via mesh" : d.quarantined ? "cut off" : d.present && !d.blocked ? `${d.rssi} dBm` : d.blocked ? "blocked" : "out of range";
      const cls = d.quarantined ? "bad" : n.kind === "far" || !d.present || d.blocked ? "away" : "";
      tmpV.set(n.pos.x, HEIGHT + 0.5, n.pos.z);
      placeTag(el, tmpV.clone(), `<b>${esc(d.nick || id)}</b><small>${esc(sub)}</small>`, cls, hideBelow);
    }
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const realDt = lastNow ? Math.min((now - lastNow) / 1000, 0.25) : 1 / 60;
    const dt = Math.min(realDt, 1 / 20);
    lastNow = now;
    if (!reducedMotion) time += dt;
    uTime.value = time;
    updateNodes(dt);
    updateEffects(dt);
    updateCamera(dt, realDt);
    const P = post.params;
    P.uTime.value = time;
    P.uBloom.value = fx.bloom;
    P.uExposure.value = fx.exposure;
    P.uWarm.value = fx.warm;
    post.render(scene, camera);
    updateTags();
    if (first) { first = false; onFirstFrame?.(); }
  }

  resize();
  addEventListener("resize", resize, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; lastNow = 0; }
    else if (!raf) raf = requestAnimationFrame(frame);
  });
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); cancelAnimationFrame(raf); raf = 0; document.body.classList.add("no-webgl"); });
  camera.position.set(0, 60, 70);         // the opening move flies in from high above the city
  prevPos.copy(camera.position);
  cur.tgt.set(0, 0, 0);
  setTimeout(() => { chapter = ""; setChapter("mesh"); }, 0);
  renderer.compileAsync ? renderer.compileAsync(scene, camera).then(() => { raf = requestAnimationFrame(frame); }) : (raf = requestAnimationFrame(frame));

  return {
    setState,
    handleEvents,
    setChapter,
    setViewInset(px) { viewInset = px; },
    get chapter() { return chapter; },
    debug: { camera, cur, move, orbit, endpoint: () => endpoint(), nodes, get suspect() { return suspect; } },
  };
}
