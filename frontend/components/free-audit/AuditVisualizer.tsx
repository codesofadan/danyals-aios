"use client";

// ============================================================
// AIOS · Free Audit — real-time 3D audit visualizer (WebGL / three.js)
// A single persistent canvas that cross-fades between three cinematic
// phases in one shared 3D space, driven by the parent's `genStep`:
//   phase 0 — NEURAL: nodes + pathways construct themselves (the crawl)
//   phase 1 — BOTS:   two minimalist AI heads exchange data packets
//                     over a glowing waveform (signal analysis)
//   phase 2 — GLOBE:  scattered particles condense into a procedural
//                     wireframe globe (data synthesis)
//   phase 3 — hands off to the DOM report (parallax assembly, in CSS)
//
// three.js is a project dependency but was previously unused; this is
// the first WebGL surface. Everything is additive-blended neon over a
// dark stage (see .fa-viz in freeaudit.css) so the neon reads clearly.
// Colors are pulled from the live CSS design tokens at mount, so the
// scene picks up the Avant-Garde theme accents. Reduced motion
// freezes oscillation/rotation but keeps the (vestibular-safe) fades.
// ============================================================

import { useEffect, useRef } from "react";
import * as THREE from "three";

type Props = { phase: number };

// Read a CSS custom property into a THREE.Color (falls back if unset).
function readColor(cs: CSSStyleDeclaration, name: string, fallback: string) {
  const raw = cs.getPropertyValue(name).trim();
  try {
    return new THREE.Color(raw || fallback);
  } catch {
    return new THREE.Color(fallback);
  }
}

// Soft radial disc used by every glow-points system — no textures needed.
const POINT_FRAG = /* glsl */ `
  precision mediump float;
  varying vec3 vColor;
  varying float vA;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float core = smoothstep(0.5, 0.06, d);
    float glow = smoothstep(0.5, 0.0, d);
    float a = core * 0.9 + glow * glow * 0.6;
    if (a <= 0.002) discard;
    gl_FragColor = vec4(vColor, a * vA);
  }
`;

