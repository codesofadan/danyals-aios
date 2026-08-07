"use client";

// ============================================================
// AIOS · Content · Research-first bulk pages + site-design matcher
// Pick a content type + site → research a recommended page set (the
// "checkboxes") → generate the picks in one shot as content jobs.
// Optionally extract the site's existing design first and attach it so
// every generated page is built to MATCH the client's site.
// All three actions spend metered budget, so they're disabled while the
// global API-spend halt is engaged (mirrors NewJobForm / BriefBar).
// ============================================================

import { useMemo, useState } from "react";
import {
  RESEARCH_CONTENT_TYPES, DIFFICULTY_META, FRAMEWORKS, TARGETS,
  type ResearchContentType, type ResearchItem, type SiteDesignProfile,
  type Framework, type PublishTarget,
} from "@/lib/content";
import {
  useContentResearch, useGenerateFromResearch, useSiteDesign,
} from "@/lib/hooks/content";
import { useClients } from "@/lib/hooks/clients";

// One item per non-blank line — how the grounding textareas map to the API arrays.
const _lines = (s: string): string[] => s.split("\n").map((l) => l.trim()).filter(Boolean);

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];

export default function ResearchPanel({ halted = false }: { halted?: boolean }) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];

  const [site, setSite] = useState("");
  const [contentType, setContentType] = useState<ResearchContentType>("service");
  const [count, setCount] = useState("");
  const [clientId, setClientId] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [target, setTarget] = useState<PublishTarget>("WordPress");
  const [proof, setProof] = useState("");
  const [testimonials, setTestimonials] = useState("");
  const [uniqueData, setUniqueData] = useState("");
  const [services, setServices] = useState("");

  // Selected recommendations, keyed by title (unique per page set).
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // The extracted design profile + whether to attach it to the generated pages.
  const [design, setDesign] = useState<SiteDesignProfile | null>(null);
  const [attachDesign, setAttachDesign] = useState(true);
  const [maxPages, setMaxPages] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);

  const research = useContentResearch();
  const generate = useGenerateFromResearch();
  const siteDesign = useSiteDesign();

  const items: ResearchItem[] = research.data?.items ?? [];
  const effectiveClientId = clientId || clients[0]?.id || "";

  function runResearch() {
    if (!site.trim() || halted || research.isPending) return;
    setCodes(null);
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
      if (next.has(title)) next.delete(title);
      else next.add(title);
      return next;
    });
  }

  const allSelected = items.length > 0 && selected.size === items.length;
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.title)));
  }

  function generatePages(all: boolean) {
    if (!effectiveClientId || halted || generate.isPending) return;
    const picks = all ? items : items.filter((i) => selected.has(i.title));
    if (picks.length === 0) return;
    setCodes(null);
    generate.mutate(
      {
        items: picks,
        clientId: effectiveClientId,
        framework,
        target,
        proofPoints: _lines(proof).slice(0, 12),
        testimonials: _lines(testimonials).slice(0, 12),
        uniqueData: _lines(uniqueData).slice(0, 12),
        services: _lines(services).slice(0, 20),
        ...(attachDesign && design ? { designProfile: design } : {}),
      },
      { onSuccess: (r) => setCodes(r.jobs) },
    );
  }

  const selectedCount = useMemo(
    () => items.filter((i) => selected.has(i.title)).length,
    [items, selected],
  );

  const researchDegraded = research.data?.status === "degraded";

  return (
    <section className="card co-research-card">
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", marginRight: 6 }}>travel_explore</span>
            Research-first bulk pages
          </div>
          <div className="cs">
            Pick a content type + a site. Claude researches the site and its competitors,
            recommends a page set, and fans your picks into content jobs in one shot.
          </div>
        </div>
      </div>

      <div className="co-research">
        {/* 1 — content type */}
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

        {/* 2 — site + count + run */}
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
            {halted ? "API spend halted" : research.isPending ? "Researching…" : "Research page set"}
          </button>
          <button className="ghostbtn" type="button" onClick={runSiteDesign}
            disabled={!site.trim() || halted || siteDesign.isPending}>
            <span className="material-symbols-rounded">palette</span>
            {siteDesign.isPending ? "Analysing…" : "Match this site's design"}
          </button>
        </div>

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

        {/* Site-design profile (extracted) */}
        {(siteDesign.isPending || siteDesign.data) && (
          <DesignProfileView
            profile={design}
            degraded={siteDesign.data?.status === "degraded"}
            reason={siteDesign.data?.reason ?? ""}
            attach={attachDesign}
            onAttach={setAttachDesign}
            maxPages={maxPages}
            onMaxPages={setMaxPages}
          />
        )}

        {/* 3 — recommendations checkbox list */}
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

            {/* 4 — generate config (client / framework / target / proof) */}
            <div className="co-gen">
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
                  <select value={target} onChange={(e) => setTarget(e.target.value as PublishTarget)}>
                    {TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
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
              </div>
              <div className="fld">
                <label>Proof &amp; first-hand experience <span className="cs">(shared across every page, one per line)</span></label>
                <textarea rows={2} value={proof} onChange={(e) => setProof(e.target.value)}
                  placeholder={"Required to publish — the E-E-A-T gate holds any page with zero first-hand proof."} />
              </div>
              <div className="fld-row">
                <div className="fld">
                  <label>Testimonials <span className="cs">(optional)</span></label>
                  <textarea rows={2} value={testimonials} onChange={(e) => setTestimonials(e.target.value)} />
                </div>
                <div className="fld">
                  <label>Unique data <span className="cs">(optional)</span></label>
                  <textarea rows={2} value={uniqueData} onChange={(e) => setUniqueData(e.target.value)} />
                </div>
                <div className="fld">
                  <label>Services <span className="cs">(optional)</span></label>
                  <textarea rows={2} value={services} onChange={(e) => setServices(e.target.value)} />
                </div>
              </div>

              {design && attachDesign && (
                <div className="cs" role="status" style={{ color: "var(--ok)", marginBottom: 8 }}>
                  <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>palette</span>{" "}
                  The extracted site design will be attached to every generated page.
                </div>
              )}

              <div className="op-toolset">
                <button className="primary-btn" type="button" onClick={() => generatePages(false)}
                  disabled={selectedCount === 0 || !effectiveClientId || halted || generate.isPending}>
                  <span className="material-symbols-rounded">bolt</span>
                  {generate.isPending ? "Queuing…" : `Generate selected (${selectedCount})`}
                </button>
                <button className="ghostbtn" type="button" onClick={() => generatePages(true)}
                  disabled={!effectiveClientId || halted || generate.isPending}>
                  <span className="material-symbols-rounded">library_add</span>
                  Generate all ({items.length})
                </button>
              </div>
              {halted && (
                <div className="cs" role="status" style={{ color: "var(--warn)", marginTop: 8 }}>
                  API spend is halted. Resume it in Cost Controls to generate pages.
                </div>
              )}
              {generate.isError && (
                <div className="cs" role="alert" style={{ color: "var(--warn)", marginTop: 8 }}>
                  Couldn&apos;t queue the pages. {(generate.error as Error)?.message ?? "Try again"}.
                </div>
              )}
            </div>
          </>
        )}

        {/* 5 — queued job codes */}
        {codes && codes.length > 0 && (
          <div className="co-codes-wrap">
            <div className="co-rec-h" style={{ marginBottom: 6 }}>
              <span className="op-strong">
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", color: "var(--ok)" }}>task_alt</span>{" "}
                Queued {codes.length} content {codes.length === 1 ? "job" : "jobs"} — now in the pipeline board above.
              </span>
            </div>
            <div className="co-codes">
              {codes.map((code) => (
                <span key={code} className="co-code">{code}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// The extracted design profile: palette swatches, fonts, and the ordered section list.
function DesignProfileView({
  profile, degraded, reason, attach, onAttach, maxPages, onMaxPages,
}: {
  profile: SiteDesignProfile | null;
  degraded: boolean;
  reason: string;
  attach: boolean;
  onAttach: (v: boolean) => void;
  maxPages: string;
  onMaxPages: (v: string) => void;
}) {
  return (
    <div className="co-design">
      <div className="co-design-h">
        <span className="co-design-t">
          <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>palette</span>{" "}
          Extracted site design
        </span>
        <div className="fld co-design-pages">
          <label>Max pages</label>
          <input value={maxPages} onChange={(e) => onMaxPages(e.target.value.replace(/[^0-9]/g, ""))}
            inputMode="numeric" placeholder="auto" />
        </div>
      </div>

      {!profile && degraded && (
        <div className="cs" style={{ color: "var(--warn)" }}>
          Design analysis degraded — {reason || "no key or the dial/budget blocked the call"}.
        </div>
      )}

      {profile && (
        <>
          {/* Live preview — how a matching page would look, rendered from the extracted
              colours/fonts/layout. Sandboxed (no scripts, no same-origin) so the model-
              generated HTML can never touch the app. */}
          {profile.wireframeHtml && (
            <div className="co-wireframe">
              <div className="co-order-lbl op-muted" style={{ marginBottom: 6 }}>
                <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>preview</span>{" "}
                Preview — how a matching page would look
              </div>
              <iframe
                title="Matching page preview"
                srcDoc={profile.wireframeHtml}
                sandbox=""
                loading="lazy"
                style={{
                  width: "100%",
                  height: 320,
                  border: "1px solid var(--line, #e5e7eb)",
                  borderRadius: 10,
                  background: "#fff",
                  display: "block",
                  marginBottom: 12,
                }}
              />
            </div>
          )}

          <div className="co-swatches">
            {(Object.entries(profile.palette) as [string, string][]).map(([name, hex]) => (
              <div key={name} className="co-swatch">
                <span className="co-swatch-chip" style={{ background: hex }} />
                <span className="co-swatch-name">{name}</span>
                <span className="co-swatch-hex">{hex}</span>
              </div>
            ))}
          </div>

          <div className="co-design-meta">
            <div><span className="op-muted">Heading</span> <b>{profile.typography.heading_font}</b></div>
            <div><span className="op-muted">Body</span> <b>{profile.typography.body_font}</b></div>
            <div><span className="op-muted">Base size</span> <b>{profile.typography.base_size}</b></div>
            <div><span className="op-muted">Container</span> <b>{profile.layout.container_width}</b></div>
            <div><span className="op-muted">Hero</span> <b>{profile.layout.hero_style}</b></div>
            <div><span className="op-muted">CTA</span> <b>{profile.layout.cta_style}</b></div>
          </div>

          <div className="co-order-lbl op-muted">Section order</div>
          <ol className="co-order">
            {profile.layout.section_order.map((s, i) => (
              <li key={`${s}-${i}`} className="co-order-item">{s}</li>
            ))}
          </ol>

          {profile.notes && <div className="cs" style={{ marginTop: 6 }}>{profile.notes}</div>}

          <label className="co-attach">
            <input type="checkbox" checked={attach} onChange={(e) => onAttach(e.target.checked)} />
            Match this design on the generated pages
          </label>
        </>
      )}
    </div>
  );
}
