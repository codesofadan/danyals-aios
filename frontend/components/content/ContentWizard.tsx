"use client";

// ============================================================
// AIOS · Content · ONE guided wizard
// Replaces the three disjoint entry cards (bulk research, site-design copy,
// single-job form) with a single step-by-step flow:
//   1  Pick pages      — content type + site → research → pick recommendations
//   2  Design (opt.)   — copy the site's look and attach it to every page
//   3  Details         — client, framework, publish target + grounding (shared)
//   4  Generate & preview — fan the picks into jobs, then review the draft + images
//   5  Approve → WordPress — one-click approve pushes a DRAFT to WordPress
//
// Reuses the existing hooks (useContentResearch / useSiteDesign /
// useGenerateFromResearch) and the existing ReviewPreview surface. No new
// endpoints. Every metered action is disabled while the API-spend halt is on.
// ============================================================

import { useMemo, useState } from "react";
import {
  RESEARCH_CONTENT_TYPES, DIFFICULTY_META, FRAMEWORKS, TARGETS, PAGE_TEMPLATES,
  type ContentJob, type ResearchContentType, type ResearchItem,
  type SiteDesignProfile, type Framework, type PublishTarget, type PageTemplate,
} from "@/lib/content";
import {
  useContentResearch, useGenerateFromResearch, useSiteDesign,
} from "@/lib/hooks/content";
import { useClients } from "@/lib/hooks/clients";
import ReviewPreview from "./ReviewPreview";
import LivePageEditor from "./LivePageEditor";
import type { ReviewAction } from "./ReviewGate";

// One item per non-blank line — how the grounding textareas map to the API arrays.
const _lines = (s: string): string[] => s.split("\n").map((l) => l.trim()).filter(Boolean);

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];
const TPL_OPTIONS: (PageTemplate | "Auto")[] = ["Auto", ...PAGE_TEMPLATES.map((t) => t.key)];
const TPL_LABEL: Record<string, string> = { Auto: "Auto", ...Object.fromEntries(PAGE_TEMPLATES.map((t) => [t.key, t.label])) };

// ── ONE unified, industry-neutral placeholder voice for the four grounding fields ──
// (short instruction lives in each field's label; a single neutral example here).
const PH = {
  proof: "e.g. Completed 450+ projects across the region since 2016",
  testimonials: "e.g. \"They delivered on time and the results speak for themselves.\" — a long-standing client",
  uniqueData: "e.g. Our 2025 review of 200 past projects found a 32% faster turnaround",
  services: "e.g. Consultation\ne.g. Installation\ne.g. Ongoing maintenance",
} as const;

const STEP_LABELS = ["Pick pages", "Design", "Details", "Preview", "Approve"] as const;
type Step = 1 | 2 | 3 | 4 | 5;

// Pull an http(s) URL out of a pushed job's stage label ("Pushed to WordPress: <url>").
function wpUrlFromStage(job: ContentJob): string | null {
  if (job.status !== "done" || !job.stage.startsWith("Pushed to WordPress")) return null;
  return job.stage.match(/https?:\/\/\S+/)?.[0] ?? null;
}

