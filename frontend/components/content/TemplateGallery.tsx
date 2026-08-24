"use client";

// ============================================================
// AIOS · Content · Template gallery + live theme customizer
// The Design step's centrepiece: the 7 seeded "best of the best" page templates,
// each rendered as a LIVE mini-mockup (not a name in a box). Selecting one reveals a
// customizer — recolour it and re-pair its fonts (loaded on demand from Google Fonts) —
// with a large preview that updates as you tweak. The generated copy is slotted into
// the chosen template in the chosen look (via profileFromTemplate → design_profile).
// ============================================================

import { useEffect, useMemo } from "react";
import {
  PAGE_TEMPLATES, TEMPLATE_BLUEPRINTS, TEMPLATE_THEME_DEFAULTS, GOOGLE_FONTS,
  type PageTemplate, type TemplateTheme, type PreviewBlock,
} from "@/lib/content";

// Preset accent colours the operator can one-click (plus a free colour input). A modern
// editorial / SaaS row — blues, indigo, teal/emerald, a warm orange and a clean ink — no
// dated violet default.
const SWATCHES = ["#2563EB", "#4F46E5", "#0891B2", "#059669", "#EA580C", "#0EA5E9", "#0F172A", "#E11D48"];

function mix(hex: string, toward: "black" | "white", amt: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const t = toward === "black" ? 0 : 255;
  const ch = (sh: number) => {
    const c = (n >> sh) & 0xff;
    return Math.round(c + (t - c) * amt).toString(16).padStart(2, "0");
  };
  return `#${ch(16)}${ch(8)}${ch(0)}`;
}

// Ensure the given font families are loaded from Google Fonts (one managed <link>).
function useGoogleFonts(families: string[]) {
  const key = useMemo(() => Array.from(new Set(families)).sort().join("|"), [families]);
  useEffect(() => {
    if (typeof document === "undefined") return;
    const fams = key.split("|").filter(Boolean);
    if (!fams.length) return;
    const href =
      "https://fonts.googleapis.com/css2?" +
      fams.map((f) => `family=${encodeURIComponent(f).replace(/%20/g, "+")}:wght@400;600;700;800`).join("&") +
      "&display=swap";
    let link = document.getElementById("aios-gfonts") as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.id = "aios-gfonts";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    if (link.href !== href) link.href = href;
  }, [key]);
}

// ── tiny skeleton primitives ────────────────────────────────────────────────
function Bar({ w = "100%", h = 6, c = "#d8dde5", r = 3, mb = 0, ml = 0 }:
  { w?: string | number; h?: number; c?: string; r?: number; mb?: number; ml?: number }) {
  return <div style={{ width: w, height: h, background: c, borderRadius: r, marginBottom: mb, marginLeft: ml, flexShrink: 0 }} />;
}

