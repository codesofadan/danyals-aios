"use client";

// ============================================================
// AIOS · 3D OS Loader (presentational)
// ------------------------------------------------------------
// A full-screen, theme-matched loading overlay. The centrepiece is a
// live three.js "kernel" — a glowing acid-lime icosahedron core wrapped
// in a wireframe lattice with orbiting data nodes, meant to read as the
// AIOS operating system spinning up. anime.js drives the DOM entrance
// (the stage pop) and the caption/progress-dot pulse.
//
// The WebGL context is created ONCE on mount and simply parked when the
// loader is idle: the render loop only runs while `active` is true, so
// there is no GPU churn between navigations. All colours are pulled from
// the Avant-Garde accent (#C6FF3C) so it never fights the theme.
// ============================================================

import { useEffect, useRef } from "react";
import * as THREE from "three";
import anime from "animejs";

const SIZE = 208; // stage px (square). Kept fixed so WebGL never re-sizes.
const LIME = 0xc6ff3c;
const LIME_SOFT = 0xd6ff6b;

type Props = { active: boolean; label: string };

export default function OSLoader({ active, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dotsRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const sceneRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    core: THREE.Group;
    orbit: THREE.Group;
    wire: THREE.LineSegments;
    glow: THREE.Sprite;
    clock: THREE.Clock;
  } | null>(null);

  // ---- one-time three.js setup ----------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(SIZE, SIZE, false);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
    // Pulled back so the kernel + orbit sit well inside the viewport with
    // margin to spare — nothing touches the canvas edge (no square clip).
    camera.position.set(0, 0, 6.4);

    // --- soft radial glow behind the kernel (matches the app's ambient glow)
    const glowTex = makeGlowTexture();
    const glow = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: glowTex, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false })
    );
    glow.scale.set(4.6, 4.6, 1);
    scene.add(glow);

    // --- the kernel: solid dark facets + bright wireframe + vertex points
    const core = new THREE.Group();
    const geo = new THREE.IcosahedronGeometry(1, 1);

    const solid = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.88, 1),
      new THREE.MeshBasicMaterial({ color: 0x0c0e08, transparent: true, opacity: 0.9 })
    );
    core.add(solid);

    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: LIME, transparent: true, opacity: 0.9 })
    );
    core.add(wire);

    const verts = new THREE.Points(
      geo,
      new THREE.PointsMaterial({
        color: LIME_SOFT,
        size: 0.09,
        transparent: true,
        opacity: 0.95,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    core.add(verts);
    scene.add(core);

    // --- orbiting data nodes (packets circling the kernel)
    const orbit = new THREE.Group();
    orbit.rotation.x = 1.05;
    const N = 22;
    const pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2;
      const r = 1.7;
      pos[i * 3] = Math.cos(a) * r;
      pos[i * 3 + 1] = Math.sin(a) * r;
      pos[i * 3 + 2] = (i % 2 ? 1 : -1) * 0.12;
    }
    const orbitGeo = new THREE.BufferGeometry();
    orbitGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const nodes = new THREE.Points(
      orbitGeo,
      new THREE.PointsMaterial({
        color: 0xffffff,
        size: 0.08,
        transparent: true,
        opacity: 0.85,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    orbit.add(nodes);
    // faint orbit ring
    const ringPts = new Float32Array(120 * 3);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2;
      ringPts[i * 3] = Math.cos(a) * 1.7;
      ringPts[i * 3 + 1] = Math.sin(a) * 1.7;
      ringPts[i * 3 + 2] = 0;
    }
    const ringGeo = new THREE.BufferGeometry();
    ringGeo.setAttribute("position", new THREE.BufferAttribute(ringPts, 3));
    const ring = new THREE.LineLoop(
      ringGeo,
      new THREE.LineBasicMaterial({ color: LIME, transparent: true, opacity: 0.22 })
    );
    orbit.add(ring);
    scene.add(orbit);

    sceneRef.current = { renderer, scene, camera, core, orbit, wire, glow, clock: new THREE.Clock() };
    // paint one idle frame so the canvas isn't blank if it ever flashes
    renderer.render(scene, camera);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      scene.traverse((o) => {
        const any = o as THREE.Mesh;
        if (any.geometry) any.geometry.dispose();
        const m = (any as THREE.Mesh).material;
        if (Array.isArray(m)) m.forEach((x) => x.dispose());
        else if (m) (m as THREE.Material).dispose();
      });
      glowTex.dispose();
      renderer.dispose();
      sceneRef.current = null;
    };
  }, []);

  // ---- run / park the render loop with `active` -----------------------
  useEffect(() => {
    const ctx = sceneRef.current;
    if (!ctx) return;

    if (!active) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      if (stageRef.current) anime.remove(stageRef.current);
      if (dotsRef.current) anime.remove(dotsRef.current.children as unknown as HTMLElement[]);
      return;
    }

    // Entrance — the kernel pops in, the dots pulse in sequence.
    ctx.clock.start();
    if (stageRef.current) {
      anime.remove(stageRef.current);
      anime({
        targets: stageRef.current,
        scale: [0.72, 1],
        opacity: [0, 1],
        duration: 620,
        easing: "easeOutElastic(1, 0.72)",
      });
    }
    if (dotsRef.current) {
      const dots = dotsRef.current.children;
      anime.remove(dots as unknown as HTMLElement[]);
      anime({
        targets: dots,
        translateY: [0, -6, 0],
        opacity: [0.35, 1, 0.35],
        delay: anime.stagger(140),
        duration: 900,
        easing: "easeInOutSine",
        loop: true,
      });
    }

    const tick = () => {
      const { renderer, scene, camera, core, orbit, wire, glow, clock } = ctx;
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;

      core.rotation.y += dt * 0.6;
      core.rotation.x += dt * 0.24;
      const breathe = 1 + Math.sin(t * 1.9) * 0.04;
      core.scale.setScalar(breathe);

      orbit.rotation.z += dt * 1.15;

      (wire.material as THREE.LineBasicMaterial).opacity = 0.68 + Math.sin(t * 3) * 0.22;
      const gs = 4.6 + Math.sin(t * 1.9) * 0.3;
      glow.scale.set(gs, gs, 1);

      renderer.render(scene, camera);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
  }, [active]);

  return (
    <div className={`os-loader${active ? " is-on" : ""}`} role="status" aria-live="polite" aria-hidden={!active}>
      <div className="os-loader-inner" ref={stageRef}>
        <div className="os-loader-stage" style={{ width: SIZE, height: SIZE }}>
          <canvas ref={canvasRef} className="os-loader-canvas" width={SIZE} height={SIZE} />
        </div>
        <div className="os-loader-cap">
          <div className="os-loader-title">
            AIOS<span>·</span>
          </div>
          <div className="os-loader-sub">{label}</div>
          <div className="os-loader-dots" ref={dotsRef} aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
    </div>
  );
}

// A soft radial gradient baked to a canvas texture — the kernel's halo.
function makeGlowTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(198,255,60,0.55)");
  g.addColorStop(0.35, "rgba(198,255,60,0.18)");
  g.addColorStop(1, "rgba(198,255,60,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}