export default function ContentWizard({
  jobs, halted, onReview,
}: {
  jobs: ContentJob[];
  halted: boolean;
  onReview: (id: string, action: ReviewAction, note?: string) => void;
}) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];

  const [step, setStep] = useState<Step>(1);

  // Step 1 — research
  const [site, setSite] = useState("");
  const [contentType, setContentType] = useState<ResearchContentType>("service");
  const [count, setCount] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Step 2 — design
  const [maxPages, setMaxPages] = useState("");
  const [design, setDesign] = useState<SiteDesignProfile | null>(null);
  const [attachDesign, setAttachDesign] = useState(true);

  // Step 3 — details (shared across every picked page)
  const [clientId, setClientId] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [template, setTemplate] = useState<PageTemplate | "Auto">("Auto");
  const [target, setTarget] = useState<PublishTarget>("WordPress");
  const [proof, setProof] = useState("");
  const [testimonials, setTestimonials] = useState("");
  const [uniqueData, setUniqueData] = useState("");
  const [services, setServices] = useState("");

  // Step 4/5 — the queued job codes + which one is previewed
  const [codes, setCodes] = useState<string[] | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  // The job whose page is open in the live editor (null = editor closed).
  const [editorCode, setEditorCode] = useState<string | null>(null);

  const research = useContentResearch();
  const siteDesign = useSiteDesign();
  const generate = useGenerateFromResearch();

  const items: ResearchItem[] = research.data?.items ?? [];
  const effectiveClientId = clientId || clients[0]?.id || "";
  const selectedCount = useMemo(
    () => items.filter((i) => selected.has(i.title)).length,
    [items, selected],
  );
  const picks = useMemo(
    () => items.filter((i) => selected.has(i.title)),
    [items, selected],
  );

  // The jobs the wizard just created, in the order they were queued.
  const generatedJobs = useMemo(() => {
    if (!codes) return [];
    const by = new Map(jobs.map((j) => [j.id, j]));
    return codes.map((c) => by.get(c)).filter((j): j is ContentJob => !!j);
  }, [codes, jobs]);
  const previewJob = generatedJobs.find((j) => j.id === previewId) ?? generatedJobs[0] ?? null;

  // ── actions ──────────────────────────────────────────────────────────────
  function runResearch() {
    if (!site.trim() || halted || research.isPending) return;
    const n = parseInt(count, 10);
    research.mutate(
      { site: site.trim(), contentType, count: Number.isFinite(n) && n > 0 ? n : undefined },
      { onSuccess: (r) => setSelected(new Set(r.items.map((i) => i.title))) },
    );
  }

  function runSiteDesign() {
    if (!site.trim() || halted || siteDesign.isPending) return;
    const n = parseInt(maxPages, 10);
    siteDesign.mutate(
      { site: site.trim(), maxPages: Number.isFinite(n) && n > 0 ? n : undefined },
      { onSuccess: (r) => { setDesign(r.profile); setAttachDesign(!!r.profile); } },
    );
  }

  function toggleOne(title: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(title)) next.delete(title); else next.add(title);
      return next;
    });
  }
  const allSelected = items.length > 0 && selected.size === items.length;
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.title)));
  }

  function generatePages() {
    // Proof / first-hand experience is REQUIRED to generate (not just to publish): a page
    // with zero grounding can never clear the E-E-A-T QA gate, so block at input, not review.
    if (picks.length === 0 || !effectiveClientId || _lines(proof).length === 0 || halted || generate.isPending) return;
    generate.mutate(
      {
        items: picks,
        clientId: effectiveClientId,
        framework,
        template,
        target,
        proofPoints: _lines(proof).slice(0, 12),
        testimonials: _lines(testimonials).slice(0, 12),
        uniqueData: _lines(uniqueData).slice(0, 12),
        services: _lines(services).slice(0, 20),
        ...(attachDesign && design ? { designProfile: design } : {}),
      },
      { onSuccess: (r) => { setCodes(r.jobs); setPreviewId(r.jobs[0] ?? null); setStep(4); } },
    );
  }

  function resetWizard() {
    setStep(1); setSite(""); setContentType("service"); setCount("");
    setSelected(new Set()); setMaxPages(""); setDesign(null); setAttachDesign(true);
    setFramework("Auto"); setTemplate("Auto"); setTarget("WordPress");
    setProof(""); setTestimonials(""); setUniqueData(""); setServices("");
    setCodes(null); setPreviewId(null);
    research.reset(); siteDesign.reset(); generate.reset();
  }

  // Proof is a HARD requirement to generate — the details must be supplied by the user.
  const hasRequiredDetails = _lines(proof).length > 0;
  const researchDegraded = research.data?.status === "degraded";
  const designDegraded = siteDesign.data?.status === "degraded";
  const clientName = clients.find((c) => c.id === effectiveClientId)?.cn ?? "";

  // ── per-step footer gating ────────────────────────────────────────────────
  const canNext =
    step === 1 ? selectedCount > 0 :
    step === 2 ? true :                                // design is optional / skippable
    step === 3 ? !!effectiveClientId && hasRequiredDetails && !halted :
    step === 4 ? generatedJobs.length > 0 :
    false;

  return (
    <section className="card co-wiz-card">
      {editorCode && (
        <LivePageEditor
          code={editorCode}
          onClose={() => setEditorCode(null)}
          onPublish={(c) => { onReview(c, "approve"); setEditorCode(null); }}
        />
      )}
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", marginRight: 6 }}>auto_awesome</span>
            Create content
          </div>
          <div className="cs">
            One guided flow: pick the pages, match the site&apos;s design, add the details,
            preview the draft with images, then approve to push a WordPress draft.
          </div>
        </div>
      </div>

      {/* step indicator */}
      <div className="wiz-steps co-wiz-steps">
        {STEP_LABELS.map((label, i) => {
          const n = (i + 1) as Step;
          const state = n < step ? "done" : n === step ? "on" : "";
          return (
            <div className={`wiz-step ${state}`} key={label}>
              <span className="wiz-dot">{n < step ? <span className="material-symbols-rounded">check</span> : n}</span>
              <span className="wiz-slabel">{label}</span>
            </div>
          );
        })}
      </div>

      <div className="wiz-body co-wiz-body">
        {/* ───────────────────────── STEP 1 — PICK PAGES ───────────────────────── */}
        {step === 1 && (
          <>
            <div className="fld">
              <label>Content type</label>
              <div className="co-chips wrap">
                {RESEARCH_CONTENT_TYPES.map((t) => (
                  <button type="button" key={t.key}
                    className={contentType === t.key ? "chip on" : "chip"}
                    onClick={() => setContentType(t.key)}>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="fld-row">
              <div className="fld" style={{ flex: 3 }}>
                <label>Site</label>
                <input value={site} onChange={(e) => setSite(e.target.value)}
                  placeholder="https://client-site.com" />
              </div>
              <div className="fld" style={{ flex: 1 }}>
                <label>Count <span className="cs">(optional)</span></label>
                <input value={count} onChange={(e) => setCount(e.target.value.replace(/[^0-9]/g, ""))}
                  inputMode="numeric" placeholder="auto" />
              </div>
            </div>

            <div className="op-toolset" style={{ marginBottom: 6 }}>
              <button className="primary-btn" type="button" onClick={runResearch}
                disabled={!site.trim() || halted || research.isPending}>
                <span className="material-symbols-rounded">{halted ? "block" : "search"}</span>
                {halted ? "API spend halted" : research.isPending ? "Researching…" : items.length ? "Re-run research" : "Research page set"}
              </button>
            </div>

            {/* Research takes ~40–60s — show real progress, not a stuck spinner. */}
            {research.isPending && (
              <div className="co-prog" role="status">
                <div className="co-prog-bar"><span /></div>
                <div className="co-prog-txt">
                  Researching the site and its competitors, then recommending a page set.
                  This usually takes 40–60 seconds.
                </div>
              </div>
            )}
            {research.isError && (
              <div className="cs" role="alert" style={{ color: "var(--warn)" }}>
                Research failed. {(research.error as Error)?.message ?? "Try again"}.
              </div>
            )}
            {researchDegraded && (
              <div className="cs" role="status" style={{ color: "var(--warn)" }}>
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>info</span>{" "}
                Research degraded — {research.data?.reason || "no key or the dial/budget blocked the call"}.
              </div>
            )}

            {/* Empty state before the first run */}
            {!research.isPending && items.length === 0 && !research.isError && (
              <div className="co-wiz-empty">
                <span className="material-symbols-rounded">travel_explore</span>
                <div>Enter a site and run research to get a recommended set of pages to build.</div>
              </div>
            )}

            {/* Recommendation checkbox list */}
            {items.length > 0 && (
              <>
                <div className="co-rec-h">
                  <button type="button" className="chip" onClick={toggleAll}>
                    <span className="material-symbols-rounded" style={{ fontSize: 15, verticalAlign: "middle" }}>
                      {allSelected ? "check_box" : "check_box_outline_blank"}
                    </span>{" "}
                    {allSelected ? "Clear all" : "Select all"}
                  </button>
                  <span className="op-muted">{selectedCount} of {items.length} selected</span>
                </div>
                <div className="co-rec-list">
                  {items.map((it) => {
                    const dm = DIFFICULTY_META[it.difficulty];
                    const on = selected.has(it.title);
                    return (
                      <button type="button" key={it.title}
                        className={on ? "co-rec-row on" : "co-rec-row"}
                        onClick={() => toggleOne(it.title)}>
                        <span className="material-symbols-rounded co-rec-check">
                          {on ? "check_box" : "check_box_outline_blank"}
                        </span>
                        <span className="co-rec-main">
                          <span className="co-rec-title">{it.title}</span>
                          <span className="co-rec-meta">
                            {it.primaryKeyword && <span className="co-rec-kw">{it.primaryKeyword}</span>}
                            {(it.city || it.service) && (
                              <span className="co-sep">{[it.service, it.city].filter(Boolean).join(" · ")}</span>
                            )}
                          </span>
                        </span>
                        <span className="co-rec-vol" title="Estimated monthly search volume">
                          {it.estVolume.toLocaleString()} <i>vol</i>
                        </span>
                        <span className={`status-pill ${dm.cls}`}>{dm.label}</span>
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {/* ───────────────────────── STEP 2 — DESIGN (optional) ───────────────────────── */}
        {step === 2 && (
          <>
            {/* Template gallery — pick the page layout HERE in the design step */}
            <div className="fld" style={{ marginBottom: 14 }}>
              <label>Choose a page template</label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <button type="button" onClick={() => setTemplate("Auto")}
                  style={{ textAlign: "left", padding: "10px 12px", cursor: "pointer",
                    border: `1px solid ${template === "Auto" ? "var(--maroon-2, #8c1d2e)" : "var(--line)"}`,
                    borderRadius: 10, background: template === "Auto" ? "var(--blush, #f8ecee)" : "#fff" }}>
                  <div style={{ fontWeight: 800 }}>Auto <span className="cs">(recommended)</span></div>
                  <div className="cs">Pick the best template from each page&apos;s type + search intent.</div>
                </button>
                {PAGE_TEMPLATES.map((t) => (
                  <button type="button" key={t.key} onClick={() => setTemplate(t.key)}
                    style={{ textAlign: "left", padding: "10px 12px", cursor: "pointer",
                      border: `1px solid ${template === t.key ? "var(--maroon-2, #8c1d2e)" : "var(--line)"}`,
                      borderRadius: 10, background: template === t.key ? "var(--blush, #f8ecee)" : "#fff" }}>
                    <div style={{ fontWeight: 800 }}>{t.label}</div>
                    <div className="cs">{t.bestFor}</div>
                  </button>
                ))}
              </div>
              <div className="fld-hint">
                The template sets each page&apos;s section layout. {template === "Auto"
                  ? "Auto adapts per page type."
                  : `Selected: ${TPL_LABEL[template]}.`} Then optionally match the site&apos;s look below.
              </div>
            </div>

            <div className="co-wiz-note">
              <span className="material-symbols-rounded">palette</span>
              <div>
                <b>Match the client&apos;s existing look.</b> Copy the site&apos;s colours, fonts and
                layout so every generated page fits right in. This step is optional — skip it to
                use the default styling.
              </div>
            </div>

            <div className="fld-row">
              <div className="fld" style={{ flex: 3 }}>
                <label>Site to copy the design from</label>
                <input value={site} onChange={(e) => setSite(e.target.value)}
                  placeholder="https://client-site.com" />
              </div>
              <div className="fld" style={{ flex: 1 }}>
                <label>Max pages <span className="cs">(optional)</span></label>
                <input value={maxPages} onChange={(e) => setMaxPages(e.target.value.replace(/[^0-9]/g, ""))}
                  inputMode="numeric" placeholder="auto" />
              </div>
            </div>

            <div className="op-toolset" style={{ marginBottom: 6 }}>
              <button className="primary-btn" type="button" onClick={runSiteDesign}
                disabled={!site.trim() || halted || siteDesign.isPending}>
                <span className="material-symbols-rounded">{halted ? "block" : "palette"}</span>
                {halted ? "API spend halted" : siteDesign.isPending ? "Analysing…" : design ? "Re-analyse design" : "Match this site's design"}
              </button>
            </div>

            {siteDesign.isPending && (
              <div className="co-prog" role="status">
                <div className="co-prog-bar"><span /></div>
                <div className="co-prog-txt">Reading the site&apos;s pages and extracting its design system…</div>
              </div>
            )}
            {designDegraded && !design && (
              <div className="cs" role="status" style={{ color: "var(--warn)" }}>
                Design analysis degraded — {siteDesign.data?.reason || "no key or the dial/budget blocked the call"}.
              </div>
            )}

            {design && (
              <div className="co-design">
                {design.wireframeHtml && (
                  <>
                    <div className="co-order-lbl op-muted" style={{ marginBottom: 6 }}>
                      <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>preview</span>{" "}
                      Preview — how a matching page would look
                    </div>
                    <iframe
                      title="Matching page preview"
                      srcDoc={design.wireframeHtml}
                      sandbox=""
                      loading="lazy"
                      style={{
                        width: "100%", height: 320, border: "1px solid var(--line)",
                        borderRadius: 10, background: "#fff", display: "block", marginBottom: 12,
                      }}
                    />
                  </>
                )}

                <div className="co-swatches">
                  {(Object.entries(design.palette) as [string, string][]).map(([name, hex]) => (
                    <div key={name} className="co-swatch">
                      <span className="co-swatch-chip" style={{ background: hex }} />
                      <span className="co-swatch-name">{name}</span>
                      <span className="co-swatch-hex">{hex}</span>
                    </div>
                  ))}
                </div>

                <div className="co-design-meta">
                  <div><span className="op-muted">Heading</span> <b>{design.typography.heading_font}</b></div>
                  <div><span className="op-muted">Body</span> <b>{design.typography.body_font}</b></div>
                  <div><span className="op-muted">Base size</span> <b>{design.typography.base_size}</b></div>
                  <div><span className="op-muted">Container</span> <b>{design.layout.container_width}</b></div>
                  <div><span className="op-muted">Hero</span> <b>{design.layout.hero_style}</b></div>
                  <div><span className="op-muted">CTA</span> <b>{design.layout.cta_style}</b></div>
                </div>

                <div className="co-order-lbl op-muted">Section order</div>
                <ol className="co-order">
                  {design.layout.section_order.map((s, i) => (
                    <li key={`${s}-${i}`} className="co-order-item">{s}</li>
                  ))}
                </ol>

                {design.notes && <div className="cs" style={{ marginTop: 6 }}>{design.notes}</div>}

                <label className="co-attach">
                  <input type="checkbox" checked={attachDesign} onChange={(e) => setAttachDesign(e.target.checked)} />
                  Apply this design to the {selectedCount} selected page{selectedCount === 1 ? "" : "s"}
                </label>
              </div>
            )}
          </>
        )}

        {/* ───────────────────────── STEP 3 — DETAILS ───────────────────────── */}
        {step === 3 && (
          <>
            {selectedCount > 1 && (
              <div className="co-wiz-note">
                <span className="material-symbols-rounded">info</span>
                <div>These details apply to <b>all {selectedCount} selected pages</b>. Each page keeps its own title and page type from the research above.</div>
              </div>
            )}

            <div className="fld-row">
              <div className="fld">
                <label>Client</label>
                <select value={effectiveClientId} onChange={(e) => setClientId(e.target.value)}
                  disabled={clients.length === 0}>
                  {clients.length === 0 ? (
                    <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
                  ) : (
                    clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
                  )}
                </select>
              </div>
              <div className="fld">
                <label>Publish target</label>
                <div className="seg co-target-seg">
                  {TARGETS.map((t) => (
                    <button type="button" key={t}
                      className={target === t ? "on" : ""}
                      onClick={() => setTarget(t)}>
                      {t === "WordPress" ? "WordPress" : "PDF / Markdown"}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="fld">
              <label>Framework</label>
              <div className="co-chips wrap">
                {FW_OPTIONS.map((f) => (
                  <button type="button" key={f}
                    className={framework === f ? "chip on" : "chip"}
                    onClick={() => setFramework(f)}>
                    {f}
                  </button>
                ))}
              </div>
              <div className="fld-hint">
                {framework === "Auto"
                  ? "Auto selects a framework from each page type + search intent."
                  : FRAMEWORKS.find((x) => x.key === framework)?.expansion}
              </div>
            </div>

            <div className="fld">
              <label>Layout template</label>
              <div className="co-chips wrap">
                {TPL_OPTIONS.map((t) => (
                  <button type="button" key={t}
                    className={template === t ? "chip on" : "chip"}
                    onClick={() => setTemplate(t)}>
                    {TPL_LABEL[t]}
                  </button>
                ))}
              </div>
              <div className="fld-hint">
                {template === "Auto"
                  ? (attachDesign && design
                      ? "Auto — the page mirrors the analyzed site's layout. Pick a template to override it."
                      : "Auto picks a template from each page type. Pick one to force a specific layout.")
                  : `${PAGE_TEMPLATES.find((x) => x.key === template)?.bestFor} — content is slotted into this template's sections${attachDesign && design ? " (overrides the analyzed site)" : ""}.`}
              </div>
            </div>

            <div className="fld">
              <label>
                Proof &amp; first-hand experience{" "}
                <span style={{ color: "var(--warn)", fontWeight: 700 }}>*</span>{" "}
                <span className="cs">(required · one per line)</span>
              </label>
              <textarea rows={3} value={proof} onChange={(e) => setProof(e.target.value)}
                placeholder={PH.proof} aria-required="true"
                style={!hasRequiredDetails ? { borderColor: "var(--warn)" } : undefined} />
              <div className="fld-hint">
                Required to generate — supply at least one real, first-hand proof point. The E-E-A-T /
                fact-grounding QA gate holds any page with zero proof, so pages are not built without it.
              </div>
            </div>

            <div className="fld">
              <label>Testimonials <span className="cs">(optional, one per line)</span></label>
              <textarea rows={2} value={testimonials} onChange={(e) => setTestimonials(e.target.value)} placeholder={PH.testimonials} />
            </div>

            <div className="fld-row">
              <div className="fld">
                <label>Unique data / original stats <span className="cs">(optional, one per line)</span></label>
                <textarea rows={2} value={uniqueData} onChange={(e) => setUniqueData(e.target.value)} placeholder={PH.uniqueData} />
              </div>
              <div className="fld">
                <label>Services <span className="cs">(optional, one per line)</span></label>
                <textarea rows={2} value={services} onChange={(e) => setServices(e.target.value)} placeholder={PH.services} />
              </div>
            </div>

            {!hasRequiredDetails && (
              <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 4 }}>
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>error</span>{" "}
                Add at least one <b>Proof &amp; first-hand experience</b> point above — it&apos;s required to
                generate. The page won&apos;t build without it.
              </div>
            )}
            {design && attachDesign && (
              <div className="cs" role="status" style={{ color: "var(--ok)" }}>
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>palette</span>{" "}
                The copied site design will be applied to every generated page.
              </div>
            )}

            {/* recap */}
            <div className="wiz-recap">
              <span className="material-symbols-rounded">fact_check</span>
              <div>
                <div className="recap-t">{selectedCount} page{selectedCount === 1 ? "" : "s"} · {clientName || "no client"}</div>
                <div className="recap-s">
                  {framework} framework · {target}{design && attachDesign ? " · design matched" : ""}
                </div>
              </div>
              <button type="button" className="recap-edit" onClick={() => setStep(1)}>Edit pages</button>
            </div>

            {generate.isError && (
              <div className="cs" role="alert" style={{ color: "var(--warn)", marginTop: 8 }}>
                Couldn&apos;t queue the pages. {(generate.error as Error)?.message ?? "Try again"}.
              </div>
            )}
          </>
        )}

        {/* ───────────────────────── STEP 4 — GENERATE & PREVIEW ───────────────────────── */}
        {step === 4 && (
          <>
            <div className="co-codes-wrap" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
              <div className="co-rec-h" style={{ marginTop: 0 }}>
                <span className="op-strong">
                  <span className="material-symbols-rounded" style={{ verticalAlign: "middle", color: "var(--ok)" }}>task_alt</span>{" "}
                  Queued {generatedJobs.length || codes?.length || 0} content {(codes?.length ?? 0) === 1 ? "job" : "jobs"} — the pipeline is drafting them now.
                </span>
              </div>
              {generatedJobs.length > 1 && (
                <div className="co-wiz-jobtabs">
                  {generatedJobs.map((j) => (
                    <button type="button" key={j.id}
                      className={j.id === previewJob?.id ? "chip on" : "chip"}
                      onClick={() => setPreviewId(j.id)}>
                      {j.topic.length > 32 ? j.topic.slice(0, 32) + "…" : j.topic}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {previewJob ? (
              previewJob.status === "queued" || previewJob.status === "drafting" ? (
                <div className="co-prog" role="status">
                  <div className="co-prog-bar"><span /></div>
                  <div className="co-prog-txt">
                    Writing “{previewJob.topic}” — research, outline, draft, titles &amp; meta, schema and images.
                    The preview appears here the moment it reaches review.
                  </div>
                </div>
              ) : (
                <>
                  <div className="co-wiz-note">
                    <span className="material-symbols-rounded">edit_square</span>
                    <div>
                      <b>Edit this page live.</b> Open the editor to change any text, swap images and
                      reorder sections right on the page — exactly as it will publish. Then Save &amp;
                      Publish to push it to WordPress.
                    </div>
                    <button type="button" className="primary-btn" onClick={() => setEditorCode(previewJob.id)}>
                      Edit page live
                    </button>
                  </div>
                  <ReviewPreview job={previewJob} onAction={onReview} hideActions />
                </>
              )
            ) : (
              <div className="co-wiz-empty">
                <span className="material-symbols-rounded">hourglass_top</span>
                <div>Waiting for the first draft to land…</div>
              </div>
            )}
          </>
        )}

        {/* ───────────────────────── STEP 5 — APPROVE → WORDPRESS ───────────────────────── */}
        {step === 5 && (
          <>
            <div className="co-wiz-note">
              <span className="material-symbols-rounded">cloud_upload</span>
              <div>
                <b>One click approves and pushes a WordPress draft.</b> Nothing goes live automatically —
                open the draft in WordPress to preview and publish it there.
              </div>
            </div>

            <div className="co-approve-list">
              {generatedJobs.map((j) => {
                const url = wpUrlFromStage(j);
                const pushed = !!url || (j.status === "done" && j.stage.startsWith("Pushed to WordPress"));
                return (
                  <div className="co-approve-row" key={j.id}>
                    <div className="co-approve-main">
                      <div className="co-approve-topic">{j.topic}</div>
                      <div className="co-approve-meta">
                        <span className="co-dot" style={{ background: j.color }} />
                        {j.client} <span className="co-sep">·</span> {j.framework}
                        <span className="co-sep">·</span> {j.words.toLocaleString()} words
                        <span className="co-sep">·</span> {j.images} image{j.images === 1 ? "" : "s"}
                      </div>
                    </div>
                    {pushed ? (
                      <a className="primary-btn" href={url ?? "#"} target="_blank" rel="noopener noreferrer"
                        style={{ textDecoration: "none" }}>
                        <span className="material-symbols-rounded">open_in_new</span>Open in WordPress
                      </a>
                    ) : j.status === "needs_review" ? (
                      <button className="primary-btn co-approve" onClick={() => onReview(j.id, "approve")}>
                        <span className="material-symbols-rounded">cloud_upload</span>Approve &amp; push to WordPress
                      </button>
                    ) : j.status === "publishing" ? (
                      <span className="pill-tag info"><span className="material-symbols-rounded">rocket_launch</span>Pushing…</span>
                    ) : j.status === "rejected" ? (
                      <span className="pill-tag warn"><span className="material-symbols-rounded">block</span>Rejected</span>
                    ) : (
                      <span className="pill-tag"><span className="material-symbols-rounded">hourglass_top</span>Still drafting…</span>
                    )}
                  </div>
                );
              })}
            </div>

            {generatedJobs.some((j) => wpUrlFromStage(j)) && (
              <div className="cs" role="status" style={{ color: "var(--muted)", marginTop: 4 }}>
                Pushed as a draft. Preview &amp; publish inside WordPress to take it live.
              </div>
            )}
          </>
        )}
      </div>

      {/* ── footer nav ── */}
      <div className="co-wiz-foot">
        {step > 1 ? (
          <button type="button" className="ghostbtn" onClick={() => setStep((s) => (s - 1) as Step)}>
            <span className="material-symbols-rounded">arrow_back</span>Back
          </button>
        ) : <span />}

        {step === 2 && (
          <button type="button" className="ghostbtn" onClick={() => setStep(3)}>
            Skip design<span className="material-symbols-rounded">skip_next</span>
          </button>
        )}

        {step < 3 && (
          <button type="button" className="primary-btn" disabled={!canNext} onClick={() => setStep((s) => (s + 1) as Step)}>
            Next<span className="material-symbols-rounded">arrow_forward</span>
          </button>
        )}
        {step === 3 && (
          <button type="button" className="primary-btn" disabled={!canNext || generate.isPending} onClick={generatePages}
            title={!hasRequiredDetails ? "Add a proof / first-hand experience point to generate" : undefined}>
            <span className="material-symbols-rounded">{halted ? "block" : "bolt"}</span>
            {halted ? "API spend halted"
              : generate.isPending ? "Generating…"
              : !effectiveClientId ? "Pick a client"
              : !hasRequiredDetails ? "Add proof to generate"
              : `Generate ${selectedCount} page${selectedCount === 1 ? "" : "s"}`}
          </button>
        )}
        {step === 4 && (
          <button type="button" className="primary-btn" disabled={!canNext} onClick={() => setStep(5)}>
            Approve step<span className="material-symbols-rounded">arrow_forward</span>
          </button>
        )}
        {step === 5 && (
          <button type="button" className="primary-btn" onClick={resetWizard}>
            <span className="material-symbols-rounded">add</span>Start another
          </button>
        )}
      </div>
    </section>
  );
}
