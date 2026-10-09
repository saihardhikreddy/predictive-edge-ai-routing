/* Cinematic finish: HDR scene → bright pass → 4-level mip bloom → composite
   (chromatic aberration, bloom, lightning flash, exposure, split-tone grade,
   ACES, vignette, animated grain, scanlines, sRGB). No addons required. */

import * as THREE from "three";

const quadVert = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const brightFrag = /* glsl */ `
  uniform sampler2D tMap;
  uniform float uThreshold;
  varying vec2 vUv;
  void main() {
    vec3 c = texture2D(tMap, vUv).rgb;
    float l = max(c.r, max(c.g, c.b));
    gl_FragColor = vec4(c * smoothstep(uThreshold, uThreshold + 0.7, l), 1.0);
  }
`;

const blurFrag = /* glsl */ `
  uniform sampler2D tMap;
  uniform vec2 uDir;
  varying vec2 vUv;
  void main() {
    vec3 s = texture2D(tMap, vUv).rgb * 0.2270270270;
    s += texture2D(tMap, vUv + uDir * 1.3846153846).rgb * 0.3162162162;
    s += texture2D(tMap, vUv - uDir * 1.3846153846).rgb * 0.3162162162;
    s += texture2D(tMap, vUv + uDir * 3.2307692308).rgb * 0.0702702703;
    s += texture2D(tMap, vUv - uDir * 3.2307692308).rgb * 0.0702702703;
    gl_FragColor = vec4(s, 1.0);
  }
`;

const copyFrag = /* glsl */ `
  uniform sampler2D tMap;
  varying vec2 vUv;
  void main() { gl_FragColor = texture2D(tMap, vUv); }
`;

const compositeFrag = /* glsl */ `
  uniform sampler2D tScene, tB0, tB1, tB2, tB3;
  uniform float uBloom, uAberr, uGrain, uTime, uVignette, uExposure, uFlash, uWarm, uScan;
  uniform vec2 uRes;
  varying vec2 vUv;

  vec3 aces(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
  }
  float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

  void main() {
    vec2 uv = vUv;
    vec2 d = uv - 0.5;
    float r2 = dot(d, d);

    // Radial chromatic aberration, stronger toward the frame edge.
    vec2 off = d * uAberr * (0.004 + r2 * 0.05);
    vec3 col;
    col.r = texture2D(tScene, uv + off).r;
    col.g = texture2D(tScene, uv).g;
    col.b = texture2D(tScene, uv - off).b;

    vec3 bloom = texture2D(tB0, uv).rgb * 0.5
               + texture2D(tB1, uv).rgb * 0.65
               + texture2D(tB2, uv).rgb * 0.85
               + texture2D(tB3, uv).rgb * 1.1;
    col += bloom * uBloom;
    col += vec3(0.42, 0.5, 0.8) * uFlash * (0.25 + 0.5 * (1.0 - uv.y));

    col *= uExposure;
    col *= mix(vec3(0.88, 0.98, 1.12), vec3(1.1, 0.97, 0.84), uWarm);
    col = aces(col);

    float vig = smoothstep(0.98, 0.18, sqrt(r2) * 1.3);
    col *= mix(1.0, vig, uVignette);
    col *= 1.0 - uScan * 0.07 * (0.5 + 0.5 * sin(uv.y * uRes.y * 1.4 + uTime * 6.0));
    col += (hash(uv * uRes + fract(uTime * 7.3) * 113.0) - 0.5) * uGrain;

    gl_FragColor = vec4(pow(max(col, 0.0), vec3(1.0 / 2.2)), 1.0);
  }
`;

export function createPost(renderer, { lite = false } = {}) {
  const O = { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, type: THREE.HalfFloatType, depthBuffer: false, stencilBuffer: false };
  const sceneRT = new THREE.WebGLRenderTarget(2, 2, { ...O, depthBuffer: true, samples: lite ? 0 : 4 });
  const levels = [];
  for (let i = 0; i < 4; i++) levels.push({ a: new THREE.WebGLRenderTarget(2, 2, O), b: new THREE.WebGLRenderTarget(2, 2, O) });

  const mk = (fragmentShader, uniforms) => new THREE.ShaderMaterial({ vertexShader: quadVert, fragmentShader, uniforms, depthTest: false, depthWrite: false });
  const bright = mk(brightFrag, { tMap: { value: null }, uThreshold: { value: 0.95 } });
  const blur = mk(blurFrag, { tMap: { value: null }, uDir: { value: new THREE.Vector2() } });
  const copy = mk(copyFrag, { tMap: { value: null } });
  const composite = mk(compositeFrag, {
    tScene: { value: sceneRT.texture },
    tB0: { value: levels[0].a.texture }, tB1: { value: levels[1].a.texture },
    tB2: { value: levels[2].a.texture }, tB3: { value: levels[3].a.texture },
    uBloom: { value: 1 }, uAberr: { value: 0.6 }, uGrain: { value: 0.028 }, uTime: { value: 0 },
    uVignette: { value: 0.85 }, uExposure: { value: 1.1 }, uFlash: { value: 0 }, uWarm: { value: 0.6 }, uScan: { value: 0 },
    uRes: { value: new THREE.Vector2(1, 1) },
  });

  const quadScene = new THREE.Scene();
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), composite);
  quad.frustumCulled = false;
  quadScene.add(quad);
  const quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  function pass(material, target) {
    quad.material = material;
    renderer.setRenderTarget(target);
    renderer.render(quadScene, quadCam);
  }

  return {
    params: composite.uniforms,
    resize(w, h) {
      sceneRT.setSize(w, h);
      let lw = Math.max(2, w >> 1), lh = Math.max(2, h >> 1);
      for (const L of levels) {
        L.a.setSize(lw, lh); L.b.setSize(lw, lh); L.w = lw; L.h = lh;
        lw = Math.max(2, lw >> 1); lh = Math.max(2, lh >> 1);
      }
      composite.uniforms.uRes.value.set(w, h);
    },
    render(scene, camera) {
      renderer.setRenderTarget(sceneRT);
      renderer.render(scene, camera);

      bright.uniforms.tMap.value = sceneRT.texture;
      pass(bright, levels[0].a);
      levels.forEach((L, i) => {
        if (i > 0) { copy.uniforms.tMap.value = levels[i - 1].a.texture; pass(copy, L.a); }
        blur.uniforms.tMap.value = L.a.texture; blur.uniforms.uDir.value.set(1 / L.w, 0); pass(blur, L.b);
        blur.uniforms.tMap.value = L.b.texture; blur.uniforms.uDir.value.set(0, 1 / L.h); pass(blur, L.a);
      });
      pass(composite, null);
    },
  };
}