// Render ONE template block in the given theme.
function Block({ b, theme }: { b: PreviewBlock; theme: TemplateTheme }) {
  const p = theme.primary;
  const tint = mix(p, "white", 0.88);
  const dark = mix(p, "black", 0.4);
  const n = b.n ?? 3;
  const card = { flex: 1, background: "#fff", border: "1px solid #eceff3", borderRadius: 6, padding: 8 } as const;

  switch (b.t) {
    case "nav":
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid #eceff3" }}>
          <div style={{ width: 14, height: 14, borderRadius: 4, background: p }} />
          <Bar w={34} /> <Bar w={30} /> <Bar w={30} />
          <div style={{ marginLeft: "auto", width: 46, height: 16, borderRadius: 5, background: tint, border: `1px solid ${p}` }} />
        </div>
      );
    case "hero":
      return (
        <div style={{ background: tint, padding: 16, borderRadius: 8 }}>
          <Bar w="72%" h={13} c={dark} r={4} mb={9} />
          <Bar w="90%" h={6} mb={5} /><Bar w="66%" h={6} mb={12} />
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ width: 92, height: 22, borderRadius: 6, background: p }} />
            <div style={{ width: 74, height: 22, borderRadius: 6, background: "#fff", border: `1px solid ${mix(p, "white", 0.5)}` }} />
          </div>
        </div>
      );
    case "heading":
      return <div style={{ padding: "2px 2px" }}><Bar w="52%" h={11} c={dark} r={4} /></div>;
    case "text":
      return <div><Bar w="100%" mb={5} /><Bar w="97%" mb={5} /><Bar w="78%" /></div>;
    case "cards":
      return (
        <div style={{ display: "flex", gap: 8 }}>
          {Array.from({ length: n }).map((_, i) => (
            <div key={i} style={card}>
              <div style={{ width: 16, height: 16, borderRadius: 5, background: mix(p, "white", 0.2), marginBottom: 7 }} />
              <Bar w="80%" h={5} mb={5} /><Bar w="95%" h={4} mb={3} /><Bar w="70%" h={4} />
            </div>
          ))}
        </div>
      );
    case "image":
      return <div style={{ height: 74, borderRadius: 8, background: `linear-gradient(120deg, ${tint}, ${mix(p, "white", 0.55)})`, border: "1px solid #eceff3" }} />;
    case "stats":
      return (
        <div style={{ display: "flex", gap: 8 }}>
          {Array.from({ length: n }).map((_, i) => (
            <div key={i} style={{ flex: 1, textAlign: "center" }}>
              <Bar w="60%" h={14} c={p} r={4} mb={5} ml={"20%" as unknown as number} />
              <Bar w="80%" h={4} ml={"10%" as unknown as number} />
            </div>
          ))}
        </div>
      );
    case "review":
      return (
        <div style={{ background: "#fff", border: "1px solid #eceff3", borderRadius: 8, padding: 10 }}>
          <div style={{ display: "flex", gap: 3, marginBottom: 7 }}>
            {Array.from({ length: 5 }).map((_, i) => <div key={i} style={{ width: 9, height: 9, borderRadius: 2, background: "#f5b301", transform: "rotate(45deg)" }} />)}
          </div>
          <Bar w="96%" mb={5} /><Bar w="84%" />
        </div>
      );
    case "map":
      return (
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ width: "44%", height: 66, borderRadius: 8, background: `linear-gradient(135deg, ${mix(p, "white", 0.6)}, #e8edf3)`, border: "1px solid #e2e7ee", position: "relative" }}>
            <div style={{ position: "absolute", left: "52%", top: "40%", width: 10, height: 10, borderRadius: "50% 50% 50% 0", background: p, transform: "rotate(-45deg)" }} />
          </div>
          <div style={{ flex: 1, paddingTop: 6 }}><Bar w="70%" h={7} c={dark} mb={7} /><Bar w="90%" mb={5} /><Bar w="60%" mb={5} /><Bar w="75%" /></div>
        </div>
      );
    case "toc":
      return (
        <div style={{ border: "1px solid #eceff3", borderRadius: 8, padding: 10, background: "#fbfcfe" }}>
          <Bar w={54} h={6} c={dark} mb={8} />
          {[92, 80, 86, 68].map((w, i) => <Bar key={i} w={`${w}%`} h={5} c={mix(p, "white", 0.35)} mb={i < 3 ? 6 : 0} />)}
        </div>
      );
    case "split":
      return (
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ width: "46%", height: 70, borderRadius: 8, background: `linear-gradient(120deg, ${tint}, ${mix(p, "white", 0.55)})`, border: "1px solid #eceff3" }} />
          <div style={{ flex: 1, paddingTop: 4 }}><Bar w="80%" h={8} c={dark} mb={8} /><Bar w="100%" mb={5} /><Bar w="88%" mb={10} /><div style={{ width: 78, height: 20, borderRadius: 6, background: p }} /></div>
        </div>
      );
    case "faq":
      return (
        <div>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 2px", borderTop: i ? "1px solid #eceff3" : "none" }}>
              <Bar w={`${72 - i * 6}%`} h={6} />
              <div style={{ marginLeft: "auto", width: 10, height: 10, borderRight: `2px solid ${p}`, borderBottom: `2px solid ${p}`, transform: "rotate(45deg)" }} />
            </div>
          ))}
        </div>
      );
    default:
      return null;
  }
}

// Render a whole template's blocks in one themed page surface.
function Preview({ tpl, theme, dense }: { tpl: PageTemplate; theme: TemplateTheme; dense?: boolean }) {
  const blocks = TEMPLATE_BLUEPRINTS[tpl] ?? [];
  return (
    <div style={{ fontFamily: `'${theme.body}', system-ui, sans-serif`, background: "#fff", display: "flex", flexDirection: "column", gap: dense ? 10 : 14, padding: dense ? 12 : 18 }}>
      {blocks.map((b, i) => <Block key={`${b.t}-${i}`} b={b} theme={theme} />)}
    </div>
  );
}