export default function AuditVisualizer({ phase }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  // Live phase read inside the RAF loop without rebuilding the scene.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const MOTION = reduced ? 0 : 1;

    // ---- renderer (guarded: some environments have no WebGL) -------------
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "high-performance" });
    } catch {
      return; // canvas host stays empty; the HUD still narrates the run
    }
    renderer.setClearColor(0x000000, 0); // dark stage comes from CSS behind
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block;";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    camera.position.set(0, 0, 6);

    // Theme palette snapshot.
    const cs = getComputedStyle(document.documentElement);
    const cAccent = readColor(cs, "--violet-2", "#D6FF6B");
    const cSoft = readColor(cs, "--lilac", "#E6FF9E");
    const cBlue = readColor(cs, "--c4", "#4CC9F0");
    const cTeal = readColor(cs, "--c2", "#22E0C0");
    const cOk = readColor(cs, "--ok", "#3DE68A");

    // Track resources for disposal.
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const track = <T extends THREE.BufferGeometry | THREE.Material>(x: T): T => {
      if (x instanceof THREE.BufferGeometry) geometries.push(x);
      else materials.push(x);
      return x;
    };

    // =====================================================================
    // PHASE 0 · NEURAL — nodes pop in, pathways draw + pulse energy along
    // =====================================================================
    const neural = new THREE.Group();
    scene.add(neural);

    const NODE_COUNT = 48;
    const nodePos: THREE.Vector3[] = [];
    const nodeDelay: number[] = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      // A flattened, softly clustered network cloud.
      const r = 1.1 + Math.pow(Math.random(), 0.7) * 1.7;
      const theta = Math.random() * Math.PI * 2;
      const y = (Math.random() - 0.5) * 2.4;
      const v = new THREE.Vector3(Math.cos(theta) * r, y, Math.sin(theta) * r * 0.7);
      nodePos.push(v);
      nodeDelay.push(0.15 + (r / 2.8) * 1.0 + Math.random() * 0.25); // outward reveal
    }

    const nodeGeo = track(new THREE.BufferGeometry());
    {
      const p = new Float32Array(NODE_COUNT * 3);
      const col = new Float32Array(NODE_COUNT * 3);
      const scl = new Float32Array(NODE_COUNT);
      const dly = new Float32Array(NODE_COUNT);
      const palette = [cAccent, cSoft, cBlue, cTeal];
      for (let i = 0; i < NODE_COUNT; i++) {
        p.set([nodePos[i].x, nodePos[i].y, nodePos[i].z], i * 3);
        const c = palette[i % palette.length];
        col.set([c.r, c.g, c.b], i * 3);
        scl[i] = 0.7 + Math.random() * 1.0;
        dly[i] = nodeDelay[i];
      }
      nodeGeo.setAttribute("position", new THREE.BufferAttribute(p, 3));
      nodeGeo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
      nodeGeo.setAttribute("aScale", new THREE.BufferAttribute(scl, 1));
      nodeGeo.setAttribute("aDelay", new THREE.BufferAttribute(dly, 1));
    }
    const neuralU = {
      uTime: { value: 0 },
      uWeight: { value: 0 },
      uSize: { value: 125 },
      uMotion: { value: MOTION },
    };
    const nodeMat = track(
      new THREE.ShaderMaterial({
        uniforms: neuralU,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          attribute vec3 aColor; attribute float aScale; attribute float aDelay;
          uniform float uTime, uWeight, uSize, uMotion;
          varying vec3 vColor; varying float vA;
          void main() {
            vColor = aColor;
            float reveal = smoothstep(aDelay, aDelay + 0.6, uTime);
            float pulse = 1.0 + 0.35 * sin(uTime * 2.0 + aDelay * 6.2831) * uMotion;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            gl_Position = projectionMatrix * mv;
            gl_PointSize = uSize * aScale * reveal * pulse * uWeight / -mv.z;
            vA = reveal * uWeight;
          }
        `,
        fragmentShader: POINT_FRAG,
      })
    );
    neural.add(new THREE.Points(nodeGeo, nodeMat));

    // Pathways: connect each node to its 2 nearest neighbours (deduped).
    const edges: [number, number][] = [];
    const seen = new Set<string>();
    for (let i = 0; i < NODE_COUNT; i++) {
      const dists = nodePos
        .map((p, j) => ({ j, d: p.distanceTo(nodePos[i]) }))
        .filter((o) => o.j !== i)
        .sort((a, b) => a.d - b.d);
      for (let k = 0; k < 2; k++) {
        const j = dists[k].j;
        const key = i < j ? `${i}-${j}` : `${j}-${i}`;
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push([i, j]);
      }
    }
    const edgeGeo = track(new THREE.BufferGeometry());
    {
      const p = new Float32Array(edges.length * 2 * 3);
      const col = new Float32Array(edges.length * 2 * 3);
      const t = new Float32Array(edges.length * 2);
      const dly = new Float32Array(edges.length * 2);
      const phase = new Float32Array(edges.length * 2);
      edges.forEach(([a, b], e) => {
        const d = Math.max(nodeDelay[a], nodeDelay[b]) + 0.18;
        const ph = Math.random();
        for (const [slot, idx] of [[0, a], [1, b]] as const) {
          const o = (e * 2 + slot) * 3;
          p.set([nodePos[idx].x, nodePos[idx].y, nodePos[idx].z], o);
          col.set([cAccent.r, cAccent.g, cAccent.b], o);
          t[e * 2 + slot] = slot; // 0 at start, 1 at end → param along edge
          dly[e * 2 + slot] = d;
          phase[e * 2 + slot] = ph;
        }
      });
      edgeGeo.setAttribute("position", new THREE.BufferAttribute(p, 3));
      edgeGeo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
      edgeGeo.setAttribute("aT", new THREE.BufferAttribute(t, 1));
      edgeGeo.setAttribute("aDelay", new THREE.BufferAttribute(dly, 1));
      edgeGeo.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
    }
    const edgeMat = track(
      new THREE.ShaderMaterial({
        uniforms: neuralU,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          attribute vec3 aColor; attribute float aT; attribute float aDelay; attribute float aPhase;
          uniform float uTime;
          varying vec3 vColor; varying float vT; varying float vReveal; varying float vPhase;
          void main() {
            vColor = aColor; vT = aT; vPhase = aPhase;
            vReveal = smoothstep(aDelay, aDelay + 0.5, uTime);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: /* glsl */ `
          precision mediump float;
          uniform float uTime, uWeight, uMotion;
          varying vec3 vColor; varying float vT; varying float vReveal; varying float vPhase;
          void main() {
            float base = 0.16 * vReveal;
            float p = fract(uTime * 0.5 + vPhase);
            float pulse = smoothstep(0.10, 0.0, abs(vT - p)) * uMotion * vReveal;
            gl_FragColor = vec4(vColor, (base + pulse * 0.9) * uWeight);
          }
        `,
      })
    );
    neural.add(new THREE.LineSegments(edgeGeo, edgeMat));

    // =====================================================================
    // PHASE 1 · BOTS — two heads facing each other, packets + waveform
    // =====================================================================
    const bots = new THREE.Group();
    scene.add(bots);
    const BOT_X = 1.6; // heads a touch closer so the exchange reads as a conversation
    const HEAD = BOT_X - 0.5; // packets/waveform emit + arrive at each head's surface

    // Reusable radial-glow plane (billboarded) for halos + eyes.
    const billboards: THREE.Mesh[] = [];
    const makeGlow = (color: THREE.Color, size: number, opacity: number) => {
      const geo = track(new THREE.PlaneGeometry(size, size));
      const mat = track(
        new THREE.ShaderMaterial({
          uniforms: { uColor: { value: color.clone() }, uOpacity: { value: opacity }, uW: { value: 0 } },
          transparent: true,
          depthWrite: false,
          depthTest: false,
          blending: THREE.AdditiveBlending,
          vertexShader: /* glsl */ `
            varying vec2 vUv;
            void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
          `,
          fragmentShader: /* glsl */ `
            precision mediump float;
            varying vec2 vUv; uniform vec3 uColor; uniform float uOpacity; uniform float uW;
            void main() {
              float d = distance(vUv, vec2(0.5));
              float a = smoothstep(0.5, 0.0, d); a *= a;
              gl_FragColor = vec4(uColor, a * uOpacity * uW);
            }
          `,
        })
      );
      const mesh = new THREE.Mesh(geo, mat);
      billboards.push(mesh);
      return mesh;
    };

    const botHalo: THREE.ShaderMaterial[] = [];
    const botCores: THREE.Group[] = [];
    for (const dir of [-1, 1]) {
      const g = new THREE.Group();
      g.position.set(BOT_X * dir, 0, 0);
      bots.add(g);
      botCores.push(g);

      const halo = makeGlow(cAccent, 2.6, 0.8);
      g.add(halo);
      botHalo.push(halo.material as THREE.ShaderMaterial);

      // Wireframe "head" + faint solid inner shell.
      const wireGeo = track(new THREE.IcosahedronGeometry(0.52, 1));
      const wireMat = track(new THREE.MeshBasicMaterial({ color: cAccent, wireframe: true, transparent: true, opacity: 0, depthWrite: false }));
      g.add(new THREE.Mesh(wireGeo, wireMat));
      const shellGeo = track(new THREE.IcosahedronGeometry(0.34, 0));
      const shellMat = track(new THREE.MeshBasicMaterial({ color: cSoft, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
      g.add(new THREE.Mesh(shellGeo, shellMat));

      // Eye: a bright glow toward the other bot (facing center).
      const eye = makeGlow(new THREE.Color("#ffffff").lerp(cSoft, 0.4), 0.5, 1.0);
      eye.position.set(-0.34 * dir, 0.04, 0.34);
      g.add(eye);
    }

    // Data packets streaming both ways between the bots.
    const PACKETS = 22;
    const pktGeo = track(new THREE.BufferGeometry());
    const pktPos = new Float32Array(PACKETS * 3);
    {
      const col = new Float32Array(PACKETS * 3);
      const scl = new Float32Array(PACKETS);
      for (let i = 0; i < PACKETS; i++) {
        const c = i % 3 === 0 ? cOk : i % 3 === 1 ? cBlue : cTeal;
        col.set([c.r, c.g, c.b], i * 3);
        scl[i] = 0.7 + Math.random() * 0.7;
      }
      pktGeo.setAttribute("position", new THREE.BufferAttribute(pktPos, 3).setUsage(THREE.DynamicDrawUsage));
      pktGeo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
      pktGeo.setAttribute("aScale", new THREE.BufferAttribute(scl, 1));
      pktGeo.setAttribute("aDelay", new THREE.BufferAttribute(new Float32Array(PACKETS), 1)); // 0 → always revealed
    }
    const pktU = { uTime: { value: 0 }, uWeight: { value: 0 }, uSize: { value: 95 }, uMotion: { value: MOTION } };
    const pktMat = track(
      new THREE.ShaderMaterial({
        uniforms: pktU,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          attribute vec3 aColor; attribute float aScale;
          uniform float uWeight, uSize;
          varying vec3 vColor; varying float vA;
          void main() {
            vColor = aColor;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            gl_Position = projectionMatrix * mv;
            gl_PointSize = uSize * aScale * uWeight / -mv.z;
            vA = uWeight;
          }
        `,
        fragmentShader: POINT_FRAG,
      })
    );
    bots.add(new THREE.Points(pktGeo, pktMat));

    // Communication waveform between the two heads.
    const WAVE_N = 120;
    const waveGeo = track(new THREE.BufferGeometry());
    const wavePos = new Float32Array(WAVE_N * 3);
    for (let i = 0; i < WAVE_N; i++) wavePos[i * 3] = THREE.MathUtils.lerp(-HEAD, HEAD, i / (WAVE_N - 1));
    waveGeo.setAttribute("position", new THREE.BufferAttribute(wavePos, 3).setUsage(THREE.DynamicDrawUsage));
    const waveMat = track(new THREE.LineBasicMaterial({ color: cSoft, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    const waveLine = new THREE.Line(waveGeo, waveMat);
    bots.add(waveLine);

    // =====================================================================
    // PHASE 2 · GLOBE — particles condense onto a procedural wireframe globe
    // =====================================================================
    const globe = new THREE.Group();
    globe.rotation.z = 0.32; // gentle axial tilt
    scene.add(globe);
    const R = 1.65;

    const GLOBE_N = 2600;
    const globeGeo = track(new THREE.BufferGeometry());
    {
      const target = new Float32Array(GLOBE_N * 3);
      const start = new Float32Array(GLOBE_N * 3);
      const col = new Float32Array(GLOBE_N * 3);
      const scl = new Float32Array(GLOBE_N);
      const GA = Math.PI * (3 - Math.sqrt(5)); // golden angle
      for (let i = 0; i < GLOBE_N; i++) {
        const y = 1 - (i / (GLOBE_N - 1)) * 2;
        const rad = Math.sqrt(Math.max(0, 1 - y * y));
        const th = i * GA;
        const tx = Math.cos(th) * rad * R;
        const tz = Math.sin(th) * rad * R;
        const ty = y * R;
        target.set([tx, ty, tz], i * 3);
        // Scattered origin cloud.
        const sr = 2.8 + Math.random() * 2.2;
        const su = Math.random() * Math.PI * 2;
        const sv = Math.acos(2 * Math.random() - 1);
        start.set([Math.sin(sv) * Math.cos(su) * sr, Math.cos(sv) * sr, Math.sin(sv) * Math.sin(su) * sr], i * 3);
        const c = cAccent.clone().lerp(cBlue, (y + 1) / 2).lerp(cTeal, Math.random() * 0.25);
        col.set([c.r, c.g, c.b], i * 3);
        scl[i] = 0.5 + Math.random() * 0.7;
      }
      globeGeo.setAttribute("position", new THREE.BufferAttribute(target, 3));
      globeGeo.setAttribute("aStart", new THREE.BufferAttribute(start, 3));
      globeGeo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
      globeGeo.setAttribute("aScale", new THREE.BufferAttribute(scl, 1));
    }
    const globeU = {
      uTime: { value: 0 },
      uWeight: { value: 0 },
      uProgress: { value: 0 },
      uSize: { value: 72 },
      uMotion: { value: MOTION },
    };
    const globeMat = track(
      new THREE.ShaderMaterial({
        uniforms: globeU,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          attribute vec3 aStart; attribute vec3 aColor; attribute float aScale;
          uniform float uTime, uWeight, uProgress, uSize, uMotion;
          varying vec3 vColor; varying float vA;
          mat3 rotY(float a){ float s = sin(a), c = cos(a); return mat3(c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c); }
          void main() {
            vColor = aColor;
            float e = uProgress * uProgress * (3.0 - 2.0 * uProgress);
            vec3 target = rotY((1.0 - e) * 3.0 * uMotion) * position; // swirl in
            vec3 p = mix(aStart, target, e);
            p *= 1.0 + 0.02 * sin(uTime * 1.5) * uMotion * e;
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            gl_Position = projectionMatrix * mv;
            gl_PointSize = uSize * aScale * (0.4 + 0.6 * e) * uWeight / -mv.z;
            vA = uWeight * (0.3 + 0.7 * e);
          }
        `,
        fragmentShader: POINT_FRAG,
      })
    );
    globe.add(new THREE.Points(globeGeo, globeMat));

    // Procedural wireframe shell that builds up around the particles.
    const wireGlobeGeo = track(new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(R, 2)));
    const wireGlobeMat = track(new THREE.LineBasicMaterial({ color: cAccent, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    const wireGlobe = new THREE.LineSegments(wireGlobeGeo, wireGlobeMat);
    globe.add(wireGlobe);

    // A few great-circle rings — the "constructed geometry" latticing in.
    const ringMats: THREE.LineBasicMaterial[] = [];
    for (let r = 0; r < 3; r++) {
      const pts: THREE.Vector3[] = [];
      const SEG = 96;
      for (let i = 0; i <= SEG; i++) {
        const a = (i / SEG) * Math.PI * 2;
        pts.push(new THREE.Vector3(Math.cos(a) * R * 1.01, Math.sin(a) * R * 1.01, 0));
      }
      const rg = track(new THREE.BufferGeometry().setFromPoints(pts));
      const rm = track(new THREE.LineBasicMaterial({ color: cSoft, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
      ringMats.push(rm);
      const ring = new THREE.Line(rg, rm);
      ring.rotation.set((r * Math.PI) / 3, r * 0.9, r * 0.5);
      globe.add(ring);
    }

    // =====================================================================
    // Interaction · pointer parallax (disabled under reduced motion)
    // =====================================================================
    let pointerX = 0;
    let pointerY = 0;
    const onPointer = (e: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      pointerX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
      pointerY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    };
    if (!reduced) host.addEventListener("pointermove", onPointer);

    // ---- resize ----------------------------------------------------------
    const resize = () => {
      const w = host.clientWidth || 1;
      const h = host.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    // =====================================================================
    // Animation loop
    // =====================================================================
    const clock = new THREE.Clock();
    let neuralW = 0;
    let botsW = 0;
    let globeW = 0;
    let globeProg = 0;
    let camX = 0;
    let camY = 0;
    let camZ = 6;
    let running = true;
    const V = new THREE.Vector3();

    const damp = (cur: number, to: number, dt: number, rate: number) => cur + (to - cur) * Math.min(1, dt * rate);

    const frame = () => {
      if (!running) return;
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;
      const ph = phaseRef.current;

      neuralW = damp(neuralW, ph === 0 ? 1 : 0, dt, 3.0);
      botsW = damp(botsW, ph === 1 ? 1 : 0, dt, 3.0);
      globeW = damp(globeW, ph >= 2 ? 1 : 0, dt, 2.6);
      globeProg = damp(globeProg, ph >= 2 ? 1 : 0, dt, 1.5);

      // --- neural uniforms ---
      neuralU.uTime.value = t;
      neuralU.uWeight.value = neuralW;
      neural.rotation.y = t * 0.12 * MOTION;
      neural.visible = neuralW > 0.002;

      // --- bots ---
      pktU.uTime.value = t;
      pktU.uWeight.value = botsW;
      bots.visible = botsW > 0.002;
      bots.position.y = Math.sin(t * 0.9) * 0.05 * MOTION;
      botHalo.forEach((m) => {
        m.uniforms.uW.value = botsW * (0.75 + 0.25 * Math.sin(t * 2.2) * MOTION);
      });
      billboards.forEach((b) => b.quaternion.copy(camera.quaternion)); // face camera
      botCores.forEach((g, i) => {
        g.rotation.y += dt * 0.5 * MOTION * (i === 0 ? 1 : -1);
        g.rotation.x = Math.sin(t * 0.6 + i) * 0.15 * MOTION;
        g.children.forEach((ch) => {
          const m = (ch as THREE.Mesh).material as THREE.MeshBasicMaterial | undefined;
          if (m && "wireframe" in m) m.opacity = (m.wireframe ? 0.85 : 0.16) * botsW;
        });
      });
      // Packet stream: two tidy lanes head-to-head — outbound messages arc
      // up, replies arc down — so the exchange reads as a clean back-and-forth
      // and stays in one camera-facing plane (no scattered z noise).
      for (let i = 0; i < PACKETS; i++) {
        const forward = i % 2 === 0;
        const lane = forward ? 1 : -1;
        const speed = 0.42 * (0.7 + (i % 4) * 0.14);
        const s = ((i / PACKETS) + t * speed * MOTION) % 1;
        const u = forward ? s : 1 - s; // travel from one head's surface to the other
        const x = THREE.MathUtils.lerp(-HEAD, HEAD, u);
        const y = Math.sin(u * Math.PI) * 0.5 * lane; // 0 at both heads → connected
        pktPos.set([x, y, 0], i * 3);
      }
      pktGeo.attributes.position.needsUpdate = true;
      // Communication waveform: the channel line down the middle, fading into
      // each head so it never floats past them.
      for (let i = 0; i < WAVE_N; i++) {
        const fx = i / (WAVE_N - 1);
        const env = Math.sin(fx * Math.PI); // fade at the two heads (x stays fixed)
        wavePos[i * 3 + 1] = Math.sin(fx * 20 - t * 6 * MOTION) * 0.2 * env * (0.4 + 0.6 * MOTION);
        wavePos[i * 3 + 2] = 0;
      }
      waveGeo.attributes.position.needsUpdate = true;
      waveMat.opacity = botsW * 0.9;

      // --- globe ---
      globeU.uTime.value = t;
      globeU.uWeight.value = globeW;
      globeU.uProgress.value = globeProg;
      globe.visible = globeW > 0.002;
      globe.rotation.y = t * 0.22 * MOTION + (1 - globeProg) * 1.5;
      const shell = globeProg * globeW;
      wireGlobeMat.opacity = shell * 0.35;
      wireGlobe.scale.setScalar(THREE.MathUtils.lerp(0.82, 1, globeProg));
      ringMats.forEach((m, i) => (m.opacity = shell * 0.4 * (0.6 + 0.4 * Math.sin(t * 1.5 + i) * MOTION)));

      // --- camera: per-phase framing + pointer parallax ---
      const targetZ = ph >= 2 ? 6.9 : ph === 1 ? 6.1 : 6.0;
      const offX = (ph === 0 ? -0.15 : 0) + pointerX * 0.5 * MOTION;
      const offY = pointerY * -0.35 * MOTION;
      camX = damp(camX, offX, dt, 2.4);
      camY = damp(camY, offY, dt, 2.4);
      camZ = damp(camZ, targetZ, dt, 1.6);
      camera.position.set(camX, camY + Math.sin(t * 0.4) * 0.08 * MOTION, camZ);
      camera.lookAt(V.set(0, 0, 0));

      renderer.render(scene, camera);
      raf = requestAnimationFrame(frame);
    };
    let raf = requestAnimationFrame(frame);

    // Pause when the tab is hidden (saves the GPU during a long run).
    const onVis = () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        clock.getDelta(); // drop the accumulated gap
        raf = requestAnimationFrame(frame);
      }
    };
    document.addEventListener("visibilitychange", onVis);

    // =====================================================================
    // Cleanup
    // =====================================================================
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      host.removeEventListener("pointermove", onPointer);
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
    };
  }, []);

  return <div className="fa-viz-canvas" ref={hostRef} aria-hidden />;
}
