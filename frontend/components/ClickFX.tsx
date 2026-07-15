"use client";

import { useEffect } from "react";

/**
 * Global tactile feedback for every button in the app.
 *
 * Two effects, applied without touching any individual button:
 *  1. a quick "press" scale on pointer-down so the button physically
 *     reacts to the click, and
 *  2. a synthesized click sound (Web Audio — no asset files) whose weight
 *     scales with the button's importance: dense/low for main action
 *     buttons, lighter/higher for icon and secondary buttons.
 *
 * Mounted once from the root layout.
 */

type Weight = "heavy" | "medium" | "light";

// Main action buttons → a dense, low click.
const HEAVY = ".primary-btn, .danger-btn, .bk-runbtn, .rp-syncbtn, [data-click='heavy']";
// Small / icon / segmented buttons → a light, crisp tick.
const LIGHT =
  ".iconbtn, .kv-iconbtn, .mini-btn, .clear-btn, .pf-btn, .kv-pf-btn, .cred-btn, .seg button, .tw-tab, [data-click='light']";
// Anything clickable we want to react to.
const CLICKABLE = "button, [role='button'], a.primary-btn, a.ghostbtn";

function weightFor(el: Element): Weight {
  if (el.closest(HEAVY)) return "heavy";
  if (el.closest(LIGHT)) return "light";
  return "medium";
}

const TONE: Record<Weight, { freq: number; dur: number; vol: number; type: OscillatorType; noiseVol: number; hp: number }> = {
  //         pitch  length  loudness  waveform       body      brightness
  heavy: { freq: 125, dur: 0.115, vol: 0.17, type: "triangle", noiseVol: 0.09, hp: 850 },
  medium: { freq: 215, dur: 0.07, vol: 0.11, type: "triangle", noiseVol: 0.05, hp: 1200 },
  light: { freq: 340, dur: 0.045, vol: 0.075, type: "sine", noiseVol: 0.03, hp: 1900 },
};

export default function ClickFX() {
  useEffect(() => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    let ctx: AudioContext | null = null;
    const getCtx = () => {
      if (!ctx) {
        const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        if (AC) ctx = new AC();
      }
      if (ctx?.state === "suspended") void ctx.resume();
      return ctx;
    };

    const playClick = (weight: Weight) => {
      const ac = getCtx();
      if (!ac) return;
      const now = ac.currentTime;
      const cfg = TONE[weight];

      // Tonal "thock" — a fast downward pitch sweep gives the tactile body.
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = cfg.type;
      osc.frequency.setValueAtTime(cfg.freq * 2.3, now);
      osc.frequency.exponentialRampToValueAtTime(cfg.freq, now + cfg.dur * 0.6);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(cfg.vol, now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + cfg.dur);
      osc.connect(gain).connect(ac.destination);
      osc.start(now);
      osc.stop(now + cfg.dur + 0.02);

      // Filtered noise transient — the "click" attack; heavier buttons get more body.
      const nDur = 0.03;
      const buffer = ac.createBuffer(1, Math.max(1, Math.floor(ac.sampleRate * nDur)), ac.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
      const noise = ac.createBufferSource();
      noise.buffer = buffer;
      const hp = ac.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = cfg.hp;
      const nGain = ac.createGain();
      nGain.gain.setValueAtTime(cfg.noiseVol, now);
      nGain.gain.exponentialRampToValueAtTime(0.0001, now + nDur);
      noise.connect(hp).connect(nGain).connect(ac.destination);
      noise.start(now);
      noise.stop(now + nDur);
    };

    // --- visual press ---
    let pressed: HTMLElement | null = null;
    let prevTransform = "";
    let prevTransition = "";

    const release = () => {
      if (!pressed) return;
      pressed.style.transform = prevTransform;
      pressed.style.transition = prevTransition;
      pressed = null;
    };

    const onDown = (e: PointerEvent) => {
      const target = e.target as Element | null;
      const btn = target?.closest?.(CLICKABLE) as HTMLElement | null;
      if (!btn || btn.hasAttribute("disabled") || (btn as HTMLButtonElement).disabled) return;

      const weight = weightFor(btn);
      playClick(weight);

      if (reduceMotion) return;
      release();
      pressed = btn;
      prevTransform = btn.style.transform;
      prevTransition = btn.style.transition;
      const scale = weight === "heavy" ? 0.955 : weight === "light" ? 0.9 : 0.94;
      btn.style.transition = "transform .05s ease";
      btn.style.transform = `${prevTransform ? prevTransform + " " : ""}scale(${scale})`.trim();
    };

    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    window.addEventListener("blur", release);

    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
      window.removeEventListener("blur", release);
      release();
      void ctx?.close();
    };
  }, []);

  return null;
}