export default function TemplateGallery({
  value, theme, onSelect, onTheme,
}: {
  value: PageTemplate | "Auto";
  theme: TemplateTheme;
  onSelect: (tpl: PageTemplate | "Auto") => void;
  onTheme: (theme: TemplateTheme) => void;
}) {
  // Load every gallery font (each card's default) plus the active custom theme's fonts.
  const fonts = useMemo(() => {
    const f: string[] = [theme.heading, theme.body];
    for (const t of Object.values(TEMPLATE_THEME_DEFAULTS)) { f.push(t.heading, t.body); }
    return f;
  }, [theme]);
  useGoogleFonts(fonts);

  const selected = value !== "Auto" ? value : null;

  return (
    <div className="tpl-gallery">
      <div className="tpl-grid">
        {/* Auto card */}
        <button type="button" onClick={() => onSelect("Auto")}
          className={`tpl-card${value === "Auto" ? " on" : ""}`} aria-pressed={value === "Auto"}>
          <div className="tpl-thumb tpl-thumb-auto">
            <span className="material-symbols-rounded">auto_awesome</span>
            <div className="tpl-auto-txt">Best template<br />per page, automatically</div>
          </div>
          <div className="tpl-meta">
            <div className="tpl-name">Auto <span className="cs">· recommended</span></div>
            <div className="tpl-best cs">Picks the ideal template from each page&apos;s type + search intent.</div>
          </div>
        </button>

        {/* The 7 seeded templates, each a live mockup in its own default look */}
        {PAGE_TEMPLATES.map((t) => {
          const th = value === t.key ? theme : TEMPLATE_THEME_DEFAULTS[t.key];
          const on = value === t.key;
          return (
            <button type="button" key={t.key} onClick={() => onSelect(t.key)}
              className={`tpl-card${on ? " on" : ""}`} aria-pressed={on}
              style={on ? { borderColor: theme.primary, boxShadow: `0 0 0 2px ${mix(theme.primary, "white", 0.6)}` } : undefined}>
              <div className="tpl-thumb"><Preview tpl={t.key} theme={th} dense /></div>
              <div className="tpl-meta">
                <div className="tpl-name">
                  <span className="tpl-dot" style={{ background: th.primary }} />{t.label}
                </div>
                <div className="tpl-best cs">{t.bestFor}</div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Customizer — appears when a specific template is selected */}
      {selected && (
        <div className="tpl-customize">
          <div>
            <div className="tpl-cz-h">
              <span className="material-symbols-rounded">tune</span>
              Customize <b>{PAGE_TEMPLATES.find((t) => t.key === selected)?.label}</b>
            </div>

            <div className="fld">
              <label>Accent colour</label>
              <div className="tpl-swatches">
                {SWATCHES.map((c) => (
                  <button type="button" key={c} title={c}
                    onClick={() => onTheme({ ...theme, primary: c })}
                    className={`tpl-sw${theme.primary.toLowerCase() === c.toLowerCase() ? " on" : ""}`}
                    style={{ background: c }} />
                ))}
                <label className="tpl-sw-custom" title="Custom colour">
                  <input type="color" value={theme.primary}
                    onChange={(e) => onTheme({ ...theme, primary: e.target.value })} />
                  <span className="material-symbols-rounded">colorize</span>
                </label>
              </div>
            </div>

            <div className="fld-row">
              <div className="fld" style={{ flex: 1 }}>
                <label>Heading font</label>
                <select value={theme.heading} onChange={(e) => onTheme({ ...theme, heading: e.target.value })}>
                  <optgroup label="Sans-serif">
                    {GOOGLE_FONTS.filter((f) => f.cat === "sans").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                  </optgroup>
                  <optgroup label="Serif">
                    {GOOGLE_FONTS.filter((f) => f.cat === "serif").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                  </optgroup>
                </select>
                <div className="tpl-font-demo" style={{ fontFamily: `'${theme.heading}', system-ui, sans-serif`, fontWeight: 800 }}>Ag — {theme.heading}</div>
              </div>
              <div className="fld" style={{ flex: 1 }}>
                <label>Body font</label>
                <select value={theme.body} onChange={(e) => onTheme({ ...theme, body: e.target.value })}>
                  <optgroup label="Sans-serif">
                    {GOOGLE_FONTS.filter((f) => f.cat === "sans").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                  </optgroup>
                  <optgroup label="Serif">
                    {GOOGLE_FONTS.filter((f) => f.cat === "serif").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                  </optgroup>
                </select>
                <div className="tpl-font-demo" style={{ fontFamily: `'${theme.body}', system-ui, sans-serif` }}>The quick brown fox — {theme.body}</div>
              </div>
            </div>

            <div className="tpl-cz-actions">
              <button type="button" className="tpl-reset"
                onClick={() => onTheme(TEMPLATE_THEME_DEFAULTS[selected])}>
                <span className="material-symbols-rounded">restart_alt</span> Reset to default
              </button>
              <span className="cs">Fonts load live from Google Fonts.</span>
            </div>
          </div>

          {/* Large live preview of the selected template in the current theme */}
          <div className="tpl-cz-preview">
            <div className="tpl-cz-preview-bar">
              <span /><span /><span />
              <div className="tpl-cz-url">yoursite.com/{selected.replace("_", "-")}</div>
            </div>
            <div className="tpl-cz-preview-body">
              <Preview tpl={selected} theme={theme} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
