"use client";

// ============================================================
// AIOS · Site Builder · the website-reconstruction creation wizard
// Mirrors components/content/ContentWizard.tsx's exact shell (step indicator,
// canNext gating, footer nav) applied to the NEW /site-builder API:
//   1  What are you creating?     — a curated page-type starting point
//   2  Where should the design
//      come from?                 — existing site / reference URL / template / blank
//   3  Details                    — client, industry, editor mode, fidelity mode
//   4  Build                      — progress → resolved design summary → publish
// ============================================================

import { useMemo, useState } from "react";
import {
  CREATION_TYPES, SOURCE_TYPES, EDITOR_MODES, FIDELITY_MODES, STATUS_META,
  type SourceType, type EditorMode, type FidelityMode,
} from "@/lib/site-builder";
import {
  useCreateSiteBuilderJob, useSiteBuilderJob, useSiteBuilderDesign,
  useSiteBuilderTemplates, usePublishSiteBuilderJob, useSiteBuilderVisualValidations,
} from "@/lib/hooks/site-builder";
import { useClients } from "@/lib/hooks/clients";

const STEP_LABELS = ["Create", "Design source", "Details", "Build"] as const;
type Step = 1 | 2 | 3 | 4;

export default function SiteBuilderWizard() {
  const [step, setStep] = useState<Step>(1);
  const [creationKey, setCreationKey] = useState(CREATION_TYPES[0].key);
  const [sourceType, setSourceType] = useState<SourceType>("template");
  const [sourceUrl, setSourceUrl] = useState("");
  const [templateKey, setTemplateKey] = useState<string | null>(null);
  const [clientId, setClientId] = useState<string | null>(null);
  const [industry, setIndustry] = useState("");
  const [editorMode, setEditorMode] = useState<EditorMode>("auto");
  const [fidelityMode, setFidelityMode] = useState<FidelityMode>("balanced");
  const [jobCode, setJobCode] = useState<string | null>(null);

  const creation = CREATION_TYPES.find((c) => c.key === creationKey) ?? CREATION_TYPES[0];
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const templatesQ = useSiteBuilderTemplates(industry, creation.pageType);

  const create = useCreateSiteBuilderJob();
  const jobQ = useSiteBuilderJob(jobCode);
  const job = jobQ.data ?? null;
  const designQ = useSiteBuilderDesign(job?.designIrId ?? null);
  const design = designQ.data ?? null;
  const validationsQ = useSiteBuilderVisualValidations(jobCode);
  const validations = validationsQ.data ?? [];
  const publish = usePublishSiteBuilderJob();

  const urlRequired = sourceType === "existing_site" || sourceType === "reference_site";
  const canNext = useMemo(() => {
    if (step === 1) return true;
    if (step === 2) return urlRequired ? sourceUrl.trim().length > 0 : sourceType !== "template" || !!templateKey;
    if (step === 3) return !!clientId;
    return false;
  }, [step, urlRequired, sourceUrl, sourceType, templateKey, clientId]);

  async function startBuild() {
    const result = await create.mutateAsync({
      sourceType,
      sourceUrl: urlRequired ? sourceUrl.trim() : undefined,
      template: sourceType === "template" ? (templateKey ?? undefined) : undefined,
      industry,
      pageType: creation.pageType,
      editorMode,
      fidelityMode,
      clientId,
    });
    setJobCode(result.code);
    setStep(4);
  }

  const statusMeta = job ? STATUS_META[job.status] : null;
  const isBuilding = job ? job.status !== "completed" && job.status !== "failed" && job.status !== "correcting" : false;
  const canPublish = job?.status === "generating";

  return (
    <section className="card sb-wiz-card">
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", marginRight: 6 }}>auto_awesome</span>
            Build a website
          </div>
          <div className="cs">
            Reconstruct an existing site, borrow a reference&apos;s layout, or start from an
            audited template — then review the resolved design and publish a WordPress draft.
          </div>
        </div>
      </div>

      <div className="wiz-steps sb-wiz-steps">
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

      <div className="wiz-body sb-wiz-body">
        {step === 1 && (
          <div className="fld">
            <label>What are you creating?</label>
            <div className="sb-type-grid">
              {CREATION_TYPES.map((t) => (
                <button
                  type="button" key={t.key}
                  className={`sb-type-card${t.key === creationKey ? " on" : ""}`}
                  onClick={() => setCreationKey(t.key)}
                >
                  <span className="material-symbols-rounded">{t.icon}</span>
                  <span className="sb-type-label">{t.label}</span>
                  <span className="sb-type-hint">{t.hint}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <>
            <div className="fld">
              <label>Where should the design come from?</label>
              <div className="sb-type-grid">
                {SOURCE_TYPES.map((s) => (
                  <button
                    type="button" key={s.key}
                    className={`sb-type-card${s.key === sourceType ? " on" : ""}`}
                    onClick={() => setSourceType(s.key)}
                  >
                    <span className="material-symbols-rounded">{s.icon}</span>
                    <span className="sb-type-label">{s.label}</span>
                    <span className="sb-type-hint">{s.hint}</span>
                  </button>
                ))}
              </div>
            </div>

            {urlRequired && (
              <div className="fld">
                <label>{sourceType === "existing_site" ? "Website URL" : "Reference URL"}</label>
                <input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://example.com" />
                <div className="fld-hint">
                  {sourceType === "existing_site"
                    ? "We measure the real DOM/CSS at desktop, tablet, and mobile and reconstruct it."
                    : "We borrow the LAYOUT only — never this site's copy, logos, or images."}
                </div>
              </div>
            )}

            {sourceType === "template" && (
              <div className="fld">
                <label>Template</label>
                {templatesQ.isLoading ? (
                  <div className="sb-wiz-empty">
                    <span className="material-symbols-rounded">hourglass_top</span>
                    <div>Loading templates…</div>
                  </div>
                ) : (templatesQ.data ?? []).length === 0 ? (
                  <div className="sb-wiz-empty">
                    <span className="material-symbols-rounded">grid_view</span>
                    <div>No templates match yet — try a different page type.</div>
                  </div>
                ) : (
                  <div className="sb-tpl-grid">
                    {(templatesQ.data ?? []).map((t) => (
                      <button
                        type="button" key={t.key}
                        className={`sb-tpl-card${t.key === templateKey ? " on" : ""}`}
                        onClick={() => setTemplateKey(t.key)}
                      >
                        <span className="sb-tpl-name">{t.name}</span>
                        <span className="sb-tpl-desc">{t.description}</span>
                        <div className="sb-tpl-meta">
                          {t.category && <span className="chip">{t.category}</span>}
                          {t.industry && <span className="chip">{t.industry}</span>}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {sourceType === "manual" && (
              <div className="sb-note">
                <span className="material-symbols-rounded">info</span>
                <div>A blank canvas seeded from a default homepage structure — build it by hand in the editor.</div>
              </div>
            )}
          </>
        )}

        {step === 3 && (
          <>
            <div className="fld-row">
              <div className="fld">
                <label>Client</label>
                <select value={clientId ?? ""} onChange={(e) => setClientId(e.target.value || null)}>
                  <option value="">Select a client…</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.cn}</option>
                  ))}
                </select>
              </div>
              <div className="fld">
                <label>Industry</label>
                <input value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. real_estate, plumbing…" />
              </div>
            </div>

            <div className="fld">
              <label>Editor</label>
              <div className="seg">
                {EDITOR_MODES.map((m) => (
                  <button type="button" key={m.key} className={editorMode === m.key ? "on" : ""} onClick={() => setEditorMode(m.key)}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="fld-hint">{EDITOR_MODES.find((m) => m.key === editorMode)?.hint}</div>
            </div>

            <div className="fld">
              <label>Fidelity</label>
              <div className="seg">
                {FIDELITY_MODES.map((m) => (
                  <button type="button" key={m.key} className={fidelityMode === m.key ? "on" : ""} onClick={() => setFidelityMode(m.key)}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="fld-hint">{FIDELITY_MODES.find((m) => m.key === fidelityMode)?.hint}</div>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            {isBuilding && (
              <div className="sb-prog" role="status">
                <div className="sb-prog-bar"><span /></div>
                <div className="sb-prog-txt">
                  <span>{job?.stageDetail || "Starting…"}</span>
                  {statusMeta && <span className={`status-pill ${statusMeta.cls}`}>{statusMeta.label}</span>}
                </div>
              </div>
            )}

            {job?.status === "failed" && (
              <div className="sb-note">
                <span className="material-symbols-rounded">error</span>
                <div><b>Build failed.</b> {job.error || job.stageDetail}</div>
              </div>
            )}

            {design && (
              <div className="sb-design-summary">
                <div>
                  <label style={{ display: "block", fontSize: 11, fontWeight: 800, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
                    Resolved design
                  </label>
                  <div className="sb-swatches">
                    {[design.palette.primary, design.palette.accent, design.palette.background, design.palette.text].map((c, i) => (
                      <span key={i} className="sb-swatch" style={{ background: c }} title={c} />
                    ))}
                  </div>
                </div>
                <div className="sb-section-list">
                  {design.sections.map((s, i) => (
                    <div key={i} className={`sb-section-row${s.content ? "" : " hidden"}`}>
                      <span className="sb-sec-kind">{s.kind}</span>
                      <span className="sb-sec-heading">{s.heading || "(unfilled — edit in WordPress)"}</span>
                      <span className="chip">{s.layout}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {validations.length > 0 && (
              <div className="fld">
                <label>Visual QA</label>
                <div className="sb-diag-list">
                  {validations[0].diagnostics.length === 0 ? (
                    <div className="sb-diag-row">✓ No mismatches found against the resolved design.</div>
                  ) : (
                    validations[0].diagnostics.map((d, i) => (
                      <div key={i} className="sb-diag-row">
                        <span className="sb-diag-kind">{d.kind}</span>
                        <span>{d.detail}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="sb-wiz-foot">
        {step > 1 && step < 4 ? (
          <button type="button" className="ghostbtn" onClick={() => setStep((s) => (s - 1) as Step)}>
            <span className="material-symbols-rounded">arrow_back</span>Back
          </button>
        ) : <span />}

        {step < 3 && (
          <button type="button" className="primary-btn" disabled={!canNext} onClick={() => setStep((s) => (s + 1) as Step)}>
            Next<span className="material-symbols-rounded">arrow_forward</span>
          </button>
        )}
        {step === 3 && (
          <button type="button" className="primary-btn" disabled={!canNext || create.isPending} onClick={startBuild}>
            <span className="material-symbols-rounded">bolt</span>
            {create.isPending ? "Starting…" : !clientId ? "Pick a client" : "Start build"}
          </button>
        )}
        {step === 4 && canPublish && (
          <button
            type="button" className="primary-btn" disabled={publish.isPending}
            onClick={() => jobCode && publish.mutate(jobCode)}
          >
            <span className="material-symbols-rounded">cloud_upload</span>
            {publish.isPending ? "Publishing…" : "Publish to WordPress"}
          </button>
        )}
      </div>
    </section>
  );
}
