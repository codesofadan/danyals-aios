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
// Hooks: useContentResearch (step 1), useSiteDesign (step 2 - a claim this
// comment made for weeks before the wizard actually called it), and
// useGenerateFromResearch (the commit).
// useGenerateFromResearch) and the existing ReviewPreview surface. No new
// endpoints. Every metered action is disabled while the API-spend halt is on.
// ============================================================

import { useMemo, useState } from "react";
import {
  RESEARCH_CONTENT_TYPES, DIFFICULTY_META, FRAMEWORKS, TARGETS, PAGE_TEMPLATES,
  TEMPLATE_THEME_DEFAULTS, profileFromTemplate,
  type ContentJob, type ResearchContentType, type ResearchItem,
  type Framework, type PublishTarget, type PageTemplate,
  type TemplateTheme, type SiteDesignProfile,
} from "@/lib/content";
import {
  useContentResearch, useGenerateFromResearch, useSiteDesign,
  type SiteDesignResult,
} from "@/lib/hooks/content";
import { useClients } from "@/lib/hooks/clients";
import ReviewPreview from "./ReviewPreview";
import TemplateGallery from "./TemplateGallery";
import type { ReviewAction } from "./ReviewGate";

// One item per non-blank line — how the grounding textareas map to the API arrays.
const _lines = (s: string): string[] => s.split("\n").map((l) => l.trim()).filter(Boolean);

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];
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
  // Skip-research: single pages the admin adds by hand (no research run needed).
  const [manualItems, setManualItems] = useState<ResearchItem[]>([]);
  const [manualTitle, setManualTitle] = useState("");

  // Step 3 — details (shared across every picked page)
  const [clientId, setClientId] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [template, setTemplate] = useState<PageTemplate | "Auto">("Auto");
  // DESIGN EXTRACTION - the other real choice on this step. POST /content/site-design
  // measures the client's existing site and returns a SiteDesignProfile; this hook
  // sat exported with ZERO callers while the step's own header comment claimed the
  // wizard used it. When an extraction succeeds it becomes the design that rides to
  // generate, beating any template pick. One paid call, metered under the content
  // dial; a degraded result says why and costs the operator nothing further.
  const extract = useSiteDesign();
  const [extracted, setExtracted] = useState<SiteDesignProfile | null>(null);
  const [extractedFrom, setExtractedFrom] = useState("");
  // The editable look for the chosen template (recolour + Google-Font pairing). Seeded
  // from the template's curated default; synthesised into a design_profile at generate.
  const [theme, setTheme] = useState<TemplateTheme>(TEMPLATE_THEME_DEFAULTS.service);
  // Select a template and, when switching to a NEW one, seed its default theme (a
  // re-click of the same card keeps any customization the operator already made).
  function selectTemplate(t: PageTemplate | "Auto") {
    if (t !== "Auto" && t !== template) setTheme(TEMPLATE_THEME_DEFAULTS[t]);
    setTemplate(t);
  }
  const [target, setTarget] = useState<PublishTarget>("WordPress");
  const [proof, setProof] = useState("");
  const [testimonials, setTestimonials] = useState("");
  const [uniqueData, setUniqueData] = useState("");
  const [services, setServices] = useState("");

  // Step 4/5 — the queued job codes + which one is previewed
  const [codes, setCodes] = useState<string[] | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);

  const research = useContentResearch();
  const generate = useGenerateFromResearch();

  // Research recommendations PLUS any single pages added by hand (skip-research).
  const items: ResearchItem[] = useMemo(
    () => [...manualItems, ...(research.data?.items ?? [])],
    [manualItems, research.data],
  );
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

  // Skip research: add ONE page by hand (title/topic) — becomes a selected pick so the
  // flow continues straight to design → details → generate, no research run needed.
  function addManualPage() {
    const t = manualTitle.trim();
    if (!t) return;
    const item: ResearchItem = {
      title: t, pageType: contentType, primaryKeyword: t, secondaryKeywords: [],
      estVolume: 0, difficulty: "medium", rationale: "Added manually (research skipped)",
      city: "", service: "",
    };
    setManualItems((prev) => (prev.some((p) => p.title === t) ? prev : [...prev, item]));
    setSelected((prev) => { const n = new Set(prev); n.add(t); return n; });
    setManualTitle("");
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
    // The look sent to the backend: a matched real site wins if attached; otherwise the
    // chosen template's theme (colour + fonts) is synthesised into the same design_profile.
    // An extracted profile wins over a template: matching the client's real site
    // is the stronger promise, and the operator made it explicitly.
    const designToSend =
      extracted ?? (template !== "Auto" ? profileFromTemplate(template, theme) : null);
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
        ...(designToSend ? { designProfile: designToSend } : {}),
      },
      { onSuccess: (r) => { setCodes(r.jobs); setPreviewId(r.jobs[0] ?? null); setStep(4); } },
    );
  }

  function resetWizard() {
    setStep(1); setSite(""); setContentType("service"); setCount("");
    setSelected(new Set()); setManualItems([]); setManualTitle("");
    setFramework("Auto"); setTemplate("Auto"); setTheme(TEMPLATE_THEME_DEFAULTS.service); setTarget("WordPress");
    setProof(""); setTestimonials(""); setUniqueData(""); setServices("");
    setCodes(null); setPreviewId(null);
    research.reset(); generate.reset();
  }

  // Proof is a HARD requirement to generate — the details must be supplied by the user.
  const hasRequiredDetails = _lines(proof).length > 0;
  const researchDegraded = research.data?.status === "degraded";
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
      <div className="card-h">
        <div>
          <div className="ct">
            Create content
          </div>
          <div className="cs">
            One guided flow: pick the pages, choose a template, add the details,
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

            <div className="co-toolset" style={{ marginBottom: 6 }}>
              <button className="primary-btn" type="button" onClick={runResearch}
                disabled={!site.trim() || halted || research.isPending}>
                <span className="material-symbols-rounded">{halted ? "block" : "search"}</span>
                {halted ? "API spend halted" : research.isPending ? "Researching…" : items.length ? "Re-run research" : "Research page set"}
              </button>
              <span className="co-muted" style={{ alignSelf: "center" }}>— or skip research and add one page —</span>
            </div>

            {/* Skip research: add a single page by hand (for when you just want one page). */}
            <div className="fld-row" style={{ marginBottom: 8 }}>
              <div className="fld" style={{ flex: 3 }}>
                <input value={manualTitle} onChange={(e) => setManualTitle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addManualPage(); } }}
                  placeholder="Page title / topic — e.g. Emergency plumbing in Dallas" />
              </div>
              <button type="button" className="ghostbtn" style={{ flex: 1 }}
                onClick={addManualPage} disabled={!manualTitle.trim()}>
                <span className="material-symbols-rounded">add</span>Add this page
              </button>
            </div>
            {manualItems.length > 0 && (
              <div className="cs" role="status" style={{ color: "var(--ok)", marginBottom: 4 }}>
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>check</span>{" "}
                {manualItems.length} page{manualItems.length === 1 ? "" : "s"} added manually — continue to Design when ready.
              </div>
            )}

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
                  <span className="co-muted">{selectedCount} of {items.length} selected</span>
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
            {/* EXTRACT the client's own design - the option this step always
                claimed to have. The site from Step 1 seeds the field. */}
            <div className="fld" style={{ marginBottom: 14 }}>
              <label htmlFor="wiz-extract-site">Match the client&apos;s existing site</label>
              <div className="fld-hint" style={{ marginTop: 0, marginBottom: 8 }}>
                One metered analysis reads the live site&apos;s colours, fonts and layout so
                every generated page is built to match it. Or skip this and pick a template below.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  id="wiz-extract-site"
                  value={extractedFrom || site}
                  onChange={(e) => setExtractedFrom(e.target.value)}
                  placeholder="https://clientsite.com"
                  autoComplete="off"
                  inputMode="url"
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="ghostbtn"
                  disabled={extract.isPending || !(extractedFrom || site).trim()}
                  onClick={() =>
                    extract.mutate(
                      { site: (extractedFrom || site).trim() },
                      {
                        onSuccess: (res: SiteDesignResult) => {
                          if (res.status === "ok" && res.profile) {
                            setExtracted(res.profile);
                            setExtractedFrom((extractedFrom || site).trim());
                          } else {
                            setExtracted(null);
                          }
                        },
                      },
                    )
                  }
                >
                  <span className="material-symbols-rounded">auto_fix_high</span>
                  {extract.isPending ? "Analyzing…" : "Extract design"}
                </button>
              </div>
              {extracted && (
                <div className="co-wiz-note" style={{ marginTop: 10 }} role="status">
                  <span className="material-symbols-rounded">check_circle</span>
                  <div>
                    <b>Design extracted from {extractedFrom}.</b> Generated pages will match it -
                    this beats any template pick below.{" "}
                    <button type="button" className="clear-btn" onClick={() => setExtracted(null)}>
                      Use a template instead
                    </button>
                  </div>
                </div>
              )}
              {extract.data && extract.data.status === "degraded" && !extracted && (
                <div className="co-wiz-note" style={{ marginTop: 10 }} role="alert">
                  <span className="material-symbols-rounded">warning</span>
                  <div>
                    <b>Couldn&apos;t extract a design.</b>{" "}
                    {extract.data.reason || "The analysis degraded."} Pick a template below instead.
                  </div>
                </div>
              )}
              {extract.isError && (
                <div className="co-wiz-note" style={{ marginTop: 10 }} role="alert">
                  <span className="material-symbols-rounded">error</span>
                  <div><b>The analysis failed.</b> Try again, or pick a template below.</div>
                </div>
              )}
            </div>

            {/* Template gallery — pick one of the 7 seeded templates, see it live, recolour + re-font it */}
            <div className="fld" style={{ marginBottom: 14 }}>
              <label>Choose a page template</label>
              <div className="fld-hint" style={{ marginTop: 0, marginBottom: 10 }}>
                Seven ready-made page designs — the best of the best. Pick one to see it live, then
                recolour it and pair fonts from Google Fonts. Your generated copy is slotted straight in.
              </div>
              <TemplateGallery value={template} theme={theme} onSelect={selectTemplate} onTheme={setTheme} />
            </div>

            <div className="co-wiz-note">
              <span className="material-symbols-rounded">palette</span>
              <div>
                <b>Pick a template and make it yours.</b> Recolour it and pair fonts from Google Fonts — every generated page is built into this layout. Optional: leave it on <b>Auto</b> and the engine chooses a template from each page type.
              </div>
            </div>
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
              <div className="tpl-summary">
                <span className="tpl-dot" style={{ background: template === "Auto" ? "var(--line)" : theme.primary }} />
                <b>{TPL_LABEL[template]}</b>
                {template !== "Auto" && (
                  <span className="cs">· {theme.primary} · {theme.heading}/{theme.body}</span>
                )}
                <button type="button" className="tpl-summary-edit" onClick={() => setStep(2)}>
                  <span className="material-symbols-rounded">edit</span> Change in Design
                </button>
              </div>
              <div className="fld-hint">
                {template === "Auto"
                  ? "Auto picks a template from each page type. Pick one in the Design step to force a specific layout + theme."
                  : `${PAGE_TEMPLATES.find((x) => x.key === template)?.bestFor} — content is slotted into this template, in your chosen theme.`}
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

            {/* recap */}
            <div className="wiz-recap">
              <span className="material-symbols-rounded">fact_check</span>
              <div>
                <div className="recap-t">{selectedCount} page{selectedCount === 1 ? "" : "s"} · {clientName || "no client"}</div>
                <div className="recap-s">
                  {framework} framework · {target}
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
                <span className="co-strong">
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
                <ReviewPreview job={previewJob} onAction={onReview} hideActions />
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
